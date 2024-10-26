from flask import Blueprint, request, jsonify
from psycopg2 import sql
from psycopg2.extras import DictCursor
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.utils import make_msgid
import smtplib
import time
import os
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from psycopg2._json import Json

# Import utility functions
from utilities import get_db_connection, insert_failed_email, insert_inquiry_emails_sent, get_client_config, \
    update_client_config

emails_bp = Blueprint('emails', __name__)


@emails_bp.route('/store_email_template', methods=['POST'])
def create_template():
    try:
        data = request.get_json()
        name = data['name']
        subject = data['subject']
        content = data['content']

        if not name or not subject or not content:
            return jsonify({"error": "All fields (name, subject, content) are required"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        query = sql.SQL("INSERT INTO email_templates (name, subject, content, created_at) VALUES (%s, %s, %s, %s)")
        cursor.execute(query, (name, subject, content, datetime.now()))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"message": "Template created successfully!"}), 201

    except Exception as e:
        print(str(e))
        return jsonify({"error": str(e)}), 500


@emails_bp.route('/fetch_email_templates', methods=['GET'])
def fetch_email_templates():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id, name, subject, content FROM email_templates")
        templates = cursor.fetchall()

        templates_data = []
        for template in templates:
            templates_data.append({
                'id': template[0],
                'name': template[1],
                'subject': template[2],
                'content': template[3]
            })

        cursor.close()
        conn.close()

        return jsonify(templates_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@emails_bp.route('/update_email_template/<int:id>', methods=['PUT'])
def update_email_template(id):
    try:
        data = request.get_json()
        name = data.get('name')
        subject = data.get('subject')
        content = data.get('content')

        if not name and not subject and not content:
            return jsonify(
                {"error": "At least one of the fields (name, subject, content) must be provided to update"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

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

        update_values.append(id)

        query = sql.SQL("UPDATE email_templates SET {} WHERE id = %s").format(sql.SQL(", ").join(update_fields))

        cursor.execute(query, update_values)
        conn.commit()

        if cursor.rowcount == 0:
            return jsonify({"error": "Template not found"}), 404

        cursor.close()
        conn.close()

        return jsonify({"message": "Template updated successfully!"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@emails_bp.route('/send_email', methods=['POST'])
def send_email():
    try:
        data = request.get_json()
        subject = data.get('subject')
        body = data.get('body')
        sender_email = data.get('sender_email')
        sender_password = data.get('sender_password')
        distribution_list_id = data.get('distribution_list_id')
        inquiry_id = data.get('inquiry_id')
        attachments = data.get('attachments', [])
        wait_time = data.get('wait_time', 1)

        if not all([subject, body, sender_email, sender_password, distribution_list_id, inquiry_id]):
            return jsonify({"error": "Missing required fields"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name, emails, ccEmails FROM distribution_lists WHERE id = %s", (distribution_list_id,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "Distribution list not found"}), 404

        distribution_name, to_emails, cc_emails = result

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)

            successful_sends = 0
            failed_sends = 0

            for to_email in to_emails:
                msg = MIMEMultipart()
                msg['From'] = sender_email
                msg['To'] = to_email
                if cc_emails:
                    msg['Cc'] = ', '.join(cc_emails)
                msg['Subject'] = subject
                msg['Message-ID'] = make_msgid(domain=sender_email.split('@')[1])
                msg.attach(MIMEText(body, 'html'))

                for attachment in attachments:
                    with open(attachment, "rb") as file:
                        part = MIMEApplication(file.read(), Name=os.path.basename(attachment))
                    part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment)}"'
                    msg.attach(part)

                recipients = [to_email] + cc_emails if cc_emails else [to_email]

                send_success = False
                for attempt in range(3):
                    try:
                        server.send_message(msg, to_addrs=recipients)
                        send_success = True
                        message_id = msg['Message-ID']
                        successful_sends += 1
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
                        if attempt < 2:
                            time.sleep(15 if attempt == 0 else 30)

                if not send_success:
                    failed_sends += 1
                    insert_failed_email(
                        conn,
                        inquiry_id,
                        datetime.now(),
                        subject,
                        to_email,
                        ', '.join(cc_emails) if cc_emails else None,
                        body
                    )

                time.sleep(wait_time)

        conn.close()
        return jsonify({
            "message": f"Email sending completed. Successful: {successful_sends}, Failed: {failed_sends}"
        }), 200

    except Exception as e:
        print(str(e))
        return jsonify({"error": str(e)}), 500


def parse_email(msg):
    subject = decode_header(msg["Subject"])[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()

    sender = msg["From"]
    recipient = msg["To"]
    cc = msg.get("Cc", "").split(",") if msg.get("Cc") else []
    bcc = msg.get("Bcc", "").split(",") if msg.get("Bcc") else []

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


@emails_bp.route('/fetch_and_store_emails', methods=['POST'])
def fetch_and_store_emails():
    try:
        data = request.json
        email_address = get_client_config('default', 'default', 'email_address')
        password = get_client_config('default', 'default', 'email_password')
        imap_server = get_client_config('default', 'default', 'imap_server')
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


@emails_bp.route('/get_processed_emails', methods=['GET'])
def get_processed_emails():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT * FROM processed_emails ORDER BY received_date DESC")
        emails = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify([dict(_email) for _email in emails]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def monitor_mailbox():
    try:
        email_address = get_client_config('default', 'default', 'email_address')
        password = get_client_config('default', 'default', 'email_password')
        imap_server = get_client_config('default', 'default', 'imap_server')
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

    except Exception as e:
        print(str(e))
