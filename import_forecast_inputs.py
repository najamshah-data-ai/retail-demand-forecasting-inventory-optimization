from pathlib import Path
import pandas as pd

from app.database import get_connection


BASE_DIR = Path("data/forecast_inputs")

SALES_FILE = BASE_DIR / "sales_history_input.csv"
FUTURE_FILE = BASE_DIR / "future_7day_inputs.csv"


# ============================================================
# REQUIRED COLUMNS
# ============================================================

SALES_COLUMNS = [
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

FUTURE_COLUMNS = [
    "forecast_date",
    "store_nbr",
    "family_name",
    "onpromotion",
    "is_closed_day",
    "is_holiday",
    "is_event",
    "is_work_day",
]


# ============================================================
# LOAD FAMILY LOOKUP
# ============================================================

def get_family_lookup(conn):

    query = """
        SELECT
            family_id,
            family_name
        FROM dbo.ProductFamilies
    """

    df = pd.read_sql(query, conn)

    return dict(
        zip(
            df["family_name"],
            df["family_id"]
        )
    )


# ============================================================
# VALIDATE COLUMNS
# ============================================================

def validate_columns(df, required, filename):

    if list(df.columns) != required:

        raise ValueError(
            f"{filename}: columns do not match expected format.\n"
            f"Expected: {required}\n"
            f"Found: {list(df.columns)}"
        )


# ============================================================
# IMPORT SALES HISTORY
# ============================================================

def import_sales_history(conn, family_lookup):

    df = pd.read_csv(SALES_FILE)

    validate_columns(
        df,
        SALES_COLUMNS,
        SALES_FILE.name
    )

    if df.empty:

        print(
            "Sales history template is currently empty."
        )
        return 0

    df["sales_date"] = pd.to_datetime(
        df["sales_date"],
        errors="raise"
    ).dt.date

    numeric_columns = [
        "store_nbr",
        "sales",
        "onpromotion",
        "is_closed_day",
        "is_holiday",
        "is_event",
        "is_work_day",
        "oil_price",
    ]

    for col in numeric_columns:

        df[col] = pd.to_numeric(
            df[col],
            errors="raise"
        )

    if df[
        ["sales", "onpromotion"]
    ].lt(0).any().any():

        raise ValueError(
            "Negative sales or promotion values found."
        )

    if df.duplicated(
        subset=[
            "sales_date",
            "store_nbr",
            "family_name"
        ]
    ).any():

        raise ValueError(
            "Duplicate Store + Family + Date found "
            "in sales history."
        )

    unknown_families = set(
        df["family_name"]
    ) - set(family_lookup)

    if unknown_families:

        raise ValueError(
            f"Unknown families: {unknown_families}"
        )

    cursor = conn.cursor()

    inserted = 0

    sql = """
        IF NOT EXISTS
        (
            SELECT 1
            FROM dbo.DailySalesHistory
            WHERE
                sales_date = ?
                AND store_nbr = ?
                AND family_id = ?
        )
        BEGIN

            INSERT INTO dbo.DailySalesHistory
            (
                sales_date,
                store_nbr,
                family_id,
                sales,
                onpromotion,
                is_closed_day,
                is_holiday,
                is_event,
                is_work_day,
                oil_price
            )
            VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

        END
    """

    for row in df.itertuples(index=False):

        family_id = family_lookup[
            row.family_name
        ]

        cursor.execute(
            sql,

            row.sales_date,
            int(row.store_nbr),
            family_id,

            row.sales_date,
            int(row.store_nbr),
            family_id,
            float(row.sales),
            int(row.onpromotion),
            int(row.is_closed_day),
            int(row.is_holiday),
            int(row.is_event),
            int(row.is_work_day),

            None
            if pd.isna(row.oil_price)
            else float(row.oil_price)
        )

        inserted += cursor.rowcount

    conn.commit()

    return inserted


# ============================================================
# IMPORT FUTURE INPUTS
# ============================================================

def import_future_inputs(conn, family_lookup):

    df = pd.read_csv(FUTURE_FILE)

    validate_columns(
        df,
        FUTURE_COLUMNS,
        FUTURE_FILE.name
    )

    if df.empty:

        print(
            "Future 7-day input template is currently empty."
        )
        return 0

    df["forecast_date"] = pd.to_datetime(
        df["forecast_date"],
        errors="raise"
    ).dt.date

    numeric_columns = [
        "store_nbr",
        "onpromotion",
        "is_closed_day",
        "is_holiday",
        "is_event",
        "is_work_day",
    ]

    for col in numeric_columns:

        df[col] = pd.to_numeric(
            df[col],
            errors="raise"
        )

    if df["onpromotion"].lt(0).any():

        raise ValueError(
            "Negative promotion values found."
        )

    if df.duplicated(
        subset=[
            "forecast_date",
            "store_nbr",
            "family_name"
        ]
    ).any():

        raise ValueError(
            "Duplicate Store + Family + Date found "
            "in future inputs."
        )

    unknown_families = set(
        df["family_name"]
    ) - set(family_lookup)

    if unknown_families:

        raise ValueError(
            f"Unknown families: {unknown_families}"
        )

    cursor = conn.cursor()

    inserted = 0

    sql = """
        IF NOT EXISTS
        (
            SELECT 1
            FROM dbo.FutureForecastInputs
            WHERE
                forecast_date = ?
                AND store_nbr = ?
                AND family_id = ?
        )
        BEGIN

            INSERT INTO dbo.FutureForecastInputs
            (
                forecast_date,
                store_nbr,
                family_id,
                onpromotion,
                is_closed_day,
                is_holiday,
                is_event,
                is_work_day
            )
            VALUES
            (?, ?, ?, ?, ?, ?, ?, ?)

        END
    """

    for row in df.itertuples(index=False):

        family_id = family_lookup[
            row.family_name
        ]

        cursor.execute(
            sql,

            row.forecast_date,
            int(row.store_nbr),
            family_id,

            row.forecast_date,
            int(row.store_nbr),
            family_id,
            int(row.onpromotion),
            int(row.is_closed_day),
            int(row.is_holiday),
            int(row.is_event),
            int(row.is_work_day)
        )

        inserted += cursor.rowcount

    conn.commit()

    return inserted


# ============================================================
# MAIN
# ============================================================

def main():

    conn = get_connection()

    try:

        family_lookup = get_family_lookup(conn)

        sales_inserted = import_sales_history(
            conn,
            family_lookup
        )

        future_inserted = import_future_inputs(
            conn,
            family_lookup
        )

        print("\n=== FORECAST INPUT IMPORT ===")

        print(
            "Sales history inserted:",
            sales_inserted
        )

        print(
            "Future inputs inserted:",
            future_inserted
        )

        print("\n✅ Import process completed.")

    finally:

        conn.close()


if __name__ == "__main__":
    main()