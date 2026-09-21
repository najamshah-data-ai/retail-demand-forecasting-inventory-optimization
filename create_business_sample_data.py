from pathlib import Path
import pandas as pd
import numpy as np


OUTPUT_DIR = Path(
    "data/business_mode"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# SAMPLE BUSINESS SALES HISTORY
# 180 DAYS
# 2 STORES
# 3 PRODUCTS
# ============================================================

dates = pd.date_range(
    "2026-01-01",
    periods=180,
    freq="D"
)

stores = [
    "STORE_1",
    "STORE_2",
]

products = [
    {
        "product_id": "P001",
        "product_name": "Milk",
        "category": "Dairy",
        "base_sales": 25,
    },
    {
        "product_id": "P002",
        "product_name": "Bread",
        "category": "Bakery",
        "base_sales": 18,
    },
    {
        "product_id": "P003",
        "product_name": "Soft Drink",
        "category": "Beverages",
        "base_sales": 35,
    },
]


rows = []

rng = np.random.default_rng(
    42
)

for date in dates:

    day_of_week = date.dayofweek

    for store in stores:

        for product in products:

            promotion = (
                1
                if rng.random() < 0.10
                else 0
            )

            weekend_boost = (
                1.20
                if day_of_week >= 5
                else 1.0
            )

            promo_boost = (
                1.30
                if promotion == 1
                else 1.0
            )

            noise = rng.normal(
                0,
                3
            )

            units_sold = (
                product["base_sales"]
                * weekend_boost
                * promo_boost
                + noise
            )

            units_sold = max(
                0,
                round(
                    units_sold
                )
            )

            rows.append({
                "date":
                    date.date(),

                "store_id":
                    store,

                "product_id":
                    product["product_id"],

                "product_name":
                    product["product_name"],

                "category":
                    product["category"],

                "units_sold":
                    units_sold,

                "promotion":
                    promotion,
            })


sales_df = pd.DataFrame(
    rows
)


output_path = (
    OUTPUT_DIR
    / "sample_business_sales.csv"
)

sales_df.to_csv(
    output_path,
    index=False
)


print(
    "=== SAMPLE BUSINESS SALES CREATED ==="
)

print(
    "Path:",
    output_path
)

print(
    "Rows:",
    len(sales_df)
)

print(
    "Start:",
    sales_df["date"].min()
)

print(
    "End:",
    sales_df["date"].max()
)

print(
    "Stores:",
    sales_df["store_id"].nunique()
)

print(
    "Products:",
    sales_df["product_id"].nunique()
)

print(
    "Categories:",
    sales_df["category"].nunique()
)