import smtplib
import psycopg2
from flask import Flask, request, jsonify
import imaplib
import email
from psycopg2 import sql
from datetime import datetime
from email.header import decode_header
from flask_cors import CORS
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import os

app = Flask(__name__)
CORS(app)


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


def clean(text):
    # Clean text for creating a folder
    return "".join(c if c.isalnum() else "_" for c in text)


@app.route('/fetch_emails', methods=['POST'])
def fetch_emails():
    data = request.json
    email_address = data.get('email')
    password = data.get('password')
    imap_server = data.get('imap_server')

    if not email_address or not password or not imap_server:
        return jsonify({"error": "Missing required fields"}), 400

    try:
        # Create an IMAP4 client authenticated with SSL
        imap = imaplib.IMAP4_SSL(imap_server)

        # Authenticate
        imap.login(email_address, password)

        # Select the mailbox you want to read from
        imap.select("INBOX")

        # Search for emails
        _, message_numbers = imap.search(None, "ALL")

        # Prepare the response structure
        response = {"inboxItems": []}

        for num in message_numbers[0].split()[:10]:  # Limit to 10 emails
            _, msg_data = imap.fetch(num, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    email_body = response_part[1]
                    email_message = email.message_from_bytes(email_body)

                    # Decode the email subject
                    subject, encoding = decode_header(email_message["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding if encoding else "utf-8")

                    # Get the sender
                    from_ = email_message.get("From")

                    # Get the received date
                    received_date = email_message.get('Date')

                    # Get the email body
                    if email_message.is_multipart():
                        for part in email_message.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode()
                                break
                    else:
                        body = email_message.get_payload(decode=True).decode()

                    # Add email details to the response structure
                    response["inboxItems"].append({
                        'subject': subject,
                        'sender': from_,
                        'body': body,
                        'receivedDate': received_date
                    })

        # Close the connection
        imap.close()
        imap.logout()

        return jsonify(response)

    except Exception as e:
        print(str(e))
        return jsonify({"error": str(e)}), 500


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


@app.route('/send_email', methods=['POST'])
def send_email():
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

        # Insert record into inquiry_details table
        insert_query = """
        INSERT INTO inquiry_details (sent_on, subject, distribution_name, responses_received)
        VALUES (%s, %s, %s, %s)
        """
        cursor.execute(insert_query, (datetime.now(), subject, distribution_name, 0))
        conn.commit()

        return jsonify({"message": "Email sent successfully and inquiry details recorded!"}), 200

    except Exception as e:
        print(str(e))
        return jsonify({"error": str(e)}), 500

    finally:
        if conn:
            cursor.close()
            conn.close()


@app.route('/fetch_freight_inquiries', methods=['GET'])
def fetch_freight_inquiries():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Query to fetch all distribution lists
        cursor.execute("select id, sent_on, subject, distribution_name, sent_to, responses_received,lowest_quote from inquiry_details")
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
                'lowest_quote': list_item[6]
            })

        # Close the connection
        cursor.close()
        conn.close()

        return jsonify(lists_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
