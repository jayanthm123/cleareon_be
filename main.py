from datetime import timezone, timedelta
from flask import Flask, request, jsonify
import imaplib
import email
from flask_cors import CORS, cross_origin
import os
import logging
from logging.handlers import RotatingFileHandler
from psycopg2._json import Json
from psycopg2.extras import DictCursor
from utilities import utilities_bp
from inquiries import inquiries_bp
from sitecontrols import sitecontrol_bp
from emails import emails_bp
from auth import auth_bp
import psycopg2
import uuid
from argon2 import PasswordHasher
from datetime import datetime
from AI import get_quote_from_response

app = Flask(__name__)
app.register_blueprint(utilities_bp, url_prefix='/')
app.register_blueprint(inquiries_bp, url_prefix='/')
app.register_blueprint(sitecontrol_bp, url_prefix='/')
app.register_blueprint(auth_bp, url_prefix='/')
app.register_blueprint(emails_bp, url_prefix='/')

# Configuration

app.config['SECRET_KEY'] = 'your-secure-secret-key'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['SESSION_COOKIE_SECURE'] = True        # Ensures cookies are only sent over HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True      # Prevents JavaScript access to cookies
app.config['SESSION_COOKIE_SAMESITE'] = 'None'    # Allows cross-site cookies
app.config['SESSION_COOKIE_PATH'] = '/'           # Ensures the cookie is available on all routes

# Configure logging
if not os.path.exists('logs'):
    os.mkdir('logs')
file_handler = RotatingFileHandler('logs/app.log', maxBytes=10240, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)

# Enable CORS
CORS(
    app,
    supports_credentials=True,
    origins=['http://localhost:3000'],  # Your frontend URL
    methods=['GET', 'POST', 'OPTIONS'],
    allow_headers=['Content-Type', 'Authorization']
)

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


def get_client_config(client_id, client_account_id, config_key):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT config_value FROM client_config 
        WHERE client_id = %s AND client_account_id = %s AND config_key = %s
    """, (client_id, client_account_id, config_key))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result[0] if result else None


def update_client_config(client_id, client_account_id, config_key, config_value):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO client_config (client_id, client_account_id, config_key, config_value)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (client_id, client_account_id, config_key) 
        DO UPDATE SET config_value = EXCLUDED.config_value
    """, (client_id, client_account_id, config_key, config_value))
    conn.commit()
    cur.close()
    conn.close()


@app.route('/fetch_and_store_emails', methods=['POST'])
def fetch_and_store_emails():
    try:
        data = request.json
        email_address = data.get('email')
        password = data.get('password')
        imap_server = data.get('imap_server')
        imap = imaplib.IMAP4_SSL(imap_server)
        imap.login(email_address, password)
        imap.select('INBOX')
        last_refresh = get_client_config('default', 'default', 'last_refresh_datetime')
        last_refresh = datetime.fromisoformat(last_refresh)
        search_criterion = f'(SINCE "{last_refresh.strftime("%d-%b-%Y")}")'

        _, messages = imap.search(None, search_criterion)

        conn = get_db_connection()
        cur = conn.cursor()
        ctr = 0
        for num in messages[0].split():
            _, msg_data = imap.fetch(num, '(RFC822)')
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    ctr = ctr + 1
                    msg = email.message_from_bytes(response_part[1])
                    email_data = parse_email(msg)
                    cur.execute("""
                        INSERT INTO processed_emails 
                        (message_id, subject, sender, recipient, cc, bcc, received_date, body_text, body_html, headers, attachments, folder)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (message_id) DO NOTHING
                    """, (
                        email_data['message_id'],
                        email_data['subject'],
                        email_data['sender'],
                        email_data['recipient'],
                        email_data['cc'],
                        email_data['bcc'],
                        email_data['received_date'],
                        email_data['body_text'],
                        email_data['body_html'],
                        Json(email_data['headers']),
                        Json(email_data['attachments']),
                        'INBOX'
                    ))
        conn.commit()
        cur.close()
        conn.close()
        imap.close()
        imap.logout()
        update_client_config('default', 'default', 'last_refresh_datetime', datetime.now(timezone.utc).isoformat())
        find_and_store_email_replies()
        print(f"{ctr} new emails processed")
        return jsonify({"message": "Emails fetched and stored successfully"}), 200

    except Exception as e:
        print(str(e))
        return jsonify({"error": str(e)}), 500


