from pathlib import Path
import json
import joblib
import numpy as np
import pandas as pd

from app.database import get_connection


# ============================================================
# PATHS
# ============================================================

MODEL_PATH = Path(
    "models/FINAL_lightgbm_retail_model.joblib"
)

METADATA_PATH = Path(
    "models/FINAL_lightgbm_model_metadata.json"
)


# ============================================================
# LOAD MODEL + METADATA
# ============================================================

_model = None
_metadata = None


def load_model():

    global _model

    if _model is None:

        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Model not found: {MODEL_PATH}"
            )

        _model = joblib.load(
            MODEL_PATH
        )

    return _model


def load_metadata():

    global _metadata

    if _metadata is None:

        if not METADATA_PATH.exists():
            raise FileNotFoundError(
                f"Metadata not found: {METADATA_PATH}"
            )

        with open(
            METADATA_PATH,
            "r",
            encoding="utf-8"
        ) as f:

            _metadata = json.load(f)

    return _metadata


# ============================================================
# READ DATABASE INPUTS
# ============================================================

def load_history(conn):

    query = """
        SELECT
            h.sales_date AS date,
            h.store_nbr,
            f.family_name AS family,
            h.sales,
            h.onpromotion,
            h.is_closed_day,
            h.is_holiday,
            h.is_event,
            h.is_work_day,
            h.oil_price

        FROM dbo.DailySalesHistory h

        INNER JOIN dbo.ProductFamilies f
            ON h.family_id = f.family_id

        ORDER BY
            h.store_nbr,
            f.family_name,
            h.sales_date
    """

    df = pd.read_sql(
        query,
        conn
    )

    df["date"] = pd.to_datetime(
        df["date"]
    )

    return df


def load_future_inputs(conn):

    query = """
        SELECT
            i.forecast_date AS date,
            i.store_nbr,
            f.family_name AS family,
            i.onpromotion,
            i.is_closed_day,
            i.is_holiday,
            i.is_event,
            i.is_work_day

        FROM dbo.FutureForecastInputs i

        INNER JOIN dbo.ProductFamilies f
            ON i.family_id = f.family_id

        ORDER BY
            i.store_nbr,
            f.family_name,
            i.forecast_date
    """

    df = pd.read_sql(
        query,
        conn
    )

    df["date"] = pd.to_datetime(
        df["date"]
    )

    return df


def load_store_metadata(conn):

    query = """
        SELECT
            store_nbr,
            city,
            state,
            store_type AS type,
            cluster

        FROM dbo.Stores

        WHERE is_active = 1

        ORDER BY store_nbr
    """

    return pd.read_sql(
        query,
        conn
    )


# ============================================================
# INPUT VALIDATION
# ============================================================

def validate_inputs(
    history,
    future,
    stores
):

    if history.empty:
        raise ValueError(
            "DailySalesHistory is empty."
        )

    if future.empty:
        raise ValueError(
            "FutureForecastInputs is empty."
        )

    if stores.empty:
        raise ValueError(
            "Stores table is empty."
        )

    future_dates = sorted(
        future["date"].unique()
    )

    if len(future_dates) != 7:
        raise ValueError(
            "Exactly 7 future forecast dates are required. "
            f"Found: {len(future_dates)}"
        )

    if future["store_nbr"].nunique() != 54:
        raise ValueError(
            "Expected 54 stores in future inputs."
        )

    if future["family"].nunique() != 33:
        raise ValueError(
            "Expected 33 families in future inputs."
        )

    expected_rows = 7 * 54 * 33

    if len(future) != expected_rows:
        raise ValueError(
            f"Expected {expected_rows} future rows, "
            f"found {len(future)}."
        )

    duplicate_count = future.duplicated(
        [
            "date",
            "store_nbr",
            "family"
        ]
    ).sum()

    if duplicate_count != 0:
        raise ValueError(
            f"Future inputs contain "
            f"{duplicate_count} duplicates."
        )

    history_end = history["date"].max()
    future_start = future["date"].min()

    expected_future_start = (
        history_end
        + pd.Timedelta(days=1)
    )

    if future_start != expected_future_start:
        raise ValueError(
            "Future forecast window must start "
            "immediately after history.\n"
            f"History end: {history_end.date()}\n"
            f"Future start: {future_start.date()}"
        )


