from flask import Blueprint
import psycopg2

utilities_bp = Blueprint('utilities', __name__)


@utilities_bp.route('testbp', methods=['GET'])
def testbp():
    return "working"


def get_db_connection():
    """Establish and return a database connection."""
    conn = psycopg2.connect(
        host="pg-3c0f63d9-cleareon.l.aivencloud.com",
        database="cleareon_db",
        user="avnadmin",
        password="AVNS_mPoJaHeUZxZjg-eWQ_p",
        port="22635",
        sslmode="require"
    )
    return conn
