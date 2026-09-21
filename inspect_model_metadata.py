import joblib

MODEL_PATH = "models/FINAL_lightgbm_retail_model.joblib"

model = joblib.load(MODEL_PATH)

print("=== MODEL METADATA ===")

print("Features:", model.n_features_in_)

print("\nCategorical metadata:")

categorical_data = getattr(
    model.booster_,
    "pandas_categorical",
    None
)

if categorical_data is None:
    print("No pandas categorical metadata found.")
else:
    print("Categorical feature groups:", len(categorical_data))

    for i, categories in enumerate(
        categorical_data,
        start=1
    ):
        print(
            f"\nCategorical Group {i}"
        )
        print("Count:", len(categories))
        print("Sample:", categories[:10])