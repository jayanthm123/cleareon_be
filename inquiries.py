from flask import Blueprint, request, jsonify
from psycopg2 import sql
from datetime import datetime

# Import utility functions
from utilities import get_db_connection, execute_query

inquiries_bp = Blueprint('inquiries', __name__)


@inquiries_bp.route('/store_distribution_list', methods=['POST'])
def store_distribution_list():
    try:
        data = request.get_json()
        name = data.get('name')
        emails = data.get('emails')
        ccEmails = data.get('ccEmails')

        if not name or not emails or not isinstance(emails, list):
            return jsonify({"error": "Name and a list of emails are required"}), 400

        query = """
            INSERT INTO distribution_lists (name, emails, ccEmails, created_at) 
            VALUES (%s, %s, %s, %s) RETURNING id
        """
        result = execute_query(query, (name, emails, ccEmails, datetime.now()), fetch=True)
        new_id = result[0]['id']

        return jsonify({
            "message": "Distribution list created successfully!",
            "id": new_id,
            "name": name,
            "emails": emails,
            "ccEmails": ccEmails
        }), 201

    except Exception as e:
        print(str(e))
        return jsonify({"error": str(e)}), 500


@inquiries_bp.route('/fetch_distribution_lists', methods=['GET'])
def fetch_distribution_lists():
    try:
        query = "SELECT id, name, emails, ccEmails FROM distribution_lists"
        lists = execute_query(query)

        lists_data = [{
            'id': list_item['id'],
            'name': list_item['name'],
            'emails': list_item['emails'],
            'ccEmails': list_item['ccemails']
        } for list_item in lists]

        return jsonify(lists_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@inquiries_bp.route('/update_distribution_list/<int:id>', methods=['PUT'])
def update_distribution_list(id):
    try:
        data = request.get_json()
        name = data.get('name')
        emails = data.get('emails')
        ccEmails = data.get('ccEmails')

        if not name and not emails and not ccEmails:
            return jsonify(
                {"error": "At least one of the fields (name, emails, ccEmails) must be provided to update"}), 400

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

        update_values.append(id)

        query = sql.SQL("UPDATE distribution_lists SET {} WHERE id = %s").format(sql.SQL(", ").join(update_fields))
        result = execute_query(query, update_values, fetch=False)

        if result is None:
            return jsonify({"error": "Distribution list not found"}), 404

        return jsonify({"message": "Distribution list updated successfully!"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@inquiries_bp.route('/store_new_inquiry', methods=['POST'])
def store_new_inquiry():
    try:
        data = request.get_json()
        subject = data.get('subject')
        body = data.get('body')
        sender_email = data.get('sender_email')
        mail_content = data.get('mail_content')
        distribution_list_id = data.get('distribution_list_id')

        if not all([subject, body, sender_email, distribution_list_id]):
            return jsonify({"error": "Missing required fields"}), 400

        # Fetch the distribution list
        dist_query = "SELECT name, emails FROM distribution_lists WHERE id = %s"
        dist_result = execute_query(dist_query, (distribution_list_id,))

        if not dist_result:
            return jsonify({"error": "Distribution list not found"}), 404

        distribution_name, to_emails = dist_result[0]['name'], dist_result[0]['emails']
        total_to_emails = len(to_emails)
        print("tester1")
        # Insert record into inquiry_details table
        insert_query = """
            INSERT INTO inquiry_details (sent_on, subject, distribution_name, mail_content, responses_received, Status, sent_to)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        result = execute_query(insert_query,
                               (datetime.now(), subject, distribution_name, mail_content, 0, "Pending",
                                str(total_to_emails)),
                               fetch=True
                               )
        new_inquiry_id = result[0]['id']
        print(new_inquiry_id)
        return jsonify({
            "message": "Inquiry stored successfully!",
            "inquiry_id": new_inquiry_id
        }), 200

    except Exception as e:
        print(f"Error in store_new_inquiry: {str(e)}")
        return jsonify({"error": str(e)}), 500


@inquiries_bp.route('/update_inquiry_status/<int:id>', methods=['PUT'])
def update_inquiry_status(id):
    try:
        data = request.get_json()
        new_status = data.get('status')
        responses_received = data.get('responses_received')
        lowest_quote = data.get('lowest_quote')

        if not new_status:
            return jsonify({"error": "New status is required"}), 400

        update_fields = ["status = %s"]
        update_values = [new_status]

        if responses_received is not None:
            update_fields.append("responses_received = %s")
            update_values.append(responses_received)

        if lowest_quote is not None:
            update_fields.append("lowest_quote = %s")
            update_values.append(lowest_quote)

        update_values.append(id)

        query = f"UPDATE inquiry_details SET {', '.join(update_fields)} WHERE id = %s RETURNING id"
        result = execute_query(query, update_values, fetch=True)

        if not result:
            return jsonify({"error": "Inquiry not found"}), 404

        return jsonify({
            "message": "Inquiry status updated successfully!",
            "inquiry_id": result[0]['id'],
            "new_status": new_status
        }), 200

    except Exception as e:
        print(f"Error in update_inquiry_status: {str(e)}")
        return jsonify({"error": str(e)}), 500


@inquiries_bp.route('/fetch_freight_inquiries', methods=['GET'])
def fetch_freight_inquiries():
    try:
        query = """
            SELECT id, sent_on, subject, distribution_name, sent_to, responses_received, lowest_quote, status 
            FROM inquiry_details
        """
        inquiries = execute_query(query)

        inquiries_data = [{
            'id': inquiry['id'],
            'sent_on': inquiry['sent_on'],
            'subject': inquiry['subject'],
            'distribution_name': inquiry['distribution_name'],
            'sent_to': inquiry['sent_to'],
            'responses_received': inquiry['responses_received'],
            'lowest_quote': inquiry['lowest_quote'],
            'status': inquiry['status']
        } for inquiry in inquiries]

        return jsonify(inquiries_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500