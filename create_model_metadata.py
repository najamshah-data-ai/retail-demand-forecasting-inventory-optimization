import json
import joblib


MODEL_PATH = (
    "models/FINAL_lightgbm_retail_model.joblib"
)

OUTPUT_PATH = (
    "models/FINAL_lightgbm_model_metadata.json"
)


model = joblib.load(
    MODEL_PATH
)

feature_names = list(
    model.feature_name_
)

categorical_groups = (
    model.booster_.pandas_categorical
)

categorical_features = [
    "store_nbr",
    "family",
    "city",
    "state",
    "type",
    "cluster"
]


if len(categorical_groups) != len(
    categorical_features
):
    raise ValueError(
        "Categorical metadata count mismatch"
    )


category_levels = {

    feature: categories

    for feature, categories in zip(
        categorical_features,
        categorical_groups
    )
}


metadata = {

    "model_name":
        "LightGBM Retail Demand",

    "model_version":
        "v3-final",

    "forecast_horizon_days":
        7,

    "feature_count":
        len(feature_names),

    "feature_names":
        feature_names,

    "categorical_features":
        categorical_features,

    "category_levels":
        category_levels
}


with open(
    OUTPUT_PATH,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        metadata,
        f,
        indent=4
    )


print(
    "=== INFERENCE METADATA CREATED ==="
)

print(
    "Features:",
    len(feature_names)
)

print(
    "Categorical Features:",
    categorical_features
)

for feature in categorical_features:

    print(
        feature,
        ":",
        len(
            category_levels[
                feature
            ]
        ),
        "categories"
    )

print(
    "\nSaved:",
    OUTPUT_PATH
)

print(
    "\n✅ Exact training categories preserved."
)