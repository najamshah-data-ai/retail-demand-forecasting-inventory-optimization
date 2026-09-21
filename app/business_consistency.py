import pandas as pd


def check_business_consistency(
    sales_df: pd.DataFrame,
    inventory_df: pd.DataFrame
):

    errors = []
    warnings = []


    sales_pairs = set(
        zip(
            sales_df["store_id"].astype(str),
            sales_df["product_id"].astype(str),
        )
    )

    inventory_pairs = set(
        zip(
            inventory_df["store_id"].astype(str),
            inventory_df["product_id"].astype(str),
        )
    )


    # Inventory contains products/stores
    # that have no sales history
    missing_sales_history = (
        inventory_pairs - sales_pairs
    )

    if missing_sales_history:

        errors.append(
            {
                "message":
                    "Inventory contains store-product combinations "
                    "with no sales history.",

                "combinations":
                    sorted(
                        list(
                            missing_sales_history
                        )
                    )[:20]
            }
        )


    # Products in sales data but missing
    # from current inventory
    missing_inventory = (
        sales_pairs - inventory_pairs
    )

    if missing_inventory:

        warnings.append(
            {
                "message":
                    "Some store-product combinations in sales history "
                    "are missing from the current inventory file.",

                "combinations":
                    sorted(
                        list(
                            missing_inventory
                        )
                    )[:20]
            }
        )


    return {

        "valid":
            len(errors) == 0,

        "errors":
            errors,

        "warnings":
            warnings,

        "summary": {

            "sales_store_product_pairs":
                len(sales_pairs),

            "inventory_store_product_pairs":
                len(inventory_pairs),

            "inventory_pairs_without_sales_history":
                len(
                    missing_sales_history
                ),

            "sales_pairs_without_inventory":
                len(
                    missing_inventory
                ),
        }
    }