# ============================================================
# BUILD COMPLETE DATAFRAME
# ============================================================

def build_base_frame(
    history,
    future,
    stores
):

    history = history.copy()
    future = future.copy()

    # Future sales are unknown.
    future["sales"] = np.nan

    # Future oil price is intentionally unknown.
    # Model only uses oil_price_lag_7,
    # which comes from historical data.
    future["oil_price"] = np.nan

    required_base_columns = [
        "date",
        "store_nbr",
        "family",
        "sales",
        "onpromotion",
        "is_closed_day",
        "is_holiday",
        "is_event",
        "is_work_day",
        "oil_price",
    ]

    history = history[
        required_base_columns
    ]

    future = future[
        required_base_columns
    ]

    combined = pd.concat(
        [
            history,
            future
        ],
        ignore_index=True
    )

    combined = combined.merge(
        stores,
        on="store_nbr",
        how="left",
        validate="many_to_one"
    )

    metadata_columns = [
        "city",
        "state",
        "type",
        "cluster"
    ]

    if combined[
        metadata_columns
    ].isna().any().any():

        raise ValueError(
            "Missing store metadata detected."
        )

    combined = combined.sort_values(
        [
            "store_nbr",
            "family",
            "date"
        ]
    ).reset_index(drop=True)

    return combined


# ============================================================
# FEATURE ENGINEERING
# EXACTLY MATCHES TRAINING LOGIC
# ============================================================

def create_features(df):

    df = df.copy()

    group_columns = [
        "store_nbr",
        "family"
    ]

    grouped = df.groupby(
        group_columns,
        sort=False,
        observed=True
    )


    # --------------------------------------------------------
    # SALES LAGS
    # --------------------------------------------------------

    df["lag_7"] = (
        grouped["sales"]
        .shift(7)
    )

    df["lag_14"] = (
        grouped["sales"]
        .shift(14)
    )

    df["lag_28"] = (
        grouped["sales"]
        .shift(28)
    )


    # --------------------------------------------------------
    # SHIFTED SALES USED BY TRAINING PIPELINE
    # --------------------------------------------------------

    df["_sales_shift_7"] = (
        grouped["sales"]
        .shift(7)
    )


    # --------------------------------------------------------
    # ROLLING FEATURES
    # --------------------------------------------------------

    shifted_group = df.groupby(
        group_columns,
        sort=False,
        observed=True
    )["_sales_shift_7"]


    df["rolling_mean_7"] = (
        shifted_group
        .transform(
            lambda x:
            x.rolling(7).mean()
        )
    )

    df["rolling_mean_14"] = (
        shifted_group
        .transform(
            lambda x:
            x.rolling(14).mean()
        )
    )

    df["rolling_mean_28"] = (
        shifted_group
        .transform(
            lambda x:
            x.rolling(28).mean()
        )
    )

    df["rolling_std_7"] = (
        shifted_group
        .transform(
            lambda x:
            x.rolling(7).std()
        )
    )

    df["rolling_std_28"] = (
        shifted_group
        .transform(
            lambda x:
            x.rolling(28).std()
        )
    )


    # --------------------------------------------------------
    # ZERO / NON-ZERO FEATURES
    # --------------------------------------------------------

    df["_zero_shift_7"] = (
        df["_sales_shift_7"] == 0
    ).astype(float)

    df["_nonzero_shift_7"] = (
        df["_sales_shift_7"] != 0
    ).astype(float)


    zero_group = df.groupby(
        group_columns,
        sort=False,
        observed=True
    )["_zero_shift_7"]

    nonzero_group = df.groupby(
        group_columns,
        sort=False,
        observed=True
    )["_nonzero_shift_7"]


    df["zero_rate_7"] = (
        zero_group
        .transform(
            lambda x:
            x.rolling(7).mean()
        )
    )

    df["zero_rate_28"] = (
        zero_group
        .transform(
            lambda x:
            x.rolling(28).mean()
        )
    )

    df["nonzero_days_7"] = (
        nonzero_group
        .transform(
            lambda x:
            x.rolling(7).sum()
        )
    )

    df["nonzero_days_28"] = (
        nonzero_group
        .transform(
            lambda x:
            x.rolling(28).sum()
        )
    )


    # --------------------------------------------------------
    # ROBUST DEMAND STATISTICS
    # --------------------------------------------------------

    df["rolling_median_28"] = (
        shifted_group
        .transform(
            lambda x:
            x.rolling(28).median()
        )
    )

    df["rolling_max_28"] = (
        shifted_group
        .transform(
            lambda x:
            x.rolling(28).max()
        )
    )


    # --------------------------------------------------------
    # DEMAND VARIABILITY
    # --------------------------------------------------------

    df["demand_cv_28"] = (
        df["rolling_std_28"]
        /
        (
            df["rolling_mean_28"]
            + 1e-6
        )
    )


    # --------------------------------------------------------
    # TREND FEATURES
    # EXACT TRAINING FORMULA VERIFIED
    # --------------------------------------------------------

    df["trend_ratio_7_28"] = (
        (
            df["rolling_mean_7"] + 1
        )
        /
        (
            df["rolling_mean_28"] + 1
        )
    )

    df["trend_difference_7_28"] = (
        df["rolling_mean_7"]
        -
        df["rolling_mean_28"]
    )


    # --------------------------------------------------------
    # LAG DIFFERENCES
    # --------------------------------------------------------

    df["lag7_minus_lag14"] = (
        df["lag_7"]
        -
        df["lag_14"]
    )

    df["lag7_minus_lag28"] = (
        df["lag_7"]
        -
        df["lag_28"]
    )


    # --------------------------------------------------------
    # OIL PRICE LAG
    # --------------------------------------------------------

    df["oil_price_lag_7"] = (
        grouped["oil_price"]
        .shift(7)
    )


    # --------------------------------------------------------
    # CALENDAR FEATURES
    # --------------------------------------------------------

    df["day_of_week"] = (
        df["date"].dt.dayofweek
    )

    df["day_of_month"] = (
        df["date"].dt.day
    )

    df["month"] = (
        df["date"].dt.month
    )

    df["year"] = (
        df["date"].dt.year
    )

    df["week_of_year"] = (
        df["date"]
        .dt
        .isocalendar()
        .week
        .astype(int)
    )

    df["is_weekend"] = (
        df["day_of_week"] >= 5
    ).astype(int)

    df["is_month_start"] = (
        df["date"].dt.is_month_start
    ).astype(int)

    df["is_month_end"] = (
        df["date"].dt.is_month_end
    ).astype(int)


    return df


