from flask import Blueprint, jsonify, request
from config import get_db_connection

master_setup_bp = Blueprint('mastersetup', __name__)


@master_setup_bp.route('/clients', methods=['POST'])
def create_client():
    data = request.json
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Insert client into the master_clients table
        cursor.execute(
            """
            INSERT INTO master_clients (
                user_id, tenant_id, iec_no, company_name, address1, address2, city, district,
                pin_code, state, state_code, pan_no, gstin_id, import_ad_code, export_ad_code, remarks
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING client_id
            """,
            (
                data.get("user_id"), data.get("tenant_id"), data.get("iecNo"), data.get("companyName"),
                data.get("address1"), data.get("address2"), data.get("city"), data.get("district"),
                data.get("pinCode"), data.get("state"), data.get("stateCode"),
                data.get("panNo"), data.get("gstinId"), data.get("importADCode"),
                data.get("exportADCode"), data.get("remarks")
            )
        )
        client_id = cursor.fetchone()[0]

        # Insert contacts into master_client_contacts table
        contacts = data.get("contacts", [])
        for contact in contacts:
            cursor.execute(
                """
                INSERT INTO master_client_contacts (client_id, contact_person, phone_no, email)
                VALUES (%s, %s, %s, %s)
                """,
                (client_id, contact["contactPerson"], contact.get("phoneNo"), contact.get("email"))
            )

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"message": "Client and contacts created successfully", "client_id": client_id}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@master_setup_bp.route('/clients/<int:client_id>', methods=['PUT'])
def update_client(client_id):
    data = request.json

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Update client details
        update_fields = []
        update_values = []
        for field, value in data.items():
            if field != "contacts" and value is not None:
                update_fields.append(f"{field} = %s")
                update_values.append(value)

        if update_fields:
            update_values.append(client_id)
            cursor.execute(
                f"""
                UPDATE master_clients
                SET {', '.join(update_fields)}, updated_at = NOW()
                WHERE client_id = %s
                """,
                tuple(update_values)
            )

        # Handle contacts update: Remove existing contacts and add new ones
        if "contacts" in data:
            cursor.execute("DELETE FROM master_client_contacts WHERE client_id = %s", (client_id,))

            contacts = data.get("contacts", [])
            for contact in contacts:
                cursor.execute(
                    """
                    INSERT INTO master_client_contacts (client_id, contact_person, phone_no, email)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (client_id, contact["contactPerson"], contact.get("phoneNo"), contact.get("email"))
                )

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"message": "Client and contacts updated successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@master_setup_bp.route('/clients', methods=['GET'])
def get_clients():
    try:
        # Query to fetch clients
        query = """
        SELECT mc.client_id, mc.user_id, mc.tenant_id, mc.iec_no, mc.company_name,
               mc.address1, mc.address2, mc.city, mc.district, mc.pin_code,
               mc.state, mc.state_code, mc.pan_no, mc.gstin_id,
               mc.import_ad_code, mc.export_ad_code, mc.remarks,
               mc.created_at, mc.updated_at,
               json_agg(
                 json_build_object(
                   'contact_id', cc.contact_id,
                   'contact_person', cc.contact_person,
                   'phone_no', cc.phone_no,
                   'email', cc.email
                 )
               ) AS contacts
        FROM master_clients mc
        LEFT JOIN master_client_contacts cc ON mc.client_id = cc.client_id
        GROUP BY mc.client_id
        ORDER BY mc.created_at DESC;
        """

        # Execute the query
        conn = get_db_connection()
        cursor = conn.cursor()


        cursor.execute(query)
        clients = cursor.fetchall()

        # Convert the results into a list of dictionaries
        client_list = [
            {
                "client_id": row[0],
                "user_id": row[1],
                "tenant_id": row[2],
                "iec_no": row[3],
                "company_name": row[4],
                "address1": row[5],
                "address2": row[6],
                "city": row[7],
                "district": row[8],
                "pin_code": row[9],
                "state": row[10],
                "state_code": row[11],
                "pan_no": row[12],
                "gstin_id": row[13],
                "import_ad_code": row[14],
                "export_ad_code": row[15],
                "remarks": row[16],
                "created_at": row[17],
                "updated_at": row[18],
                "contacts": row[19] if row[19] is not None else []
            }
            for row in clients
        ]

        return jsonify(client_list), 200

    except Exception as e:
        print(f"Error fetching clients: {e}")
        return jsonify({"error": "Failed to fetch clients"}), 500
