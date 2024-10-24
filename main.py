import smtplib
import time
from datetime import datetime, timezone, timedelta
import psycopg2
from flask import Flask, request, jsonify
import imaplib
import email
from flask_jwt_extended import jwt_required, get_jwt_identity, JWTManager, create_access_token
from psycopg2.errors import DatabaseError
from flask.cli import load_dotenv
from psycopg2 import sql
from email.header import decode_header
from flask_cors import CORS
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import os
import logging
from logging.handlers import RotatingFileHandler
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from psycopg2._json import Json
from psycopg2.extras import DictCursor, RealDictCursor
from email.utils import parsedate_to_datetime, make_msgid
from psycopg2.extras import DictCursor
import uuid
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError


app = Flask(__name__)

# Configuration
app.config['JWT_SECRET_KEY'] = 'your-super-secret-key'  # Change this in production!
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(minutes=10)
app.config['DATABASE_URL'] = "postgresql://user:password@localhost:5432/dbname"
app.config['MAX_LOGIN_ATTEMPTS'] = 5
app.config['LOGIN_ATTEMPT_TIMEOUT'] = 300  # 5 minutes in seconds

# Initialize extensions
jwt = JWTManager(app)
ph = PasswordHasher()
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="memory://"  # Using in-memory storage for rate limiting
)

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

# Initialize SQLAlchemy
engine = create_engine(app.config['DATABASE_URL'])
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Enable CORS
CORS(app)


# Database session management
@app.before_request
def create_db_session():
    app.db_session = SessionLocal()


@app.teardown_appcontext
def close_db_session(exception=None):
    db_session = getattr(app, 'db_session', None)
    if db_session is not None:
        db_session.close()


# Create sessions table
def create_sessions_table(db):
    """Create sessions table if it doesn't exist"""
    query = text("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            session_id UUID PRIMARY KEY,
            user_id UUID NOT NULL,
            token TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            is_active BOOLEAN DEFAULT TRUE
        )
    """)
    db.execute(query)
    db.commit()


# Helper Functions
def get_user_permissions(user_id, db):
    """Get user permissions from database"""
    query = text("""
        SELECT DISTINCT p.permission_name 
        FROM permissions p
        JOIN role_permissions rp ON p.permission_id = rp.permission_id
        JOIN users u ON u.role_id = rp.role_id
        WHERE u.user_id = :user_id
    """)
    result = db.execute(query, {'user_id': user_id})
    return [row[0] for row in result]


def check_client_term_date(client_id, db):
    """Check if client's term date is valid"""
    query = text("""
        SELECT term_date 
        FROM clients 
        WHERE client_id = :client_id
    """)
    result = db.execute(query, {'client_id': client_id}).first()
    if result and result[0]:
        return datetime.now().date() <= result[0]
    return True


def invalidate_user_sessions(user_id, db):
    """Invalidate all active sessions for a user"""
    query = text("""
        UPDATE user_sessions 
        SET is_active = FALSE 
        WHERE user_id = :user_id AND is_active = TRUE
    """)
    db.execute(query, {'user_id': user_id})
    db.commit()


def create_user_session(user_id, token, expires_at, db):
    """Create a new session for a user"""
    query = text("""
        INSERT INTO user_sessions (session_id, user_id, token, expires_at)
        VALUES (:session_id, :user_id, :token, :expires_at)
    """)
    session_id = uuid.uuid4()
    db.execute(query, {
        'session_id': session_id,
        'user_id': user_id,
        'token': token,
        'expires_at': expires_at
    })
    db.commit()
    return session_id


def is_token_revoked(token, db):
    """Check if a token is revoked"""
    query = text("""
        SELECT EXISTS(
            SELECT 1 
            FROM user_sessions 
            WHERE token = :token 
            AND is_active = FALSE
        )
    """)
    result = db.execute(query, {'token': token}).scalar()
    return result


