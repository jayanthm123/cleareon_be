from flask import Blueprint, request, jsonify
from psycopg2 import sql
from datetime import datetime

from psycopg2.extras import DictCursor

from auth import check_session
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
        distribution_group = data.get('distribution_group')  # This is the group name (using 'name' column)

        # Validate required fields
        if not all([subject, body, sender_email, distribution_group]):
            return jsonify({"error": "Missing required fields"}), 400

        # Fetch all distribution lists with the given group name (using 'name' column)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, emails FROM distribution_lists 
            WHERE name = %s
        """, (distribution_group,))
        lists = cursor.fetchall()

        if not lists:
            return jsonify({"error": "No distribution lists found for the group"}), 404

        # Calculate total distribution lists (not individual emails)
        total_lists = len(lists)

        # Insert a single record into emails_inquiry_summary for the entire group
        insert_query = """
            INSERT INTO emails_inquiry_summary (sent_on, subject, distribution_name, mail_content, Status, sent_to)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        cursor.execute(insert_query, (
            datetime.now(), subject, distribution_group, mail_content, "Pending", total_lists
        ))
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

        # Validate required fields
        if not new_status:
            return jsonify({"error": "New status is required"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # Create dynamic SQL update query
        update_fields = [sql.SQL("status = %s")]
        update_values = [new_status]

        # Add id to the values for the WHERE clause
        update_values.append(id)
        query = sql.SQL("UPDATE emails_inquiry_summary SET {} WHERE id = %s RETURNING id").format(
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
            emails_inquiry_summary id
        JOIN 
            emails_inquiry_emails_sent ies ON ies.inquiry_id = id.id
        LEFT JOIN (
            SELECT 
                inquiry_id, 
                COUNT(reply_mail_id) as responses_received
            FROM 
                emails_inquiry_emails_sent
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
        print(len(lists_data), "Returned inquiries")
        return jsonify(lists_data), 200

    except Exception as e:
        print(f"Error in fetch_freight_inquiries: {str(e)}")
        return jsonify({"error": str(e)}), 500


@inquiries_bp.route('/fetch_inquiry_replies/<int:inquiry_id>', methods=['GET'])
@check_session  # Add this decorator to require login
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
            FROM emails_inquiry_emails_sent i
            LEFT JOIN emails_inbox pe ON pe.id = i.reply_mail_id
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
