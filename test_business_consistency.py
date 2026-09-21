import pandas as pd

from app.business_consistency import (
    check_business_consistency,
)


sales_df = pd.read_csv(
    "data/business_mode/sample_business_sales.csv"
)

inventory_df = pd.read_csv(
    "data/business_mode/sample_business_inventory.csv"
)


result = check_business_consistency(
    sales_df,
    inventory_df
)


print(
    "=== BUSINESS DATA CONSISTENCY CHECK ==="
)

print(result)