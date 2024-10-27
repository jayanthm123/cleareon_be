import psycopg2
from flask import Blueprint, request, jsonify
import uuid

from flask_jwt_extended import jwt_required
from psycopg2.extras import DictCursor, RealDictCursor
from psycopg2 import IntegrityError, DatabaseError

sitecontrol_bp = Blueprint('sitecontrol', __name__)


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


# User routes
@sitecontrol_bp.route('/users', methods=['GET'])
def get_users():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM users")
    users = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(user) for user in users])


@sitecontrol_bp.route('/users', methods=['POST'])
def create_user():
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (user_id, client_id, role_id, username, email, password_hash) VALUES (%s, %s, %s, %s, %s, %s)",
        (str(uuid.uuid4()), data['client_id'], data['role_id'], data['username'], data['email'], data['password_hash'])
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "User created successfully"}), 201


@sitecontrol_bp.route('/users/<string:user_id>', methods=['GET'])
def get_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return jsonify(dict(user)) if user else ("User not found", 404)


# Client routes
@sitecontrol_bp.route('/clients', methods=['GET'])
def get_clients():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM clients")
    clients = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(client) for client in clients])


@sitecontrol_bp.route('/clients', methods=['POST'])
def create_client():
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO clients (client_id, company_name, invoice_number, start_date, term_date) VALUES (%s, %s, %s, %s, %s)",
        (str(uuid.uuid4()), data['company_name'], data['invoice_number'], data['start_date'], data['term_date'])
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Client created successfully"}), 201


@sitecontrol_bp.route('/clients/<string:client_id>', methods=['GET'])
def get_client(client_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM clients WHERE client_id = %s", (client_id,))
    client = cur.fetchone()
    cur.close()
    conn.close()
    return jsonify(dict(client)) if client else ("Client not found", 404)


@sitecontrol_bp.route('/clients/<string:client_id>', methods=['PUT'])
def update_client(client_id):
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE clients SET company_name = %s, invoice_number = %s, start_date = %s, term_date = %s WHERE client_id = %s",
        (data['company_name'], data['invoice_number'], data['start_date'], data['term_date'], client_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Client updated successfully"})


@sitecontrol_bp.route('/clients/<string:client_id>', methods=['DELETE'])
def delete_client(client_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM clients WHERE client_id = %s", (client_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Client deleted successfully"})


@sitecontrol_bp.route('/clients/<client_id>/users', methods=['GET'])
@jwt_required()
def get_client_users(client_id):
    """
    Get all users associated with a specific client.
    Returns user details including their roles.
    Requires either admin access or being a user of the specified client.
    """
    from main import get_jwt_identity
    current_user_id = get_jwt_identity()

    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Check if user has permission to view these users
                cur.execute("""
                    SELECT 
                        u.client_id,
                        r.role_name
                    FROM users u
                    JOIN roles r ON u.role_id = r.role_id
                    WHERE u.user_id = %s
                """, (current_user_id,))

                user_info = cur.fetchone()
                if not user_info:
                    return jsonify({
                        'error': 'User not found'
                    }), 404

                # Allow access if user is admin or belongs to the same client
                is_admin = user_info['role_name'] == 'Admin'
                is_same_client = str(user_info['client_id']) == str(client_id)

                if not (is_admin or is_same_client):
                    return jsonify({
                        'error': 'Access denied'
                    }), 403

                # Validate client exists
                cur.execute("""
                    SELECT client_id 
                    FROM clients 
                    WHERE client_id = %s
                """, (client_id,))

                if not cur.fetchone():
                    return jsonify({
                        'error': 'Client not found'
                    }), 404

                # Get all users associated with the client
                cur.execute("""
                    SELECT 
                        u.user_id,
                        u.username,
                        u.email,
                        r.role_name,
                        u.created_at,
                        u.updated_at,
                        u.last_login
                    FROM users u
                    JOIN roles r ON u.role_id = r.role_id
                    WHERE u.client_id = %s
                    ORDER BY u.username
                """, (client_id,))

                users = cur.fetchall()

                # Convert datetime objects to strings
                for user in users:
                    if user.get('created_at'):
                        user['created_at'] = user['created_at'].isoformat()
                    if user.get('updated_at'):
                        user['updated_at'] = user['updated_at'].isoformat()
                    if user.get('last_login'):
                        user['last_login'] = user['last_login'].isoformat()

                return jsonify(users)

    except ValueError as e:
        return jsonify({
            'error': 'Invalid client ID format'
        }), 400

    except DatabaseError as e:
        # Log the error details here
        print(f"Database error: {str(e)}")
        return jsonify({
            'error': 'Database error occurred'
        }), 500

    except Exception as e:
        # Log the error details here
        print(f"Unexpected error: {str(e)}")
        return jsonify({
            'error': 'An unexpected error occurred'
        }), 500
