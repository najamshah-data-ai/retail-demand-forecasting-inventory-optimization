# ============================================================
# STEP 103 — GENERATE 1782-ROW INVENTORY INPUT TEMPLATE
# ============================================================

import os
import pandas as pd

from app.database import get_connection


OUTPUT_DIR = "data"

OUTPUT_FILE = os.path.join(
    OUTPUT_DIR,
    "current_inventory_bulk_template.csv"
)

os.makedirs(
    OUTPUT_DIR,
    exist_ok=True
)


# ============================================================
# 1. LOAD ALL STORE + FAMILY COMBINATIONS
#    FROM SAVED FORECASTS
# ============================================================

conn = get_connection()

try:

    query = """
        SELECT DISTINCT

            d.store_nbr,
            f.family_name

        FROM dbo.DemandForecasts d

        INNER JOIN dbo.ProductFamilies f
            ON d.family_id = f.family_id

        ORDER BY
            d.store_nbr,
            f.family_name
    """

    template = pd.read_sql(
        query,
        conn
    )

finally:

    conn.close()


# ============================================================
# 2. ADD REAL-INVENTORY INPUT COLUMNS
# ============================================================

template["current_stock"] = ""
template["on_order"] = ""
template["backorders"] = ""


# ============================================================
# 3. SAFETY CHECKS
# ============================================================

print("=== INVENTORY TEMPLATE ===")

print(
    "Rows:",
    len(template)
)

print(
    "Stores:",
    template["store_nbr"].nunique()
)

print(
    "Families:",
    template["family_name"].nunique()
)

duplicates = template.duplicated(
    subset=[
        "store_nbr",
        "family_name"
    ]
).sum()

print(
    "Duplicate Store-Family Rows:",
    duplicates
)

assert len(template) == 1782
assert template["store_nbr"].nunique() == 54
assert template["family_name"].nunique() == 33
assert duplicates == 0


# ============================================================
# 4. SAVE CSV
# ============================================================

template.to_csv(
    OUTPUT_FILE,
    index=False
)

print("\n✅ INVENTORY TEMPLATE CREATED")

print("\nFile:")
print(
    os.path.abspath(
        OUTPUT_FILE
    )
)

print(
    "\n⚠️ current_stock, on_order and backorders "
    "are intentionally blank."
)

print(
    "Fill them with REAL business inventory values "
    "before bulk upload."
)