@app.route('/get_processed_emails', methods=['GET'])
def get_processed_emails():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT * FROM processed_emails ORDER BY received_date DESC")
        emails = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify([dict(email) for email in emails]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/update_client_config', methods=['POST'])
def update_config():
    try:
        data = request.json
        client_id = data.get('client_id')
        client_account_id = data.get('client_account_id')
        config_key = data.get('config_key')
        config_value = data.get('config_value')

        if not all([client_id, client_account_id, config_key, config_value]):
            return jsonify({"error": "Missing required parameters"}), 400

        update_client_config(client_id, client_account_id, config_key, config_value)
        return jsonify({"message": "Configuration updated successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def find_and_store_email_replies():
    print('starting')
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)

        # Fetch all sent inquiry emails
        cursor.execute("SELECT id, message_id, subject, inquiry_id, to_email FROM inquiry_emails_sent")
        sent_emails = cursor.fetchall()

        # Fetch all unprocessed emails
        cursor.execute("SELECT id, headers, subject, sender, body_text FROM processed_emails WHERE isReplyProcessed = "
                       "FALSE")
        processed_emails = cursor.fetchall()

        # Dictionary to store the results
        replies = {}

        # Set to keep track of all processed email IDs
        all_processed_ids = set()

        for sent_email in sent_emails:
            sent_id = sent_email['id']
            sent_message_id = sent_email['message_id']
            sent_subject = sent_email['subject']
            sent_to = sent_email['to_email']
            inquiry_id = sent_email['inquiry_id']

            for processed_email in processed_emails:
                processed_id = processed_email['id']
                headers = processed_email['headers']
                processed_subject = processed_email['subject']
                from_addr = processed_email['sender'][
                            processed_email['sender'].find('<') + 1:processed_email['sender'].find('>')]
                email_text = processed_email['body_text']
                # Add this processed email ID to the set of all processed IDs
                all_processed_ids.add(processed_id)

                # Check if the processed email is a reply to the sent email
                is_reply = False
                if 'In-Reply-To' in headers and headers['In-Reply-To'] == sent_message_id:
                    is_reply = True
                elif 'References' in headers and sent_message_id in headers['References']:
                    is_reply = True
                elif (from_addr == sent_to and processed_subject.lower().startswith('re:') and
                      processed_subject[3:].strip() == sent_subject.strip()):
                    is_reply = True

                if is_reply:
                    replies[sent_id] = processed_id
                    quote = get_quote_from_response(email_text)
                    print(quote)
                    if quote != 'Unable to determine':
                        cursor.execute("""
                                        UPDATE inquiry_emails_sent 
                                        SET quote = %s 
                                        WHERE id = %s
                                    """, (quote, sent_id))

        # Update the database with the reply information
        for sent_id, reply_id in replies.items():
            cursor.execute("""
                UPDATE inquiry_emails_sent 
                SET reply_mail_id = %s 
                WHERE id = %s
            """, (reply_id, sent_id))

        # Mark all processed emails as processed, whether they're replies or not
        for processed_id in all_processed_ids:
            cursor.execute("""
                UPDATE processed_emails 
                SET isReplyProcessed = TRUE 
                WHERE id = %s
            """, (processed_id,))

        conn.commit()
        cursor.close()
        conn.close()

        return f"Processed {len(replies)} replies. Marked {len(all_processed_ids)} emails as processed."

    except Exception as e:
        print(f"Error in find_and_store_email_replies: {str(e)}")
        return f"Error: {str(e)}"


@app.route('/fetch_inquiry_replies/<int:inquiry_id>', methods=['GET'])
def fetch_inquiry_replies(inquiry_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)

        # Fetch the inquiry and its replies
        cursor.execute("""
            SELECT 
                i.inquiry_id AS id,
                i.subject AS subject,
                i.to_email AS sent_to,
                i.sent_on AS sent_date,
                i.quote AS quote,
                pe.id AS reply_id,
                pe.subject AS reply_subject,
                pe.sender AS reply_sender,
                pe.received_date AS reply_date,
                pe.body_text AS body_text,
                pe.body_html AS body_html
            FROM inquiry_emails_sent i
            LEFT JOIN processed_emails pe ON pe.id = i.reply_mail_id
            WHERE i.inquiry_id = %s
            ORDER BY pe.received_date IS NULL, pe.received_date DESC 
        """, (inquiry_id,))

        results = cursor.fetchall()

        cursor.close()
        conn.close()

        if not results:
            return jsonify({"error": "Inquiry not found"}), 404

        # Process the results
        sent_items = []
        for row in results:
            sent_items.append({
                'id': row['id'],
                'subject': row['subject'],
                'sent_to': row['sent_to'],
                'quote': row['quote'],
                'sent_date': row['sent_date'].isoformat() if row['sent_date'] else None,
                'replied': 'Yes' if row['reply_id'] else 'No',
                'reply_received_on': row['reply_date'].isoformat() if row['reply_date'] else 'Not Applicable',
                'body_text': row['body_text'],
                'body_html': row['body_html']
            })

        return jsonify({'sent_items': sent_items}), 200
    except Exception as e:
        print(f"Error in fetch_inquiry_replies: {str(e)}")
        return jsonify({"error": str(e)}), 500


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
            # Insert system client
            client_id = str(uuid.uuid4())
            cursor.execute("""
                INSERT INTO clients (client_id, company_name)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                RETURNING client_id
            """, (client_id, 'System Admin'))

            client_id_result = cursor.fetchone()
            if client_id_result is None:
                # If insert failed, try to find existing System Admin client
                cursor.execute("""
                    SELECT client_id FROM clients WHERE company_name = %s
                """, ('System Admin',))
                client_id = cursor.fetchone()[0]
            else:
                client_id = client_id_result[0]

            # Create the admin user
            cursor.execute("""
                INSERT INTO users (
                    user_id,
                    username,
                    email,
                    password_hash,
                    role_id,
                    client_id
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (email) 
                DO UPDATE SET 
                    password_hash = EXCLUDED.password_hash,
                    username = EXCLUDED.username
                RETURNING user_id, email, username
            """, (admin_id, admin_username, admin_email, password_hash, 1, client_id))

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


@app.route('/users/<string:user_id>', methods=['PUT'])
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


@app.route('/users/<string:user_id>', methods=['DELETE'])
def delete_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "User deleted successfully"})


