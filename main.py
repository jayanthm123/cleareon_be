from flask import Flask, request, jsonify
import imaplib
import email
from email.header import decode_header
from flask_cors import CORS

app = Flask(__name__)
CORS(app)


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
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)