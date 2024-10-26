import psycopg2
from flask import Blueprint, request, jsonify
import uuid
from psycopg2.extras import DictCursor
from psycopg2 import IntegrityError

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
