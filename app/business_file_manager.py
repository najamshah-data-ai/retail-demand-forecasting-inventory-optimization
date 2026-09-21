from pathlib import Path
from datetime import datetime, timezone
import json

import pandas as pd


# ============================================================
# PATHS
# ============================================================

UPLOAD_DIR = Path(
    "data/business_mode/uploads"
)

ACTIVE_SALES_PATH = (
    UPLOAD_DIR
    / "active_sales_history.csv"
)

ACTIVE_INVENTORY_PATH = (
    UPLOAD_DIR
    / "active_inventory.csv"
)

ACTIVE_METADATA_PATH = (
    UPLOAD_DIR
    / "active_business_files.json"
)


# ============================================================
# HELPERS
# ============================================================

def ensure_upload_directory():

    UPLOAD_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


def load_metadata():

    ensure_upload_directory()

    if not ACTIVE_METADATA_PATH.exists():

        return {
            "sales": None,
            "inventory": None,
        }

    with open(
        ACTIVE_METADATA_PATH,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(file)


def save_metadata(
    metadata
):

    ensure_upload_directory()

    with open(
        ACTIVE_METADATA_PATH,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            metadata,
            file,
            indent=4
        )


# ============================================================
# SAVE ACTIVE SALES
# ============================================================

def save_active_sales(
    dataframe,
    original_filename
):

    ensure_upload_directory()

    dataframe.to_csv(
        ACTIVE_SALES_PATH,
        index=False
    )

    metadata = load_metadata()

    metadata["sales"] = {
        "original_filename":
            original_filename,

        "active_path":
            str(
                ACTIVE_SALES_PATH
            ),

        "rows":
            int(
                len(dataframe)
            ),

        "saved_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),
    }

    save_metadata(
        metadata
    )

    return metadata["sales"]


# ============================================================
# SAVE ACTIVE INVENTORY
# ============================================================

def save_active_inventory(
    dataframe,
    original_filename
):

    ensure_upload_directory()

    dataframe.to_csv(
        ACTIVE_INVENTORY_PATH,
        index=False
    )

    metadata = load_metadata()

    metadata["inventory"] = {
        "original_filename":
            original_filename,

        "active_path":
            str(
                ACTIVE_INVENTORY_PATH
            ),

        "rows":
            int(
                len(dataframe)
            ),

        "saved_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),
    }

    save_metadata(
        metadata
    )

    return metadata["inventory"]


# ============================================================
# ACTIVE FILE STATUS
# ============================================================

def get_active_business_files():

    metadata = load_metadata()

    sales_exists = (
        ACTIVE_SALES_PATH.exists()
    )

    inventory_exists = (
        ACTIVE_INVENTORY_PATH.exists()
    )

    return {
        "sales_ready":
            sales_exists,

        "inventory_ready":
            inventory_exists,

        "both_ready":
            (
                sales_exists
                and inventory_exists
            ),

        "sales_path":
            (
                str(ACTIVE_SALES_PATH)
                if sales_exists
                else None
            ),

        "inventory_path":
            (
                str(ACTIVE_INVENTORY_PATH)
                if inventory_exists
                else None
            ),

        "metadata":
            metadata,
    }


# ============================================================
# DIRECT TEST
# ============================================================

if __name__ == "__main__":

    status = (
        get_active_business_files()
    )

    print(
        "=== ACTIVE BUSINESS FILE STATUS ==="
    )

    print(
        "Sales ready:",
        status["sales_ready"]
    )

    print(
        "Inventory ready:",
        status["inventory_ready"]
    )

    print(
        "Both ready:",
        status["both_ready"]
    )

    print(
        "\n✅ Business file manager working."
    )