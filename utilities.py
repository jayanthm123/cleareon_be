import imaplib
import email
import psycopg2
from psycopg2._json import Json
from psycopg2.extras import DictCursor
from datetime import datetime


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


def insert_failed_email(conn, inquiry_id, tried_on, subject, to_email, cc, mail_content):
    """Insert a record of a failed email attempt into the database."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO failed_emails (inquiry_id, tried_on, subject, to_email, cc, mail_content)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (inquiry_id, tried_on, subject, to_email, cc, mail_content))
    conn.commit()


def insert_inquiry_emails_sent(conn, inquiry_id, message_id, sent_on, subject, to_email, cc):
    """Insert a record of a sent inquiry email into the database."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO inquiry_emails_sent (inquiry_id, message_id, sent_on, subject, to_email, cc)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (inquiry_id, message_id, sent_on, subject, to_email, cc))
    conn.commit()


def get_client_config(client_id, client_account_id, config_key):
    """Retrieve a client configuration value from the database."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT config_value FROM client_config 
        WHERE client_id = %s AND client_account_id = %s AND config_key = %s
    """, (client_id, client_account_id, config_key))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result[0] if result else None


def update_client_config(client_id, client_account_id, config_key, config_value):
    """Update or insert a client configuration value in the database."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO client_config (client_id, client_account_id, config_key, config_value)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (client_id, client_account_id, config_key) 
        DO UPDATE SET config_value = EXCLUDED.config_value
    """, (client_id, client_account_id, config_key, config_value))
    conn.commit()
    cur.close()
    conn.close()


def execute_query(query, params=None, fetch=True):
    """Execute a database query and optionally return results."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    try:
        if params:
            cur.execute(query, params)
        else:
            cur.execute(query)

        if fetch:
            result = cur.fetchall()
        else:
            result = None
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()
    return result


def format_datetime(dt):
    """Format a datetime object to a string."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_datetime(dt_string):
    """Parse a datetime string to a datetime object."""
    return datetime.strptime(dt_string, "%Y-%m-%d %H:%M:%S")

