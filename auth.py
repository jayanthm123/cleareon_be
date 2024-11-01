import os
import psycopg2
from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    jwt_required, get_jwt_identity, create_access_token, JWTManager, get_jwt
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

# Load sensitive information from environment variables
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_PORT = os.getenv("DB_PORT")
JWT_SECRET = os.getenv("JWT_SECRET")


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


def check_active_session(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user_identity = get_jwt_identity()
        user_id = user_identity['user_id']

        conn = get_db_connection()
        with conn.cursor() as cursor:
            query = """
                SELECT is_revoked 
                FROM user_sessions 
                WHERE user_id = %s 
                AND token = %s
            """
            cursor.execute(query, (user_id, get_jwt()["jti"]))  # Uses JTI as token ID
            session = cursor.fetchone()
            if session and session[0]:  # If is_revoked is True
                return jsonify({'error': 'Session has been revoked, please log in again.'}), 401
        return fn(*args, **kwargs)

    return wrapper


def has_active_session(user_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            query = """
                SELECT 1
                FROM user_sessions 
                WHERE user_id = %s 
                AND (is_revoked = FALSE OR 
                expires_at > CURRENT_TIMESTAMP) 
            """
            cursor.execute(query, (user_id,))
            return cursor.fetchone() is not None
    finally:
        conn.close()


def get_user_permissions(user_id):
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


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        current_user = get_jwt_identity()
        if not current_user or current_user.get('role') != 'admin':
            return jsonify({'error': 'Admin privileges required'}), 403
        return f(*args, **kwargs)

    return decorated_function


@auth_bp.route('/login', methods=['POST'])
@limiter.limit("5/5 minutes")
def login():
    conn = None
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        override_session = data.get('override_session', False)

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

        if has_active_session(user_id) and not override_session:
            return jsonify({
                'message': 'User already logged in on another device. Do you want to log in here instead?',
                'user_id': user_id
            }), 409

        if override_session:
            invalidate_user_sessions(user_id)

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
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)

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


@auth_bp.route('/extend-session', methods=['POST'])
@jwt_required()
def extend_token():
    conn = None
    try:
        user_identity = get_jwt_identity()
        user_id = user_identity['user_id']

        # Check if the current session is still active
        conn = get_db_connection()
        with conn.cursor() as cursor:
            query = """
                SELECT is_revoked, expires_at
                FROM user_sessions
                WHERE user_id = %s AND token = %s
            """
            cursor.execute(query, (user_id, get_jwt()["jti"]))
            session = cursor.fetchone()

            if not session:
                return jsonify({'error': 'Session not found or invalid'}), 401

            is_revoked, expires_at = session
            if is_revoked or datetime.now(timezone.utc) > expires_at:
                return jsonify({'error': 'Session has expired or been revoked'}), 401

            # Generate a new token with extended expiration
            new_access_token = create_access_token(identity=user_identity)
            new_expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)

            # Update the session's expiration in the database
            update_query = """
                UPDATE user_sessions
                SET expires_at = %s, token = %s
                WHERE user_id = %s AND token = %s
            """
            cursor.execute(update_query, (new_expires_at, new_access_token, user_id, get_jwt()["jti"]))
            conn.commit()

            return jsonify({
                'access_token': new_access_token,
                'expires_at': new_expires_at.isoformat()
            }), 200

    except Exception as e:
        logging.error(f"Error extending token: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        if conn:
            conn.close()


@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    print('logging out for user')
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
    data = request.get_json()
    password = data.get("password")
    if not password:
        return jsonify({'error': 'Password is required'}), 400

    hashed_password = ph.hash(password)
    return jsonify({'hashed_password': hashed_password}), 200
