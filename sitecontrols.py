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
        "INSERT INTO users (user_id, tenant_id, role_id, username, email, password_hash) VALUES (%s, %s, %s, %s, %s, %s)",
        (str(uuid.uuid4()), data['tenant_id'], data['role_id'], data['username'], data['email'], data['password_hash'])
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


# tenant routes
@sitecontrol_bp.route('/tenants', methods=['GET'])
def get_tenants():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM tenants")
    tenants = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(tenant) for tenant in tenants])


@sitecontrol_bp.route('/tenants', methods=['POST'])
def create_tenant():
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO tenants (tenant_id, tenant_name, invoice_number, start_date, term_date) VALUES (%s, %s, %s, %s, %s)",
        (str(uuid.uuid4()), data['company_name'], data['invoice_number'], data['start_date'], data['term_date'])
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Tenant created successfully"}), 201


@sitecontrol_bp.route('/tenants/<string:tenant_id>', methods=['GET'])
def get_tenant(tenant_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM tenants WHERE tenant_id = %s", (tenant_id,))
    tenant = cur.fetchone()
    cur.close()
    conn.close()
    return jsonify(dict(tenant)) if tenant else ("Tenant not found", 404)


@sitecontrol_bp.route('/tenants/<string:tenant_id>', methods=['PUT'])
def update_tenant(tenant_id):
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE tenants SET company_name = %s, invoice_number = %s, start_date = %s, term_date = %s WHERE tenant_id = %s",
        (data['company_name'], data['invoice_number'], data['start_date'], data['term_date'], tenant_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Tenant updated successfully"})


@sitecontrol_bp.route('/tenants/<string:tenant_id>', methods=['DELETE'])
def delete_tenant(tenant_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tenants WHERE tenant_id = %s", (tenant_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Tenant deleted successfully"})


@sitecontrol_bp.route('/tenants/<tenant_id>/users', methods=['GET'])
@jwt_required()
def get_tenant_users(tenant_id):
    """
    Get all users associated with a specific tenant.
    Returns user details including their roles.
    Requires either admin access or being a user of the specified tenant.
    """
    current_user_id = "dbf31fd3-831b-4ee3-a90d-91b92d5cab5e"
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Check if user has permission to view these users
                cur.execute("""
                    SELECT 
                        u.tenant_id,
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

                # Allow access if user is admin or belongs to the same tenant
                is_admin = user_info['role_name'] == 'Admin'
                is_same_tenant = str(user_info['tenant_id']) == str(tenant_id)

                if not (is_admin or is_same_tenant):
                    return jsonify({
                        'error': 'Access denied'
                    }), 403

                # Validate tenant exists
                cur.execute("""
                    SELECT tenant_id 
                    FROM tenants 
                    WHERE tenant_id = %s
                """, (tenant_id,))

                if not cur.fetchone():
                    return jsonify({
                        'error': 'Tenant not found'
                    }), 404

                # Get all users associated with the tenant
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
                    WHERE u.tenant_id = %s
                    ORDER BY u.username
                """, (tenant_id,))

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
            'error': 'Invalid tenant ID format'
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



@sitecontrol_bp.route('/users/<string:user_id>', methods=['PUT'])
def update_user(user_id):
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET tenant_id = %s, role_id = %s, username = %s, email = %s WHERE user_id = %s",
        (data['tenant_id'], data['role_id'], data['username'], data['email'], user_id)
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
    try:
        # Get roles with their permissions
        cur.execute("""
            SELECT r.role_id, r.role_name, 
                   COALESCE(array_agg(
                       DISTINCT jsonb_build_object(
                           'permission_id', p.permission_id, 
                           'permission_name', p.permission_name
                       )
                   ) FILTER (WHERE p.permission_id IS NOT NULL), '{}') as permissions
            FROM roles r
            LEFT JOIN role_permissions rp ON r.role_id = rp.role_id
            LEFT JOIN permissions p ON rp.permission_id = p.permission_id
            GROUP BY r.role_id, r.role_name
            ORDER BY r.role_id
        """)
        roles = [dict(row) for row in cur.fetchall()]
        return jsonify(roles)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


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

