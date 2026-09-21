from pathlib import Path
import json

import numpy as np
import pandas as pd

from app.business_forecast_engine import (
    generate_business_forecast,
    aggregate_business_7day_forecast,
)


# ============================================================
# PATHS
# ============================================================

INVENTORY_PATH = Path(
    "data/business_mode/uploads/active_inventory.csv"
)

SAFETY_STOCK_PATH = Path(
    "models/business_mode/business_safety_stock.csv"
)

SAFETY_STOCK_METADATA_PATH = Path(
    "models/business_mode/business_safety_stock_metadata.json"
)

MODEL_METADATA_PATH = Path(
    "models/business_mode/business_model_metadata.json"
)


# ============================================================
# LOAD INVENTORY
# ============================================================

def load_business_inventory():

    if not INVENTORY_PATH.exists():
        raise FileNotFoundError(
            "Active business inventory file not found. "
            "Upload inventory first using "
            "POST /api/business/upload-inventory. "
            f"Expected file: {INVENTORY_PATH}"
        )

    return pd.read_csv(
        INVENTORY_PATH
    )


# ============================================================
# VALIDATE INVENTORY
# ============================================================

def validate_business_inventory(inventory):

    required_columns = [
        "store_id",
        "product_id",
        "product_name",
        "current_stock",
        "on_order",
        "backorders",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in inventory.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Inventory missing columns: {missing_columns}"
        )

    if inventory.empty:
        raise ValueError(
            "Business inventory file is empty."
        )

    inventory = inventory.copy()

    inventory["store_id"] = (
        inventory["store_id"].astype(str).str.strip()
    )

    inventory["product_id"] = (
        inventory["product_id"].astype(str).str.strip()
    )

    numeric_columns = [
        "current_stock",
        "on_order",
        "backorders",
    ]

    for column in numeric_columns:
        inventory[column] = pd.to_numeric(
            inventory[column],
            errors="coerce"
        )

    if inventory[numeric_columns].isna().any().any():
        raise ValueError(
            "Inventory contains invalid numeric values."
        )

    if (inventory[numeric_columns] < 0).any().any():
        raise ValueError(
            "Inventory values cannot be negative."
        )

    duplicates = inventory.duplicated(
        ["store_id", "product_id"]
    ).sum()

    if duplicates > 0:
        raise ValueError(
            f"{duplicates} duplicate store-product inventory rows found."
        )

    return inventory


# ============================================================
# LOAD + VALIDATE SAFETY STOCK
# ============================================================

def load_business_safety_stock():

    if not SAFETY_STOCK_PATH.exists():
        raise FileNotFoundError(
            f"Safety stock file not found: {SAFETY_STOCK_PATH}"
        )

    safety_stock = pd.read_csv(
        SAFETY_STOCK_PATH
    )

    required_columns = [
        "product_id",
        "safety_stock",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in safety_stock.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Safety stock file missing columns: {missing_columns}"
        )

    if safety_stock.empty:
        raise ValueError(
            "Safety stock file is empty."
        )

    safety_stock = safety_stock.copy()

    safety_stock["product_id"] = (
        safety_stock["product_id"].astype(str).str.strip()
    )

    safety_stock["safety_stock"] = pd.to_numeric(
        safety_stock["safety_stock"],
        errors="coerce"
    )

    if safety_stock["safety_stock"].isna().any():
        raise ValueError(
            "Safety stock contains invalid numeric values."
        )

    if (safety_stock["safety_stock"] < 0).any():
        raise ValueError(
            "Safety stock cannot be negative."
        )

    duplicates = safety_stock.duplicated(
        ["product_id"]
    ).sum()

    if duplicates > 0:
        raise ValueError(
            f"{duplicates} duplicate product safety-stock rows found."
        )

    return safety_stock


# ============================================================
# VERIFY SAFETY-STOCK FRESHNESS
# ============================================================

def verify_safety_stock_freshness():

    if not SAFETY_STOCK_METADATA_PATH.exists():
        raise FileNotFoundError(
            "Safety-stock metadata not found. "
            "Calibrate safety stock before generating recommendations."
        )

    if not MODEL_METADATA_PATH.exists():
        raise FileNotFoundError(
            "Business model metadata not found. "
            "Train the business model before generating recommendations."
        )

    with open(
        SAFETY_STOCK_METADATA_PATH,
        "r",
        encoding="utf-8",
    ) as file:

        safety_metadata = json.load(
            file
        )

    with open(
        MODEL_METADATA_PATH,
        "r",
        encoding="utf-8",
    ) as file:

        model_metadata = json.load(
            file
        )

    safety_sha256 = safety_metadata.get(
        "source_sales_sha256"
    )

    model_sha256 = model_metadata.get(
        "source_sales_sha256"
    )

    if not safety_sha256:
        raise ValueError(
            "Safety-stock metadata does not contain "
            "source_sales_sha256. Recalibrate safety stock."
        )

    if not model_sha256:
        raise ValueError(
            "Business model metadata does not contain "
            "source_sales_sha256. Retrain the business model."
        )

    if safety_sha256 != model_sha256:
        raise ValueError(
            "Safety stock is stale for the current trained model. "
            "Recalibrate safety stock before generating "
            "inventory recommendations."
        )

    return {
        "source_sales_sha256":
            model_sha256,
    }


