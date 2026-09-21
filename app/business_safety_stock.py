from pathlib import Path
import json
import math
import joblib

import numpy as np
import pandas as pd

from app.business_forecast_engine import (
    load_metadata,
    create_features,
    apply_categories,
    calculate_file_sha256,
)


# ============================================================
# PATHS
# ============================================================

SALES_PATH = Path(
    "data/business_mode/uploads/active_sales_history.csv"
)

OUTPUT_DIR = Path(
    "models/business_mode"
)

SAFETY_STOCK_PATH = (
    OUTPUT_DIR
    / "business_safety_stock.csv"
)

EVALUATION_MODEL_PATH = (
    OUTPUT_DIR
    / "business_lightgbm_evaluation_model.joblib"
)

BACKTEST_PATH = (
    OUTPUT_DIR
    / "business_safety_stock_backtest.csv"
)

DAILY_BACKTEST_PATH = (
    OUTPUT_DIR
    / "business_recursive_daily_backtest.csv"
)

METADATA_OUTPUT_PATH = (
    OUTPUT_DIR
    / "business_safety_stock_metadata.json"
)


# ============================================================
# SETTINGS
# ============================================================

SERVICE_LEVEL = 0.95

# At least 8 weekly residual observations
# before using product-level calibration.
MIN_PRODUCT_OBSERVATIONS = 8


# ============================================================
# LOAD LEAKAGE-FREE EVALUATION MODEL
# ============================================================

def load_evaluation_model():

    if not EVALUATION_MODEL_PATH.exists():
        raise FileNotFoundError(
            "Evaluation model not found. "
            "Train the business model first so the holdout "
            f"evaluation model is created: {EVALUATION_MODEL_PATH}"
        )

    return joblib.load(
        EVALUATION_MODEL_PATH
    )


# ============================================================
# EMPIRICAL QUANTILE
# ============================================================

def empirical_quantile_higher(
    values,
    q
):

    values = np.asarray(
        values,
        dtype=float
    )

    if len(values) == 0:

        return 0.0


    try:

        return float(
            np.quantile(
                values,
                q,
                method="higher"
            )
        )

    except TypeError:

        # Compatibility with older NumPy
        return float(
            np.quantile(
                values,
                q,
                interpolation="higher"
            )
        )


# ============================================================
# FORECAST ONE 7-DAY HISTORICAL BLOCK
# ============================================================

