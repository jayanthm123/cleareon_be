import smtplib
import time
from datetime import datetime, timezone
import psycopg2
from flask import Flask, request, jsonify
import imaplib
import email
from email.policy import default
from apscheduler.schedulers.background import BackgroundScheduler
from flask.cli import load_dotenv
from psycopg2 import sql
from datetime import datetime
from email.header import decode_header
from flask_cors import CORS
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import os

from psycopg2._json import Json
from psycopg2.extras import DictCursor
from email.utils import parsedate_to_datetime, make_msgid

load_dotenv()
app = Flask(__name__)
CORS(app)


def my_scheduled_job():
    # Your task logic here
    print("Scheduled function is running every 10 minutes")

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

        # Query to fetch all distribution lists
        cursor.execute(
            "select id, sent_on, subject, distribution_name, sent_to, responses_received,lowest_quote, status from inquiry_details")
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
        print("Starting")
        data = request.json
        email_address = data.get('email')
        password = data.get('password')
        imap_server = data.get('imap_server')

        imap = imaplib.IMAP4_SSL(imap_server)
        imap.login(email_address, password)
        imap.select('INBOX')
        print(imap.capabilities)

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
        return jsonify([dict(email) for email in emails]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# New route to update client configuration
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


def monitor_mailbox():
    try:
        print("Starting")
        data = request.json
        email_address = 'cleareontestmailbox@gmail.com'
        password = 'awiqwxcxapuaxdxl'
        imap_server = 'imap.gmail.com'

        # Connect to the IMAP server
        imap = imaplib.IMAP4_SSL(imap_server)
        imap.login(email_address, password)
        imap.select('INBOX')
        print(imap.capabilities)

        # Store the last refresh datetime
        last_refresh = get_client_config('default', 'default', 'last_refresh_datetime')
        last_refresh = datetime.fromisoformat(last_refresh)

        # Function to process new messages
        def process_new_messages():
            search_criterion = f'(SINCE "{last_refresh.strftime("%d-%b-%Y")}")'
            _, messages = imap.search(None, search_criterion)

            conn = get_db_connection()
            cur = conn.cursor()
            ctr = 0

            for num in messages[0].split():
                _, msg_data = imap.fetch(num, '(RFC822)')
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        ctr += 1
                        msg = email.message_from_bytes(response_part[1], policy=default)
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
            return ctr

        # Continuous monitoring using IDLE
        while True:
            # Start the IDLE command
            imap.idle()
            print("Waiting for new emails...")

            # Wait for new mail notifications
            while True:
                try:
                    # Wait for an email to arrive
                    imap.idle_check(timeout=300)  # 5-minute timeout
                    new_email_count = process_new_messages()
                    if new_email_count > 0:
                        print(f"{new_email_count} new emails processed")
                        # Update last refresh datetime
                        update_client_config('default', 'default', 'last_refresh_datetime',
                                             datetime.now(timezone.utc).isoformat())
                except imaplib.IMAP4.error as idle_error:
                    print(f"Error during IDLE: {idle_error}")
                    break  # Break the inner loop to re-establish IDLE

            # Re-establish IDLE connection after timeout or error
            print("Re-establishing IDLE connection...")
            imap.idle_done()
            time.sleep(1)  # Delay before re-establishing

    except Exception as e:
        print(str(e))
        return jsonify({"error": str(e)}), 500
    finally:
        imap.close()
        imap.logout()


@app.route('/start_monitoring', methods=['POST'])
def start_monitoring():
    # Call the mailbox monitoring function
    response = monitor_mailbox()
    return response


if __name__ == '__main__':
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=my_scheduled_job, trigger="interval", minutes=1)
    scheduler.start()

    try:
        app.run(debug=True)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()