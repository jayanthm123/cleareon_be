from datetime import timezone, timedelta
from flask import Flask, request, jsonify, session
from flask_cors import CORS
import os
from utilities import utilities_bp
from inquiries import inquiries_bp
from sitecontrols import sitecontrol_bp
from jobs import jobs_bp
from emails import emails_bp
from auth import auth_bp, check_session
from mastersetup import master_setup_bp
import psycopg2
import uuid
from argon2 import PasswordHasher

app = Flask(__name__)
app.register_blueprint(utilities_bp, url_prefix='/')
app.register_blueprint(inquiries_bp, url_prefix='/')
app.register_blueprint(sitecontrol_bp, url_prefix='/')
app.register_blueprint(auth_bp, url_prefix='/')
app.register_blueprint(emails_bp, url_prefix='/')
app.register_blueprint(master_setup_bp, url_prefix='/')
app.register_blueprint(jobs_bp, url_prefix='/')


app.config.update(
    SECRET_KEY='your-secure-secret-key',
    SESSION_COOKIE_NAME='session_id',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
    SESSION_TYPE='filesystem',
    SESSION_COOKIE_SECURE=True,  # Must be False for localhost HTTP
    SESSION_COOKIE_HTTPONLY=True,
)

# Updated CORS configuration
CORS(app,
     supports_credentials=True,
     resources={
         r"/*": {
             "methods": ["GET", "POST", "PUT", "OPTIONS"],
             "allow_headers": ["Content-Type", "Authorization", "X-User-ID"],
             "expose_headers": ["Content-Type", "Authorization"],
             "supports_credentials": True
         }
     })


# Database connection
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


def setup_admin():
    conn = None
    try:
        # Initialize password hasher
        ph = PasswordHasher()

        # Generate admin credentials
        admin_id = str(uuid.uuid4())
        admin_email = input("Enter admin email: ")
        admin_username = input("Enter admin username: ")
        admin_password = input("Enter admin password: ")

        # Hash the password
        password_hash = ph.hash(admin_password)

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Insert system tenant
            tenant_id = str(uuid.uuid4())
            cursor.execute("""
                INSERT INTO tenants (tenant_id, tenant_name)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                RETURNING tenant_id
            """, (tenant_id, 'System Admin'))

            tenant_id_result = cursor.fetchone()
            if tenant_id_result is None:
                # If insert failed, try to find existing System Admin tenant
                cursor.execute("""
                    SELECT tenant_id FROM tenants WHERE company_name = %s
                """, ('System Admin',))
                tenant_id = cursor.fetchone()[0]
            else:
                tenant_id = tenant_id_result[0]

            # Create the admin user
            cursor.execute("""
                INSERT INTO users (
                    user_id,
                    username,
                    email,
                    password_hash,
                    role_id,
                    tenant_id
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (email) 
                DO UPDATE SET 
                    password_hash = EXCLUDED.password_hash,
                    username = EXCLUDED.username
                RETURNING user_id, email, username
            """, (admin_id, admin_username, admin_email, password_hash, 1, tenant_id))

            created_user = cursor.fetchone()

        conn.commit()
        print(f"\nAdmin account successfully created/updated:")
        print(f"Username: {created_user[2]}")
        print(f"Email: {created_user[1]}")
        print(f"User ID: {created_user[0]}")
        print("\nPlease save these credentials securely.")

    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Error creating admin account: {str(e)}")
        raise
    finally:
        if conn:
            conn.close()


@app.route('/')
def health_check():
    return {"status": "healthy"}


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
