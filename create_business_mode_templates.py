from pathlib import Path
import pandas as pd


OUTPUT_DIR = Path(
    "data/business_mode"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# 1. REAL BUSINESS SALES HISTORY TEMPLATE
# ============================================================

sales_columns = [
    "date",
    "store_id",
    "product_id",
    "product_name",
    "category",
    "units_sold",
    "promotion",
]

sales_template = pd.DataFrame(
    columns=sales_columns
)

sales_path = (
    OUTPUT_DIR
    / "sales_history_template.csv"
)

sales_template.to_csv(
    sales_path,
    index=False
)


# ============================================================
# 2. CURRENT INVENTORY TEMPLATE
# ============================================================

inventory_columns = [
    "store_id",
    "product_id",
    "product_name",
    "current_stock",
    "on_order",
    "backorders",
]

inventory_template = pd.DataFrame(
    columns=inventory_columns
)

inventory_path = (
    OUTPUT_DIR
    / "inventory_template.csv"
)

inventory_template.to_csv(
    inventory_path,
    index=False
)


# ============================================================
# RESULT
# ============================================================

print(
    "=== REAL BUSINESS MODE TEMPLATES CREATED ==="
)

print("\nSales History:")
print(sales_path)
print(
    "Columns:",
    len(sales_columns)
)

print("\nInventory:")
print(inventory_path)
print(
    "Columns:",
    len(inventory_columns)
)

print(
    "\n✅ Business data templates created successfully."
)