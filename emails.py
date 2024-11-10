import email
import imaplib
import os
import smtplib
import time
from email.header import decode_header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid, parsedate_to_datetime

import psycopg2
from flask import Blueprint, request, jsonify
from psycopg2 import sql
from datetime import datetime, timezone
from psycopg2._json import Json
from psycopg2.extras import DictCursor

from AI import get_quote_from_response
from config import get_tenant_config, update_tenant_config

emails_bp = Blueprint('emails', __name__)


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


@emails_bp.route('/store_email_template', methods=['POST'])
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


@emails_bp.route('/fetch_email_templates', methods=['GET'])
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
@emails_bp.route('/update_email_template/<int:id>', methods=['PUT'])
def update_email_template(template_id):
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
        update_values.append(template_id)

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


@emails_bp.route('/store_distribution_list', methods=['POST'])
def store_distribution_list():
    try:
        data = request.get_json()
        group_name = data.get('name')
        emails = data.get('emails')
        ccEmails = data.get('ccEmails')
        list_name = data.get('list_label', '')  # Label describing the distribution list

        if not group_name or not emails or not isinstance(emails, list):
            return jsonify({"error": "Group name and a list of emails are required"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        query = sql.SQL(
            "INSERT INTO distribution_lists (name, emails, ccEmails, list_name, created_at) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id")
        cursor.execute(query, (group_name, emails, ccEmails, list_name, datetime.now()))
        new_id = cursor.fetchone()[0]
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({
            "message": "Distribution list created successfully!",
            "id": new_id,
            "name": group_name,
            "emails": emails,
            "ccEmails": ccEmails,
            "list_label": list_name
        }), 201

    except Exception as e:
        print(str(e))
        return jsonify({"error": str(e)}), 500


@emails_bp.route('/fetch_distribution_lists', methods=['GET'])
def fetch_distribution_lists():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, name, emails, ccEmails, list_name "
            "FROM distribution_lists "
            "ORDER BY name"
        )
        lists = cursor.fetchall()

        grouped_data = {}
        for list_item in lists:
            group_name = list_item[1]
            if group_name not in grouped_data:
                grouped_data[group_name] = []

            grouped_data[group_name].append({
                'id': list_item[0],
                'emails': list_item[2],
                'ccEmails': list_item[3],
                'list_label': list_item[4]
            })

        lists_data = [
            {
                'group_name': group_name,
                'distributions': distributions
            }
            for group_name, distributions in grouped_data.items()
        ]

        cursor.close()
        conn.close()

        return jsonify(lists_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@emails_bp.route('/update_distribution_list/<int:dist_list_id>', methods=['PUT'])
def update_distribution_list(dist_list_id):
    try:
        data = request.get_json()
        group_name = data.get('name')
        emails = data.get('emails')
        ccEmails = data.get('ccEmails')
        list_label = data.get('list_label')

        if not any([group_name, emails, ccEmails, list_label]):
            return jsonify({
                "error": "At least one of the fields (name, emails, ccEmails, list_label) must be provided to update"
            }), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        update_fields = []
        update_values = []

        if group_name:
            update_fields.append(sql.SQL("name = %s"))
            update_values.append(group_name)
        if emails:
            update_fields.append(sql.SQL("emails = %s"))
            update_values.append(emails)
        if ccEmails:
            update_fields.append(sql.SQL("ccEmails = %s"))
            update_values.append(ccEmails)
        if list_label:
            update_fields.append(sql.SQL("list_label = %s"))
            update_values.append(list_label)

        update_values.append(dist_list_id)

        query = sql.SQL("UPDATE distribution_lists SET {} WHERE id = %s").format(
            sql.SQL(", ").join(update_fields)
        )

        cursor.execute(query, update_values)
        conn.commit()

        if cursor.rowcount == 0:
            return jsonify({"error": "Distribution list not found"}), 404

        cursor.close()
        conn.close()

        return jsonify({"message": "Distribution list updated successfully!"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# New endpoint to fetch distinct group names
@emails_bp.route('/fetch_groups', methods=['GET'])
def fetch_groups():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT DISTINCT name FROM distribution_lists ORDER BY name"
        )
        groups = cursor.fetchall()

        cursor.close()
        conn.close()

        return jsonify([group[0] for group in groups]), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@emails_bp.route('/delete_distribution_list/<int:id>', methods=['DELETE', 'OPTIONS'])
def delete_distribution_list(id):
    if request.method == 'OPTIONS':
        # Handling OPTIONS request for CORS
        return '', 200

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if the distribution list exists
        cursor.execute("SELECT id FROM distribution_lists WHERE id = %s", (id,))
        if not cursor.fetchone():
            return jsonify({"error": "Distribution list not found"}), 404

        # Delete the distribution list
        cursor.execute("DELETE FROM distribution_lists WHERE id = %s", (id,))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"message": "Distribution list deleted successfully"}), 200

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
        attachments = data.get('attachments', [])  # List of file paths
        wait_time = data.get('wait_time', 1)  # Default wait time of 1 second

        # Validate required fields
        if not all([subject, body, sender_email, sender_password, distribution_list_id, inquiry_id]):
            return jsonify({"error": "Missing required fields"}), 400

        # Establish a database connection
        conn = get_db_connection()
        cursor = conn.cursor()

        # Fetch the distribution list from the database
        cursor.execute("SELECT name, emails, ccemails FROM distribution_lists WHERE id = %s", (distribution_list_id,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "Distribution list not found"}), 404

        distribution_name, to_emails, cc_emails = result
        cursor.close()  # Close the cursor after fetching the data

        # Convert emails from lists (array in database) to comma-separated strings
        to_emails_list = to_emails  # Already a list
        cc_emails_list = cc_emails if cc_emails else []  # Default to empty list if None

        # Create SMTP connection
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:  # Adjust SMTP server as needed
            server.login(sender_email, sender_password)

            successful_sends = 0
            failed_sends = 0

            msg = MIMEMultipart()
            msg['From'] = sender_email
            msg['To'] = ', '.join(to_emails_list)  # All To emails in one string
            if cc_emails_list:
                msg['Cc'] = ', '.join(cc_emails_list)  # Cc emails in one string
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

            # Recipients: Combined To and Cc emails
            recipients = to_emails_list + cc_emails_list  # Combine both lists

            # Attempt to send email with retries
            send_success = False
            for attempt in range(3):  # 3 attempts: initial + 2 retries
                try:
                    server.send_message(msg, to_addrs=recipients)
                    send_success = True
                    message_id = msg['Message-ID']
                    successful_sends += 1
                    # Insert a single record for this distribution list
                    insert_inquiry_emails_sent(
                        conn,
                        inquiry_id,
                        message_id,
                        datetime.now(),
                        subject,
                        ', '.join(to_emails_list),  # Insert comma-separated To emails
                        ', '.join(cc_emails_list) if cc_emails_list else None  # Insert comma-separated Cc emails
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
                    ', '.join(to_emails_list),  # Log comma-separated To emails
                    ', '.join(cc_emails_list) if cc_emails_list else None,
                    body
                )

            # Wait before sending the next email
            time.sleep(wait_time)

        conn.close()  # Close the database connection after use
        return jsonify({
            "message": f"Email sending completed. Successful: {successful_sends}, Failed: {failed_sends}"
        }), 200

    except Exception as e:
        print(str(e))
        return jsonify({"error": str(e)}), 500


def insert_inquiry_emails_sent(conn, inquiry_id, message_id, sent_on, subject, to_email, cc):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO emails_inquiry_emails_sent (inquiry_id, message_id, sent_on, subject, to_email, cc)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (inquiry_id, message_id, sent_on, subject, to_email, cc))
    conn.commit()


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


