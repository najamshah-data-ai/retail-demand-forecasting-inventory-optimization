import pandas as pd

from app.database import get_connection


FORECAST_FILE = (
    "data/latest_7day_inventory_forecast.parquet"
)


# ============================================================
# LOAD FORECAST FILE
# ============================================================

df = pd.read_parquet(
    FORECAST_FILE
)

print("=== FORECAST FILE ===")
print("Rows:", len(df))
print("Stores:", df["store_nbr"].nunique())
print("Families:", df["family"].nunique())

required_columns = {
    "store_nbr",
    "family",
    "forecast_start",
    "forecast_end",
    "forecast_demand_7d",
    "safety_stock",
    "reorder_point",
}

missing = required_columns - set(df.columns)

if missing:
    raise ValueError(
        f"Missing forecast columns: {missing}"
    )


# ============================================================
# CONNECT DATABASE
# ============================================================

conn = get_connection()
cursor = conn.cursor()

try:

    inserted = 0
    updated = 0

    for _, row in df.iterrows():

        # ----------------------------------------------------
        # FIND FAMILY ID
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT family_id
            FROM dbo.ProductFamilies
            WHERE family_name = ?
              AND is_active = 1
            """,
            str(row["family"]),
        )

        family = cursor.fetchone()

        if not family:
            raise ValueError(
                f"Family not found: {row['family']}"
            )

        family_id = family.family_id

        # ----------------------------------------------------
        # CHECK EXISTING FORECAST
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT forecast_id
            FROM dbo.DemandForecasts
            WHERE store_nbr = ?
              AND family_id = ?
              AND forecast_start = ?
            """,
            int(row["store_nbr"]),
            int(family_id),
            row["forecast_start"],
        )

        existing = cursor.fetchone()

        # ----------------------------------------------------
        # UPDATE IF ALREADY EXISTS
        # ----------------------------------------------------

        if existing:

            cursor.execute(
                """
                UPDATE dbo.DemandForecasts

                SET
                    forecast_end = ?,
                    forecast_demand_7d = ?,
                    safety_stock = ?,
                    reorder_point = ?,
                    model_name = ?,
                    model_version = ?

                WHERE forecast_id = ?
                """,
                row["forecast_end"],
                float(row["forecast_demand_7d"]),
                float(row["safety_stock"]),
                float(row["reorder_point"]),
                "LightGBM Retail Demand",
                "v3-final",
                existing.forecast_id,
            )

            updated += 1

        # ----------------------------------------------------
        # INSERT NEW FORECAST
        # ----------------------------------------------------

        else:

            cursor.execute(
                """
                INSERT INTO dbo.DemandForecasts
                (
                    store_nbr,
                    family_id,
                    forecast_start,
                    forecast_end,
                    forecast_demand_7d,
                    safety_stock,
                    reorder_point,
                    model_name,
                    model_version
                )

                VALUES
                (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,

                int(row["store_nbr"]),
                int(family_id),
                row["forecast_start"],
                row["forecast_end"],
                float(row["forecast_demand_7d"]),
                float(row["safety_stock"]),
                float(row["reorder_point"]),
                "LightGBM Retail Demand",
                "v3-final",
            )

            inserted += 1

    conn.commit()

    # ========================================================
    # VERIFY
    # ========================================================

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM dbo.DemandForecasts
        """
    )

    total = cursor.fetchone()[0]

    print("\n======================================")
    print("FORECAST DATABASE IMPORT COMPLETE")
    print("======================================")

    print("\nInserted:", inserted)
    print("Updated :", updated)
    print("Total Forecast Rows:", total)

    print("\n✅ Forecasts saved in RetailDemandDB.")

except Exception:

    conn.rollback()
    raise

finally:

    cursor.close()
    conn.close()
    