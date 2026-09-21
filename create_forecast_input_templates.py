from pathlib import Path
import pandas as pd


OUTPUT_DIR = Path("data/forecast_inputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 1. SALES HISTORY TEMPLATE
# ============================================================

sales_history_columns = [
    "sales_date",
    "store_nbr",
    "family_name",
    "sales",
    "onpromotion",
    "is_closed_day",
    "is_holiday",
    "is_event",
    "is_work_day",
    "oil_price",
]

sales_history_template = pd.DataFrame(
    columns=sales_history_columns
)

sales_history_path = (
    OUTPUT_DIR / "sales_history_template.csv"
)

sales_history_template.to_csv(
    sales_history_path,
    index=False
)


# ============================================================
# 2. FUTURE FORECAST INPUT TEMPLATE
# ============================================================

future_input_columns = [
    "forecast_date",
    "store_nbr",
    "family_name",
    "onpromotion",
    "is_closed_day",
    "is_holiday",
    "is_event",
    "is_work_day",
]

future_input_template = pd.DataFrame(
    columns=future_input_columns
)

future_input_path = (
    OUTPUT_DIR / "future_7day_inputs_template.csv"
)

future_input_template.to_csv(
    future_input_path,
    index=False
)


# ============================================================
# RESULT
# ============================================================

print("=== FORECAST INPUT TEMPLATES CREATED ===")

print("\nSales history:")
print(sales_history_path)
print("Columns:", len(sales_history_columns))

print("\nFuture inputs:")
print(future_input_path)
print("Columns:", len(future_input_columns))

print("\n✅ Templates created successfully.")