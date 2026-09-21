import os
import pyodbc
from dotenv import load_dotenv

load_dotenv()

DB_SERVER = os.getenv("DB_SERVER")
DB_NAME = os.getenv("DB_NAME")
DB_DRIVER = os.getenv("DB_DRIVER")


def get_connection():
    connection_string = (
        f"DRIVER={{{DB_DRIVER}}};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_NAME};"
        "Trusted_Connection=yes;"
    )

    return pyodbc.connect(connection_string)


def test_connection():
    conn = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT DB_NAME()")
        database_name = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM dbo.Stores")
        stores = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM dbo.ProductFamilies")
        families = cursor.fetchone()[0]

        return {
            "status": "connected",
            "database": database_name,
            "stores": stores,
            "product_families": families
        }

    finally:
        if conn:
            conn.close()