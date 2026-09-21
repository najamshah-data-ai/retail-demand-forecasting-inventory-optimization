from app.database import get_connection
from app.forecast_engine import (
    generate_forecast,
    aggregate_7day_forecast,
)


MODEL_NAME = "LightGBM Retail Demand"
MODEL_VERSION = "v3-final"


def main():

    print("=== GENERATING LIVE FORECAST ===")

    daily = generate_forecast()

    summary = aggregate_7day_forecast(
        daily
    )

    conn = get_connection()

    try:

        cursor = conn.cursor()

        # ====================================================
        # FAMILY LOOKUP + FROZEN SAFETY STOCK
        # ====================================================

        cursor.execute(
            """
            SELECT
                f.family_id,
                f.family_name,
                MAX(d.safety_stock) AS safety_stock
            FROM dbo.ProductFamilies f

            INNER JOIN dbo.DemandForecasts d
                ON f.family_id = d.family_id

            GROUP BY
                f.family_id,
                f.family_name
            """
        )

        rows = cursor.fetchall()

        family_lookup = {}

        for row in rows:

            family_lookup[row.family_name] = {
                "family_id": int(row.family_id),
                "safety_stock": float(row.safety_stock),
            }


        if len(family_lookup) != 33:

            raise ValueError(
                f"Expected 33 family safety-stock mappings, "
                f"found {len(family_lookup)}."
            )


        # ====================================================
        # INSERT NEW FORECAST WINDOW
        # ====================================================

        insert_sql = """
            IF NOT EXISTS
            (
                SELECT 1
                FROM dbo.DemandForecasts
                WHERE
                    store_nbr = ?
                    AND family_id = ?
                    AND forecast_start = ?
            )
            BEGIN

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

            END
        """

        inserted = 0

        for row in summary.itertuples(
            index=False
        ):

            family_info = family_lookup[
                row.family
            ]

            family_id = family_info[
                "family_id"
            ]

            safety_stock = round(
                family_info[
                    "safety_stock"
                ],
                2
            )

            forecast_demand = round(
                float(
                    row.forecast_demand_7d
                ),
                2
            )

            reorder_point = round(
                forecast_demand
                + safety_stock,
                2
            )

            cursor.execute(
                insert_sql,

                int(row.store_nbr),
                family_id,
                row.forecast_start.date(),

                int(row.store_nbr),
                family_id,
                row.forecast_start.date(),
                row.forecast_end.date(),
                forecast_demand,
                safety_stock,
                reorder_point,
                MODEL_NAME,
                MODEL_VERSION,
            )

            inserted += cursor.rowcount


        conn.commit()


        # ====================================================
        # VERIFY NEW WINDOW
        # ====================================================

        forecast_start = (
            summary[
                "forecast_start"
            ].min().date()
        )

        cursor.execute(
            """
            SELECT
                COUNT(*)
            FROM dbo.DemandForecasts
            WHERE forecast_start = ?
            """,
            forecast_start
        )

        saved_rows = cursor.fetchone()[0]


        print("\n=== DATABASE SAVE COMPLETE ===")
        print(
            "Forecast start:",
            forecast_start
        )
        print(
            "Forecast end:",
            summary["forecast_end"].max().date()
        )
        print(
            "Rows in new window:",
            saved_rows
        )
        print(
            "Expected rows:",
            54 * 33
        )

        if saved_rows != 54 * 33:
            raise ValueError(
                "New forecast window does not "
                "contain exactly 1782 rows."
            )

        print(
            "\n✅ New 7-day forecast saved successfully."
        )


    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


if __name__ == "__main__":
    main()