def forecast_backtest_block(
    model,
    metadata,
    full_data,
    block_start,
    block_end,
):

    feature_names = metadata[
        "feature_names"
    ]

    categorical_features = metadata[
        "categorical_features"
    ]


    # --------------------------------------------------------
    # ONLY DATA KNOWN BEFORE FORECAST START
    # --------------------------------------------------------

    working_history = full_data[
        full_data["date"]
        < block_start
    ].copy()


    actual_block = full_data[
        (
            full_data["date"]
            >= block_start
        )
        &
        (
            full_data["date"]
            <= block_end
        )
    ].copy()


    if actual_block.empty:

        raise ValueError(
            f"No actual rows found for "
            f"{block_start.date()} to "
            f"{block_end.date()}."
        )


    forecast_dates = pd.date_range(
        block_start,
        block_end,
        freq="D"
    )


    predictions_all = []


    # ========================================================
    # RECURSIVE DAILY FORECAST
    # ========================================================

    for forecast_date in forecast_dates:

        actual_day = actual_block[
            actual_block["date"]
            == forecast_date
        ].copy()


        if actual_day.empty:

            raise ValueError(
                "Missing actual business data for "
                f"{forecast_date.date()}."
            )


        day_future = actual_day[
            [
                "date",
                "store_id",
                "product_id",
                "product_name",
                "category",
                "promotion",
            ]
        ].copy()


        # Actual target must NOT be visible to model
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
        # CHECK REQUIRED FEATURES
        # ----------------------------------------------------

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
                "Missing model feature values during "
                f"backtest on {forecast_date.date()}:\n"
                f"{missing_numeric}"
            )


        # ----------------------------------------------------
        # APPLY ORIGINAL TRAINING CATEGORIES
        # ----------------------------------------------------

        prediction_rows = apply_categories(
            prediction_rows,
            metadata
        )


        X = prediction_rows[
            feature_names
        ].copy()


        # ----------------------------------------------------
        # PREDICT
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


        predictions_all.append(
            prediction_rows[
                [
                    "date",
                    "store_id",
                    "product_id",
                    "product_name",
                    "category",
                    "predicted_units",
                ]
            ].copy()
        )


        # ----------------------------------------------------
        # RECURSIVE FEEDBACK
        # ----------------------------------------------------

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


    predicted_block = pd.concat(
        predictions_all,
        ignore_index=True
    )


    # ========================================================
    # AGGREGATE PREDICTED 7-DAY DEMAND
    # ========================================================

    predicted_summary = (
        predicted_block
        .groupby(
            [
                "store_id",
                "product_id",
                "product_name",
                "category",
            ],
            as_index=False
        )
        .agg(
            predicted_7d=(
                "predicted_units",
                "sum"
            )
        )
    )


    # ========================================================
    # AGGREGATE ACTUAL 7-DAY DEMAND
    # ========================================================

    actual_summary = (
        actual_block
        .groupby(
            [
                "store_id",
                "product_id",
                "product_name",
                "category",
            ],
            as_index=False
        )
        .agg(
            actual_7d=(
                "units_sold",
                "sum"
            )
        )
    )


    result = actual_summary.merge(
        predicted_summary,
        on=[
            "store_id",
            "product_id",
            "product_name",
            "category",
        ],
        how="inner",
        validate="one_to_one",
    )


    result["block_start"] = (
        block_start
    )

    result["block_end"] = (
        block_end
    )


    result["forecast_error"] = (
        result["actual_7d"]
        - result["predicted_7d"]
    )


    result["underforecast_error"] = (
        result["forecast_error"]
        .clip(lower=0)
    )


    result["actual_7d"] = (
        result["actual_7d"]
        .round(2)
    )


    result["predicted_7d"] = (
        result["predicted_7d"]
        .round(2)
    )


    result["forecast_error"] = (
        result["forecast_error"]
        .round(2)
    )


    result["underforecast_error"] = (
        result["underforecast_error"]
        .round(2)
    )


    # ========================================================
    # DAILY RECURSIVE COMPARISON
    # Same granularity as daily deployment predictions.
    # ========================================================

    actual_daily = actual_block[
        [
            "date",
            "store_id",
            "product_id",
            "units_sold",
        ]
    ].copy()

    actual_daily = actual_daily.rename(
        columns={
            "units_sold":
                "actual_units"
        }
    )

    predicted_daily = predicted_block[
        [
            "date",
            "store_id",
            "product_id",
            "product_name",
            "category",
            "predicted_units",
        ]
    ].copy()

    daily_comparison = predicted_daily.merge(
        actual_daily,
        on=[
            "date",
            "store_id",
            "product_id",
        ],
        how="inner",
        validate="one_to_one",
    )

    if len(daily_comparison) != len(predicted_daily):

        raise ValueError(
            "Daily recursive backtest row mismatch. "
            f"Predicted rows: {len(predicted_daily)}, "
            f"matched rows: {len(daily_comparison)}."
        )

    daily_comparison["error"] = (
        daily_comparison["actual_units"]
        - daily_comparison["predicted_units"]
    )

    daily_comparison["absolute_error"] = (
        daily_comparison["error"]
        .abs()
    )

    daily_comparison["squared_error"] = (
        daily_comparison["error"]
        ** 2
    )

    daily_comparison["block_start"] = (
        block_start
    )

    daily_comparison["block_end"] = (
        block_end
    )


    return (
        result,
        daily_comparison,
    )


# ============================================================
# CALIBRATE SAFETY STOCK
# ============================================================