# ============================================================
# CREATE FINAL INVENTORY RECOMMENDATIONS
# ============================================================

def create_business_inventory_analysis():

    verify_safety_stock_freshness()

    daily_forecast = generate_business_forecast()

    forecast = aggregate_business_7day_forecast(
        daily_forecast
    )

    inventory = load_business_inventory()
    inventory = validate_business_inventory(
        inventory
    )

    safety_stock = load_business_safety_stock()

    forecast = forecast.copy()

    forecast["store_id"] = (
        forecast["store_id"].astype(str).str.strip()
    )

    forecast["product_id"] = (
        forecast["product_id"].astype(str).str.strip()
    )

    forecast_pairs = set(
        zip(
            forecast["store_id"],
            forecast["product_id"]
        )
    )

    inventory_pairs = set(
        zip(
            inventory["store_id"],
            inventory["product_id"]
        )
    )

    missing_inventory = forecast_pairs - inventory_pairs

    if missing_inventory:
        raise ValueError(
            "Inventory missing for forecasted store-product combinations: "
            f"{sorted(missing_inventory)}"
        )

    analysis = forecast.merge(
        inventory[
            [
                "store_id",
                "product_id",
                "current_stock",
                "on_order",
                "backorders",
            ]
        ],
        on=["store_id", "product_id"],
        how="left",
        validate="one_to_one",
    )

    analysis["inventory_position"] = (
        analysis["current_stock"]
        + analysis["on_order"]
        - analysis["backorders"]
    )

    analysis = analysis.merge(
        safety_stock[
            [
                "product_id",
                "safety_stock",
            ]
        ],
        on="product_id",
        how="left",
        validate="many_to_one",
    )

    if analysis["safety_stock"].isna().any():
        missing_products = (
            analysis.loc[
                analysis["safety_stock"].isna(),
                "product_id"
            ]
            .drop_duplicates()
            .tolist()
        )

        raise ValueError(
            "Safety stock missing for products: "
            f"{missing_products}"
        )

    analysis["base_demand_gap"] = (
        analysis["forecast_demand_7d"]
        - analysis["inventory_position"]
    ).clip(lower=0)

    analysis["reorder_point"] = (
        analysis["forecast_demand_7d"]
        + analysis["safety_stock"]
    )

    analysis["recommended_order"] = (
        analysis["reorder_point"]
        - analysis["inventory_position"]
    ).clip(lower=0)

    analysis["recommended_order"] = (
        np.ceil(
            analysis["recommended_order"]
        ).astype(int)
    )

    analysis["status"] = "HEALTHY"

    analysis.loc[
        analysis["inventory_position"]
        < analysis["reorder_point"],
        "status"
    ] = "LOW_STOCK"

    analysis.loc[
        analysis["inventory_position"]
        < analysis["forecast_demand_7d"],
        "status"
    ] = "CRITICAL"

    round_columns = [
        "forecast_demand_7d",
        "current_stock",
        "on_order",
        "backorders",
        "inventory_position",
        "base_demand_gap",
        "safety_stock",
        "reorder_point",
    ]

    for column in round_columns:
        analysis[column] = analysis[column].round(2)

    columns = [
        "store_id",
        "product_id",
        "product_name",
        "category",
        "forecast_start",
        "forecast_end",
        "forecast_demand_7d",
        "current_stock",
        "on_order",
        "backorders",
        "inventory_position",
        "base_demand_gap",
        "safety_stock",
        "reorder_point",
        "recommended_order",
        "status",
    ]

    analysis = (
        analysis[
            columns
        ]
        .sort_values(
            ["store_id", "product_id"]
        )
        .reset_index(drop=True)
    )

    return analysis


# ============================================================
# DIRECT TEST
# ============================================================

if __name__ == "__main__":

    analysis = create_business_inventory_analysis()

    print(
        "=== FINAL BUSINESS INVENTORY RECOMMENDATIONS ==="
    )

    print(
        "Active inventory source:",
        INVENTORY_PATH
    )

    freshness = verify_safety_stock_freshness()

    print(
        "Verified sales/safety SHA-256:",
        freshness[
            "source_sales_sha256"
        ]
    )

    print(
        "Rows:",
        len(analysis)
    )

    print(
        "Stores:",
        analysis["store_id"].nunique()
    )

    print(
        "Products:",
        analysis["product_id"].nunique()
    )

    print(
        "Total forecast demand:",
        round(
            analysis["forecast_demand_7d"].sum(),
            2
        )
    )

    print(
        "Total inventory position:",
        round(
            analysis["inventory_position"].sum(),
            2
        )
    )

    print(
        "Total safety stock:",
        round(
            analysis["safety_stock"].sum(),
            2
        )
    )

    print(
        "Total recommended order:",
        int(
            analysis["recommended_order"].sum()
        )
    )

    print(
        "\nSTATUS COUNTS:"
    )

    print(
        analysis["status"].value_counts()
    )

    print(
        "\nFINAL RECOMMENDATIONS:"
    )

    print(
        analysis.to_string(
            index=False
        )
    )

    print(
        "\n✅ Final business inventory recommendations successful."
    )
