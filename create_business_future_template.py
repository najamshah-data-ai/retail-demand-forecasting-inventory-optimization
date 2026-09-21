from pathlib import Path
import pandas as pd


SALES_PATH = Path(
    "data/business_mode/sample_business_sales.csv"
)

OUTPUT_PATH = Path(
    "data/business_mode/future_7day_template.csv"
)


# ============================================================
# LOAD HISTORICAL BUSINESS DATA
# ============================================================

sales = pd.read_csv(
    SALES_PATH,
    parse_dates=["date"]
)


# ============================================================
# UNIQUE STORE-PRODUCT COMBINATIONS
# ============================================================

products = (
    sales[
        [
            "store_id",
            "product_id",
            "product_name",
            "category",
        ]
    ]
    .drop_duplicates()
    .sort_values(
        [
            "store_id",
            "product_id"
        ]
    )
)


# ============================================================
# NEXT 7 DAYS
# ============================================================

last_date = sales["date"].max()

future_dates = pd.date_range(
    last_date + pd.Timedelta(days=1),
    periods=7,
    freq="D"
)


# ============================================================
# CREATE FUTURE INPUT
# ============================================================

rows = []

for date in future_dates:

    for row in products.itertuples(
        index=False
    ):

        rows.append({
            "date":
                date.date(),

            "store_id":
                row.store_id,

            "product_id":
                row.product_id,

            "product_name":
                row.product_name,

            "category":
                row.category,

            # Business should fill planned promotion.
            # 0 = no promotion
            # 1 = promotion
            "promotion":
                0,
        })


future_df = pd.DataFrame(
    rows
)


# ============================================================
# SAVE
# ============================================================

future_df.to_csv(
    OUTPUT_PATH,
    index=False
)


print(
    "=== BUSINESS FUTURE INPUT CREATED ==="
)

print(
    "Path:",
    OUTPUT_PATH
)

print(
    "Start:",
    future_df["date"].min()
)

print(
    "End:",
    future_df["date"].max()
)

print(
    "Rows:",
    len(future_df)
)

print(
    "Stores:",
    future_df["store_id"].nunique()
)

print(
    "Products:",
    future_df["product_id"].nunique()
)

print(
    "\n✅ Future 7-day business input created."
)