def insert_failed_email(conn, inquiry_id, tried_on, subject, to_email, cc, mail_content):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO failed_emails (inquiry_id, tried_on, subject, to_email, cc, mail_content)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (inquiry_id, tried_on, subject, to_email, cc, mail_content))
    conn.commit()


def find_and_store_email_replies():
    print('starting')
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)

        # Fetch all sent inquiry emails
        cursor.execute("SELECT id, message_id, subject, inquiry_id, to_email FROM emails_inquiry_emails_sent")
        sent_emails = cursor.fetchall()

        # Fetch all unprocessed emails
        cursor.execute("SELECT id, headers, subject, sender, body_text FROM emails_inbox WHERE isReplyProcessed = FALSE")
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
                                        UPDATE emails_inquiry_emails_sent 
                                        SET quote = %s 
                                        WHERE id = %s
                                    """, (quote, sent_id))

        # Update the database with the reply information
        for sent_id, reply_id in replies.items():
            cursor.execute("""
                UPDATE emails_inquiry_emails_sent 
                SET reply_mail_id = %s 
                WHERE id = %s
            """, (reply_id, sent_id))

        # Mark all processed emails as processed, whether they're replies or not
        for processed_id in all_processed_ids:
            cursor.execute("""
                UPDATE emails_inbox 
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


@emails_bp.route('/fetch_and_store_emails', methods=['POST'])
def fetch_and_store_emails():
    try:
        data = request.json
        email_address = data.get('email')
        password = data.get('password')
        imap_server = data.get('imap_server')
        imap = imaplib.IMAP4_SSL(imap_server)
        imap.login(email_address, password)
        imap.select('INBOX')
        last_refresh = get_tenant_config('default', 'default', 'last_refresh_datetime')
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
                        INSERT INTO emails_inbox 
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
        update_tenant_config('default', 'default', 'last_refresh_datetime', datetime.now(timezone.utc).isoformat())
        find_and_store_email_replies()
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
        cur.execute("SELECT * FROM emails_inbox ORDER BY received_date DESC")
        emails = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify([dict(email) for email in emails]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

