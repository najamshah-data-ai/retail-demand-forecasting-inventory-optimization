from pathlib import Path

from app.business_inventory_engine import (
    create_business_inventory_analysis,
)


OUTPUT_PATH = Path(
    "data/business_mode/business_recommendations.csv"
)


recommendations = (
    create_business_inventory_analysis()
)


recommendations.to_csv(
    OUTPUT_PATH,
    index=False
)


print(
    "=== BUSINESS RECOMMENDATIONS SAVED ==="
)

print(
    "Path:",
    OUTPUT_PATH
)

print(
    "Rows:",
    len(recommendations)
)

print(
    "Total recommended order:",
    int(
        recommendations[
            "recommended_order"
        ].sum()
    )
)

print(
    "\n✅ Recommendations saved successfully."
)