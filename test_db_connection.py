import pyodbc

SERVER = r"(localdb)\MSSQLLocalDB"
DATABASE = "RetailDemandDB"

connection_string = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    "Trusted_Connection=yes;"
)

try:
    conn = pyodbc.connect(connection_string)

    print("✅ Connected to RetailDemandDB successfully.")

    cursor = conn.cursor()

    # Stores count
    cursor.execute(
        "SELECT COUNT(*) FROM dbo.Stores"
    )
    total_stores = cursor.fetchone()[0]

    # Product families count
    cursor.execute(
        "SELECT COUNT(*) FROM dbo.ProductFamilies"
    )
    total_families = cursor.fetchone()[0]

    # Active model
    cursor.execute("""
        SELECT
            model_name,
            model_version,
            test_wape
        FROM dbo.ModelRegistry
        WHERE is_active = 1
    """)

    active_model = cursor.fetchone()

    print("\n=== DATABASE CHECK ===")
    print("Stores:", total_stores)
    print("Product Families:", total_families)

    if active_model:
        print("\nActive Model:")
        print("Name:", active_model[0])
        print("Version:", active_model[1])
        print("Test WAPE:", active_model[2])

    cursor.close()
    conn.close()

    print("\n✅ Database connection test passed.")

except Exception as e:
    print("❌ Database connection failed.")
    print(e)