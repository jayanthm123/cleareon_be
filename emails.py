import psycopg2
from flask import Blueprint, request, jsonify
from psycopg2 import sql
from psycopg2.extras import DictCursor
from datetime import datetime

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


@emails_bp.route('/store_distribution_list', methods=['POST'])
def store_distribution_list():
    try:
        data = request.get_json()
        group_name = data.get('name')
        emails = data.get('emails')
        ccEmails = data.get('ccEmails')
        list_label = data.get('list_label', '')  # Label describing the distribution list

        if not group_name or not emails or not isinstance(emails, list):
            return jsonify({"error": "Group name and a list of emails are required"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        query = sql.SQL(
            "INSERT INTO distribution_lists (name, emails, ccEmails, list_label, created_at) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id")
        cursor.execute(query, (group_name, emails, ccEmails, list_label, datetime.now()))
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
            "list_label": list_label
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
            "SELECT id, name, emails, ccEmails, list_label "
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


@emails_bp.route('/update_distribution_list/<int:id>', methods=['PUT'])
def update_distribution_list(id):
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

        update_values.append(id)

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
