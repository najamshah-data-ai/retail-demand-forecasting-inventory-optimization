from pathlib import Path
import hashlib
import json
import joblib
import numpy as np
import pandas as pd

from lightgbm import LGBMRegressor

from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
)


# ============================================================
# PATHS
# ============================================================

SALES_PATH = Path(
    "data/business_mode/uploads/active_sales_history.csv"
)

MODEL_DIR = Path(
    "models/business_mode"
)

MODEL_PATH = (
    MODEL_DIR
    / "business_lightgbm_model.joblib"
)

EVALUATION_MODEL_PATH = (
    MODEL_DIR
    / "business_lightgbm_evaluation_model.joblib"
)

METADATA_PATH = (
    MODEL_DIR
    / "business_model_metadata.json"
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
# FEATURE ENGINEERING
# ============================================================

def create_training_features(
    data
):

    df = data.copy()

    df = df.sort_values(
        [
            "store_id",
            "product_id",
            "date",
        ]
    ).reset_index(drop=True)

    groups = df.groupby(
        [
            "store_id",
            "product_id",
        ],
        sort=False,
    )

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

    shifted = (
        groups["units_sold"]
        .shift(1)
    )

    shifted_group = shifted.groupby(
        [
            df["store_id"],
            df["product_id"],
        ]
    )

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
# TRAIN BUSINESS MODEL
# ============================================================

def train_business_model():

    MODEL_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # 1. ACTIVE SALES FILE
    # --------------------------------------------------------

    if not SALES_PATH.exists():

        raise FileNotFoundError(
            "Active business sales file not found. "
            "Upload sales data first using "
            "POST /api/business/upload-sales."
        )

    sales_file_sha256 = (
        calculate_file_sha256(
            SALES_PATH
        )
    )

    # --------------------------------------------------------
    # 2. LOAD DATA
    # --------------------------------------------------------

    df = pd.read_csv(
        SALES_PATH,
        parse_dates=["date"],
    )

    raw_rows_loaded = int(
        len(df)
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
        if col not in df.columns
    ]

    if missing_columns:

        raise ValueError(
            "Active sales file is missing columns: "
            f"{missing_columns}"
        )

    df = df[
        required_columns
    ].copy()

    if df.empty:

        raise ValueError(
            "Active sales file contains no rows."
        )

    df["date"] = pd.to_datetime(
        df["date"],
        errors="coerce",
    )

    df["units_sold"] = pd.to_numeric(
        df["units_sold"],
        errors="coerce",
    )

    df["promotion"] = pd.to_numeric(
        df["promotion"],
        errors="coerce",
    )

    if df[
        required_columns
    ].isna().any().any():

        raise ValueError(
            "Active sales file contains missing "
            "or invalid values."
        )

    if (
        df["units_sold"] < 0
    ).any():

        raise ValueError(
            "units_sold cannot contain negative values."
        )

    # --------------------------------------------------------
    # 3. HISTORY CHECK
    # --------------------------------------------------------

    history_days = (
        df["date"].max()
        - df["date"].min()
    ).days + 1

    if history_days < 56:

        raise ValueError(
            "At least 56 days of sales history are required "
            "for 28-day lag features plus 28-day validation."
        )

    # --------------------------------------------------------
    # 4. FEATURES
    # --------------------------------------------------------

    df = create_training_features(
        df
    )

    df = df.dropna().reset_index(
        drop=True
    )

    if df.empty:

        raise ValueError(
            "No usable rows remain after feature engineering. "
            "Provide more sales history."
        )

    categorical_features = [
        "store_id",
        "product_id",
        "product_name",
        "category",
    ]

    for col in categorical_features:

        df[col] = df[col].astype(
            "category"
        )

    feature_names = [
        "store_id",
        "product_id",
        "product_name",
        "category",
        "promotion",
        "lag_1",
        "lag_7",
        "lag_14",
        "lag_28",
        "rolling_mean_7",
        "rolling_mean_14",
        "rolling_mean_28",
        "rolling_std_7",
        "rolling_std_28",
        "day_of_week",
        "day_of_month",
        "month",
        "week_of_year",
        "is_weekend",
    ]

    # --------------------------------------------------------
    # 5. CHRONOLOGICAL VALIDATION
    # --------------------------------------------------------

    max_date = df["date"].max()

    validation_start = (
        max_date
        - pd.Timedelta(days=27)
    )

    train_df = df[
        df["date"] < validation_start
    ].copy()

    valid_df = df[
        df["date"] >= validation_start
    ].copy()

    if train_df.empty:

        raise ValueError(
            "Training split is empty. "
            "Provide more historical sales data."
        )

    if valid_df.empty:

        raise ValueError(
            "Validation split is empty."
        )

    X_train = train_df[
        feature_names
    ]

    y_train = train_df[
        "units_sold"
    ]

    X_valid = valid_df[
        feature_names
    ]

    y_valid = valid_df[
        "units_sold"
    ]

    # --------------------------------------------------------
    # 6. TRAIN HOLDOUT EVALUATION MODEL
    # --------------------------------------------------------

    evaluation_model = LGBMRegressor(
        objective="regression_l1",
        n_estimators=500,
        learning_rate=0.03,
        num_leaves=31,
        min_child_samples=20,
        random_state=42,
        verbosity=-1,
    )

    evaluation_model.fit(
        X_train,
        y_train,
        categorical_feature=
            categorical_features,
    )

    # --------------------------------------------------------
    # 7. VALIDATE ON UNSEEN FINAL 28 DAYS
    # --------------------------------------------------------

    predictions = evaluation_model.predict(
        X_valid
    )

    predictions = np.maximum(
        predictions,
        0,
    )

    mae = mean_absolute_error(
        y_valid,
        predictions,
    )

    rmse = np.sqrt(
        mean_squared_error(
            y_valid,
            predictions,
        )
    )

    actual_sum = float(
        y_valid.sum()
    )

    if actual_sum > 0:

        wape = (
            np.abs(
                y_valid.values
                - predictions
            ).sum()
            /
            actual_sum
            * 100
        )

    else:

        wape = None

    # --------------------------------------------------------
    # 8. SAVE HOLDOUT EVALUATION MODEL
    # --------------------------------------------------------
    # IMPORTANT:
    # This model has NOT seen the validation period.
    # It is preserved for leakage-free historical backtesting
    # and safety-stock calibration.

    joblib.dump(
        evaluation_model,
        EVALUATION_MODEL_PATH,
    )

    # --------------------------------------------------------
    # 9. TRAIN FINAL PRODUCTION MODEL ON ALL FEATURE-READY DATA
    # --------------------------------------------------------
    # Validation metrics above remain untouched. Only after
    # evaluation is finished do we refit a fresh model using
    # every feature-ready historical observation.

    X_all = df[
        feature_names
    ]

    y_all = df[
        "units_sold"
    ]

    production_model = LGBMRegressor(
        objective="regression_l1",
        n_estimators=500,
        learning_rate=0.03,
        num_leaves=31,
        min_child_samples=20,
        random_state=42,
        verbosity=-1,
    )

    production_model.fit(
        X_all,
        y_all,
        categorical_feature=
            categorical_features,
    )

    # Main model path is now the production model used for
    # forecasting future unseen business demand.
    joblib.dump(
        production_model,
        MODEL_PATH,
    )

    category_levels = {}

    for col in categorical_features:

        category_levels[col] = (
            df[col]
            .cat
            .categories
            .astype(str)
            .tolist()
        )

    metadata = {
        "model_type":
            "LightGBM",

        "mode":
            "real_business",

        "source_sales_file":
            str(SALES_PATH),

        "source_sales_sha256":
            sales_file_sha256,

        "feature_names":
            feature_names,

        "categorical_features":
            categorical_features,

        "category_levels":
            category_levels,

        "train_start":
            str(
                train_df["date"]
                .min()
                .date()
            ),

        "train_end":
            str(
                train_df["date"]
                .max()
                .date()
            ),

        "validation_start":
            str(
                valid_df["date"]
                .min()
                .date()
            ),

        "validation_end":
            str(
                valid_df["date"]
                .max()
                .date()
            ),

        "validation_mae":
            float(mae),

        "validation_rmse":
            float(rmse),

        "validation_wape":
            (
                float(wape)
                if wape is not None
                else None
            ),

        "evaluation_model_path":
            str(EVALUATION_MODEL_PATH),

        "evaluation_training_rows":
            int(len(train_df)),

        "evaluation_validation_rows":
            int(len(valid_df)),

        "production_model_path":
            str(MODEL_PATH),

        "production_training_rows":
            int(len(df)),

        "production_train_start":
            str(
                df["date"]
                .min()
                .date()
            ),

        "production_train_end":
            str(
                df["date"]
                .max()
                .date()
            ),

        "production_model_role":
            "future_forecasting_full_history",

        "evaluation_model_role":
            "leakage_free_holdout_backtesting",

        "history_days":
            int(history_days),

        "raw_rows_loaded":
            int(raw_rows_loaded),

        "feature_ready_rows":
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

    with open(
        METADATA_PATH,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            metadata,
            file,
            indent=4,
        )

    # --------------------------------------------------------
    # 11. API-FRIENDLY RESULT
    # --------------------------------------------------------

    return {
        "message":
            "Business-specific model training completed.",

        "mode":
            "real_business",

        "source_sales_file":
            str(SALES_PATH),

        "source_sales_sha256":
            sales_file_sha256,

        "training_rows":
            int(len(train_df)),

        "validation_rows":
            int(len(valid_df)),

        "train_start":
            metadata["train_start"],

        "train_end":
            metadata["train_end"],

        "validation_start":
            metadata["validation_start"],

        "validation_end":
            metadata["validation_end"],

        "mae":
            round(
                float(mae),
                4,
            ),

        "rmse":
            round(
                float(rmse),
                4,
            ),

        "wape":
            (
                round(
                    float(wape),
                    4,
                )
                if wape is not None
                else None
            ),

        "stores":
            metadata["stores"],

        "products":
            metadata["products"],

        "production_training_rows":
            metadata[
                "production_training_rows"
            ],

        "production_train_start":
            metadata[
                "production_train_start"
            ],

        "production_train_end":
            metadata[
                "production_train_end"
            ],

        "model_path":
            str(MODEL_PATH),

        "evaluation_model_path":
            str(EVALUATION_MODEL_PATH),

        "metadata_path":
            str(METADATA_PATH),
    }


# ============================================================
# DIRECT TEST
# ============================================================

if __name__ == "__main__":

    result = train_business_model()

    print(
        "=== REAL BUSINESS MODEL TRAINING ==="
    )

    print(
        "Source sales file:",
        result["source_sales_file"]
    )

    print(
        "Sales SHA-256:",
        result["source_sales_sha256"]
    )

    print(
        "Training rows:",
        result["training_rows"]
    )

    print(
        "Validation rows:",
        result["validation_rows"]
    )

    print(
        "Train start:",
        result["train_start"]
    )

    print(
        "Train end:",
        result["train_end"]
    )

    print(
        "Validation start:",
        result["validation_start"]
    )

    print(
        "Validation end:",
        result["validation_end"]
    )

    print(
        "MAE:",
        result["mae"]
    )

    print(
        "RMSE:",
        result["rmse"]
    )

    if result["wape"] is not None:

        print(
            "WAPE:",
            result["wape"],
            "%"
        )

    else:

        print(
            "WAPE: unavailable "
            "(validation actual demand sum is 0)"
        )

    print(
        "Evaluation model saved:",
        result["evaluation_model_path"]
    )

    print(
        "Production training rows:",
        result["production_training_rows"]
    )

    print(
        "Production train start:",
        result["production_train_start"]
    )

    print(
        "Production train end:",
        result["production_train_end"]
    )

    print(
        "Production model saved:",
        result["model_path"]
    )

    print(
        "Metadata saved:",
        result["metadata_path"]
    )

    print(
        "\n✅ Holdout evaluation completed and final production "
        "model retrained on all feature-ready active sales data."
    )