# ============================================================
# APPLY EXACT CATEGORICAL LEVELS
# ============================================================

def apply_categories(
    df,
    metadata
):

    df = df.copy()

    category_levels = metadata[
        "category_levels"
    ]

    categorical_features = metadata[
        "categorical_features"
    ]

    for feature in categorical_features:

        df[feature] = (
            df[feature]
            .astype(str)
        )

        expected_categories = (
            category_levels[feature]
        )

        unknown = set(
            df[feature].dropna().unique()
        ) - set(expected_categories)

        if unknown:

            raise ValueError(
                f"Unknown category in {feature}: "
                f"{sorted(unknown)}"
            )

        df[feature] = pd.Categorical(
            df[feature],
            categories=expected_categories
        )

    return df


# ============================================================
# GENERATE 7-DAY FORECAST
# ============================================================

def generate_forecast():

    model = load_model()
    metadata = load_metadata()

    conn = get_connection()

    try:

        history = load_history(conn)
        future = load_future_inputs(conn)
        stores = load_store_metadata(conn)

    finally:

        conn.close()


    validate_inputs(
        history,
        future,
        stores
    )


    combined = build_base_frame(
        history,
        future,
        stores
    )


    featured = create_features(
        combined
    )


    future_start = future["date"].min()
    future_end = future["date"].max()


    prediction_rows = featured[
        featured["date"].between(
            future_start,
            future_end
        )
    ].copy()


    feature_names = metadata[
        "feature_names"
    ]


    # --------------------------------------------------------
    # CHECK FEATURE COMPLETENESS
    # --------------------------------------------------------

    missing_feature_columns = [
        column
        for column in feature_names
        if column not in prediction_rows.columns
    ]

    if missing_feature_columns:

        raise ValueError(
            "Missing model features: "
            f"{missing_feature_columns}"
        )


    numeric_features = [
        feature
        for feature in feature_names
        if feature not in metadata[
            "categorical_features"
        ]
    ]


    missing_numeric = (
        prediction_rows[
            numeric_features
        ]
        .isna()
        .sum()
    )

    missing_numeric = (
        missing_numeric[
            missing_numeric > 0
        ]
    )

    if not missing_numeric.empty:

        raise ValueError(
            "Missing values in model features:\n"
            f"{missing_numeric}"
        )


    # --------------------------------------------------------
    # APPLY CATEGORICAL TYPES
    # --------------------------------------------------------

    prediction_rows = apply_categories(
        prediction_rows,
        metadata
    )


    X = prediction_rows[
        feature_names
    ].copy()


    # --------------------------------------------------------
    # PREDICT
    # --------------------------------------------------------

    predictions = model.booster_.predict(
        X
    )


    # Retail demand cannot be negative.
    predictions = np.maximum(
        predictions,
        0
    )


    prediction_rows[
        "predicted_sales"
    ] = predictions


    result = prediction_rows[
        [
            "date",
            "store_nbr",
            "family",
            "predicted_sales",
            "onpromotion",
        ]
    ].copy()


    result = result.sort_values(
        [
            "date",
            "store_nbr",
            "family"
        ]
    ).reset_index(drop=True)


    # --------------------------------------------------------
    # FINAL VALIDATION
    # --------------------------------------------------------

    expected_rows = (
        7 * 54 * 33
    )

    if len(result) != expected_rows:

        raise ValueError(
            "Unexpected prediction count. "
            f"Expected {expected_rows}, "
            f"got {len(result)}."
        )


    return result


