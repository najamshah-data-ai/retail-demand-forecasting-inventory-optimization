from pathlib import Path
import pandas as pd


OUTPUT_DIR = Path(
    "data/business_mode"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


inventory_df = pd.DataFrame([
    {
        "store_id": "STORE_1",
        "product_id": "P001",
        "product_name": "Milk",
        "current_stock": 120,
        "on_order": 20,
        "backorders": 0,
    },
    {
        "store_id": "STORE_1",
        "product_id": "P002",
        "product_name": "Bread",
        "current_stock": 80,
        "on_order": 0,
        "backorders": 5,
    },
    {
        "store_id": "STORE_1",
        "product_id": "P003",
        "product_name": "Soft Drink",
        "current_stock": 200,
        "on_order": 40,
        "backorders": 0,
    },
    {
        "store_id": "STORE_2",
        "product_id": "P001",
        "product_name": "Milk",
        "current_stock": 90,
        "on_order": 10,
        "backorders": 0,
    },
    {
        "store_id": "STORE_2",
        "product_id": "P002",
        "product_name": "Bread",
        "current_stock": 60,
        "on_order": 0,
        "backorders": 8,
    },
    {
        "store_id": "STORE_2",
        "product_id": "P003",
        "product_name": "Soft Drink",
        "current_stock": 150,
        "on_order": 25,
        "backorders": 0,
    },
])


output_path = (
    OUTPUT_DIR
    / "sample_business_inventory.csv"
)

inventory_df.to_csv(
    output_path,
    index=False
)


print(
    "=== SAMPLE BUSINESS INVENTORY CREATED ==="
)

print(
    "Path:",
    output_path
)

print(
    "Rows:",
    len(inventory_df)
)

print(
    "Stores:",
    inventory_df["store_id"].nunique()
)

print(
    "Products:",
    inventory_df["product_id"].nunique()
)

print(
    "Total current stock:",
    inventory_df["current_stock"].sum()
)