from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    jwt_required, get_jwt_identity, create_access_token, JWTManager
)
from datetime import datetime, timezone, timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from psycopg2 import sql
import logging
from functools import wraps

# Initialize blueprint
auth_bp = Blueprint('auth', __name__)

# Initialize password hasher
ph = PasswordHasher()

# Initialize rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://"
)

def get_db_connection():
    """Database connection function - import from your database module"""
    from main import get_db_connection
    return get_db_connection()

# Helper Functions
def get_user_permissions(user_id):
    """Get user permissions from database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    query = sql.SQL("""
        SELECT DISTINCT p.permission_name 
        FROM permissions p 
        JOIN role_permissions rp ON p.permission_id = rp.permission_id 
        JOIN users u ON u.role_id = rp.role_id 
        WHERE u.user_id = %s
    """)
    try:
        cursor.execute(query, (user_id,))
        result = cursor.fetchall()
        return [row[0] for row in result]
    finally:
        cursor.close()
        conn.close()

def check_client_term_date(client_id):
    """Check if client's term date is valid"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        query = sql.SQL("SELECT term_date FROM clients WHERE client_id = %s")
        cursor.execute(query, (client_id,))
        result = cursor.fetchone()
        if result and result[0]:
            return datetime.now().date() <= result[0]
        return True
    finally:
        cursor.close()
        conn.close()

def create_user_session(user_id, token, expires_at):
    """Create a new session for a user"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            query = """
                INSERT INTO user_sessions (session_id, user_id, token, expires_at)
                VALUES (gen_random_uuid(), %s, %s, %s)
                RETURNING session_id
            """
            cursor.execute(query, (user_id, token, expires_at))
            session_id = cursor.fetchone()[0]
            conn.commit()
            return session_id
    finally:
        conn.close()

def validate_session(token):
    """Validate if a session is active and not expired"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            query = """
                SELECT user_id
                FROM user_sessions 
                WHERE token = %s 
                AND is_revoked = FALSE 
                AND expires_at > CURRENT_TIMESTAMP
            """
            cursor.execute(query, (token,))
            result = cursor.fetchone()
            return result[0] if result else None
    finally:
        conn.close()

def invalidate_user_sessions(user_id):
    """Invalidate all active sessions for a user"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            query = """
                UPDATE user_sessions 
                SET is_revoked = TRUE 
                WHERE user_id = %s AND is_revoked = FALSE
            """
            cursor.execute(query, (user_id,))
            conn.commit()
    finally:
        conn.close()

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        current_user = get_jwt_identity()
        if not current_user or current_user.get('role') != 'admin':
            return jsonify({'error': 'Admin privileges required'}), 403
        return f(*args, **kwargs)
    return decorated_function

# Routes
@auth_bp.route('/login', methods=['POST'])
@limiter.limit("5/5 minutes")
def login():
    conn = None
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({'error': 'Missing credentials'}), 400

        conn = get_db_connection()
        with conn.cursor() as cursor:
            query = """
                SELECT u.user_id, u.password_hash, u.client_id, u.email, r.role_name, c.company_name 
                FROM users u 
                JOIN roles r ON u.role_id = r.role_id 
                JOIN clients c ON u.client_id = c.client_id 
                WHERE u.email = %s
            """
            cursor.execute(query, (username,))
            result = cursor.fetchone()

        if not result:
            return jsonify({'error': 'Invalid credentials'}), 401

        user_id, password_hash, client_id, email, role_name, company_name = result

        try:
            ph.verify(password_hash, password)
        except VerifyMismatchError:
            return jsonify({'error': 'Invalid credentials'}), 401

        if not check_client_term_date(client_id):
            return jsonify({'error': 'Account expired'}), 403

        permissions = get_user_permissions(user_id)

        user_identity = {
            'user_id': str(user_id),
            'username': username,
            'email': email,
            'role': role_name,
            'client_id': str(client_id),
            'company_name': company_name,
            'permissions': permissions
        }

        access_token = create_access_token(identity=user_identity)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)  # Adjust timing as needed

        invalidate_user_sessions(user_id)
        create_user_session(user_id, access_token, expires_at)

        return jsonify({
            'access_token': access_token,
            'user': user_identity
        }), 200

    except Exception as e:
        logging.error(f"Login error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        if conn:
            conn.close()

@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    conn = None
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or 'Bearer' not in auth_header:
            return jsonify({'error': 'Missing token'}), 401

        token = auth_header.split(' ')[1]
        user_identity = get_jwt_identity()
        user_id = user_identity['user_id']

        conn = get_db_connection()
        with conn.cursor() as cursor:
            query = """
                UPDATE user_sessions 
                SET is_revoked = TRUE 
                WHERE user_id = %s 
                AND token = %s
            """
            cursor.execute(query, (user_id, token))
        conn.commit()

        return jsonify({'message': 'Successfully logged out'}), 200

    except Exception as e:
        logging.error(f"Logout error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        if conn:
            conn.close()

@auth_bp.route('/hash-password', methods=['POST'])
@jwt_required()
@admin_required
def hash_password():
    conn = None
    try:
        data = request.get_json()
        password = data.get('password')
        user_id = data.get('user_id')

        if not password or not user_id:
            return jsonify({'error': 'Missing password or user_id'}), 400

        hashed_password = ph.hash(password)

        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
            if not cursor.fetchone():
                return jsonify({'error': 'User not found'}), 404

            query = """
                UPDATE users 
                SET password_hash = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
                RETURNING user_id
            """
            cursor.execute(query, (hashed_password, user_id))

            if cursor.rowcount == 0:
                return jsonify({'error': 'Failed to update password'}), 500

        conn.commit()
        invalidate_user_sessions(user_id)

        return jsonify({
            'message': 'Password successfully updated',
            'user_id': user_id
        }), 200

    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        logging.error(f"Password hash error: {str(e)}")
        if conn:
            conn.rollback()
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        if conn:
            conn.close()