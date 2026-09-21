import pandas as pd
import numpy as np


SALES_REQUIRED_COLUMNS = [
    "date",
    "store_id",
    "product_id",
    "product_name",
    "category",
    "units_sold",
    "promotion",
]


INVENTORY_REQUIRED_COLUMNS = [
    "store_id",
    "product_id",
    "product_name",
    "current_stock",
    "on_order",
    "backorders",
]


def validate_sales_data(df: pd.DataFrame):

    errors = []
    warnings = []

    # --------------------------------------------------------
    # REQUIRED COLUMNS
    # --------------------------------------------------------

    missing_columns = [
        col
        for col in SALES_REQUIRED_COLUMNS
        if col not in df.columns
    ]

    if missing_columns:
        return {
            "valid": False,
            "errors": [
                f"Missing columns: {missing_columns}"
            ],
            "warnings": [],
        }

    if df.empty:
        return {
            "valid": False,
            "errors": [
                "Sales history contains no rows."
            ],
            "warnings": [],
        }


    df = df[
        SALES_REQUIRED_COLUMNS
    ].copy()


    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    df["date"] = pd.to_datetime(
        df["date"],
        errors="coerce"
    )

    invalid_dates = df["date"].isna().sum()

    if invalid_dates > 0:
        errors.append(
            f"{invalid_dates} invalid dates found."
        )


    # --------------------------------------------------------
    # NUMERIC VALUES
    # --------------------------------------------------------

    df["units_sold"] = pd.to_numeric(
        df["units_sold"],
        errors="coerce"
    )

    df["promotion"] = pd.to_numeric(
        df["promotion"],
        errors="coerce"
    )

    if df["units_sold"].isna().any():
        errors.append(
            "Invalid or blank units_sold values found."
        )

    if df["promotion"].isna().any():
        errors.append(
            "Invalid or blank promotion values found."
        )

    if (
        df["units_sold"]
        .dropna()
        .lt(0)
        .any()
    ):
        errors.append(
            "Negative units_sold values are not allowed."
        )

    if (
        df["promotion"]
        .dropna()
        .lt(0)
        .any()
    ):
        errors.append(
            "Negative promotion values are not allowed."
        )


    # --------------------------------------------------------
    # IDENTIFIERS
    # --------------------------------------------------------

    identifier_columns = [
        "store_id",
        "product_id",
        "product_name",
        "category",
    ]

    for col in identifier_columns:

        if df[col].isna().any():

            errors.append(
                f"Blank values found in {col}."
            )


    # --------------------------------------------------------
    # DUPLICATES
    # --------------------------------------------------------

    duplicate_count = df.duplicated(
        subset=[
            "date",
            "store_id",
            "product_id"
        ]
    ).sum()

    if duplicate_count > 0:

        errors.append(
            f"{duplicate_count} duplicate "
            "date-store-product rows found."
        )


    # --------------------------------------------------------
    # DATA PROFILE
    # --------------------------------------------------------

    valid_dates = df["date"].dropna()

    if valid_dates.empty:

        date_start = None
        date_end = None
        history_days = 0

    else:

        date_start = valid_dates.min()
        date_end = valid_dates.max()

        history_days = (
            date_end - date_start
        ).days + 1


    stores = df["store_id"].nunique(
        dropna=True
    )

    products = df["product_id"].nunique(
        dropna=True
    )

    categories = df["category"].nunique(
        dropna=True
    )


    # --------------------------------------------------------
    # TRAINING READINESS
    # --------------------------------------------------------

    if history_days < 90:

        warnings.append(
            "Less than 90 days of history. "
            "Forecasting model may be unreliable."
        )

    elif history_days < 180:

        warnings.append(
            "3–6 months of history available. "
            "Usable, but more history is recommended."
        )


    if products == 0:

        errors.append(
            "No products detected."
        )


    valid = len(errors) == 0


    return {

        "valid":
            valid,

        "errors":
            errors,

        "warnings":
            warnings,

        "profile": {

            "rows":
                int(len(df)),

            "stores":
                int(stores),

            "products":
                int(products),

            "categories":
                int(categories),

            "date_start":
                (
                    date_start.date().isoformat()
                    if date_start is not None
                    else None
                ),

            "date_end":
                (
                    date_end.date().isoformat()
                    if date_end is not None
                    else None
                ),

            "history_days":
                int(history_days),

            "total_units_sold":
                float(
                    df["units_sold"]
                    .fillna(0)
                    .sum()
                ),

            "promotion_rows":
                int(
                    (
                        df["promotion"]
                        .fillna(0)
                        > 0
                    ).sum()
                ),
        }
    }


def validate_inventory_data(
    df: pd.DataFrame
):

    errors = []

    missing_columns = [
        col
        for col in INVENTORY_REQUIRED_COLUMNS
        if col not in df.columns
    ]

    if missing_columns:

        return {
            "valid": False,
            "errors": [
                f"Missing columns: {missing_columns}"
            ],
        }


    if df.empty:

        return {
            "valid": False,
            "errors": [
                "Inventory file contains no rows."
            ],
        }


    df = df[
        INVENTORY_REQUIRED_COLUMNS
    ].copy()


    numeric_columns = [
        "current_stock",
        "on_order",
        "backorders",
    ]

    for col in numeric_columns:

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

        if df[col].isna().any():

            errors.append(
                f"Invalid or blank {col} values found."
            )

        if df[col].dropna().lt(0).any():

            errors.append(
                f"Negative {col} values are not allowed."
            )


    duplicates = df.duplicated(
        subset=[
            "store_id",
            "product_id"
        ]
    ).sum()

    if duplicates > 0:

        errors.append(
            f"{duplicates} duplicate "
            "store-product rows found."
        )


    return {

        "valid":
            len(errors) == 0,

        "errors":
            errors,

        "profile": {

            "rows":
                int(len(df)),

            "stores":
                int(
                    df["store_id"]
                    .nunique()
                ),

            "products":
                int(
                    df["product_id"]
                    .nunique()
                ),
        }
    }