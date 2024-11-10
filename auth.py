import psycopg2
from flask import Blueprint, request, jsonify, session
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
    conn = psycopg2.connect(
        host="pg-3c0f63d9-cleareon.l.aivencloud.com",
        database="cleareon_db",
        user="avnadmin",
        password="AVNS_mPoJaHeUZxZjg-eWQ_p",
        port="22635",
        sslmode="require"
    )
    return conn


def check_session(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if user_id is present in the session
        if 'user_id' not in session:
            print("No user_id found in session")
            return jsonify({'error': 'Please login to continue'}), 401

        # Verify if the client term is still valid
        client_id = session.get('client_id')
        if client_id:
            if not check_client_term_date(client_id):
                print("Client term expired for client_id:", client_id)
                session.clear()
                return jsonify({'error': 'Session expired'}), 401

        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'role' not in session or session['role'] != 'admin':
            return jsonify({'error': 'Admin privileges required'}), 403
        return f(*args, **kwargs)

    return decorated_function


def check_client_term_date(client_id):
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


def get_user_permissions(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        query = sql.SQL("""
            SELECT DISTINCT p.permission_name 
            FROM permissions p 
            JOIN role_permissions rp ON p.permission_id = rp.permission_id 
            JOIN users u ON u.role_id = rp.role_id 
            WHERE u.user_id = %s
        """)
        cursor.execute(query, (user_id,))
        result = cursor.fetchall()
        return [row[0] for row in result]
    finally:
        cursor.close()
        conn.close()


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

        # Check client term date
        if not check_client_term_date(client_id):
            return jsonify({'error': 'Account expired'}), 403

        # Get permissions
        permissions = get_user_permissions(user_id)

        # Set session data
        session.permanent = True  # Uses app.permanent_session_lifetime
        session['user_id'] = str(user_id)
        session['username'] = username
        session['email'] = email
        session['role'] = role_name
        session['client_id'] = str(client_id)
        session['company_name'] = company_name
        session['permissions'] = permissions
        session['login_time'] = datetime.now(timezone.utc).isoformat()

        # Update last login timestamp
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE user_id = %s",
                (user_id,)
            )
            conn.commit()

        return jsonify({
            'message': 'Login successful',
            'user': {
                'user_id': str(user_id),
                'username': username,
                'email': email,
                'role': role_name,
                'client_id': str(client_id),
                'company_name': company_name,
                'permissions': permissions
            }
        }), 200

    except Exception as e:
        logging.error(f"Login error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        if conn:
            conn.close()


@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Successfully logged out'}), 200


@auth_bp.route('/check-auth', methods=['GET'])
@check_session
def check_auth():
    return jsonify({
        'authenticated': True,
        'user': {
            'user_id': session['user_id'],
            'username': session['username'],
            'email': session['email'],
            'role': session['role'],
            'client_id': session['client_id'],
            'company_name': session['company_name'],
            'permissions': session['permissions']
        }
    }), 200


@auth_bp.route('/extend-session', methods=['POST'])
@check_session
def extend_session():
    print("Extending Session")
    try:
        # Verify the client's term date hasn't expired
        client_id = session.get('client_id')
        print(client_id)
        if not check_client_term_date(client_id):
            session.clear()
            return jsonify({'error': 'Account expired'}), 403

        # Update session login time
        session['login_time'] = datetime.now(timezone.utc).isoformat()

        return jsonify({
            'message': 'Session extended successfully',
            'login_time': session['login_time']
        }), 200

    except Exception as e:
        logging.error(f"Error extending session: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/hash-password', methods=['POST'])
@check_session
@admin_required
def hash_password():
    data = request.get_json()
    password = data.get("password")
    if not password:
        return jsonify({'error': 'Password is required'}), 400

    hashed_password = ph.hash(password)
    return jsonify({'hashed_password': hashed_password}), 200
