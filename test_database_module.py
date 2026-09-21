from app.database import test_connection

result = test_connection()

print("=== DATABASE MODULE TEST ===")
print("Status:", result["status"])
print("Database:", result["database"])
print("Stores:", result["stores"])
print("Product Families:", result["product_families"])

print("\n✅ Reusable database module working.")