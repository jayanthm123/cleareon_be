from flask import Flask, request, jsonify
from flask_jwt_extended import JWTManager, create_access_token, get_jwt_identity
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import redis
import json
from datetime import datetime
from config import Config
from database import SessionLocal
from sqlalchemy import text

app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions
jwt = JWTManager(app)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="redis://localhost:6379"
)

# Initialize Redis for session management
redis_client = redis.from_url(Config.REDIS_URL)
ph = PasswordHasher()


def get_user_permissions(user_id, db):
    """Get user permissions from database"""
    query = text("""
        SELECT DISTINCT p.permission_name 
        FROM permissions p
        JOIN role_permissions rp ON p.permission_id = rp.permission_id
        JOIN users u ON u.role_id = rp.role_id
        WHERE u.user_id = :user_id
    """)
    result = db.execute(query, {'user_id': user_id})
    return [row[0] for row in result]


def check_client_term_date(client_id, db):
    """Check if client's term date is valid"""
    query = text("""
        SELECT term_date 
        FROM clients 
        WHERE client_id = :client_id
    """)
    result = db.execute(query, {'client_id': client_id}).first()
    if result and result[0]:
        return datetime.now().date() <= result[0]
    return True


@app.route('/login', methods=['POST'])
@limiter.limit(f"{Config.MAX_LOGIN_ATTEMPTS}/5 minutes")
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({'error': 'Missing credentials'}), 400

        db = SessionLocal()

        # Get user details
        query = text("""
            SELECT u.user_id, u.password_hash, u.client_id, u.email, 
                   r.role_name, c.company_name
            FROM users u
            JOIN roles r ON u.role_id = r.role_id
            JOIN clients c ON u.client_id = c.client_id
            WHERE u.username = :username
        """)

        result = db.execute(query, {'username': username}).first()

        if not result:
            return jsonify({'error': 'Invalid credentials'}), 401

        user_id, password_hash, client_id, email, role_name, company_name = result

        # Verify password
        try:
            ph.verify(password_hash, password)
        except VerifyMismatchError:
            return jsonify({'error': 'Invalid credentials'}), 401

        # Check client term date
        if not check_client_term_date(client_id, db):
            return jsonify({'error': 'Account expired'}), 403

        # Get user permissions
        permissions = get_user_permissions(user_id, db)

        # Create user identity
        user_identity = {
            'user_id': str(user_id),
            'username': username,
            'email': email,
            'role': role_name,
            'client_id': str(client_id),
            'company_name': company_name,
            'permissions': permissions
        }

        # Create access token
        access_token = create_access_token(identity=user_identity)

        # Invalidate old sessions for this user
        old_token = redis_client.get(f"user_session:{user_id}")
        if old_token:
            redis_client.sadd("revoked_tokens", old_token)

        # Store new session
        redis_client.setex(
            f"user_session:{user_id}",
            Config.JWT_ACCESS_TOKEN_EXPIRES.total_seconds(),
            access_token
        )

        return jsonify({
            'access_token': access_token,
            'user': user_identity
        }), 200

    except Exception as e:
        app.logger.error(f"Login error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

    finally:
        db.close()


@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    jti = jwt_payload["jti"]
    token_in_redis = redis_client.sismember("revoked_tokens", jti)
    return token_in_redis


# Logout endpoint
@app.route('/logout', methods=['POST'])
def logout():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or 'Bearer' not in auth_header:
            return jsonify({'error': 'Missing token'}), 401

        token = auth_header.split(' ')[1]
        user_identity = get_jwt_identity()
        user_id = user_identity['user_id']

        # Add token to revoked tokens set
        redis_client.sadd("revoked_tokens", token)

        # Remove user session
        redis_client.delete(f"user_session:{user_id}")

        return jsonify({'message': 'Successfully logged out'}), 200

    except Exception as e:
        app.logger.error(f"Logout error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
