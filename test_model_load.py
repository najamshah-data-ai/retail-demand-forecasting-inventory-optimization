from pathlib import Path
import joblib


MODEL_PATH = Path(
    "models/FINAL_lightgbm_retail_model.joblib"
)

print("=== FINAL MODEL LOAD TEST ===")

if not MODEL_PATH.exists():
    raise FileNotFoundError(
        f"Model not found: {MODEL_PATH}"
    )

model = joblib.load(MODEL_PATH)

print("✅ Model loaded successfully")
print("Model type:", type(model).__name__)


if hasattr(model, "n_features_in_"):
    print(
        "Feature count:",
        model.n_features_in_
    )


if hasattr(model, "feature_name_"):
    print("\n=== MODEL FEATURES ===")

    for i, feature in enumerate(
        model.feature_name_,
        start=1
    ):
        print(
            f"{i}. {feature}"
        )