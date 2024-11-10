import psycopg2
from flask import Flask, request, jsonify, Blueprint

config_bp = Blueprint('config', __name__)


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


def get_tenant_config(tenant_id, tenant_account_id, config_key):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT config_value FROM tenant_id 
        WHERE tenant_id = %s AND tenant_account_id = %s AND config_key = %s
    """, (tenant_id, tenant_account_id, config_key))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result[0] if result else None


def update_tenant_config(tenant_id, tenant_account_id, config_key, config_value):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO tenant_config (tenant_id, tenant_account_id, config_key, config_value)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (tenant_id, tenant_account_id, config_key) 
        DO UPDATE SET config_value = EXCLUDED.config_value
    """, (tenant_id, tenant_account_id, config_key, config_value))
    conn.commit()
    cur.close()
    conn.close()


@config_bp.route('/update_tenant_config', methods=['POST'])
def update_config():
    try:
        data = request.json
        tenant_id = data.get('tenant_id')
        tenant_account_id = data.get('tenant_account_id')
        config_key = data.get('config_key')
        config_value = data.get('config_value')

        if not all([tenant_id, tenant_account_id, config_key, config_value]):
            return jsonify({"error": "Missing required parameters"}), 400

        update_tenant_config(tenant_id, tenant_account_id, config_key, config_value)
        return jsonify({"message": "Configuration updated successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

