import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, request, jsonify
from datetime import datetime

jobs_bp = Blueprint('jobs', __name__)


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


def generate_job_id():
    """Generate a unique job ID in format IYYYYMMDD###"""
    conn = get_db_connection()
    cur = conn.cursor()

    today = datetime.utcnow().strftime('%Y%m%d')
    base = f"I{today}"

    # Find latest job ID for today
    cur.execute("""
        SELECT job_id FROM import_jobs 
        WHERE job_id LIKE %s 
        ORDER BY job_id DESC LIMIT 1
    """, (f"{base}%",))

    result = cur.fetchone()

    if result:
        sequence = int(result[0][-3:]) + 1
    else:
        sequence = 1

    cur.close()
    conn.close()

    return f"{base}{sequence:03d}"


@jobs_bp.route('/generate-job-id', methods=['GET'])
def generate_job_id_api():
    try:
        job_id = generate_job_id()
        return jsonify({'jobId': job_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@jobs_bp.route('/import-jobs', methods=['GET'])
def get_import_jobs():
    try:
        # Get query parameters
        status = request.args.get('status')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        search = request.args.get('search')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build the WHERE clause
        where_clauses = ["is_deleted = FALSE"]
        params = []

        if status:
            where_clauses.append("status = %s")
            params.append(status)

        if start_date:
            where_clauses.append("created_date >= %s")
            params.append(start_date)

        if end_date:
            where_clauses.append("created_date <= %s")
            params.append(end_date)

        if search:
            where_clauses.append("""
                (job_id ILIKE %s OR 
                importer_name ILIKE %s OR 
                invoice_number ILIKE %s)
            """)
            search_term = f"%{search}%"
            params.extend([search_term, search_term, search_term])

        # Calculate pagination
        offset = (page - 1) * per_page
        params.extend([per_page, offset])

        # Build and execute query
        where_clause = " AND ".join(where_clauses)
        query = f"""
            SELECT 
                job_id,
                created_date,
                status,
                importer_name,
                iec_no,
                invoice_number,
                arrival_date,
                be_type,
                transport_mode,
                custom_house
            FROM import_jobs 
            WHERE {where_clause}
            ORDER BY created_date DESC
            LIMIT %s OFFSET %s
        """

        cur.execute(query, params)
        jobs = cur.fetchall()

        # Get total count
        count_query = f"SELECT COUNT(*) FROM import_jobs WHERE {where_clause}"
        cur.execute(count_query, params[:-2])  # Exclude LIMIT and OFFSET params
        total = cur.fetchone()['count']

        cur.close()
        conn.close()

        return jsonify({
            'jobs': jobs,
            'total': total,
            'pages': (total + per_page - 1) // per_page,
            'current_page': page
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@jobs_bp.route('/import-jobs/<job_id>', methods=['GET'])
def get_import_job(job_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT * FROM import_jobs 
            WHERE job_id = %s AND is_deleted = FALSE
        """, (job_id,))

        job = cur.fetchone()

        cur.close()
        conn.close()

        if not job:
            return jsonify({'error': 'Import job not found'}), 404

        return jsonify(job)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@jobs_bp.route('/import-jobs', methods=['POST'])
def create_import_job():
    try:
        data = request.json
        conn = get_db_connection()
        cur = conn.cursor()

        # Generate new job ID
        job_id = generate_job_id()

        cur.execute("""
            INSERT INTO import_jobs (
                job_id, mode, importer_name, iec_no, ad_code,
                address_line1, address_line2, city, state, zip_code,
                origin_country, shipping_country, port_of_origin, port_of_shipment,
                invoice_number, exporter_name, arrival_date, created_by,
                be_type, transport_mode, custom_house
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s
            )
        """, (
            job_id, data.get('mode'), data.get('importer_name'),
            data.get('iec_no'), data.get('ad_code'),
            data.get('address_line1'), data.get('address_line2'),
            data.get('city'), data.get('state'), data.get('zip_code'),
            data.get('origin_country'), data.get('shipping_country'),
            data.get('port_of_origin'), data.get('port_of_shipment'),
            data.get('invoice_number'), data.get('exporter_name'),
            data.get('arrival_date'), data.get('created_by', 'SYSTEM'),
            data.get('be_type'), data.get('transport_mode'), data.get('custom_house')
        ))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'message': 'Import job created successfully',
            'job_id': job_id
        }), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@jobs_bp.route('/import-jobs/<job_id>', methods=['PUT'])
def update_import_job(job_id):
    try:
        data = request.json
        conn = get_db_connection()
        cur = conn.cursor()

        # Build UPDATE query dynamically based on provided fields
        update_fields = []
        params = []

        for field in [
            'mode', 'status', 'importer_name', 'iec_no', 'ad_code',
            'address_line1', 'address_line2', 'city', 'state', 'zip_code',
            'origin_country', 'shipping_country', 'port_of_origin',
            'port_of_shipment', 'invoice_number', 'exporter_name',
            'arrival_date', 'be_type', 'transport_mode', 'custom_house'
        ]:
            if field in data:
                update_fields.append(f"{field} = %s")
                params.append(data[field])

        # Add audit fields
        update_fields.extend([
            "modified_by = %s",
            "modified_datetime = CURRENT_TIMESTAMP"
        ])
        params.extend([data.get('modified_by', 'SYSTEM'), job_id])

        query = f"""
            UPDATE import_jobs 
            SET {', '.join(update_fields)}
            WHERE job_id = %s AND is_deleted = FALSE
        """

        cur.execute(query, params)

        if cur.rowcount == 0:
            return jsonify({'error': 'Import job not found'}), 404

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'message': 'Import job updated successfully',
            'job_id': job_id
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@jobs_bp.route('/import-jobs/<job_id>', methods=['DELETE'])
def delete_import_job(job_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            UPDATE import_jobs 
            SET 
                is_deleted = TRUE,
                modified_by = %s,
                modified_datetime = CURRENT_TIMESTAMP
            WHERE job_id = %s AND is_deleted = FALSE
        """, (request.args.get('modified_by', 'SYSTEM'), job_id))

        if cur.rowcount == 0:
            return jsonify({'error': 'Import job not found'}), 404

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'message': 'Import job deleted successfully',
            'job_id': job_id
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
