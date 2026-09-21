from pathlib import Path
import hashlib
import json
import joblib
import numpy as np
import pandas as pd


# ============================================================
# PATHS
# ============================================================

SALES_PATH = Path(
    "data/business_mode/uploads/active_sales_history.csv"
)

MODEL_PATH = Path(
    "models/business_mode/business_lightgbm_model.joblib"
)

METADATA_PATH = Path(
    "models/business_mode/business_model_metadata.json"
)

FUTURE_PROMOTION_PATH = Path(
    "data/business_mode/uploads/active_future_promotions.csv"
)


# ============================================================
# FILE FINGERPRINT
# ============================================================

def calculate_file_sha256(
    file_path,
    chunk_size=1024 * 1024,
):

    sha256 = hashlib.sha256()

    with open(
        file_path,
        "rb",
    ) as file:

        while True:

            chunk = file.read(
                chunk_size
            )

            if not chunk:
                break

            sha256.update(
                chunk
            )

    return sha256.hexdigest()


# ============================================================
# LOAD MODEL + METADATA
# ============================================================

def load_model():

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Model not found: {MODEL_PATH}"
        )

    return joblib.load(
        MODEL_PATH
    )


def load_metadata():

    if not METADATA_PATH.exists():
        raise FileNotFoundError(
            f"Metadata not found: {METADATA_PATH}"
        )

    with open(
        METADATA_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


# ============================================================
# OPTIONAL FUTURE PROMOTION PLAN
# ============================================================

def apply_future_promotion_plan(
    future
):

    future = future.copy()

    # Default behavior:
    # if no promotion plan exists, assume no promotions.
    future["promotion"] = 0

    if not FUTURE_PROMOTION_PATH.exists():

        return (
            future,
            {
                "promotion_plan_used": False,
                "promotion_rows_applied": 0,
                "promotion_plan_path": None,
            },
        )

    plan = pd.read_csv(
        FUTURE_PROMOTION_PATH
    )

    required_columns = [
        "date",
        "store_id",
        "product_id",
        "promotion",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in plan.columns
    ]

    if missing_columns:

        raise ValueError(
            "Future promotion plan is missing columns: "
            f"{missing_columns}"
        )

    plan = plan[
        required_columns
    ].copy()

    if plan.empty:

        return (
            future,
            {
                "promotion_plan_used": True,
                "promotion_rows_applied": 0,
                "promotion_plan_path":
                    str(FUTURE_PROMOTION_PATH),
            },
        )

    plan["date"] = pd.to_datetime(
        plan["date"],
        errors="coerce"
    )

    plan["store_id"] = (
        plan["store_id"]
        .astype(str)
        .str.strip()
    )

    plan["product_id"] = (
        plan["product_id"]
        .astype(str)
        .str.strip()
    )

    plan["promotion"] = pd.to_numeric(
        plan["promotion"],
        errors="coerce"
    )

    if plan[
        [
            "date",
            "store_id",
            "product_id",
            "promotion",
        ]
    ].isna().any().any():

        raise ValueError(
            "Future promotion plan contains missing "
            "or invalid values."
        )

    invalid_promotion = (
        ~plan["promotion"].isin(
            [0, 1]
        )
    )

    if invalid_promotion.any():

        bad_values = (
            plan.loc[
                invalid_promotion,
                "promotion"
            ]
            .drop_duplicates()
            .tolist()
        )

        raise ValueError(
            "Future promotion values must be 0 or 1. "
            f"Invalid values: {bad_values[:20]}"
        )

    duplicates = plan.duplicated(
        [
            "date",
            "store_id",
            "product_id",
        ]
    ).sum()

    if duplicates > 0:

        raise ValueError(
            "Future promotion plan contains "
            f"{duplicates} duplicate date-store-product rows."
        )

    future = future.copy()

    future["store_id"] = (
        future["store_id"]
        .astype(str)
        .str.strip()
    )

    future["product_id"] = (
        future["product_id"]
        .astype(str)
        .str.strip()
    )

    valid_dates = set(
        pd.to_datetime(
            future["date"]
        )
    )

    plan_dates = set(
        plan["date"]
    )

    invalid_dates = (
        plan_dates
        - valid_dates
    )

    if invalid_dates:

        invalid_date_strings = sorted(
            str(
                pd.Timestamp(value).date()
            )
            for value in invalid_dates
        )

        raise ValueError(
            "Future promotion plan contains dates outside "
            "the next 7-day forecast window: "
            f"{invalid_date_strings[:20]}"
        )

    valid_pairs = set(
        zip(
            future["store_id"],
            future["product_id"],
        )
    )

    plan_pairs = set(
        zip(
            plan["store_id"],
            plan["product_id"],
        )
    )

    unknown_pairs = (
        plan_pairs
        - valid_pairs
    )

    if unknown_pairs:

        raise ValueError(
            "Future promotion plan contains unknown "
            "store-product combinations: "
            f"{sorted(unknown_pairs)[:20]}"
        )

    plan = plan.rename(
        columns={
            "promotion":
                "planned_promotion"
        }
    )

    future = future.merge(
        plan,
        on=[
            "date",
            "store_id",
            "product_id",
        ],
        how="left",
        validate="one_to_one",
    )

    future["promotion"] = (
        future["planned_promotion"]
        .fillna(
            future["promotion"]
        )
        .astype(int)
    )

    future = future.drop(
        columns=[
            "planned_promotion"
        ]
    )

    applied_rows = int(
        (
            future["promotion"] == 1
        ).sum()
    )

    return (
        future,
        {
            "promotion_plan_used": True,
            "promotion_rows_applied":
                applied_rows,
            "promotion_plan_path":
                str(FUTURE_PROMOTION_PATH),
        },
    )


# ============================================================
# BUILD AUTOMATIC NEXT 7-DAY INPUT
# ============================================================

def build_future_input(history):

    if history.empty:
        raise ValueError(
            "Business sales history is empty."
        )

    required_columns = [
        "date",
        "store_id",
        "product_id",
        "product_name",
        "category",
        "units_sold",
        "promotion",
    ]

    missing_columns = [
        col
        for col in required_columns
        if col not in history.columns
    ]

    if missing_columns:
        raise ValueError(
            f"History missing columns: {missing_columns}"
        )

    history = history.copy()

    history["date"] = pd.to_datetime(
        history["date"],
        errors="coerce"
    )

    if history["date"].isna().any():
        raise ValueError(
            "Invalid dates found in active sales history."
        )

    history_end = history["date"].max()

    future_dates = pd.date_range(
        start=history_end + pd.Timedelta(days=1),
        periods=7,
        freq="D"
    )

    # Use the latest known product metadata for each store-product pair.
    latest_products = (
        history
        .sort_values(
            [
                "store_id",
                "product_id",
                "date"
            ]
        )
        .groupby(
            [
                "store_id",
                "product_id"
            ],
            as_index=False
        )
        .tail(1)
        [
            [
                "store_id",
                "product_id",
                "product_name",
                "category"
            ]
        ]
        .reset_index(drop=True)
    )

    if latest_products.empty:
        raise ValueError(
            "No store-product combinations found in active sales history."
        )

    dates_df = pd.DataFrame(
        {
            "date": future_dates
        }
    )

    latest_products["_join_key"] = 1
    dates_df["_join_key"] = 1

    future = (
        latest_products
        .merge(
            dates_df,
            on="_join_key",
            how="inner"
        )
        .drop(
            columns=["_join_key"]
        )
    )

    (
        future,
        promotion_info,
    ) = apply_future_promotion_plan(
        future
    )

    future.attrs[
        "promotion_info"
    ] = promotion_info

    future = future[
        [
            "date",
            "store_id",
            "product_id",
            "product_name",
            "category",
            "promotion",
        ]
    ]

    promotion_info = future.attrs.get(
        "promotion_info",
        {
            "promotion_plan_used": False,
            "promotion_rows_applied": 0,
            "promotion_plan_path": None,
        }
    )

    future = future.sort_values(
        [
            "date",
            "store_id",
            "product_id"
        ]
    ).reset_index(drop=True)

    future.attrs[
        "promotion_info"
    ] = promotion_info

    return future


# ============================================================
# LOAD INPUT DATA
# ============================================================

def load_inputs():

    if not SALES_PATH.exists():
        raise FileNotFoundError(
            "Active business sales file not found. "
            "Upload sales data first using "
            "POST /api/business/upload-sales."
        )

    history = pd.read_csv(
        SALES_PATH,
        parse_dates=["date"]
    )

    future = build_future_input(
        history
    )

    return history, future


# ============================================================
# VALIDATE INPUTS
# ============================================================

def validate_inputs(
    history,
    future
):

    if history.empty:
        raise ValueError(
            "Business sales history is empty."
        )

    if future.empty:
        raise ValueError(
            "Future business input is empty."
        )

    required_history = [
        "date",
        "store_id",
        "product_id",
        "product_name",
        "category",
        "units_sold",
        "promotion",
    ]

    required_future = [
        "date",
        "store_id",
        "product_id",
        "product_name",
        "category",
        "promotion",
    ]

    missing_history = [
        col
        for col in required_history
        if col not in history.columns
    ]

    missing_future = [
        col
        for col in required_future
        if col not in future.columns
    ]

    if missing_history:
        raise ValueError(
            f"History missing columns: {missing_history}"
        )

    if missing_future:
        raise ValueError(
            f"Future input missing columns: {missing_future}"
        )

    future_dates = sorted(
        future["date"].unique()
    )

    if len(future_dates) != 7:
        raise ValueError(
            "Exactly 7 future dates are required. "
            f"Found: {len(future_dates)}"
        )

    history_end = history["date"].max()
    future_start = future["date"].min()

    expected_start = (
        history_end
        + pd.Timedelta(days=1)
    )

    if future_start != expected_start:
        raise ValueError(
            "Future data must start immediately "
            "after historical data.\n"
            f"History end: {history_end.date()}\n"
            f"Future start: {future_start.date()}"
        )

    duplicates = future.duplicated(
        [
            "date",
            "store_id",
            "product_id"
        ]
    ).sum()

    if duplicates > 0:
        raise ValueError(
            f"{duplicates} duplicate future rows found."
        )


    # --------------------------------------------------------
    # SAME STORE-PRODUCT PAIRS
    # --------------------------------------------------------

    history_pairs = set(
        zip(
            history["store_id"].astype(str),
            history["product_id"].astype(str)
        )
    )

    future_pairs = set(
        zip(
            future["store_id"].astype(str),
            future["product_id"].astype(str)
        )
    )

    unknown_pairs = (
        future_pairs
        - history_pairs
    )

    if unknown_pairs:

        raise ValueError(
            "Future input contains store-product "
            "combinations not present in training history: "
            f"{sorted(unknown_pairs)[:20]}"
        )


    # --------------------------------------------------------
    # MINIMUM HISTORY
    # --------------------------------------------------------

    counts = (
        history
        .groupby(
            [
                "store_id",
                "product_id"
            ]
        )
        .size()
    )

    insufficient = counts[
        counts < 28
    ]

    if not insufficient.empty:
        raise ValueError(
            "Every store-product series requires "
            "at least 28 historical observations."
        )


    # --------------------------------------------------------
    # RECENT 28-DAY DAILY CONTINUITY
    # --------------------------------------------------------

    history_end = history["date"].max()

    expected_recent_dates = set(
        pd.date_range(
            end=history_end,
            periods=28,
            freq="D"
        )
    )

    continuity_errors = []

    for (
        store_id,
        product_id
    ), group in history.groupby(
        [
            "store_id",
            "product_id"
        ]
    ):

        recent_dates = set(
            pd.to_datetime(
                group["date"]
            )
        )

        missing_recent = (
            expected_recent_dates
            - recent_dates
        )

        if missing_recent:

            continuity_errors.append(
                (
                    str(store_id),
                    str(product_id),
                    len(missing_recent)
                )
            )

    if continuity_errors:

        raise ValueError(
            "Each store-product series must contain "
            "continuous daily observations for the most recent "
            "28 days. Problems found: "
            f"{continuity_errors[:20]}"
        )


    # --------------------------------------------------------
    # EXACTLY 7 FUTURE ROWS PER STORE-PRODUCT
    # --------------------------------------------------------

    future_counts = (
        future
        .groupby(
            [
                "store_id",
                "product_id"
            ]
        )
        .size()
    )

    invalid_future_counts = future_counts[
        future_counts != 7
    ]

    if not invalid_future_counts.empty:

        raise ValueError(
            "Every store-product pair must have exactly "
            "7 future rows."
        )


# ============================================================
# FEATURE ENGINEERING
# EXACTLY MATCH BUSINESS TRAINING SCRIPT
# ============================================================

def create_features(df):

    df = df.copy()

    df = df.sort_values(
        [
            "store_id",
            "product_id",
            "date"
        ]
    ).reset_index(drop=True)


    groups = df.groupby(
        [
            "store_id",
            "product_id"
        ],
        sort=False
    )


    # --------------------------------------------------------
    # LAGS
    # --------------------------------------------------------

    df["lag_1"] = (
        groups["units_sold"]
        .shift(1)
    )

    df["lag_7"] = (
        groups["units_sold"]
        .shift(7)
    )

    df["lag_14"] = (
        groups["units_sold"]
        .shift(14)
    )

    df["lag_28"] = (
        groups["units_sold"]
        .shift(28)
    )


    # --------------------------------------------------------
    # SHIFTED SALES
    # --------------------------------------------------------

    shifted = (
        groups["units_sold"]
        .shift(1)
    )


    shifted_group = shifted.groupby(
        [
            df["store_id"],
            df["product_id"]
        ]
    )


    # --------------------------------------------------------
    # ROLLING FEATURES
    # --------------------------------------------------------

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

    df["week_of_year"] = (
        df["date"]
        .dt.isocalendar()
        .week
        .astype(int)
    )

    df["is_weekend"] = (
        df["day_of_week"] >= 5
    ).astype(int)


    return df


# ============================================================
# APPLY TRAINING CATEGORIES
# ============================================================

def apply_categories(
    df,
    metadata
):

    df = df.copy()

    categorical_features = metadata[
        "categorical_features"
    ]

    category_levels = metadata[
        "category_levels"
    ]


    for feature in categorical_features:

        df[feature] = (
            df[feature]
            .astype(str)
        )

        expected = (
            category_levels[
                feature
            ]
        )

        unknown = set(
            df[feature]
            .dropna()
            .unique()
        ) - set(expected)

        if unknown:

            raise ValueError(
                f"Unknown categories in {feature}: "
                f"{sorted(unknown)}"
            )

        df[feature] = pd.Categorical(
            df[feature],
            categories=expected
        )


    return df


# ============================================================
# RECURSIVE 7-DAY FORECAST
# ============================================================

def generate_business_forecast():

    model = load_model()
    metadata = load_metadata()

    if not SALES_PATH.exists():
        raise FileNotFoundError(
            "Active business sales file not found. "
            "Upload sales data first."
        )

    expected_sales_sha256 = (
        metadata.get(
            "source_sales_sha256"
        )
    )

    if not expected_sales_sha256:
        raise ValueError(
            "Business model metadata does not contain "
            "source_sales_sha256. Retrain the business model "
            "before forecasting."
        )

    current_sales_sha256 = (
        calculate_file_sha256(
            SALES_PATH
        )
    )

    if (
        current_sales_sha256
        != expected_sales_sha256
    ):
        raise ValueError(
            "The active sales file has changed since the "
            "business model was trained. Retrain the model "
            "before generating forecasts."
        )

    trained_source = (
        metadata.get(
            "source_sales_file"
        )
    )

    if not trained_source:

        raise ValueError(
            "Business model metadata does not identify "
            "the active sales source. Retrain the business model "
            "using the current train_business_model.py."
        )

    trained_source_normalized = (
        str(trained_source)
        .replace("\\", "/")
        .lower()
    )

    expected_source_normalized = (
        str(SALES_PATH)
        .replace("\\", "/")
        .lower()
    )

    if (
        trained_source_normalized
        != expected_source_normalized
    ):

        raise ValueError(
            "The business model was not trained on the current "
            "active sales file. Retrain the model before forecasting."
        )

    history, future = load_inputs()

    promotion_info = future.attrs.get(
        "promotion_info",
        {
            "promotion_plan_used": False,
            "promotion_rows_applied": 0,
            "promotion_plan_path": None,
        }
    )


    history["store_id"] = (
        history["store_id"]
        .astype(str)
    )

    history["product_id"] = (
        history["product_id"]
        .astype(str)
    )

    future["store_id"] = (
        future["store_id"]
        .astype(str)
    )

    future["product_id"] = (
        future["product_id"]
        .astype(str)
    )


    validate_inputs(
        history,
        future
    )


    feature_names = metadata[
        "feature_names"
    ]


    categorical_features = metadata[
        "categorical_features"
    ]


    working_history = history.copy()

    all_predictions = []


    future_dates = sorted(
        future["date"].unique()
    )
    
    # ========================================================
    # FORECAST ONE DAY AT A TIME
    # ========================================================

    for forecast_date in future_dates:

        day_future = future[
            future["date"]
            == forecast_date
        ].copy()


        # Target is unknown before prediction
        day_future["units_sold"] = np.nan


        combined = pd.concat(
            [
                working_history,
                day_future
            ],
            ignore_index=True
        )


        featured = create_features(
            combined
        )


        prediction_rows = featured[
            featured["date"]
            == forecast_date
        ].copy()


        # ----------------------------------------------------
        # FEATURE CHECK
        # ----------------------------------------------------

        missing_columns = [
            feature
            for feature in feature_names
            if feature
            not in prediction_rows.columns
        ]

        if missing_columns:

            raise ValueError(
                f"Missing model features: "
                f"{missing_columns}"
            )


        numeric_features = [
            feature
            for feature in feature_names
            if feature
            not in categorical_features
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
                "Missing feature values detected:\n"
                f"{missing_numeric}"
            )


        # ----------------------------------------------------
        # CATEGORICAL TYPES
        # ----------------------------------------------------

        prediction_rows = apply_categories(
            prediction_rows,
            metadata
        )


        X = prediction_rows[
            feature_names
        ].copy()


        # ----------------------------------------------------
        # PREDICTION
        # ----------------------------------------------------

        predictions = (
            model.booster_.predict(
                X
            )
        )


        predictions = np.maximum(
            predictions,
            0
        )


        prediction_rows[
            "predicted_units"
        ] = predictions


        # Small floating-point values treated as zero
        prediction_rows.loc[
            prediction_rows[
                "predicted_units"
            ] < 1e-8,
            "predicted_units"
        ] = 0.0


        all_predictions.append(
            prediction_rows[
                [
                    "date",
                    "store_id",
                    "product_id",
                    "product_name",
                    "category",
                    "promotion",
                    "predicted_units",
                ]
            ].copy()
        )


        # ====================================================
        # FEED PREDICTIONS BACK INTO HISTORY
        # Needed because model uses lag_1
        # ====================================================

        predicted_history = (
            prediction_rows[
                [
                    "date",
                    "store_id",
                    "product_id",
                    "product_name",
                    "category",
                    "promotion",
                    "predicted_units",
                ]
            ]
            .rename(
                columns={
                    "predicted_units":
                        "units_sold"
                }
            )
        )


        working_history = pd.concat(
            [
                working_history,
                predicted_history
            ],
            ignore_index=True
        )


    # ========================================================
    # FINAL DAILY FORECAST
    # ========================================================

    result = pd.concat(
        all_predictions,
        ignore_index=True
    )


    result = result.sort_values(
        [
            "date",
            "store_id",
            "product_id"
        ]
    ).reset_index(drop=True)


    result["predicted_units"] = (
        result["predicted_units"]
        .round(2)
    )


    expected_rows = (
        len(future_dates)
        *
        future[
            [
                "store_id",
                "product_id"
            ]
        ]
        .drop_duplicates()
        .shape[0]
    )


    if len(result) != expected_rows:

        raise ValueError(
            "Unexpected forecast row count. "
            f"Expected {expected_rows}, "
            f"found {len(result)}."
        )

    result.attrs[
        "promotion_info"
    ] = promotion_info


    return result

# ============================================================
# AGGREGATE 7-DAY BUSINESS FORECAST
# ============================================================

def aggregate_business_7day_forecast(daily_forecast):

    if daily_forecast.empty:
        raise ValueError("Business forecast is empty.")

    summary = (
        daily_forecast
        .groupby(
            ["store_id", "product_id", "product_name", "category"],
            as_index=False
        )
        .agg(
            forecast_demand_7d=("predicted_units", "sum")
        )
    )

    summary["forecast_demand_7d"] = (
        summary["forecast_demand_7d"]
        .clip(lower=0)
        .round(2)
    )

    summary["forecast_start"] = daily_forecast["date"].min()
    summary["forecast_end"] = daily_forecast["date"].max()

    expected_rows = (
        daily_forecast[["store_id", "product_id"]]
        .drop_duplicates()
        .shape[0]
    )

    if len(summary) != expected_rows:
        raise ValueError(
            f"Unexpected aggregated forecast row count. "
            f"Expected {expected_rows}, found {len(summary)}."
        )

    return summary



# ============================================================
# DIRECT TEST
# ============================================================

if __name__ == "__main__":

    forecast = generate_business_forecast()

    print("=== REAL BUSINESS 7-DAY FORECAST ===")
    print("Active sales source:", SALES_PATH)
    print(
        "Verified sales SHA-256:",
        calculate_file_sha256(
            SALES_PATH
        )
    )
    promotion_info = forecast.attrs.get(
        "promotion_info",
        {}
    )

    if promotion_info.get(
        "promotion_plan_used"
    ):

        print(
            "Future promotion plan:",
            promotion_info.get(
                "promotion_plan_path"
            )
        )

        print(
            "Promotion rows applied:",
            promotion_info.get(
                "promotion_rows_applied",
                0
            )
        )

    else:

        print(
            "Future promotion plan: none "
            "(promotion defaults to 0)"
        )

    print("Future input: automatically generated next 7 days")
    print("Rows:", len(forecast))
    print("Start:", forecast["date"].min())
    print("End:", forecast["date"].max())
    print("Stores:", forecast["store_id"].nunique())
    print("Products:", forecast["product_id"].nunique())
    print(
        "Total predicted units:",
        round(forecast["predicted_units"].sum(), 2)
    )

    print("\nFIRST 10 PREDICTIONS:")
    print(forecast.head(10).to_string(index=False))
    print("\n✅ Recursive business forecast successful.")

    summary = aggregate_business_7day_forecast(forecast)

    print("\n=== BUSINESS 7-DAY AGGREGATED FORECAST ===")
    print("Rows:", len(summary))
    print("Forecast start:", summary["forecast_start"].min())
    print("Forecast end:", summary["forecast_end"].max())
    print("Stores:", summary["store_id"].nunique())
    print("Products:", summary["product_id"].nunique())
    print(
        "Total 7-day demand:",
        round(summary["forecast_demand_7d"].sum(), 2)
    )

    print("\nAGGREGATED FORECASTS:")
    print(summary.to_string(index=False))

