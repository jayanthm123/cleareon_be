from flask import Blueprint, request, jsonify
from psycopg2 import sql
from datetime import datetime

# Import utility functions
from utilities import get_db_connection

inquiries_bp = Blueprint('inquiries', __name__)


@inquiries_bp.route('/store_new_inquiry', methods=['POST'])
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


@inquiries_bp.route('/update_inquiry_status/<int:id>', methods=['PUT'])
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


@inquiries_bp.route('/fetch_freight_inquiries', methods=['GET'])
def fetch_freight_inquiries():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
        SELECT 
        id.id, 
        id.sent_on, 
        id.subject, 
        id.distribution_name, 
        id.sent_to, 
        COALESCE(reply_count.responses_received, 0) as responses_received,
        MIN(ies.quote) as quote,   -- Get the minimum quote for each inquiry
        id.status
        FROM 
            inquiry_details id
        JOIN 
            inquiry_emails_sent ies ON ies.inquiry_id = id.id
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
        GROUP BY 
            id.id, id.sent_on, id.subject, id.distribution_name, id.sent_to, reply_count.responses_received, id.status
        ORDER BY 
            id.sent_on DESC;
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