def aggregate_7day_forecast(daily_forecast):

    if daily_forecast.empty:
        raise ValueError(
            "Daily forecast is empty."
        )

    forecast_start = (
        daily_forecast["date"].min()
    )

    forecast_end = (
        daily_forecast["date"].max()
    )

    summary = (
        daily_forecast
        .groupby(
            [
                "store_nbr",
                "family"
            ],
            as_index=False
        )
        .agg(
            forecast_demand_7d=(
                "predicted_sales",
                "sum"
            )
        )
    )

    summary[
        "forecast_demand_7d"
    ] = (
        summary[
            "forecast_demand_7d"
        ]
        .clip(lower=0)
        .round(2)
    )

    summary[
        "forecast_start"
    ] = forecast_start

    summary[
        "forecast_end"
    ] = forecast_end

    expected_rows = 54 * 33

    if len(summary) != expected_rows:
        raise ValueError(
            f"Expected {expected_rows} aggregated forecasts, "
            f"found {len(summary)}."
        )

    return summary


# ============================================================
# DIRECT TEST
# ============================================================

if __name__ == "__main__":

    forecast = generate_forecast()

    print(
        "=== 7-DAY FORECAST ENGINE TEST ==="
    )

    print(
        "Rows:",
        len(forecast)
    )

    print(
        "Start:",
        forecast["date"].min()
    )

    print(
        "End:",
        forecast["date"].max()
    )

    print(
        "Stores:",
        forecast["store_nbr"].nunique()
    )

    print(
        "Families:",
        forecast["family"].nunique()
    )

    print(
        "Minimum prediction:",
        forecast["predicted_sales"].min()
    )

    print(
        "Maximum prediction:",
        forecast["predicted_sales"].max()
    )

    print(
        "Total predicted demand:",
        forecast["predicted_sales"].sum()
    )

    print(
        "\nFIRST 10 PREDICTIONS:"
    )

    print(
        forecast.head(10).to_string(
            index=False
        )
    )

    print(
        "\n✅ Forecast generation successful."
    )

    summary = aggregate_7day_forecast(
        forecast
    )

    print(
        "\n=== AGGREGATED 7-DAY FORECAST ==="
    )

    print(
        "Rows:",
        len(summary)
    )

    print(
        "Forecast start:",
        summary["forecast_start"].min()
    )

    print(
        "Forecast end:",
        summary["forecast_end"].max()
    )

    print(
        "Stores:",
        summary["store_nbr"].nunique()
    )

    print(
        "Families:",
        summary["family"].nunique()
    )

    print(
        "Total 7-day demand:",
        summary["forecast_demand_7d"].sum()
    )

    print(
        "\nFIRST 10 AGGREGATED FORECASTS:"
    )

    print(
        summary.head(10).to_string(
            index=False
        )
    )
