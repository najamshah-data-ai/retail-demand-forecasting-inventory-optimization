import pandas as pd

from app.business_data_validator import (
    validate_sales_data,
    validate_inventory_data,
)


# ============================================================
# SAMPLE REAL-BUSINESS STYLE SALES DATA
# ============================================================

sales_df = pd.DataFrame({
    "date": pd.date_range(
        "2026-01-01",
        periods=100,
        freq="D"
    ),
    "store_id": ["STORE_1"] * 100,
    "product_id": ["P001"] * 100,
    "product_name": ["Milk"] * 100,
    "category": ["Dairy"] * 100,
    "units_sold": [20] * 100,
    "promotion": [0] * 100,
})


# ============================================================
# SAMPLE INVENTORY DATA
# ============================================================

inventory_df = pd.DataFrame({
    "store_id": ["STORE_1"],
    "product_id": ["P001"],
    "product_name": ["Milk"],
    "current_stock": [80],
    "on_order": [20],
    "backorders": [0],
})


print("=== SALES VALIDATION ===")

sales_result = validate_sales_data(
    sales_df
)

print(sales_result)


print("\n=== INVENTORY VALIDATION ===")

inventory_result = validate_inventory_data(
    inventory_df
)

print(inventory_result)