# Auth Routes
@app.route('/login', methods=['POST'])
@limiter.limit(f"{app.config['MAX_LOGIN_ATTEMPTS']}/5 minutes")
def login():
    print('starting')
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({'error': 'Missing credentials'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        query = sql.SQL("SELECT u.user_id, u.password_hash, u.client_id, u.email,r.role_name, c.company_name "
                        "FROM users u JOIN roles r ON u.role_id = r.role_id JOIN clients c "
                        "ON u.client_id = c.client_id WHERE u.email = %s")
        cursor.execute(query, (username,))
        result = cursor.fetchone()
        print(result)
        if not result:
            return jsonify({'error': 'Invalid credentials'}), 401

        user_id, password_hash, client_id, email, role_name, company_name = result

        # Verify password
        try:
            ph.verify(password_hash, password)
        except VerifyMismatchError:
            return jsonify({'error': 'Invalid credentials'}), 401

        # Check client term date
        if not check_client_term_date(client_id, db):
            return jsonify({'error': 'Account expired'}), 403

        # Get user permissions
        permissions = get_user_permissions(user_id, db)

        # Create user identity
        user_identity = {
            'user_id': str(user_id),
            'username': username,
            'email': email,
            'role': role_name,
            'client_id': str(client_id),
            'company_name': company_name,
            'permissions': permissions
        }

        # Create access token
        access_token = create_access_token(identity=user_identity)
        expires_at = datetime.now(timezone.utc) + app.config['JWT_ACCESS_TOKEN_EXPIRES']

        # Invalidate old sessions
        invalidate_user_sessions(user_id, db)

        # Create new session
        create_user_session(user_id, access_token, expires_at, db)

        return jsonify({
            'access_token': access_token,
            'user': user_identity
        }), 200

    except Exception as e:
        app.logger.error(f"Login error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/logout', methods=['POST'])
def logout():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or 'Bearer' not in auth_header:
            return jsonify({'error': 'Missing token'}), 401

        token = auth_header.split(' ')[1]
        user_identity = get_jwt_identity()
        user_id = user_identity['user_id']

        # Invalidate the session in database
        db = app.db_session
        query = text("""
            UPDATE user_sessions 
            SET is_active = FALSE 
            WHERE user_id = :user_id 
            AND token = :token
        """)
        db.execute(query, {'user_id': user_id, 'token': token})
        db.commit()

        return jsonify({'message': 'Successfully logged out'}), 200

    except Exception as e:
        app.logger.error(f"Logout error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


# JWT token validation
@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    token = jwt_payload["jti"]
    db = app.db_session
    return is_token_revoked(token, db)


# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return {'error': 'Not Found'}, 404


@app.errorhandler(500)
def internal_error(error):
    app.db_session.rollback()
    return {'error': 'Internal Server Error'}, 500


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


@app.route('/store_email_template', methods=['POST'])
def create_template():
    try:
        # Get JSON data from the request
        data = request.get_json()
        name = data['name']
        subject = data['subject']
        content = data['content']

        # Validate the required fields
        if not name or not subject or not content:
            return jsonify({"error": "All fields (name, subject, content) are required"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        query = sql.SQL("INSERT INTO email_templates (name, subject, content, created_at) VALUES (%s, %s, %s, %s)")
        cursor.execute(query, (name, subject, content, datetime.now()))
        conn.commit()

        # Close the connection
        cursor.close()
        conn.close()

        return jsonify({"message": "Template created successfully!"}), 201

    except Exception as e:
        print(str(e))
        return jsonify({"error": str(e)}), 500


@app.route('/fetch_email_templates', methods=['GET'])
def fetch_email_templates():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Query to fetch all email templates
        cursor.execute("SELECT id, name, subject, content FROM email_templates")
        templates = cursor.fetchall()

        # Format the data into a dictionary
        templates_data = []
        for template in templates:
            templates_data.append({
                'id': template[0],
                'name': template[1],
                'subject': template[2],
                'content': template[3]
            })

        # Close the connection
        cursor.close()
        conn.close()

        return jsonify(templates_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Update email template route
@app.route('/update_email_template/<int:id>', methods=['PUT'])
def update_email_template(id):
    try:
        data = request.get_json()
        name = data.get('name')
        subject = data.get('subject')
        content = data.get('content')

        # Validate the required fields
        if not name and not subject and not content:
            return jsonify(
                {"error": "At least one of the fields (name, subject, content) must be provided to update"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # Create dynamic SQL update query
        update_fields = []
        update_values = []

        if name:
            update_fields.append(sql.SQL("name = %s"))
            update_values.append(name)
        if subject:
            update_fields.append(sql.SQL("subject = %s"))
            update_values.append(subject)
        if content:
            update_fields.append(sql.SQL("content = %s"))
            update_values.append(content)

        # Add id to the values for the WHERE clause
        update_values.append(id)

        query = sql.SQL("UPDATE email_templates SET {} WHERE id = %s").format(sql.SQL(", ").join(update_fields))

        cursor.execute(query, update_values)
        conn.commit()

        # Check if any row was updated
        if cursor.rowcount == 0:
            return jsonify({"error": "Template not found"}), 404

        # Close the connection
        cursor.close()
        conn.close()

        return jsonify({"message": "Template updated successfully!"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/store_distribution_list', methods=['POST'])
def store_distribution_list():
    try:
        data = request.get_json()
        name = data.get('name')
        emails = data.get('emails')
        ccEmails = data.get('ccEmails')

        # Validate the required fields
        if not name or not emails or not isinstance(emails, list):
            return jsonify({"error": "Name and a list of emails are required"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        query = sql.SQL(
            "INSERT INTO distribution_lists (name, emails, ccEmails, created_at) VALUES (%s, %s, %s, %s) RETURNING id")
        cursor.execute(query, (name, emails, ccEmails, datetime.now()))
        new_id = cursor.fetchone()[0]
        conn.commit()

        # Close the connection
        cursor.close()
        conn.close()

        return jsonify(
            {"message": "Distribution list created successfully!", "id": new_id, "name": name, "emails": emails,
             "ccEmails": ccEmails}), 201

    except Exception as e:
        print(str(e))
        return jsonify({"error": str(e)}), 500


# New route to fetch all distribution lists
@app.route('/fetch_distribution_lists', methods=['GET'])
def fetch_distribution_lists():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Query to fetch all distribution lists
        cursor.execute("SELECT id, name, emails ,ccEmails FROM distribution_lists")
        lists = cursor.fetchall()

        # Format the data into a dictionary
        lists_data = []
        for list_item in lists:
            lists_data.append({
                'id': list_item[0],
                'name': list_item[1],
                'emails': list_item[2],
                'ccEmails': list_item[3]
            })

        # Close the connection
        cursor.close()
        conn.close()

        return jsonify(lists_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/store_new_inquiry', methods=['POST'])
def store_new_inquiry():
    try:
        data = request.get_json()
        subject = data.get('subject')
        body = data.get('body')
        sender_email = data.get('sender_email')
        mail_content = data.get('mail_content')
        distribution_list_id = data.get('distribution_list_id')

        # Validate required fields
        if not all([subject, body, sender_email, distribution_list_id]):
            return jsonify({"error": "Missing required fields"}), 400

        # Fetch the distribution list
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name, emails, ccEmails FROM distribution_lists WHERE id = %s", (distribution_list_id,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "Distribution list not found"}), 404

        distribution_name, to_emails, cc_emails = result
        # Calculate the number of email addresses in the TO list
        # to_emails_list = to_emails.split(",")
        total_to_emails = len(to_emails)

        # Insert record into inquiry_details table
        insert_query = """
            INSERT INTO inquiry_details (sent_on, subject, distribution_name, mail_content, responses_received,Status, sent_to)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """
        cursor.execute(insert_query,
                       (datetime.now(), subject, distribution_name, mail_content, 0, "Pending", str(total_to_emails)))
        new_inquiry_id = cursor.fetchone()[0]
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({
            "message": "Inquiry stored successfully!",
            "inquiry_id": new_inquiry_id
        }), 200

    except Exception as e:
        print(f"Error in store_new_inquiry: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/update_inquiry_status/<int:id>', methods=['PUT'])
def update_inquiry_status(id):
    try:
        data = request.get_json()
        new_status = data.get('status')
        responses_received = data.get('responses_received')
        lowest_quote = data.get('lowest_quote')

        # Validate required fields
        if not new_status:
            return jsonify({"error": "New status is required"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # Create dynamic SQL update query
        update_fields = [sql.SQL("status = %s")]
        update_values = [new_status]

        if responses_received is not None:
            update_fields.append(sql.SQL("responses_received = %s"))
            update_values.append(responses_received)

        if lowest_quote is not None:
            update_fields.append(sql.SQL("lowest_quote = %s"))
            update_values.append(lowest_quote)

        # Add id to the values for the WHERE clause
        update_values.append(id)

        query = sql.SQL("UPDATE inquiry_details SET {} WHERE id = %s RETURNING id").format(
            sql.SQL(", ").join(update_fields))

        cursor.execute(query, update_values)
        updated_id = cursor.fetchone()
        conn.commit()

        # Check if any row was updated
        if not updated_id:
            return jsonify({"error": "Inquiry not found"}), 404

        # Close the connection
        cursor.close()
        conn.close()

        return jsonify({
            "message": "Inquiry status updated successfully!",
            "inquiry_id": updated_id[0],
            "new_status": new_status
        }), 200

    except Exception as e:
        print(f"Error in update_inquiry_status: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/update_distribution_list/<int:id>', methods=['PUT'])
def update_distribution_list(id):
    try:
        data = request.get_json()
        name = data.get('name')
        emails = data.get('emails')
        ccEmails = data.get('ccEmails')

        # Validate the required fields
        if not name and not emails and not ccEmails:
            return jsonify(
                {"error": "At least one of the fields (name, emails, ccEmails) must be provided to update"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # Create dynamic SQL update query
        update_fields = []
        update_values = []

        if name:
            update_fields.append(sql.SQL("name = %s"))
            update_values.append(name)
        if emails:
            update_fields.append(sql.SQL("emails = %s"))
            update_values.append(emails)
        if ccEmails:
            update_fields.append(sql.SQL("ccEmails = %s"))
            update_values.append(ccEmails)

        # Add id to the values for the WHERE clause
        update_values.append(id)

        query = sql.SQL("UPDATE distribution_lists SET {} WHERE id = %s").format(sql.SQL(", ").join(update_fields))

        cursor.execute(query, update_values)
        conn.commit()

        # Check if any row was updated
        if cursor.rowcount == 0:
            return jsonify({"error": "Distribution list not found"}), 404

        # Close the connection
        cursor.close()
        conn.close()

        return jsonify({"message": "Distribution list updated successfully!"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/send_email_generic', methods=['POST'])  # use this to send general email later if required
def send_email_():
    try:
        data = request.get_json()
        subject = data.get('subject')
        body = data.get('body')
        sender_email = data.get('sender_email')
        sender_password = data.get('sender_password')
        distribution_list_id = data.get('distribution_list_id')
        attachments = data.get('attachments', [])  # List of file paths

        # Validate required fields
        if not all([subject, body, sender_email, sender_password, distribution_list_id]):
            return jsonify({"error": "Missing required fields"}), 400

        # Fetch the distribution list
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name, emails, ccEmails FROM distribution_lists WHERE id = %s", (distribution_list_id,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "Distribution list not found"}), 404

        distribution_name, to_emails, cc_emails = result

        # Create the email
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = ', '.join(to_emails)
        if cc_emails:
            msg['Cc'] = ', '.join(cc_emails)
        msg['Subject'] = subject

        # Attach the body
        msg.attach(MIMEText(body, 'html'))

        # Attach files
        for attachment in attachments:
            with open(attachment, "rb") as file:
                part = MIMEApplication(file.read(), Name=os.path.basename(attachment))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment)}"'
            msg.attach(part)

        # Send the email
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:  # Adjust SMTP server as needed
            server.login(sender_email, sender_password)
            server.send_message(msg)

        return jsonify({"message": "Email sent successfully!"}), 200

    except Exception as e:
        print(str(e))
        return jsonify({"error": str(e)}), 500


def insert_failed_email(conn, inquiry_id, tried_on, subject, to_email, cc, mail_content):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO failed_emails (inquiry_id, tried_on, subject, to_email, cc, mail_content)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (inquiry_id, tried_on, subject, to_email, cc, mail_content))
    conn.commit()


def insert_inquiry_emails_sent(conn, inquiry_id, message_id, sent_on, subject, to_email, cc):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO inquiry_emails_sent (inquiry_id, message_id, sent_on, subject, to_email, cc)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (inquiry_id, message_id, sent_on, subject, to_email, cc))
    conn.commit()


@app.route('/send_email', methods=['POST'])
def send_email():
    try:
        data = request.get_json()
        subject = data.get('subject')
        body = data.get('body')
        sender_email = data.get('sender_email')
        sender_password = data.get('sender_password')
        distribution_list_id = data.get('distribution_list_id')
        inquiry_id = data.get('inquiry_id')
        attachments = data.get('attachments', [])  # List of file paths
        wait_time = data.get('wait_time', 1)  # Default wait time of 1 second

        # Validate required fields
        if not all([subject, body, sender_email, sender_password, distribution_list_id, inquiry_id]):
            return jsonify({"error": "Missing required fields"}), 400

        # Fetch the distribution list
        conn = get_db_connection()
        cursor = conn.cursor()
        print("step 1")
        cursor.execute("SELECT name, emails, ccEmails FROM distribution_lists WHERE id = %s", (distribution_list_id,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "Distribution list not found"}), 404

        distribution_name, to_emails, cc_emails = result

        # Create SMTP connection
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:  # Adjust SMTP server as needed
            server.login(sender_email, sender_password)

            successful_sends = 0
            failed_sends = 0

            # Send individual emails to each recipient in the To list
            for to_email in to_emails:
                msg = MIMEMultipart()
                msg['From'] = sender_email
                msg['To'] = to_email
                if cc_emails:
                    msg['Cc'] = ', '.join(cc_emails)
                msg['Subject'] = subject
                msg['Message-ID'] = make_msgid(domain=sender_email.split('@')[1])
                # Attach the body
                msg.attach(MIMEText(body, 'html'))

                # Attach files
                for attachment in attachments:
                    with open(attachment, "rb") as file:
                        part = MIMEApplication(file.read(), Name=os.path.basename(attachment))
                    part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment)}"'
                    msg.attach(part)

                recipients = [to_email] + cc_emails if cc_emails else [to_email]

                # Attempt to send email with retries
                send_success = False
                for attempt in range(3):  # 3 attempts: initial + 2 retries
                    try:
                        server.send_message(msg, to_addrs=recipients)
                        send_success = True
                        message_id = msg['Message-ID']
                        successful_sends += 1
                        print(message_id)
                        insert_inquiry_emails_sent(
                            conn,
                            inquiry_id,
                            message_id,
                            datetime.now(),
                            subject,
                            to_email,
                            ', '.join(cc_emails) if cc_emails else None
                        )
                        break
                    except Exception as e:
                        print(f"Attempt {attempt + 1} failed: {str(e)}")
                        if attempt < 2:  # Don't sleep after the last attempt
                            time.sleep(15 if attempt == 0 else 30)

                if not send_success:
                    failed_sends += 1
                    # Log failed email
                    insert_failed_email(
                        conn,
                        inquiry_id,
                        datetime.now(),
                        subject,
                        to_email,
                        ', '.join(cc_emails) if cc_emails else None,
                        body
                    )

                # Wait before sending the next email
                time.sleep(wait_time)

        conn.close()
        return jsonify({
            "message": f"Email sending completed. Successful: {successful_sends}, Failed: {failed_sends}"
        }), 200

    except Exception as e:
        print(str(e))
        return jsonify({"error": str(e)}), 500


@app.route('/fetch_freight_inquiries', methods=['GET'])
def fetch_freight_inquiries():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Query to fetch freight inquiries with reply counts
        query = """
        SELECT 
            id.id, 
            id.sent_on, 
            id.subject, 
            id.distribution_name, 
            id.sent_to, 
            COALESCE(reply_count.responses_received, 0) as responses_received,
            id.lowest_quote, 
            id.status
        FROM 
            inquiry_details id
        LEFT JOIN (
            SELECT 
                inquiry_id, 
                COUNT(reply_mail_id) as responses_received
            FROM 
                inquiry_emails_sent
            WHERE 
                reply_mail_id IS NOT NULL
            GROUP BY 
                inquiry_id
        ) reply_count ON id.id = reply_count.inquiry_id
        ORDER BY 
            id.sent_on DESC
        """

        cursor.execute(query)
        lists = cursor.fetchall()

        # Format the data into a dictionary
        lists_data = []
        for list_item in lists:
            lists_data.append({
                'id': list_item[0],
                'sent_on': list_item[1],
                'subject': list_item[2],
                'distribution_name': list_item[3],
                'sent_to': list_item[4],
                'responses_received': list_item[5],
                'lowest_quote': list_item[6],
                'status': list_item[7]
            })

        # Close the connection
        cursor.close()
        conn.close()

        return jsonify(lists_data), 200

    except Exception as e:
        print(f"Error in fetch_freight_inquiries: {str(e)}")
        return jsonify({"error": str(e)}), 500


def parse_email(msg):
    subject = decode_header(msg["Subject"])[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()

    sender = msg["From"]
    recipient = msg["To"]
    cc = msg.get("Cc", "").split(",") if msg.get("Cc") else []
    bcc = msg.get("Bcc", "").split(",") if msg.get("Bcc") else []

    # Use email.utils.parsedate_to_datetime for more flexible date parsing
    received_date = parsedate_to_datetime(msg["Date"])

    body_text = ""
    body_html = ""
    attachments = []

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body_text += part.get_payload(decode=True).decode(errors='replace')
            elif part.get_content_type() == "text/html":
                body_html += part.get_payload(decode=True).decode(errors='replace')
            elif part.get_content_disposition() == 'attachment':
                attachments.append({
                    'filename': part.get_filename(),
                    'content_type': part.get_content_type(),
                    'size': len(part.get_payload(decode=True))
                })
    else:
        body_text = msg.get_payload(decode=True).decode(errors='replace')

    return {
        'message_id': msg["Message-ID"],
        'subject': subject,
        'sender': sender,
        'recipient': recipient,
        'cc': cc,
        'bcc': bcc,
        'received_date': received_date,
        'body_text': body_text,
        'body_html': body_html,
        'headers': dict(msg.items()),
        'attachments': attachments
    }


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
        find_and_store_email_replies()
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
        cursor.execute("SELECT id, message_id, subject, to_email FROM inquiry_emails_sent WHERE reply_mail_id IS NULL")
        sent_emails = cursor.fetchall()

        # Fetch all unprocessed emails
        cursor.execute("SELECT id, headers, subject, sender FROM processed_emails WHERE isReplyProcessed = FALSE")
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

            for processed_email in processed_emails:
                processed_id = processed_email['id']
                headers = processed_email['headers']
                processed_subject = processed_email['subject']
                from_addr = processed_email['sender'][
                            processed_email['sender'].find('<') + 1:processed_email['sender'].find('>')]

                # Add this processed email ID to the set of all processed IDs
                all_processed_ids.add(processed_id)

                # Check if the processed email is a reply to the sent email
                is_reply = False
                if 'In-Reply-To' in headers and headers['In-Reply-To'] == sent_message_id:
                    is_reply = True
                elif 'References' in headers and sent_message_id in headers['References']:
                    is_reply = True
                elif from_addr == sent_to and processed_subject.lower().startswith('re:') and processed_subject[
                                                                                              3:].strip() == sent_subject.strip():
                    is_reply = True

                if is_reply:
                    replies[sent_id] = processed_id

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


# User routes
@app.route('/users', methods=['GET'])
def get_users():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM users")
    users = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(user) for user in users])


@app.route('/users', methods=['POST'])
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


@app.route('/users/<string:user_id>', methods=['GET'])
def get_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return jsonify(dict(user)) if user else ("User not found", 404)


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
    print('I am being called')
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
        print(roles)
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


# Client routes
@app.route('/clients', methods=['GET'])
def get_clients():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM clients")
    clients = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(client) for client in clients])


@app.route('/clients', methods=['POST'])
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


@app.route('/clients/<string:client_id>', methods=['GET'])
def get_client(client_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM clients WHERE client_id = %s", (client_id,))
    client = cur.fetchone()
    cur.close()
    conn.close()
    return jsonify(dict(client)) if client else ("Client not found", 404)


@app.route('/clients/<string:client_id>', methods=['PUT'])
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


@app.route('/clients/<string:client_id>', methods=['DELETE'])
def delete_client(client_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM clients WHERE client_id = %s", (client_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Client deleted successfully"})


@app.route('/clients/<client_id>/users', methods=['GET'])
@jwt_required()
def get_client_users(client_id):
    """
    Get all users associated with a specific client.
    Returns user details including their roles.
    Requires either admin access or being a user of the specified client.
    """
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


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False, threaded=False)