# Role routes
@app.route('/roles', methods=['GET'])
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


@app.route('/roles', methods=['POST'])
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


@app.route('/roles/<int:role_id>', methods=['GET'])
def get_role(role_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM roles WHERE role_id = %s", (role_id,))
    role = cur.fetchone()
    cur.close()
    conn.close()
    return jsonify(dict(role)) if role else ("Role not found", 404)


@app.route('/roles/<int:role_id>', methods=['PUT'])
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


@app.route('/roles/<int:role_id>', methods=['DELETE'])
def delete_role(role_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM roles WHERE role_id = %s", (role_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Role deleted successfully"})


# Permission routes
@app.route('/permissions', methods=['GET'])
def get_permissions():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM permissions")
    permissions = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(permission) for permission in permissions])


@app.route('/permissions', methods=['POST'])
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


@app.route('/permissions/<int:permission_id>', methods=['GET'])
def get_permission(permission_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM permissions WHERE permission_id = %s", (permission_id,))
    permission = cur.fetchone()
    cur.close()
    conn.close()
    return jsonify(dict(permission)) if permission else ("Permission not found", 404)


@app.route('/permissions/<int:permission_id>', methods=['PUT'])
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


@app.route('/permissions/<int:permission_id>', methods=['DELETE'])
def delete_permission(permission_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM permissions WHERE permission_id = %s", (permission_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Permission deleted successfully"})


@app.route('/api/test', methods=['GET'])
def test_route():
    return jsonify({"message": "API is working!"})


@app.route('/')
def health_check():
    return {"status": "healthy, new comment"}


# if __name__ == '__main__':
# setup_admin()
#    app.run(debug=True, use_reloader=False, threaded=False)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
