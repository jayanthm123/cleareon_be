import psycopg2
from flask import Blueprint, request, jsonify
from psycopg2.extras import DictCursor
import uuid

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


@sitecontrol_bp.route('/users/<string:user_id>', methods=['PUT'])
def update_user(user_id):
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET client_id = %s, role_id = %s, username = %s, email = %s WHERE user_id = %s",
        (data['client_id'], data['role_id'], data['username'], data['email'], user_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "User updated successfully"})


@sitecontrol_bp.route('/users/<string:user_id>', methods=['DELETE'])
def delete_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "User deleted successfully"})


# Role routes
@sitecontrol_bp.route('/roles', methods=['GET'])
def get_roles():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM roles")
    roles = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(role) for role in roles])


@sitecontrol_bp.route('/roles', methods=['POST'])
def create_role():
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO roles (role_name) VALUES (%s) RETURNING role_id",
        (data['role_name'],)
    )
    role_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Role created successfully", "role_id": role_id}), 201


@sitecontrol_bp.route('/roles/<int:role_id>', methods=['GET'])
def get_role(role_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM roles WHERE role_id = %s", (role_id,))
    role = cur.fetchone()
    cur.close()
    conn.close()
    return jsonify(dict(role)) if role else ("Role not found", 404)


@sitecontrol_bp.route('/roles/<int:role_id>', methods=['PUT'])
def update_role(role_id):
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE roles SET role_name = %s WHERE role_id = %s",
        (data['role_name'], role_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Role updated successfully"})


@sitecontrol_bp.route('/roles/<int:role_id>', methods=['DELETE'])
def delete_role(role_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM roles WHERE role_id = %s", (role_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Role deleted successfully"})


# Permission routes
@sitecontrol_bp.route('/permissions', methods=['GET'])
def get_permissions():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM permissions")
    permissions = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(permission) for permission in permissions])


@sitecontrol_bp.route('/permissions', methods=['POST'])
def create_permission():
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO permissions (permission_name) VALUES (%s) RETURNING permission_id",
        (data['permission_name'],)
    )
    permission_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Permission created successfully", "permission_id": permission_id}), 201


@sitecontrol_bp.route('/permissions/<int:permission_id>', methods=['GET'])
def get_permission(permission_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM permissions WHERE permission_id = %s", (permission_id,))
    permission = cur.fetchone()
    cur.close()
    conn.close()
    return jsonify(dict(permission)) if permission else ("Permission not found", 404)


@sitecontrol_bp.route('/permissions/<int:permission_id>', methods=['PUT'])
def update_permission(permission_id):
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE permissions SET permission_name = %s WHERE permission_id = %s",
        (data['permission_name'], permission_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Permission updated successfully"})


@sitecontrol_bp.route('/permissions/<int:permission_id>', methods=['DELETE'])
def delete_permission(permission_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM permissions WHERE permission_id = %s", (permission_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Permission deleted successfully"})


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