def calibrate_business_safety_stock():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    model = load_evaluation_model()
    metadata = load_metadata()


    if not SALES_PATH.exists():
        raise FileNotFoundError(
            "Active business sales file not found. "
            "Upload sales data first using "
            "POST /api/business/upload-sales."
        )


    expected_sales_sha256 = metadata.get(
        "source_sales_sha256"
    )

    if not expected_sales_sha256:
        raise ValueError(
            "Business model metadata does not contain "
            "source_sales_sha256. Retrain the business model "
            "before calibrating safety stock."
        )


    current_sales_sha256 = calculate_file_sha256(
        SALES_PATH
    )


    if current_sales_sha256 != expected_sales_sha256:
        raise ValueError(
            "The active sales file has changed since the "
            "business model was trained. Retrain the model "
            "before calibrating safety stock."
        )


    metadata_evaluation_model = metadata.get(
        "evaluation_model_path"
    )

    if not metadata_evaluation_model:
        raise ValueError(
            "Business model metadata does not contain "
            "evaluation_model_path. Retrain the business model "
            "using the Step 237 training script first."
        )

    metadata_evaluation_normalized = (
        str(metadata_evaluation_model)
        .replace("\\", "/")
        .lower()
    )

    expected_evaluation_normalized = (
        str(EVALUATION_MODEL_PATH)
        .replace("\\", "/")
        .lower()
    )

    if (
        metadata_evaluation_normalized
        != expected_evaluation_normalized
    ):
        raise ValueError(
            "Safety-stock calibration model does not match "
            "the evaluation model recorded in metadata."
        )


    trained_source = metadata.get(
        "source_sales_file"
    )

    if not trained_source:
        raise ValueError(
            "Business model metadata does not identify "
            "the active sales source. Retrain the model first."
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
            "active sales file. Retrain the model before "
            "calibrating safety stock."
        )


    sales = pd.read_csv(
        SALES_PATH,
        parse_dates=["date"]
    )


    sales["store_id"] = (
        sales["store_id"]
        .astype(str)
    )


    sales["product_id"] = (
        sales["product_id"]
        .astype(str)
    )


    sales = sales.sort_values(
        [
            "store_id",
            "product_id",
            "date"
        ]
    ).reset_index(
        drop=True
    )


    # ========================================================
    # VALIDATION RANGE FROM TRAINING METADATA
    # ========================================================

    validation_start = pd.Timestamp(
        metadata[
            "validation_start"
        ]
    )


    validation_end = pd.Timestamp(
        metadata[
            "validation_end"
        ]
    )


    validation_days = (
        validation_end
        - validation_start
    ).days + 1


    if validation_days < 28:

        raise ValueError(
            "At least 28 validation days are "
            "required for safety-stock calibration."
        )


    # ========================================================
    # FOUR 7-DAY BACKTEST BLOCKS
    # ========================================================

    blocks = []
    daily_blocks = []

    current_start = validation_start


    while (
        current_start
        + pd.Timedelta(days=6)
        <= validation_end
    ):

        current_end = (
            current_start
            + pd.Timedelta(days=6)
        )


        (
            block_result,
            daily_result,
        ) = forecast_backtest_block(
            model=model,
            metadata=metadata,
            full_data=sales,
            block_start=current_start,
            block_end=current_end,
        )


        blocks.append(
            block_result
        )

        daily_blocks.append(
            daily_result
        )


        current_start = (
            current_start
            + pd.Timedelta(days=7)
        )


    if not blocks:

        raise ValueError(
            "No complete 7-day calibration "
            "blocks were created."
        )


    backtest = pd.concat(
        blocks,
        ignore_index=True
    )

    daily_backtest = pd.concat(
        daily_blocks,
        ignore_index=True
    )


    # ========================================================
    # DAILY RECURSIVE DEPLOYMENT METRICS
    # Directly comparable in granularity to daily validation.
    # ========================================================

    recursive_daily_mae = float(
        daily_backtest[
            "absolute_error"
        ].mean()
    )

    recursive_daily_rmse = float(
        np.sqrt(
            daily_backtest[
                "squared_error"
            ].mean()
        )
    )

    recursive_daily_actual_sum = float(
        daily_backtest[
            "actual_units"
        ].sum()
    )

    if recursive_daily_actual_sum > 0:

        recursive_daily_wape = float(
            daily_backtest[
                "absolute_error"
            ].sum()
            /
            recursive_daily_actual_sum
            * 100
        )

    else:

        recursive_daily_wape = None


    # ========================================================
    # 7-DAY AGGREGATE BLOCK METRICS
    # Useful for total weekly demand accuracy, but not directly
    # comparable to daily WAPE because aggregation can cancel
    # over- and under-prediction across days.
    # ========================================================

    block_errors = (
        backtest["actual_7d"]
        - backtest["predicted_7d"]
    )

    recursive_7day_block_mae = float(
        np.mean(
            np.abs(
                block_errors
            )
        )
    )

    recursive_7day_block_rmse = float(
        np.sqrt(
            np.mean(
                np.square(
                    block_errors
                )
            )
        )
    )

    block_actual_sum = float(
        backtest["actual_7d"].sum()
    )

    if block_actual_sum > 0:

        recursive_7day_block_wape = float(
            np.abs(
                block_errors
            ).sum()
            /
            block_actual_sum
            * 100
        )

    else:

        recursive_7day_block_wape = None


    # ========================================================
    # GLOBAL FALLBACK BUFFER
    # ========================================================

    global_buffer = (
        empirical_quantile_higher(
            backtest[
                "underforecast_error"
            ].values,
            SERVICE_LEVEL
        )
    )


    # ========================================================
    # PRODUCT-LEVEL CALIBRATION
    # ========================================================

    safety_rows = []


    product_groups = backtest.groupby(
        [
            "product_id",
            "product_name",
            "category",
        ],
        sort=False
    )


    for (
        product_id,
        product_name,
        category,
    ), group in product_groups:


        observation_count = len(
            group
        )


        if (
            observation_count
            >= MIN_PRODUCT_OBSERVATIONS
        ):

            buffer_value = (
                empirical_quantile_higher(
                    group[
                        "underforecast_error"
                    ].values,
                    SERVICE_LEVEL
                )
            )

            calibration_level = (
                "PRODUCT"
            )

        else:

            buffer_value = (
                global_buffer
            )

            calibration_level = (
                "GLOBAL_FALLBACK"
            )


        # Business sells whole units
        safety_stock = max(
            0,
            math.ceil(
                buffer_value
            )
        )


        safety_rows.append({
            "product_id":
                product_id,

            "product_name":
                product_name,

            "category":
                category,

            "service_level":
                SERVICE_LEVEL,

            "calibration_level":
                calibration_level,

            "residual_observations":
                observation_count,

            "safety_stock":
                safety_stock,
        })


    safety_stock = pd.DataFrame(
        safety_rows
    )


    safety_stock = (
        safety_stock
        .sort_values(
            "product_id"
        )
        .reset_index(
            drop=True
        )
    )


    # ========================================================
    # SAVE OUTPUTS
    # ========================================================

    backtest.to_csv(
        BACKTEST_PATH,
        index=False
    )


    daily_backtest.to_csv(
        DAILY_BACKTEST_PATH,
        index=False
    )


    safety_stock.to_csv(
        SAFETY_STOCK_PATH,
        index=False
    )


    metadata_output = {
        "method":
            "empirical_underforecast_quantile",

        "source_sales_file":
            str(SALES_PATH),

        "source_sales_sha256":
            current_sales_sha256,

        "calibration_model_path":
            str(EVALUATION_MODEL_PATH),

        "calibration_model_role":
            "leakage_free_holdout_evaluation_model",

        "service_level":
            SERVICE_LEVEL,

        "validation_start":
            str(
                validation_start.date()
            ),

        "validation_end":
            str(
                validation_end.date()
            ),

        "weekly_blocks":
            int(
                backtest[
                    "block_start"
                ].nunique()
            ),

        "backtest_rows":
            int(
                len(backtest)
            ),

        "recursive_daily_mae":
            float(
                recursive_daily_mae
            ),

        "recursive_daily_rmse":
            float(
                recursive_daily_rmse
            ),

        "recursive_daily_wape":
            (
                float(
                    recursive_daily_wape
                )
                if recursive_daily_wape is not None
                else None
            ),

        "recursive_daily_rows":
            int(
                len(daily_backtest)
            ),

        "recursive_daily_metric_level":
            "store_product_day",

        "recursive_7day_block_mae":
            float(
                recursive_7day_block_mae
            ),

        "recursive_7day_block_rmse":
            float(
                recursive_7day_block_rmse
            ),

        "recursive_7day_block_wape":
            (
                float(
                    recursive_7day_block_wape
                )
                if recursive_7day_block_wape is not None
                else None
            ),

        "recursive_7day_block_metric_level":
            "store_product_7day_block",

        "global_buffer":
            float(
                global_buffer
            ),

        "minimum_product_observations":
            MIN_PRODUCT_OBSERVATIONS,

        "note":
            (
                "Safety stock and recursive deployment metrics are "
                "computed from leakage-free 7-day validation blocks "
                "using the holdout evaluation model only. "
                "Daily recursive metrics use store-product-day rows; "
                "7-day block metrics use aggregated weekly demand. "
                "The production model is not used for historical "
                "calibration or recursive evaluation."
            ),
    }


    with open(
        METADATA_OUTPUT_PATH,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            metadata_output,
            f,
            indent=4
        )


    return (
        safety_stock,
        backtest,
        metadata_output
    )


# ============================================================
# DIRECT TEST
# ============================================================

if __name__ == "__main__":

    (
        safety_stock,
        backtest,
        calibration_metadata,
    ) = calibrate_business_safety_stock()


    print(
        "=== BUSINESS SAFETY STOCK CALIBRATION ==="
    )

    print(
        "Active sales source:",
        SALES_PATH
    )

    print(
        "Verified sales SHA-256:",
        calculate_file_sha256(
            SALES_PATH
        )
    )

    print(
        "Calibration model:",
        EVALUATION_MODEL_PATH
    )


    print(
        "Validation period:",
        calibration_metadata[
            "validation_start"
        ],
        "to",
        calibration_metadata[
            "validation_end"
        ]
    )


    print(
        "7-day backtest blocks:",
        calibration_metadata[
            "weekly_blocks"
        ]
    )


    print(
        "Backtest rows:",
        calibration_metadata[
            "backtest_rows"
        ]
    )


    print(
        "Recursive DAILY MAE:",
        round(
            calibration_metadata[
                "recursive_daily_mae"
            ],
            4
        )
    )


    print(
        "Recursive DAILY RMSE:",
        round(
            calibration_metadata[
                "recursive_daily_rmse"
            ],
            4
        )
    )


    recursive_daily_wape_value = (
        calibration_metadata[
            "recursive_daily_wape"
        ]
    )

    if recursive_daily_wape_value is not None:

        print(
            "Recursive DAILY WAPE:",
            round(
                recursive_daily_wape_value,
                4
            ),
            "%"
        )

    else:

        print(
            "Recursive DAILY WAPE: unavailable "
            "(daily actual demand sum is 0)"
        )


    print(
        "Recursive 7-day BLOCK MAE:",
        round(
            calibration_metadata[
                "recursive_7day_block_mae"
            ],
            4
        )
    )


    print(
        "Recursive 7-day BLOCK RMSE:",
        round(
            calibration_metadata[
                "recursive_7day_block_rmse"
            ],
            4
        )
    )


    recursive_block_wape_value = (
        calibration_metadata[
            "recursive_7day_block_wape"
        ]
    )

    if recursive_block_wape_value is not None:

        print(
            "Recursive 7-day BLOCK WAPE:",
            round(
                recursive_block_wape_value,
                4
            ),
            "%"
        )

    else:

        print(
            "Recursive 7-day BLOCK WAPE: unavailable "
            "(block actual demand sum is 0)"
        )


    print(
        "Service level:",
        f"{SERVICE_LEVEL * 100:.0f}%"
    )


    print(
        "Global empirical buffer:",
        round(
            calibration_metadata[
                "global_buffer"
            ],
            2
        )
    )


    print(
        "\nSAFETY STOCK:"
    )


    print(
        safety_stock.to_string(
            index=False
        )
    )


    print(
        "\nFiles saved:"
    )


    print(
        BACKTEST_PATH
    )


    print(
        DAILY_BACKTEST_PATH
    )


    print(
        SAFETY_STOCK_PATH
    )


    print(
        METADATA_OUTPUT_PATH
    )


    print(
        "\n✅ Business safety stock calibration successful."
    )