from pathlib import Path
import json

from fastapi.responses import FileResponse, StreamingResponse
from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

from app.database import get_connection


app = FastAPI(
    title="Retail Demand & Inventory API",
    version="1.0.0",
)


@app.get("/")
def root():
    return {
        "message": "Retail Demand System API is running"
    }


@app.get("/api/health")
def health():
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DB_NAME()")
        database = cursor.fetchone()[0]
        return {
            "status": "healthy",
            "database": database,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()


@app.get("/api/stores")
def get_stores():
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT
                store_nbr,
                store_name,
                city,
                state,
                store_type,
                cluster
            FROM dbo.Stores
            WHERE is_active = 1
            ORDER BY store_nbr
            '''
        )

        rows = cursor.fetchall()

        stores = [
            {
                "store_nbr": row.store_nbr,
                "store_name": row.store_name,
                "city": row.city,
                "state": row.state,
                "store_type": row.store_type,
                "cluster": row.cluster,
            }
            for row in rows
        ]

        return {
            "count": len(stores),
            "stores": stores,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if conn:
            conn.close()


@app.get("/api/families")
def get_families():
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT
                family_id,
                family_name
            FROM dbo.ProductFamilies
            WHERE is_active = 1
            ORDER BY family_name
            '''
        )

        rows = cursor.fetchall()

        families = [
            {
                "family_id": row.family_id,
                "family_name": row.family_name,
            }
            for row in rows
        ]

        return {
            "count": len(families),
            "families": families,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if conn:
            conn.close()


class InventoryInput(BaseModel):
    store_nbr: int
    family_name: str
    current_stock: float = Field(ge=0)
    on_order: float = Field(default=0, ge=0)
    backorders: float = Field(default=0, ge=0)


@app.post("/api/inventory")
def add_inventory(inventory: InventoryInput):
    conn = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT store_nbr
            FROM dbo.Stores
            WHERE store_nbr = ?
              AND is_active = 1
            ''',
            inventory.store_nbr,
        )

        store = cursor.fetchone()

        if not store:
            raise HTTPException(
                status_code=404,
                detail="Store not found",
            )

        cursor.execute(
            '''
            SELECT family_id
            FROM dbo.ProductFamilies
            WHERE family_name = ?
              AND is_active = 1
            ''',
            inventory.family_name,
        )

        family = cursor.fetchone()

        if not family:
            raise HTTPException(
                status_code=404,
                detail="Product family not found",
            )

        family_id = family.family_id

        cursor.execute(
            '''
            INSERT INTO dbo.InventorySnapshots
            (
                store_nbr,
                family_id,
                current_stock,
                on_order,
                backorders
            )
            OUTPUT
                INSERTED.inventory_id,
                INSERTED.snapshot_time
            VALUES
            (
                ?, ?, ?, ?, ?
            )
            ''',
            inventory.store_nbr,
            family_id,
            inventory.current_stock,
            inventory.on_order,
            inventory.backorders,
        )

        inserted = cursor.fetchone()
        conn.commit()

        return {
            "message": "Inventory snapshot saved",
            "inventory_id": inserted.inventory_id,
            "store_nbr": inventory.store_nbr,
            "family_name": inventory.family_name,
            "current_stock": inventory.current_stock,
            "on_order": inventory.on_order,
            "backorders": inventory.backorders,
            "snapshot_time": inserted.snapshot_time,
        }

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if conn:
            conn.close()


@app.get("/api/inventory/latest")
def get_latest_inventory(
    store_nbr: int,
    family_name: str,
):
    conn = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT TOP 1
                i.inventory_id,
                i.store_nbr,
                f.family_name,
                i.current_stock,
                i.on_order,
                i.backorders,
                (
                    i.current_stock
                    + i.on_order
                    - i.backorders
                ) AS inventory_position,
                i.snapshot_time
            FROM dbo.InventorySnapshots i
            INNER JOIN dbo.ProductFamilies f
                ON i.family_id = f.family_id
            WHERE
                i.store_nbr = ?
                AND f.family_name = ?
            ORDER BY
                i.snapshot_time DESC,
                i.inventory_id DESC
            ''',
            store_nbr,
            family_name,
        )

        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Inventory snapshot not found",
            )

        return {
            "inventory_id": row.inventory_id,
            "store_nbr": row.store_nbr,
            "family_name": row.family_name,
            "current_stock": float(row.current_stock),
            "on_order": float(row.on_order),
            "backorders": float(row.backorders),
            "inventory_position": float(row.inventory_position),
            "snapshot_time": row.snapshot_time,
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# ============================================================
# SINGLE INVENTORY RECOMMENDATION
# ============================================================

@app.get("/api/recommendation")
def get_inventory_recommendation(
    store_nbr: int,
    family_name: str
):

    import math

    conn = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        # ----------------------------------------------------
        # 1. PRODUCT FAMILY
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT family_id
            FROM dbo.ProductFamilies
            WHERE family_name = ?
              AND is_active = 1
            """,
            family_name
        )

        family = cursor.fetchone()

        if not family:
            raise HTTPException(
                status_code=404,
                detail="Product family not found"
            )

        family_id = family.family_id

        # ----------------------------------------------------
        # 2. LATEST INVENTORY SNAPSHOT
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT TOP 1
                inventory_id,
                current_stock,
                on_order,
                backorders,
                snapshot_time
            FROM dbo.InventorySnapshots
            WHERE store_nbr = ?
              AND family_id = ?
            ORDER BY
                snapshot_time DESC,
                inventory_id DESC
            """,
            store_nbr,
            family_id
        )

        inventory = cursor.fetchone()

        if not inventory:
            raise HTTPException(
                status_code=404,
                detail="Inventory data not found"
            )

        # ----------------------------------------------------
        # 3. LATEST FORECAST WINDOW
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT TOP 1
                forecast_id,
                forecast_start,
                forecast_end,
                forecast_demand_7d,
                safety_stock,
                reorder_point,
                model_name,
                model_version
            FROM dbo.DemandForecasts
            WHERE store_nbr = ?
              AND family_id = ?
            ORDER BY
                forecast_start DESC,
                forecast_id DESC
            """,
            store_nbr,
            family_id
        )

        forecast = cursor.fetchone()

        if not forecast:
            raise HTTPException(
                status_code=404,
                detail="Forecast not found"
            )

        # ----------------------------------------------------
        # 4. CALCULATE INVENTORY DECISION
        # ----------------------------------------------------

        current_stock = float(
            inventory.current_stock
        )

        on_order = float(
            inventory.on_order
        )

        backorders = float(
            inventory.backorders
        )

        inventory_position = (
            current_stock
            + on_order
            - backorders
        )

        forecast_demand = float(
            forecast.forecast_demand_7d
        )

        safety_stock = float(
            forecast.safety_stock
        )

        reorder_point = float(
            forecast.reorder_point
        )

        recommended_order_qty = max(
            0,
            math.ceil(
                reorder_point
                - inventory_position
            )
        )

        reorder_required = (
            inventory_position
            <= reorder_point
        )

        if inventory_position < forecast_demand:

            stock_status = "CRITICAL"

        elif inventory_position <= reorder_point:

            stock_status = "LOW STOCK"

        else:

            stock_status = "HEALTHY"

        # ----------------------------------------------------
        # 5. RESPONSE EXPECTED BY DASHBOARD
        # ----------------------------------------------------

        return {

            "store_nbr":
                store_nbr,

            "family_name":
                family_name,

            "forecast_start":
                forecast.forecast_start,

            "forecast_end":
                forecast.forecast_end,

            "forecast_demand_7d":
                forecast_demand,

            "safety_stock":
                safety_stock,

            "reorder_point":
                reorder_point,

            "model_name":
                forecast.model_name,

            "model_version":
                forecast.model_version,

            "inventory": {

                "inventory_id":
                    inventory.inventory_id,

                "current_stock":
                    current_stock,

                "on_order":
                    on_order,

                "backorders":
                    backorders,

                "inventory_position":
                    inventory_position,

                "snapshot_time":
                    inventory.snapshot_time
            },

            "recommendation": {

                "recommended_order_qty":
                    recommended_order_qty,

                "reorder_required":
                    reorder_required,

                "stock_status":
                    stock_status
            }
        }

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if conn:
            conn.close()


# ============================================================
# AUTOMATIC INVENTORY RECOMMENDATION
# ============================================================

# ============================================================
# SAVE INVENTORY RECOMMENDATION — DUPLICATE SAFE
# ============================================================

@app.post("/api/recommendation/save")
def save_inventory_recommendation(
    store_nbr: int,
    family_name: str
):

    import math

    conn = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        # ----------------------------------------------------
        # 1. GET FAMILY
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT family_id
            FROM dbo.ProductFamilies
            WHERE family_name = ?
              AND is_active = 1
            """,
            family_name
        )

        family = cursor.fetchone()

        if not family:

            raise HTTPException(
                status_code=404,
                detail="Product family not found"
            )

        family_id = family.family_id

        # ----------------------------------------------------
        # 2. LATEST INVENTORY
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT TOP 1
                inventory_id,
                current_stock,
                on_order,
                backorders,
                snapshot_time
            FROM dbo.InventorySnapshots
            WHERE store_nbr = ?
              AND family_id = ?
            ORDER BY
                snapshot_time DESC,
                inventory_id DESC
            """,
            store_nbr,
            family_id
        )

        inventory = cursor.fetchone()

        if not inventory:

            raise HTTPException(
                status_code=404,
                detail="Inventory data not found"
            )

        # ----------------------------------------------------
        # 3. LATEST FORECAST
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT TOP 1
                forecast_id,
                forecast_start,
                forecast_end,
                forecast_demand_7d,
                safety_stock,
                reorder_point
            FROM dbo.DemandForecasts
            WHERE store_nbr = ?
              AND family_id = ?
            ORDER BY
                forecast_start DESC,
                forecast_id DESC
            """,
            store_nbr,
            family_id
        )

        forecast = cursor.fetchone()

        if not forecast:

            raise HTTPException(
                status_code=404,
                detail="Forecast not found"
            )

        # ----------------------------------------------------
        # 4. CALCULATE VALUES
        # ----------------------------------------------------

        current_stock = float(
            inventory.current_stock
        )

        on_order = float(
            inventory.on_order
        )

        backorders = float(
            inventory.backorders
        )

        inventory_position = (
            current_stock
            +
            on_order
            -
            backorders
        )

        forecast_demand = float(
            forecast.forecast_demand_7d
        )

        safety_stock = float(
            forecast.safety_stock
        )

        reorder_point = float(
            forecast.reorder_point
        )

        recommended_order_qty = max(
            0,
            math.ceil(
                reorder_point
                -
                inventory_position
            )
        )

        reorder_required = (
            inventory_position
            <=
            reorder_point
        )

        if inventory_position < forecast_demand:

            stock_status = "CRITICAL"

        elif inventory_position <= reorder_point:

            stock_status = "LOW STOCK"

        else:

            stock_status = "HEALTHY"

        # ----------------------------------------------------
        # 5. CHECK SAME RECOMMENDATION ALREADY EXISTS
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT TOP 1
                recommendation_id,
                created_at
            FROM dbo.InventoryRecommendations
            WHERE store_nbr = ?
              AND family_id = ?
              AND forecast_start = ?
              AND current_stock = ?
              AND on_order = ?
              AND backorders = ?
              AND inventory_position = ?
              AND recommended_order_qty = ?
              AND stock_status = ?
            ORDER BY
                recommendation_id DESC
            """,

            store_nbr,
            family_id,
            forecast.forecast_start,
            current_stock,
            on_order,
            backorders,
            inventory_position,
            recommended_order_qty,
            stock_status
        )

        existing = cursor.fetchone()

        # ----------------------------------------------------
        # 6. RETURN EXISTING INSTEAD OF DUPLICATING
        # ----------------------------------------------------

        if existing:

            return {

                "message":
                    "Recommendation already saved",

                "duplicate_prevented":
                    True,

                "recommendation_id":
                    existing.recommendation_id,

                "store_nbr":
                    store_nbr,

                "family_name":
                    family_name,

                "stock_status":
                    stock_status,

                "reorder_required":
                    reorder_required,

                "recommended_order_qty":
                    recommended_order_qty,

                "created_at":
                    existing.created_at
            }

        # ----------------------------------------------------
        # 7. INSERT NEW RECOMMENDATION
        # ----------------------------------------------------

        cursor.execute(
            """
            INSERT INTO dbo.InventoryRecommendations
            (
                store_nbr,
                family_id,
                forecast_start,
                forecast_end,
                forecast_demand_7d,
                safety_stock,
                reorder_point,
                current_stock,
                on_order,
                backorders,
                inventory_position,
                recommended_order_qty,
                reorder_required,
                stock_status
            )

            OUTPUT
                INSERTED.recommendation_id,
                INSERTED.created_at

            VALUES
            (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,

            store_nbr,
            family_id,
            forecast.forecast_start,
            forecast.forecast_end,
            forecast_demand,
            safety_stock,
            reorder_point,
            current_stock,
            on_order,
            backorders,
            inventory_position,
            recommended_order_qty,
            reorder_required,
            stock_status
        )

        inserted = cursor.fetchone()

        conn.commit()

        return {

            "message":
                "Inventory recommendation saved",

            "duplicate_prevented":
                False,

            "recommendation_id":
                inserted.recommendation_id,

            "store_nbr":
                store_nbr,

            "family_name":
                family_name,

            "stock_status":
                stock_status,

            "reorder_required":
                reorder_required,

            "recommended_order_qty":
                recommended_order_qty,

            "created_at":
                inserted.created_at
        }

    except HTTPException:

        if conn:
            conn.rollback()

        raise

    except Exception as e:

        if conn:
            conn.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if conn:
            conn.close()

# ============================================================
# GET RECOMMENDATION HISTORY
# ============================================================

@app.get("/api/recommendations")
def get_recommendations(
    store_nbr: int | None = None,
    stock_status: str | None = None,
    limit: int = 100
):

    conn = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        # Prevent huge responses
        limit = max(
            1,
            min(limit, 500)
        )

        query = f"""
            SELECT TOP {limit}

                r.recommendation_id,
                r.store_nbr,
                f.family_name,

                r.forecast_start,
                r.forecast_end,

                r.forecast_demand_7d,
                r.safety_stock,
                r.reorder_point,

                r.current_stock,
                r.on_order,
                r.backorders,
                r.inventory_position,

                r.recommended_order_qty,
                r.reorder_required,
                r.stock_status,

                r.created_at

            FROM dbo.InventoryRecommendations r

            INNER JOIN dbo.ProductFamilies f
                ON r.family_id = f.family_id

            WHERE 1 = 1
        """

        parameters = []

        # ----------------------------------------
        # Optional store filter
        # ----------------------------------------

        if store_nbr is not None:

            query += """
                AND r.store_nbr = ?
            """

            parameters.append(
                store_nbr
            )

        # ----------------------------------------
        # Optional status filter
        # ----------------------------------------

        if stock_status is not None:

            stock_status = (
                stock_status
                .strip()
                .upper()
            )

            valid_statuses = {
                "CRITICAL",
                "LOW STOCK",
                "HEALTHY"
            }

            if stock_status not in valid_statuses:

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "stock_status must be "
                        "CRITICAL, LOW STOCK or HEALTHY"
                    )
                )

            query += """
                AND r.stock_status = ?
            """

            parameters.append(
                stock_status
            )

        query += """
            ORDER BY
                r.created_at DESC,
                r.recommendation_id DESC
        """

        cursor.execute(
            query,
            *parameters
        )

        rows = cursor.fetchall()

        results = []

        for row in rows:

            results.append({

                "recommendation_id":
                    row.recommendation_id,

                "store_nbr":
                    row.store_nbr,

                "family_name":
                    row.family_name,

                "forecast_start":
                    row.forecast_start,

                "forecast_end":
                    row.forecast_end,

                "forecast_demand_7d":
                    float(
                        row.forecast_demand_7d
                    ),

                "safety_stock":
                    float(
                        row.safety_stock
                    ),

                "reorder_point":
                    float(
                        row.reorder_point
                    ),

                "current_stock":
                    float(
                        row.current_stock
                    ),

                "on_order":
                    float(
                        row.on_order
                    ),

                "backorders":
                    float(
                        row.backorders
                    ),

                "inventory_position":
                    float(
                        row.inventory_position
                    ),

                "recommended_order_qty":
                    float(
                        row.recommended_order_qty
                    ),

                "reorder_required":
                    bool(
                        row.reorder_required
                    ),

                "stock_status":
                    row.stock_status,

                "created_at":
                    row.created_at
            })

        return {

            "count":
                len(results),

            "recommendations":
                results
        }

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# DASHBOARD STATISTICS
# ============================================================

@app.get("/api/dashboard/stats")
def get_dashboard_stats():

    conn = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        # ----------------------------------------------------
        # TOTAL FORECASTS
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM dbo.DemandForecasts
            WHERE forecast_start =
            (
                SELECT MAX(forecast_start)
                FROM dbo.DemandForecasts
            )
            """
        )

        total_forecasts = cursor.fetchone()[0]

        # ----------------------------------------------------
        # TOTAL RECOMMENDATIONS
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM dbo.InventoryRecommendations
            """
        )

        total_recommendations = cursor.fetchone()[0]

        # ----------------------------------------------------
        # STATUS COUNTS
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT

                SUM(
                    CASE
                        WHEN stock_status = 'CRITICAL'
                        THEN 1
                        ELSE 0
                    END
                ) AS critical_count,

                SUM(
                    CASE
                        WHEN stock_status = 'LOW STOCK'
                        THEN 1
                        ELSE 0
                    END
                ) AS low_stock_count,

                SUM(
                    CASE
                        WHEN stock_status = 'HEALTHY'
                        THEN 1
                        ELSE 0
                    END
                ) AS healthy_count,

                SUM(
                    CASE
                        WHEN reorder_required = 1
                        THEN 1
                        ELSE 0
                    END
                ) AS reorder_required_count,

                SUM(
                    recommended_order_qty
                ) AS total_recommended_order_qty

            FROM dbo.InventoryRecommendations
            """
        )

        stats = cursor.fetchone()

        critical_count = (
            int(stats.critical_count)
            if stats.critical_count is not None
            else 0
        )

        low_stock_count = (
            int(stats.low_stock_count)
            if stats.low_stock_count is not None
            else 0
        )

        healthy_count = (
            int(stats.healthy_count)
            if stats.healthy_count is not None
            else 0
        )

        reorder_required_count = (
            int(stats.reorder_required_count)
            if stats.reorder_required_count is not None
            else 0
        )

        total_recommended_order_qty = (
            float(stats.total_recommended_order_qty)
            if stats.total_recommended_order_qty is not None
            else 0
        )

        # ----------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------

        return {

            "total_forecasts":
                total_forecasts,

            "total_recommendations":
                total_recommendations,

            "critical_items":
                critical_count,

            "low_stock_items":
                low_stock_count,

            "healthy_items":
                healthy_count,

            "reorder_required":
                reorder_required_count,

            "total_recommended_order_qty":
                total_recommended_order_qty
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# GET FORECASTS
# ============================================================

@app.get("/api/forecasts")
def get_forecasts(
    store_nbr: int | None = None,
    family_name: str | None = None,
    limit: int = 100
):

    conn = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        limit = max(
            1,
            min(limit, 500)
        )

        query = f"""
            SELECT TOP {limit}

                d.forecast_id,
                d.store_nbr,
                f.family_name,

                d.forecast_start,
                d.forecast_end,

                d.forecast_demand_7d,
                d.safety_stock,
                d.reorder_point,

                d.model_name,
                d.model_version,

                d.created_at

            FROM dbo.DemandForecasts d

            INNER JOIN dbo.ProductFamilies f
                ON d.family_id = f.family_id

            WHERE 1 = 1
        """

        parameters = []

        # ----------------------------------------
        # STORE FILTER
        # ----------------------------------------

        if store_nbr is not None:

            query += """
                AND d.store_nbr = ?
            """

            parameters.append(
                store_nbr
            )

        # ----------------------------------------
        # FAMILY FILTER
        # ----------------------------------------

        if family_name is not None:

            query += """
                AND f.family_name = ?
            """

            parameters.append(
                family_name
            )

        # ----------------------------------------
        # ORDER
        # ----------------------------------------

        query += """
            ORDER BY
                d.forecast_start DESC,
                d.store_nbr,
                f.family_name
        """

        cursor.execute(
            query,
            *parameters
        )

        rows = cursor.fetchall()

        forecasts = []

        for row in rows:

            forecasts.append({

                "forecast_id":
                    row.forecast_id,

                "store_nbr":
                    row.store_nbr,

                "family_name":
                    row.family_name,

                "forecast_start":
                    row.forecast_start,

                "forecast_end":
                    row.forecast_end,

                "forecast_demand_7d":
                    float(
                        row.forecast_demand_7d
                    ),

                "safety_stock":
                    float(
                        row.safety_stock
                    ),

                "reorder_point":
                    float(
                        row.reorder_point
                    ),

                "model_name":
                    row.model_name,

                "model_version":
                    row.model_version,

                "created_at":
                    row.created_at
            })

        return {

            "count":
                len(forecasts),

            "forecasts":
                forecasts
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# ============================================================
# FORECAST SUMMARY FOR DASHBOARD CHARTS
# ============================================================

@app.get("/api/dashboard/forecast-summary")
def get_forecast_summary(
    group_by: str = "family",
    limit: int = 10
):

    conn = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        group_by = group_by.strip().lower()

        if group_by not in {
            "family",
            "store"
        }:

            raise HTTPException(
                status_code=400,
                detail=(
                    "group_by must be "
                    "'family' or 'store'"
                )
            )

        limit = max(
            1,
            min(limit, 100)
        )

        # ====================================================
        # GROUP BY PRODUCT FAMILY
        # ====================================================

        if group_by == "family":

            query = f"""
                SELECT TOP {limit}

                    f.family_name AS label,

                    SUM(
                        d.forecast_demand_7d
                    ) AS total_forecast,

                    SUM(
                        d.safety_stock
                    ) AS total_safety_stock,

                    SUM(
                        d.reorder_point
                    ) AS total_reorder_point,

                    COUNT(*) AS series_count

                FROM dbo.DemandForecasts d

                INNER JOIN dbo.ProductFamilies f
                    ON d.family_id = f.family_id

                WHERE d.forecast_start =
                (
                    SELECT MAX(forecast_start)
                    FROM dbo.DemandForecasts
                )

                GROUP BY
                    f.family_name

                ORDER BY
                    total_forecast DESC
            """

        # ====================================================
        # GROUP BY STORE
        # ====================================================

        else:

            query = f"""
                SELECT TOP {limit}

                    CAST(
                        d.store_nbr
                        AS NVARCHAR(20)
                    ) AS label,

                    SUM(
                        d.forecast_demand_7d
                    ) AS total_forecast,

                    SUM(
                        d.safety_stock
                    ) AS total_safety_stock,

                    SUM(
                        d.reorder_point
                    ) AS total_reorder_point,

                    COUNT(*) AS series_count

                FROM dbo.DemandForecasts d

                WHERE d.forecast_start =
                (
                    SELECT MAX(forecast_start)
                    FROM dbo.DemandForecasts
                )

                GROUP BY
                    d.store_nbr

                ORDER BY
                    total_forecast DESC
            """

        cursor.execute(query)

        rows = cursor.fetchall()

        data = []

        for row in rows:

            data.append({

                "label":
                    row.label,

                "forecast_demand_7d":
                    float(
                        row.total_forecast
                    ),

                "safety_stock":
                    float(
                        row.total_safety_stock
                    ),

                "reorder_point":
                    float(
                        row.total_reorder_point
                    ),

                "series_count":
                    int(
                        row.series_count
                    )
            })

        return {

            "group_by":
                group_by,

            "count":
                len(data),

            "data":
                data
        }

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


    finally:

        if conn:
            conn.close()

# ============================================================
# DASHBOARD FRONTEND
# ============================================================

@app.get("/dashboard")
def dashboard():

    project_root = (
        Path(__file__)
        .resolve()
        .parent
        .parent
    )

    dashboard_file = (
        project_root
        / "frontend"
        / "index.html"
    )

    if not dashboard_file.exists():

        raise HTTPException(
            status_code=404,
            detail="Dashboard file not found"
        )

    return FileResponse(
        dashboard_file
    )
    
# ============================================================
# BULK INVENTORY CSV IMPORT
# ============================================================

# ============================================================
# BULK INVENTORY CSV IMPORT — VALIDATED VERSION
# ============================================================

@app.post("/api/inventory/bulk")
async def bulk_inventory_import(
    file: UploadFile = File(...)
):

    import io
    import numpy as np
    import pandas as pd

    conn = None

    # --------------------------------------------------------
    # 1. FILE TYPE
    # --------------------------------------------------------

    if not file.filename.lower().endswith(".csv"):

        raise HTTPException(
            status_code=400,
            detail="Only CSV files are allowed"
        )

    # --------------------------------------------------------
    # 2. READ CSV
    # --------------------------------------------------------

    try:

        contents = await file.read()

        df = pd.read_csv(
            io.BytesIO(contents)
        )

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=f"Could not read CSV: {e}"
        )

    # --------------------------------------------------------
    # 3. REQUIRED COLUMNS
    # --------------------------------------------------------

    required_columns = [
        "store_nbr",
        "family_name",
        "current_stock",
        "on_order",
        "backorders"
    ]

    missing_columns = [
        col
        for col in required_columns
        if col not in df.columns
    ]

    if missing_columns:

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    "Required columns are missing",

                "missing_columns":
                    missing_columns
            }
        )

    df = df[
        required_columns
    ].copy()

    if df.empty:

        raise HTTPException(
            status_code=400,
            detail="CSV contains no rows"
        )

    # --------------------------------------------------------
    # 4. NORMALIZE FAMILY NAME
    # --------------------------------------------------------

    df["family_name"] = (
        df["family_name"]
        .astype("string")
        .str.strip()
    )

    # --------------------------------------------------------
    # 5. CONVERT NUMERIC COLUMNS
    # --------------------------------------------------------

    numeric_columns = [
        "store_nbr",
        "current_stock",
        "on_order",
        "backorders"
    ]

    for col in numeric_columns:

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    # --------------------------------------------------------
    # 6. BLOCK BLANK / MISSING VALUES
    # --------------------------------------------------------

    missing_rows = df[
        required_columns
    ].isna().any(axis=1)

    if missing_rows.any():

        bad_rows = (
            df.index[
                missing_rows
            ]
            + 2
        ).tolist()

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    "Blank or invalid values found",

                "rows":
                    bad_rows[:20],

                "hint":
                    (
                        "Fill current_stock, on_order "
                        "and backorders before upload."
                    )
            }
        )

    # --------------------------------------------------------
    # 7. STORE NUMBER MUST BE INTEGER
    # --------------------------------------------------------

    invalid_store_numbers = (
        df["store_nbr"]
        %
        1
        != 0
    )

    if invalid_store_numbers.any():

        bad_rows = (
            df.index[
                invalid_store_numbers
            ]
            + 2
        ).tolist()

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    "store_nbr must be an integer",

                "rows":
                    bad_rows[:20]
            }
        )

    df["store_nbr"] = (
        df["store_nbr"]
        .astype(int)
    )

    # --------------------------------------------------------
    # 8. NO NEGATIVE INVENTORY VALUES
    # --------------------------------------------------------

    stock_columns = [
        "current_stock",
        "on_order",
        "backorders"
    ]

    negative_rows = (
        df[
            stock_columns
        ]
        < 0
    ).any(axis=1)

    if negative_rows.any():

        bad_rows = (
            df.index[
                negative_rows
            ]
            + 2
        ).tolist()

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    "Negative inventory values are not allowed",

                "rows":
                    bad_rows[:20]
            }
        )

    # --------------------------------------------------------
    # 9. BLOCK INFINITE VALUES
    # --------------------------------------------------------

    finite_check = np.isfinite(
        df[
            numeric_columns
        ].to_numpy(
            dtype=float
        )
    )

    if not finite_check.all():

        raise HTTPException(
            status_code=400,
            detail="Infinite numeric values are not allowed"
        )

    # --------------------------------------------------------
    # 10. DUPLICATE STORE-FAMILY CHECK
    # --------------------------------------------------------

    duplicate_mask = df.duplicated(
        subset=[
            "store_nbr",
            "family_name"
        ],
        keep=False
    )

    if duplicate_mask.any():

        duplicate_rows = (
            df.index[
                duplicate_mask
            ]
            + 2
        ).tolist()

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    "Duplicate store-family rows found",

                "rows":
                    duplicate_rows[:20]
            }
        )

    # --------------------------------------------------------
    # 11. DATABASE VALIDATION
    # --------------------------------------------------------

    try:

        conn = get_connection()
        cursor = conn.cursor()

        # Valid stores
        cursor.execute(
            """
            SELECT store_nbr
            FROM dbo.Stores
            WHERE is_active = 1
            """
        )

        valid_stores = {
            int(row.store_nbr)
            for row in cursor.fetchall()
        }

        # Valid families
        cursor.execute(
            """
            SELECT
                family_id,
                family_name
            FROM dbo.ProductFamilies
            WHERE is_active = 1
            """
        )

        family_map = {
            row.family_name:
                row.family_id
            for row in cursor.fetchall()
        }

        validation_errors = []

        for index, row in df.iterrows():

            store_nbr = int(
                row["store_nbr"]
            )

            family_name = str(
                row["family_name"]
            ).strip()

            if store_nbr not in valid_stores:

                validation_errors.append(
                    f"Row {index + 2}: "
                    f"Store {store_nbr} not found"
                )

            if family_name not in family_map:

                validation_errors.append(
                    f"Row {index + 2}: "
                    f"Family '{family_name}' not found"
                )

        if validation_errors:

            raise HTTPException(
                status_code=400,
                detail={
                    "message":
                        "Database validation failed",

                    "errors":
                        validation_errors[:20]
                }
            )

        # ----------------------------------------------------
        # 12. INSERT ONLY AFTER ALL VALIDATION PASSES
        # ----------------------------------------------------

        inserted = 0

        for _, row in df.iterrows():

            store_nbr = int(
                row["store_nbr"]
            )

            family_name = str(
                row["family_name"]
            ).strip()

            family_id = family_map[
                family_name
            ]

            cursor.execute(
                """
                INSERT INTO dbo.InventorySnapshots
                (
                    store_nbr,
                    family_id,
                    current_stock,
                    on_order,
                    backorders
                )
                VALUES
                (
                    ?, ?, ?, ?, ?
                )
                """,

                store_nbr,
                family_id,
                float(
                    row["current_stock"]
                ),
                float(
                    row["on_order"]
                ),
                float(
                    row["backorders"]
                )
            )

            inserted += 1

        conn.commit()

        return {

            "message":
                "Bulk inventory import completed",

            "filename":
                file.filename,

            "rows_received":
                int(len(df)),

            "rows_inserted":
                int(inserted),

            "status":
                "success"
        }

    except HTTPException:

        if conn:
            conn.rollback()

        raise

    except Exception as e:

        if conn:
            conn.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if conn:
            conn.close()
            
# ============================================================
# BULK GENERATE INVENTORY RECOMMENDATIONS
# ============================================================

@app.post("/api/recommendations/generate-all")
def generate_all_recommendations():

    import math

    conn = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        # ----------------------------------------------------
        # LATEST INVENTORY FOR EVERY STORE-FAMILY
        # ----------------------------------------------------

        cursor.execute(
    """
    WITH LatestInventory AS
    (
        SELECT
            i.*,

            ROW_NUMBER() OVER
            (
                PARTITION BY
                    i.store_nbr,
                    i.family_id

                ORDER BY
                    i.snapshot_time DESC,
                    i.inventory_id DESC
            ) AS rn

        FROM dbo.InventorySnapshots i
    ),

    LatestForecast AS
        (
            SELECT
                d.*,

                ROW_NUMBER() OVER
                (
                    PARTITION BY
                        d.store_nbr,
                        d.family_id

                    ORDER BY
                        d.forecast_start DESC,
                        d.forecast_id DESC
                ) AS rn

            FROM dbo.DemandForecasts d
        )

        SELECT
            li.inventory_id,
            li.store_nbr,
            li.family_id,

            li.current_stock,
            li.on_order,
            li.backorders,

            lf.forecast_start,
            lf.forecast_end,
            lf.forecast_demand_7d,
            lf.safety_stock,
            lf.reorder_point

        FROM LatestInventory li

        INNER JOIN LatestForecast lf
            ON li.store_nbr = lf.store_nbr
        AND li.family_id = lf.family_id

        WHERE
            li.rn = 1
            AND lf.rn = 1
        """
    )

        rows = cursor.fetchall()

        if not rows:

            raise HTTPException(
                status_code=400,
                detail=(
                    "No inventory data available. "
                    "Upload inventory first."
                )
            )

        inserted = 0
        duplicates_skipped = 0

        status_counts = {
            "CRITICAL": 0,
            "LOW STOCK": 0,
            "HEALTHY": 0
        }

        total_order_qty = 0

        # ----------------------------------------------------
        # PROCESS EACH STORE-FAMILY
        # ----------------------------------------------------

        for row in rows:

            current_stock = float(
                row.current_stock
            )

            on_order = float(
                row.on_order
            )

            backorders = float(
                row.backorders
            )

            inventory_position = (
                current_stock
                +
                on_order
                -
                backorders
            )

            forecast_demand = float(
                row.forecast_demand_7d
            )

            safety_stock = float(
                row.safety_stock
            )

            reorder_point = float(
                row.reorder_point
            )

            recommended_order_qty = max(
                0,
                math.ceil(
                    reorder_point
                    -
                    inventory_position
                )
            )

            reorder_required = (
                inventory_position
                <=
                reorder_point
            )

            # ----------------------------------------
            # STATUS
            # ----------------------------------------

            if inventory_position < forecast_demand:

                stock_status = "CRITICAL"

            elif inventory_position <= reorder_point:

                stock_status = "LOW STOCK"

            else:

                stock_status = "HEALTHY"

            status_counts[
                stock_status
            ] += 1

            total_order_qty += (
                recommended_order_qty
            )

            # ----------------------------------------
            # DUPLICATE CHECK
            # ----------------------------------------

            cursor.execute(
                """
                SELECT recommendation_id

                FROM dbo.InventoryRecommendations

                WHERE store_nbr = ?
                  AND family_id = ?
                  AND forecast_start = ?
                  AND current_stock = ?
                  AND on_order = ?
                  AND backorders = ?
                  AND recommended_order_qty = ?
                  AND stock_status = ?
                """,

                row.store_nbr,
                row.family_id,
                row.forecast_start,
                current_stock,
                on_order,
                backorders,
                recommended_order_qty,
                stock_status
            )

            existing = cursor.fetchone()

            if existing:

                duplicates_skipped += 1
                continue

            # ----------------------------------------
            # INSERT
            # ----------------------------------------

            cursor.execute(
                """
                INSERT INTO dbo.InventoryRecommendations
                (
                    store_nbr,
                    family_id,
                    forecast_start,
                    forecast_end,
                    forecast_demand_7d,
                    safety_stock,
                    reorder_point,
                    current_stock,
                    on_order,
                    backorders,
                    inventory_position,
                    recommended_order_qty,
                    reorder_required,
                    stock_status
                )

                VALUES
                (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,

                row.store_nbr,
                row.family_id,
                row.forecast_start,
                row.forecast_end,
                forecast_demand,
                safety_stock,
                reorder_point,
                current_stock,
                on_order,
                backorders,
                inventory_position,
                recommended_order_qty,
                reorder_required,
                stock_status
            )

            inserted += 1

        conn.commit()

        # ----------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------

        return {

            "message":
                "Bulk recommendations generated",

            "inventory_series_processed":
                len(rows),

            "recommendations_inserted":
                inserted,

            "duplicates_skipped":
                duplicates_skipped,

            "critical_items":
                status_counts["CRITICAL"],

            "low_stock_items":
                status_counts["LOW STOCK"],

            "healthy_items":
                status_counts["HEALTHY"],

            "total_recommended_order_qty":
                total_order_qty
        }

    except HTTPException:

        if conn:
            conn.rollback()

        raise

    except Exception as e:

        if conn:
            conn.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if conn:
            conn.close()
            
# ============================================================
# ACTIVE MODEL INFORMATION
# ============================================================

@app.get("/api/model/active")
def get_active_model():

    conn = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT TOP 1
                model_id,
                model_name,
                model_version,
                dataset_name,
                validation_wape,
                test_wape,
                is_active,
                created_at
            FROM dbo.ModelRegistry
            WHERE is_active = 1
            ORDER BY model_id DESC
            """
        )

        model = cursor.fetchone()

        if not model:

            raise HTTPException(
                status_code=404,
                detail="No active model found"
            )

        return {
            "model_id":
                model.model_id,

            "model_name":
                model.model_name,

            "model_version":
                model.model_version,

            "dataset":
                model.dataset_name,

            "validation_wape":
                float(model.validation_wape),

            "test_wape":
                float(model.test_wape),

            "is_active":
                bool(model.is_active),

            "created_at":
                model.created_at
        }

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if conn:
            conn.close()
            
# ============================================================
# MODEL CROSS-DATASET COMPARISON
# ============================================================

@app.get("/api/model/comparison")
def get_model_comparison():

    conn = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                model_name,
                model_version,
                dataset_name,
                validation_wape,
                test_wape,
                baseline_wape,
                improvement_over_baseline,
                is_active
            FROM dbo.ModelRegistry
            ORDER BY model_id
            """
        )

        rows = cursor.fetchall()

        models = []

        for row in rows:

            models.append({

                "model_name":
                    row.model_name,

                "model_version":
                    row.model_version,

                "dataset":
                    row.dataset_name,

                "validation_wape":
                    float(row.validation_wape),

                "test_wape":
                    float(row.test_wape),

                "baseline_wape":
                    float(row.baseline_wape),

                "improvement_over_baseline":
                    float(
                        row.improvement_over_baseline
                    ),

                "is_active":
                    bool(row.is_active)
            })

        return {

            "count":
                len(models),

            "models":
                models,

            "research_conclusion":
                (
                    "The forecasting methodology "
                    "outperformed the 7-day seasonal "
                    "naive baseline on both Favorita "
                    "and M5 retail datasets."
                )
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if conn:
            conn.close()
            
            
# ============================================================
# EXPORT INVENTORY RECOMMENDATIONS CSV
# ============================================================

# ============================================================
# EXPORT INVENTORY RECOMMENDATIONS CSV — FILTERED
# ============================================================

@app.get("/api/recommendations/export")
def export_recommendations(
    store_nbr: int | None = None,
    stock_status: str | None = None
):

    import io
    import pandas as pd

    conn = None

    try:

        conn = get_connection()

        query = """
            SELECT
                r.recommendation_id,
                r.store_nbr,
                f.family_name,
                r.forecast_start,
                r.forecast_end,
                r.forecast_demand_7d,
                r.safety_stock,
                r.reorder_point,
                r.current_stock,
                r.on_order,
                r.backorders,
                r.inventory_position,
                r.recommended_order_qty,
                r.reorder_required,
                r.stock_status,
                r.created_at

            FROM dbo.InventoryRecommendations r

            INNER JOIN dbo.ProductFamilies f
                ON r.family_id = f.family_id

            WHERE 1 = 1
        """

        params = []

        # ----------------------------------------------------
        # STORE FILTER
        # ----------------------------------------------------

        if store_nbr is not None:

            query += """
                AND r.store_nbr = ?
            """

            params.append(
                store_nbr
            )

        # ----------------------------------------------------
        # STATUS FILTER
        # ----------------------------------------------------

        if stock_status is not None:

            stock_status = (
                stock_status
                .strip()
                .upper()
            )

            valid_statuses = {
                "CRITICAL",
                "LOW STOCK",
                "HEALTHY"
            }

            if stock_status not in valid_statuses:

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "stock_status must be "
                        "CRITICAL, LOW STOCK or HEALTHY"
                    )
                )

            query += """
                AND r.stock_status = ?
            """

            params.append(
                stock_status
            )

        query += """
            ORDER BY
                r.created_at DESC,
                r.recommendation_id DESC
        """

        df = pd.read_sql(
            query,
            conn,
            params=params
        )

        output = io.StringIO()

        df.to_csv(
            output,
            index=False
        )

        output.seek(0)

        filename = "inventory_recommendations"

        if store_nbr is not None:
            filename += f"_store_{store_nbr}"

        if stock_status is not None:
            filename += "_" + stock_status.replace(
                " ",
                "_"
            ).lower()

        filename += ".csv"

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition":
                    f'attachment; filename="{filename}"'
            }
        )

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if conn:
            conn.close()
            
# ============================================================
# DOWNLOAD INVENTORY INPUT TEMPLATE
# ============================================================

@app.get("/api/inventory/template")
def download_inventory_template():

    import io
    import pandas as pd

    conn = None

    try:

        conn = get_connection()

        query = """
            SELECT DISTINCT
                d.store_nbr,
                f.family_name

            FROM dbo.DemandForecasts d

            INNER JOIN dbo.ProductFamilies f
                ON d.family_id = f.family_id

            ORDER BY
                d.store_nbr,
                f.family_name
        """

        df = pd.read_sql(
            query,
            conn
        )

        df["current_stock"] = ""
        df["on_order"] = ""
        df["backorders"] = ""

        output = io.StringIO()

        df.to_csv(
            output,
            index=False
        )

        output.seek(0)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition":
                    'attachment; filename="current_inventory_template.csv"'
            }
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if conn:
            conn.close()
            
# ============================================================
# REAL BUSINESS MODE — SALES DATA ANALYSIS
# ============================================================

@app.post("/api/business/analyze-sales")
async def analyze_business_sales(
    file: UploadFile = File(...)
):

    import io
    import pandas as pd

    from app.business_data_validator import (
        validate_sales_data,
    )

    # --------------------------------------------------------
    # FILE TYPE
    # --------------------------------------------------------

    if not file.filename.lower().endswith(".csv"):

        raise HTTPException(
            status_code=400,
            detail="Only CSV files are allowed."
        )


    # --------------------------------------------------------
    # READ CSV
    # --------------------------------------------------------

    try:

        contents = await file.read()

        df = pd.read_csv(
            io.BytesIO(contents)
        )

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=f"Could not read CSV: {e}"
        )


    # --------------------------------------------------------
    # VALIDATE + PROFILE
    # --------------------------------------------------------

    result = validate_sales_data(
        df
    )


    return {

        "filename":
            file.filename,

        "mode":
            "real_business",

        "data_type":
            "sales_history",

        **result
    }
    
# ============================================================
# REAL BUSINESS MODE — INVENTORY DATA ANALYSIS
# ============================================================

@app.post("/api/business/analyze-inventory")
async def analyze_business_inventory(
    file: UploadFile = File(...)
):

    import io
    import pandas as pd

    from app.business_data_validator import (
        validate_inventory_data,
    )

    # --------------------------------------------------------
    # FILE TYPE
    # --------------------------------------------------------

    if not file.filename.lower().endswith(".csv"):

        raise HTTPException(
            status_code=400,
            detail="Only CSV files are allowed."
        )


    # --------------------------------------------------------
    # READ CSV
    # --------------------------------------------------------

    try:

        contents = await file.read()

        df = pd.read_csv(
            io.BytesIO(contents)
        )

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=f"Could not read CSV: {e}"
        )


    # --------------------------------------------------------
    # VALIDATE + PROFILE
    # --------------------------------------------------------

    result = validate_inventory_data(
        df
    )


    return {

        "filename":
            file.filename,

        "mode":
            "real_business",

        "data_type":
            "inventory",

        **result
    }
    
# ============================================================
# REAL BUSINESS MODE — FULL READINESS CHECK
# ============================================================

@app.post("/api/business/readiness-check")
async def business_readiness_check(
    sales_file: UploadFile = File(...),
    inventory_file: UploadFile = File(...)
):

    import io
    import pandas as pd

    from app.business_data_validator import (
        validate_sales_data,
        validate_inventory_data,
    )

    from app.business_consistency import (
        check_business_consistency,
    )


    # --------------------------------------------------------
    # FILE TYPE CHECK
    # --------------------------------------------------------

    if not sales_file.filename.lower().endswith(".csv"):

        raise HTTPException(
            status_code=400,
            detail="Sales file must be CSV."
        )

    if not inventory_file.filename.lower().endswith(".csv"):

        raise HTTPException(
            status_code=400,
            detail="Inventory file must be CSV."
        )


    # --------------------------------------------------------
    # READ FILES
    # --------------------------------------------------------

    try:

        sales_contents = await sales_file.read()

        sales_df = pd.read_csv(
            io.BytesIO(
                sales_contents
            )
        )


        inventory_contents = await inventory_file.read()

        inventory_df = pd.read_csv(
            io.BytesIO(
                inventory_contents
            )
        )

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=f"Could not read files: {e}"
        )


    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    sales_validation = validate_sales_data(
        sales_df
    )

    inventory_validation = validate_inventory_data(
        inventory_df
    )


    # --------------------------------------------------------
    # CONSISTENCY
    # --------------------------------------------------------

    if (
        sales_validation["valid"]
        and inventory_validation["valid"]
    ):

        consistency = check_business_consistency(
            sales_df,
            inventory_df
        )

    else:

        consistency = {
            "valid": False,
            "errors": [
                "Consistency check skipped because "
                "sales or inventory validation failed."
            ],
            "warnings": [],
            "summary": {}
        }


    # --------------------------------------------------------
    # FINAL READINESS
    # --------------------------------------------------------

    ready_for_modeling = (
        sales_validation["valid"]
        and inventory_validation["valid"]
        and consistency["valid"]
        and sales_validation[
            "profile"
        ]["history_days"] >= 90
    )


    return {

        "mode":
            "real_business",

        "sales_file":
            sales_file.filename,

        "inventory_file":
            inventory_file.filename,

        "sales_validation":
            sales_validation,

        "inventory_validation":
            inventory_validation,

        "consistency":
            consistency,

        "ready_for_modeling":
            ready_for_modeling
    }

# ============================================================
# REAL BUSINESS MODE — FINAL INVENTORY RECOMMENDATIONS
# ============================================================

@app.get("/api/business/recommendations")
def get_business_recommendations(
    store_id: str | None = None,
    status: str | None = None,
    limit: int = 100
):

    import pandas as pd

    project_root = (
        Path(__file__)
        .resolve()
        .parent
        .parent
    )

    recommendations_file = (
        project_root
        / "data"
        / "business_mode"
        / "business_recommendations.csv"
    )

    recommendations_metadata_file = (
        project_root
        / "data"
        / "business_mode"
        / "business_recommendations_metadata.json"
    )

    # --------------------------------------------------------
    # FILE CHECK
    # --------------------------------------------------------

    if not recommendations_file.exists():

        raise HTTPException(
            status_code=404,
            detail=(
                "Business recommendations file not found. "
                "Run save_business_recommendations.py first."
            )
        )

    # --------------------------------------------------------
    # FRESHNESS CHECK
    # --------------------------------------------------------

    if not recommendations_metadata_file.exists():

        raise HTTPException(
            status_code=409,
            detail=(
                "Saved business recommendations do not have "
                "freshness metadata. Generate fresh recommendations."
            )
        )

    try:

        with open(
            recommendations_metadata_file,
            "r",
            encoding="utf-8",
        ) as f:

            recommendations_metadata = json.load(
                f
            )

        from app.business_forecast_engine import (
            SALES_PATH,
            MODEL_PATH,
            FUTURE_PROMOTION_PATH,
            calculate_file_sha256,
        )

        from app.business_inventory_engine import (
            INVENTORY_PATH,
            SAFETY_STOCK_PATH,
        )

        def optional_sha256(
            file_path
        ):

            if not file_path.exists():
                return None

            return calculate_file_sha256(
                file_path
            )

        current_fingerprints = {
            "sales_sha256":
                optional_sha256(
                    SALES_PATH
                ),

            "inventory_sha256":
                optional_sha256(
                    INVENTORY_PATH
                ),

            "promotion_sha256":
                optional_sha256(
                    FUTURE_PROMOTION_PATH
                ),

            "model_sha256":
                optional_sha256(
                    MODEL_PATH
                ),

            "safety_stock_sha256":
                optional_sha256(
                    SAFETY_STOCK_PATH
                ),
        }

        stored_fingerprints = (
            recommendations_metadata.get(
                "input_fingerprints",
                {}
            )
        )

        stale_inputs = []

        for (
            key,
            current_value
        ) in current_fingerprints.items():

            stored_value = (
                stored_fingerprints.get(
                    key
                )
            )

            if stored_value != current_value:

                stale_inputs.append(
                    key
                )

        if stale_inputs:

            raise HTTPException(
                status_code=409,
                detail={
                    "message":
                        (
                            "Saved business recommendations are stale. "
                            "One or more source inputs changed after "
                            "the recommendations were generated."
                        ),

                    "stale_inputs":
                        stale_inputs,

                    "next_action":
                        "GENERATE_RECOMMENDATIONS",
                }
            )

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                "Could not verify recommendation freshness: "
                f"{e}"
            )
        )

    # --------------------------------------------------------
    # READ RECOMMENDATIONS
    # --------------------------------------------------------

    try:

        df = pd.read_csv(
            recommendations_file
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                "Could not read business recommendations: "
                f"{e}"
            )
        )

    # --------------------------------------------------------
    # REQUIRED COLUMNS
    # --------------------------------------------------------

    required_columns = [
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

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:

        raise HTTPException(
            status_code=500,
            detail={
                "message":
                    "Business recommendations file has "
                    "an invalid structure.",

                "missing_columns":
                    missing_columns
            }
        )

    # --------------------------------------------------------
    # NORMALIZE VALUES
    # --------------------------------------------------------

    df["store_id"] = (
        df["store_id"]
        .astype(str)
        .str.strip()
    )

    df["product_id"] = (
        df["product_id"]
        .astype(str)
        .str.strip()
    )

    df["status"] = (
        df["status"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    # --------------------------------------------------------
    # OPTIONAL STORE FILTER
    # --------------------------------------------------------

    if store_id is not None:

        store_id = (
            str(store_id)
            .strip()
        )

        df = df[
            df["store_id"]
            == store_id
        ].copy()

    # --------------------------------------------------------
    # OPTIONAL STATUS FILTER
    # --------------------------------------------------------

    if status is not None:

        status = (
            status
            .strip()
            .upper()
            .replace(" ", "_")
        )

        valid_statuses = {
            "CRITICAL",
            "LOW_STOCK",
            "HEALTHY",
        }

        if status not in valid_statuses:

            raise HTTPException(
                status_code=400,
                detail=(
                    "status must be CRITICAL, "
                    "LOW_STOCK or HEALTHY."
                )
            )

        df = df[
            df["status"]
            == status
        ].copy()

    # --------------------------------------------------------
    # RESPONSE LIMIT
    # --------------------------------------------------------

    limit = max(
        1,
        min(
            int(limit),
            5000
        )
    )

    total_matching = int(
        len(df)
    )

    total_recommended_order = int(
        pd.to_numeric(
            df["recommended_order"],
            errors="coerce"
        )
        .fillna(0)
        .sum()
    )

    status_counts = {
        "CRITICAL":
            int(
                (
                    df["status"]
                    == "CRITICAL"
                ).sum()
            ),

        "LOW_STOCK":
            int(
                (
                    df["status"]
                    == "LOW_STOCK"
                ).sum()
            ),

        "HEALTHY":
            int(
                (
                    df["status"]
                    == "HEALTHY"
                ).sum()
            ),
    }

    df = (
        df
        .head(limit)
        .copy()
    )

    # --------------------------------------------------------
    # BUILD JSON-SAFE RESULT
    # --------------------------------------------------------

    recommendations = []

    for _, row in df.iterrows():

        recommendations.append({

            "store_id":
                str(row["store_id"]),

            "product_id":
                str(row["product_id"]),

            "product_name":
                str(row["product_name"]),

            "category":
                str(row["category"]),

            "forecast_start":
                str(row["forecast_start"]),

            "forecast_end":
                str(row["forecast_end"]),

            "forecast_demand_7d":
                float(
                    row["forecast_demand_7d"]
                ),

            "current_stock":
                float(
                    row["current_stock"]
                ),

            "on_order":
                float(
                    row["on_order"]
                ),

            "backorders":
                float(
                    row["backorders"]
                ),

            "inventory_position":
                float(
                    row["inventory_position"]
                ),

            "base_demand_gap":
                float(
                    row["base_demand_gap"]
                ),

            "safety_stock":
                float(
                    row["safety_stock"]
                ),

            "reorder_point":
                float(
                    row["reorder_point"]
                ),

            "recommended_order":
                int(
                    row["recommended_order"]
                ),

            "status":
                str(row["status"]),
        })

    return {

        "mode":
            "real_business",

        "source":
            "business_recommendations.csv",

        "recommendations_current":
            True,

        "generated_at_utc":
            recommendations_metadata.get(
                "generated_at_utc"
            ),

        "count":
            len(recommendations),

        "total_matching":
            total_matching,

        "total_recommended_order":
            total_recommended_order,

        "status_counts":
            status_counts,

        "recommendations":
            recommendations
    }

# ============================================================
# REAL BUSINESS MODE — EXPORT CURRENT RECOMMENDATIONS CSV
# ============================================================

@app.get("/api/business/recommendations/export")
def export_business_recommendations(
    store_id: str | None = None,
    status: str | None = None,
):

    import io
    import pandas as pd

    # Reuse the existing getter so freshness protection,
    # store filtering, status filtering, and validation stay
    # consistent with the dashboard/API.
    result = get_business_recommendations(
        store_id=store_id,
        status=status,
        limit=5000,
    )

    recommendations = (
        result.get(
            "recommendations",
            []
        )
    )

    if not recommendations:

        raise HTTPException(
            status_code=404,
            detail=(
                "No current business recommendations "
                "match the selected filters."
            ),
        )

    df = pd.DataFrame(
        recommendations
    )

    output = io.StringIO()

    df.to_csv(
        output,
        index=False,
    )

    output.seek(0)

    filename = (
        "business_recommendations.csv"
    )

    return StreamingResponse(
        iter(
            [
                output.getvalue()
            ]
        ),
        media_type="text/csv",
        headers={
            "Content-Disposition":
                (
                    "attachment; "
                    f'filename="{filename}"'
                )
        },
    )


# ============================================================
# REAL BUSINESS MODE — GENERATE + SAVE FRESH RECOMMENDATIONS
# ============================================================

@app.post("/api/business/recommendations/generate")
def generate_business_recommendations():

    from app.business_inventory_engine import (
        create_business_inventory_analysis,
    )

    project_root = (
        Path(__file__)
        .resolve()
        .parent
        .parent
    )

    output_file = (
        project_root
        / "data"
        / "business_mode"
        / "business_recommendations.csv"
    )

    metadata_file = (
        project_root
        / "data"
        / "business_mode"
        / "business_recommendations_metadata.json"
    )

    # --------------------------------------------------------
    # GENERATE FRESH RECOMMENDATIONS
    # --------------------------------------------------------

    try:

        recommendations = (
            create_business_inventory_analysis()
        )

    except FileNotFoundError as e:

        raise HTTPException(
            status_code=404,
            detail=str(e)
        )

    except ValueError as e:

        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                "Could not generate business recommendations: "
                f"{e}"
            )
        )

    # --------------------------------------------------------
    # SAVE CSV
    # --------------------------------------------------------

    try:

        output_file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        recommendations.to_csv(
            output_file,
            index=False
        )

        from datetime import (
            datetime,
            timezone,
        )

        from app.business_forecast_engine import (
            SALES_PATH,
            MODEL_PATH,
            FUTURE_PROMOTION_PATH,
            calculate_file_sha256,
        )

        from app.business_inventory_engine import (
            INVENTORY_PATH,
            SAFETY_STOCK_PATH,
        )

        def optional_sha256(
            file_path
        ):

            if not file_path.exists():
                return None

            return calculate_file_sha256(
                file_path
            )

        recommendations_metadata = {
            "generated_at_utc":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "input_fingerprints": {
                "sales_sha256":
                    optional_sha256(
                        SALES_PATH
                    ),

                "inventory_sha256":
                    optional_sha256(
                        INVENTORY_PATH
                    ),

                "promotion_sha256":
                    optional_sha256(
                        FUTURE_PROMOTION_PATH
                    ),

                "model_sha256":
                    optional_sha256(
                        MODEL_PATH
                    ),

                "safety_stock_sha256":
                    optional_sha256(
                        SAFETY_STOCK_PATH
                    ),
            },

            "recommendation_rows":
                int(
                    len(
                        recommendations
                    )
                ),
        }

        with open(
            metadata_file,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                recommendations_metadata,
                f,
                indent=2,
            )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                "Recommendations were generated but "
                "could not be saved with freshness metadata: "
                f"{e}"
            )
        )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    status_counts = {
        "CRITICAL":
            int(
                (
                    recommendations["status"]
                    == "CRITICAL"
                ).sum()
            ),

        "LOW_STOCK":
            int(
                (
                    recommendations["status"]
                    == "LOW_STOCK"
                ).sum()
            ),

        "HEALTHY":
            int(
                (
                    recommendations["status"]
                    == "HEALTHY"
                ).sum()
            ),
    }

    total_recommended_order = int(
        recommendations[
            "recommended_order"
        ].sum()
    )

    return {

        "message":
            "Fresh business recommendations generated and saved.",

        "mode":
            "real_business",

        "output_file":
            "data/business_mode/business_recommendations.csv",

        "metadata_file":
            "data/business_mode/business_recommendations_metadata.json",

        "recommendations_current":
            True,

        "generated_at_utc":
            recommendations_metadata[
                "generated_at_utc"
            ],

        "count":
            int(
                len(recommendations)
            ),

        "stores":
            int(
                recommendations[
                    "store_id"
                ].nunique()
            ),

        "products":
            int(
                recommendations[
                    "product_id"
                ].nunique()
            ),

        "forecast_start":
            str(
                recommendations[
                    "forecast_start"
                ].min()
            ),

        "forecast_end":
            str(
                recommendations[
                    "forecast_end"
                ].max()
            ),

        "total_forecast_demand":
            round(
                float(
                    recommendations[
                        "forecast_demand_7d"
                    ].sum()
                ),
                2
            ),

        "total_inventory_position":
            round(
                float(
                    recommendations[
                        "inventory_position"
                    ].sum()
                ),
                2
            ),

        "total_safety_stock":
            round(
                float(
                    recommendations[
                        "safety_stock"
                    ].sum()
                ),
                2
            ),

        "total_recommended_order":
            total_recommended_order,

        "status_counts":
            status_counts,
    }

# ============================================================
# REAL BUSINESS MODE — UPLOAD + ACTIVATE SALES HISTORY
# ============================================================

@app.post("/api/business/upload-sales")
async def upload_business_sales(
    file: UploadFile = File(...)
):

    import io
    import pandas as pd

    from app.business_data_validator import (
        validate_sales_data,
    )

    from app.business_file_manager import (
        save_active_sales,
    )

    # --------------------------------------------------------
    # 1. FILE TYPE
    # --------------------------------------------------------

    if not file.filename.lower().endswith(".csv"):

        raise HTTPException(
            status_code=400,
            detail="Only CSV files are allowed."
        )

    # --------------------------------------------------------
    # 2. READ CSV
    # --------------------------------------------------------

    try:

        contents = await file.read()

        df = pd.read_csv(
            io.BytesIO(contents)
        )

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=f"Could not read CSV: {e}"
        )

    # --------------------------------------------------------
    # 3. VALIDATE SALES DATA
    # --------------------------------------------------------

    validation = validate_sales_data(
        df
    )

    if not validation.get(
        "valid",
        False
    ):

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    "Sales file validation failed.",

                "errors":
                    validation.get(
                        "errors",
                        []
                    ),

                "warnings":
                    validation.get(
                        "warnings",
                        []
                    ),

                "profile":
                    validation.get(
                        "profile",
                        {}
                    ),
            }
        )

    # --------------------------------------------------------
    # 4. DAILY TIME-SERIES CONTINUITY CHECK
    # --------------------------------------------------------
    # The ML features use lag_1, lag_7, lag_14 and lag_28.
    # Therefore each store-product series must represent
    # consecutive calendar days. A no-sale day should exist
    # explicitly with units_sold = 0 instead of being omitted.

    continuity_df = df[
        [
            "date",
            "store_id",
            "product_id",
        ]
    ].copy()

    continuity_df["date"] = pd.to_datetime(
        continuity_df["date"],
        errors="coerce",
    )

    if continuity_df["date"].isna().any():

        raise HTTPException(
            status_code=400,
            detail=(
                "Sales history contains invalid dates and "
                "cannot be checked for daily continuity."
            )
        )

    continuity_df["store_id"] = (
        continuity_df["store_id"]
        .astype(str)
        .str.strip()
    )

    continuity_df["product_id"] = (
        continuity_df["product_id"]
        .astype(str)
        .str.strip()
    )

    duplicate_daily_rows = (
        continuity_df
        .duplicated(
            subset=[
                "date",
                "store_id",
                "product_id",
            ]
        )
        .sum()
    )

    if duplicate_daily_rows > 0:

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    (
                        "Sales history must contain exactly one "
                        "row per date-store-product combination."
                    ),

                "duplicate_rows":
                    int(
                        duplicate_daily_rows
                    ),
            }
        )

    continuity_problems = []

    for (
        store_id,
        product_id
    ), group in continuity_df.groupby(
        [
            "store_id",
            "product_id",
        ],
        sort=False,
    ):

        observed_dates = (
            pd.DatetimeIndex(
                group["date"]
                .drop_duplicates()
                .sort_values()
            )
        )

        if observed_dates.empty:
            continue

        expected_dates = pd.date_range(
            start=observed_dates.min(),
            end=observed_dates.max(),
            freq="D",
        )

        missing_dates = (
            expected_dates
            .difference(
                observed_dates
            )
        )

        if len(missing_dates) > 0:

            continuity_problems.append(
                {
                    "store_id":
                        str(store_id),

                    "product_id":
                        str(product_id),

                    "series_start":
                        str(
                            observed_dates.min().date()
                        ),

                    "series_end":
                        str(
                            observed_dates.max().date()
                        ),

                    "missing_days":
                        int(
                            len(missing_dates)
                        ),

                    "first_missing_dates":
                        [
                            str(
                                value.date()
                            )
                            for value
                            in missing_dates[:10]
                        ],
                }
            )

    if continuity_problems:

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    (
                        "Sales history contains missing calendar "
                        "days inside one or more store-product "
                        "series. Add those dates explicitly; use "
                        "units_sold = 0 when the product had no sales."
                    ),

                "affected_series":
                    int(
                        len(
                            continuity_problems
                        )
                    ),

                "problems":
                    continuity_problems[:20],
            }
        )

    sales_series_count = int(
        continuity_df[
            [
                "store_id",
                "product_id",
            ]
        ]
        .drop_duplicates()
        .shape[0]
    )

    # --------------------------------------------------------
    # 5. SAVE AS ACTIVE BUSINESS SALES FILE
    # --------------------------------------------------------

    try:

        saved = save_active_sales(
            dataframe=df,
            original_filename=file.filename,
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                "Sales file passed validation but "
                f"could not be activated: {e}"
            )
        )

    # --------------------------------------------------------
    # 6. RESPONSE
    # --------------------------------------------------------

    return {

        "message":
            "Business sales file uploaded and activated successfully.",

        "mode":
            "real_business",

        "data_type":
            "sales_history",

        "filename":
            file.filename,

        "active_file":
            saved,

        "time_series_continuity": {
            "valid": True,

            "series_checked":
                sales_series_count,

            "missing_calendar_days":
                0,

            "duplicate_date_store_product_rows":
                0,
        },

        "validation":
            validation,
    }

# ============================================================
# REAL BUSINESS MODE — UPLOAD + ACTIVATE INVENTORY
# ============================================================

@app.post("/api/business/upload-inventory")
async def upload_business_inventory(
    file: UploadFile = File(...)
):

    import io
    import pandas as pd

    from app.business_data_validator import (
        validate_inventory_data,
    )

    from app.business_file_manager import (
        save_active_inventory,
    )

    # --------------------------------------------------------
    # 1. FILE TYPE
    # --------------------------------------------------------

    if not file.filename.lower().endswith(".csv"):

        raise HTTPException(
            status_code=400,
            detail="Only CSV files are allowed."
        )

    # --------------------------------------------------------
    # 2. READ CSV
    # --------------------------------------------------------

    try:

        contents = await file.read()

        df = pd.read_csv(
            io.BytesIO(contents)
        )

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=f"Could not read CSV: {e}"
        )

    # --------------------------------------------------------
    # 3. VALIDATE INVENTORY DATA
    # --------------------------------------------------------

    validation = validate_inventory_data(
        df
    )

    if not validation.get(
        "valid",
        False
    ):

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    "Inventory file validation failed.",

                "errors":
                    validation.get(
                        "errors",
                        []
                    ),

                "warnings":
                    validation.get(
                        "warnings",
                        []
                    ),

                "profile":
                    validation.get(
                        "profile",
                        {}
                    ),
            }
        )

    # --------------------------------------------------------
    # 4. SALES ↔ INVENTORY STORE-PRODUCT CONSISTENCY
    # --------------------------------------------------------

    from app.business_forecast_engine import (
        SALES_PATH,
    )

    if not SALES_PATH.exists():

        raise HTTPException(
            status_code=400,
            detail=(
                "Upload and activate sales history before "
                "uploading inventory."
            )
        )

    try:

        sales_df = pd.read_csv(
            SALES_PATH,
            usecols=[
                "store_id",
                "product_id",
            ],
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                "Could not read active sales history "
                f"for inventory consistency validation: {e}"
            )
        )

    sales_pairs = set(
        zip(
            sales_df["store_id"]
            .astype(str)
            .str.strip(),

            sales_df["product_id"]
            .astype(str)
            .str.strip(),
        )
    )

    inventory_pairs = set(
        zip(
            df["store_id"]
            .astype(str)
            .str.strip(),

            df["product_id"]
            .astype(str)
            .str.strip(),
        )
    )

    missing_inventory_pairs = (
        sales_pairs
        - inventory_pairs
    )

    unknown_inventory_pairs = (
        inventory_pairs
        - sales_pairs
    )

    if (
        missing_inventory_pairs
        or unknown_inventory_pairs
    ):

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    (
                        "Inventory store-product pairs do not "
                        "match the active sales history."
                    ),

                "missing_inventory_pairs_count":
                    len(
                        missing_inventory_pairs
                    ),

                "unknown_inventory_pairs_count":
                    len(
                        unknown_inventory_pairs
                    ),

                "missing_inventory_pairs":
                    [
                        {
                            "store_id":
                                store_id,

                            "product_id":
                                product_id,
                        }
                        for (
                            store_id,
                            product_id
                        ) in sorted(
                            missing_inventory_pairs
                        )[:20]
                    ],

                "unknown_inventory_pairs":
                    [
                        {
                            "store_id":
                                store_id,

                            "product_id":
                                product_id,
                        }
                        for (
                            store_id,
                            product_id
                        ) in sorted(
                            unknown_inventory_pairs
                        )[:20]
                    ],
            }
        )

    # --------------------------------------------------------
    # 5. SAVE AS ACTIVE BUSINESS INVENTORY FILE
    # --------------------------------------------------------

    try:

        saved = save_active_inventory(
            dataframe=df,
            original_filename=file.filename,
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                "Inventory file passed validation but "
                f"could not be activated: {e}"
            )
        )

    # --------------------------------------------------------
    # 5. RESPONSE
    # --------------------------------------------------------

    return {

        "message":
            "Business inventory file uploaded and activated successfully.",

        "mode":
            "real_business",

        "data_type":
            "inventory",

        "filename":
            file.filename,

        "active_file":
            saved,

        "sales_inventory_consistency": {
            "matched": True,

            "sales_pairs":
                len(
                    sales_pairs
                ),

            "inventory_pairs":
                len(
                    inventory_pairs
                ),

            "missing_inventory_pairs":
                0,

            "unknown_inventory_pairs":
                0,
        },

        "validation":
            validation,
    }

# ============================================================
# REAL BUSINESS MODE — TRAIN BUSINESS-SPECIFIC MODEL
# ============================================================

@app.post("/api/business/train-model")
def train_real_business_model():

    from train_business_model import (
        train_business_model,
    )

    try:

        result = train_business_model()

    except FileNotFoundError as e:

        raise HTTPException(
            status_code=404,
            detail=str(e)
        )

    except ValueError as e:

        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                "Business model training failed: "
                f"{e}"
            )
        )

    return {
        "message":
            "Business-specific model trained successfully.",

        "mode":
            "real_business",

        "source_sales_file":
            result["source_sales_file"],

        "training_rows":
            result["training_rows"],

        "validation_rows":
            result["validation_rows"],

        "train_start":
            result["train_start"],

        "train_end":
            result["train_end"],

        "validation_start":
            result["validation_start"],

        "validation_end":
            result["validation_end"],

        "mae":
            result["mae"],

        "rmse":
            result["rmse"],

        "wape":
            result["wape"],

        "stores":
            result["stores"],

        "products":
            result["products"],

        "model_path":
            result["model_path"],

        "metadata_path":
            result["metadata_path"],
    }

# ============================================================
# REAL BUSINESS MODE — CALIBRATE SAFETY STOCK
# ============================================================

@app.post("/api/business/calibrate-safety-stock")
def calibrate_real_business_safety_stock():

    from app.business_safety_stock import (
        calibrate_business_safety_stock,
    )

    try:

        (
            safety_stock,
            backtest,
            calibration_metadata,
        ) = calibrate_business_safety_stock()

    except FileNotFoundError as e:

        raise HTTPException(
            status_code=404,
            detail=str(e)
        )

    except ValueError as e:

        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                "Business safety-stock calibration failed: "
                f"{e}"
            )
        )

    safety_records = (
        safety_stock
        .to_dict(
            orient="records"
        )
    )

    return {
        "message":
            "Business safety stock calibrated successfully.",

        "mode":
            "real_business",

        "source_sales_file":
            calibration_metadata.get(
                "source_sales_file"
            ),

        "service_level":
            calibration_metadata[
                "service_level"
            ],

        "validation_start":
            calibration_metadata[
                "validation_start"
            ],

        "validation_end":
            calibration_metadata[
                "validation_end"
            ],

        "weekly_blocks":
            calibration_metadata[
                "weekly_blocks"
            ],

        "backtest_rows":
            calibration_metadata[
                "backtest_rows"
            ],

        "global_buffer":
            round(
                float(
                    calibration_metadata[
                        "global_buffer"
                    ]
                ),
                2,
            ),

        "recursive_daily_mae":
            round(
                float(
                    calibration_metadata[
                        "recursive_daily_mae"
                    ]
                ),
                4,
            ),

        "recursive_daily_rmse":
            round(
                float(
                    calibration_metadata[
                        "recursive_daily_rmse"
                    ]
                ),
                4,
            ),

        "recursive_daily_wape":
            (
                round(
                    float(
                        calibration_metadata[
                            "recursive_daily_wape"
                        ]
                    ),
                    4,
                )
                if calibration_metadata[
                    "recursive_daily_wape"
                ] is not None
                else None
            ),

        "recursive_7day_block_mae":
            round(
                float(
                    calibration_metadata[
                        "recursive_7day_block_mae"
                    ]
                ),
                4,
            ),

        "recursive_7day_block_rmse":
            round(
                float(
                    calibration_metadata[
                        "recursive_7day_block_rmse"
                    ]
                ),
                4,
            ),

        "recursive_7day_block_wape":
            (
                round(
                    float(
                        calibration_metadata[
                            "recursive_7day_block_wape"
                        ]
                    ),
                    4,
                )
                if calibration_metadata[
                    "recursive_7day_block_wape"
                ] is not None
                else None
            ),

        "products":
            int(
                len(
                    safety_stock
                )
            ),

        "safety_stock":
            safety_records,
    }

# ============================================================
# REAL BUSINESS MODE — PIPELINE STATUS
# ============================================================

@app.get("/api/business/pipeline-status")
def get_real_business_pipeline_status():

    import json

    from app.business_forecast_engine import (
        SALES_PATH,
        MODEL_PATH,
        METADATA_PATH,
        FUTURE_PROMOTION_PATH,
        calculate_file_sha256,
    )

    from app.business_inventory_engine import (
        INVENTORY_PATH,
        SAFETY_STOCK_PATH,
        SAFETY_STOCK_METADATA_PATH,
    )

    current_sales_sha256 = None
    model_sales_sha256 = None
    safety_sales_sha256 = None

    sales_active = SALES_PATH.exists()
    inventory_active = INVENTORY_PATH.exists()
    production_model_exists = MODEL_PATH.exists()
    model_metadata_exists = METADATA_PATH.exists()
    safety_stock_exists = SAFETY_STOCK_PATH.exists()
    safety_metadata_exists = (
        SAFETY_STOCK_METADATA_PATH.exists()
    )

    promotion_plan_active = (
        FUTURE_PROMOTION_PATH.exists()
    )

    promotion_plan_rows = 0
    promotion_rows_enabled = 0
    promotion_forecast_start = None
    promotion_forecast_end = None

    project_root = (
        Path(__file__)
        .resolve()
        .parent
        .parent
    )

    recommendations_file = (
        project_root
        / "data"
        / "business_mode"
        / "business_recommendations.csv"
    )

    recommendations_metadata_file = (
        project_root
        / "data"
        / "business_mode"
        / "business_recommendations_metadata.json"
    )

    recommendations_exists = (
        recommendations_file.exists()
    )

    recommendations_metadata_exists = (
        recommendations_metadata_file.exists()
    )

    recommendations_current = False
    recommendations_stale_inputs = []
    recommendations_generated_at_utc = None

    model_metadata = {}
    safety_metadata = {}

    if sales_active:

        current_sales_sha256 = (
            calculate_file_sha256(
                SALES_PATH
            )
        )

    if model_metadata_exists:

        with open(
            METADATA_PATH,
            "r",
            encoding="utf-8",
        ) as file:

            model_metadata = json.load(
                file
            )

        model_sales_sha256 = (
            model_metadata.get(
                "source_sales_sha256"
            )
        )

    model_current = (
        sales_active
        and production_model_exists
        and model_metadata_exists
        and bool(current_sales_sha256)
        and bool(model_sales_sha256)
        and current_sales_sha256
        == model_sales_sha256
    )

    if safety_metadata_exists:

        with open(
            SAFETY_STOCK_METADATA_PATH,
            "r",
            encoding="utf-8",
        ) as file:

            safety_metadata = json.load(
                file
            )

        safety_sales_sha256 = (
            safety_metadata.get(
                "source_sales_sha256"
            )
        )

    safety_current = (
        model_current
        and safety_stock_exists
        and safety_metadata_exists
        and bool(safety_sales_sha256)
        and safety_sales_sha256
        == current_sales_sha256
    )

    if promotion_plan_active:

        import pandas as pd

        try:

            promotion_df = pd.read_csv(
                FUTURE_PROMOTION_PATH
            )

            if not promotion_df.empty:

                promotion_plan_rows = int(
                    len(
                        promotion_df
                    )
                )

                if "promotion" in promotion_df.columns:

                    promotion_rows_enabled = int(
                        (
                            pd.to_numeric(
                                promotion_df["promotion"],
                                errors="coerce"
                            )
                            == 1
                        ).sum()
                    )

                if "date" in promotion_df.columns:

                    promotion_dates = pd.to_datetime(
                        promotion_df["date"],
                        errors="coerce"
                    ).dropna()

                    if not promotion_dates.empty:

                        promotion_forecast_start = str(
                            promotion_dates.min().date()
                        )

                        promotion_forecast_end = str(
                            promotion_dates.max().date()
                        )

        except Exception:

            promotion_plan_active = False


    # --------------------------------------------------------
    # SAVED RECOMMENDATION FRESHNESS
    # --------------------------------------------------------

    if (
        recommendations_exists
        and recommendations_metadata_exists
    ):

        try:

            with open(
                recommendations_metadata_file,
                "r",
                encoding="utf-8",
            ) as file:

                recommendations_metadata = json.load(
                    file
                )

            recommendations_generated_at_utc = (
                recommendations_metadata.get(
                    "generated_at_utc"
                )
            )

            stored_fingerprints = (
                recommendations_metadata.get(
                    "input_fingerprints",
                    {}
                )
            )

            def optional_sha256(
                file_path
            ):

                if not file_path.exists():
                    return None

                return calculate_file_sha256(
                    file_path
                )

            current_fingerprints = {
                "sales_sha256":
                    optional_sha256(
                        SALES_PATH
                    ),

                "inventory_sha256":
                    optional_sha256(
                        INVENTORY_PATH
                    ),

                "promotion_sha256":
                    optional_sha256(
                        FUTURE_PROMOTION_PATH
                    ),

                "model_sha256":
                    optional_sha256(
                        MODEL_PATH
                    ),

                "safety_stock_sha256":
                    optional_sha256(
                        SAFETY_STOCK_PATH
                    ),
            }

            for (
                key,
                current_value
            ) in current_fingerprints.items():

                if (
                    stored_fingerprints.get(
                        key
                    )
                    != current_value
                ):

                    recommendations_stale_inputs.append(
                        key
                    )

            recommendations_current = (
                len(
                    recommendations_stale_inputs
                )
                == 0
            )

        except Exception:

            recommendations_current = False

            recommendations_stale_inputs = [
                "metadata_error"
            ]


    ready_for_forecast = (
        sales_active
        and model_current
    )

    ready_for_recommendations = (
        sales_active
        and inventory_active
        and model_current
        and safety_current
    )

    if not sales_active:

        next_action = (
            "UPLOAD_SALES"
        )

    elif not inventory_active:

        next_action = (
            "UPLOAD_INVENTORY"
        )

    elif not model_current:

        next_action = (
            "TRAIN_MODEL"
        )

    elif not safety_current:

        next_action = (
            "CALIBRATE_SAFETY_STOCK"
        )

    elif not recommendations_current:

        next_action = (
            "GENERATE_RECOMMENDATIONS"
        )

    else:

        next_action = (
            "COMPLETE"
        )

    return {
        "mode":
            "real_business",

        "status":
            (
                "COMPLETE"
                if recommendations_current
                else (
                    "READY"
                    if ready_for_recommendations
                    else "ACTION_REQUIRED"
                )
            ),

        "next_action":
            next_action,

        "sales_active":
            sales_active,

        "inventory_active":
            inventory_active,

        "promotion_plan_active":
            promotion_plan_active,

        "promotion_plan_rows":
            promotion_plan_rows,

        "promotion_rows_enabled":
            promotion_rows_enabled,

        "promotion_forecast_start":
            promotion_forecast_start,

        "promotion_forecast_end":
            promotion_forecast_end,

        "production_model_exists":
            production_model_exists,

        "model_current":
            model_current,

        "safety_stock_exists":
            safety_stock_exists,

        "safety_stock_current":
            safety_current,

        "ready_for_forecast":
            ready_for_forecast,

        "ready_for_recommendations":
            ready_for_recommendations,

        "recommendations_exists":
            recommendations_exists,

        "recommendations_current":
            recommendations_current,

        "recommendations_generated_at_utc":
            recommendations_generated_at_utc,

        "recommendations_stale_inputs":
            recommendations_stale_inputs,

        "current_sales_sha256":
            current_sales_sha256,

        "model_sales_sha256":
            model_sales_sha256,

        "safety_stock_sales_sha256":
            safety_sales_sha256,

        "validation_wape":
            model_metadata.get(
                "validation_wape"
            ),

        "production_training_rows":
            model_metadata.get(
                "production_training_rows"
            ),

        "production_train_end":
            model_metadata.get(
                "production_train_end"
            ),

        "safety_service_level":
            safety_metadata.get(
                "service_level"
            ),

        "recursive_daily_mae":
            safety_metadata.get(
                "recursive_daily_mae"
            ),

        "recursive_daily_rmse":
            safety_metadata.get(
                "recursive_daily_rmse"
            ),

        "recursive_daily_wape":
            safety_metadata.get(
                "recursive_daily_wape"
            ),

        "recursive_7day_block_mae":
            safety_metadata.get(
                "recursive_7day_block_mae"
            ),

        "recursive_7day_block_rmse":
            safety_metadata.get(
                "recursive_7day_block_rmse"
            ),

        "recursive_7day_block_wape":
            safety_metadata.get(
                "recursive_7day_block_wape"
            ),
    }

# ============================================================
# REAL BUSINESS MODE — RUN COMPLETE BUSINESS PIPELINE
# ============================================================

@app.post("/api/business/run-pipeline")
def run_complete_real_business_pipeline():

    from app.business_forecast_engine import (
        SALES_PATH,
    )

    from app.business_inventory_engine import (
        INVENTORY_PATH,
    )

    # --------------------------------------------------------
    # 1. REQUIRED ACTIVE INPUTS
    # --------------------------------------------------------

    if not SALES_PATH.exists():

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    "Complete pipeline cannot start because "
                    "active sales history is missing.",

                "stage":
                    "PRECHECK",

                "next_action":
                    "UPLOAD_SALES",
            },
        )

    if not INVENTORY_PATH.exists():

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    "Complete pipeline cannot start because "
                    "active inventory is missing.",

                "stage":
                    "PRECHECK",

                "next_action":
                    "UPLOAD_INVENTORY",
            },
        )

    # --------------------------------------------------------
    # 2. TRAIN BUSINESS-SPECIFIC MODEL
    # --------------------------------------------------------

    try:

        training_result = (
            train_real_business_model()
        )

    except HTTPException as e:

        raise HTTPException(
            status_code=e.status_code,
            detail={
                "message":
                    "Complete pipeline failed during "
                    "business-model training.",

                "stage":
                    "TRAIN_MODEL",

                "cause":
                    e.detail,
            },
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail={
                "message":
                    "Complete pipeline failed during "
                    "business-model training.",

                "stage":
                    "TRAIN_MODEL",

                "cause":
                    str(e),
            },
        )

    # --------------------------------------------------------
    # 3. CALIBRATE SAFETY STOCK
    # --------------------------------------------------------

    try:

        safety_result = (
            calibrate_real_business_safety_stock()
        )

    except HTTPException as e:

        raise HTTPException(
            status_code=e.status_code,
            detail={
                "message":
                    "Complete pipeline failed during "
                    "safety-stock calibration.",

                "stage":
                    "CALIBRATE_SAFETY_STOCK",

                "cause":
                    e.detail,
            },
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail={
                "message":
                    "Complete pipeline failed during "
                    "safety-stock calibration.",

                "stage":
                    "CALIBRATE_SAFETY_STOCK",

                "cause":
                    str(e),
            },
        )

    # --------------------------------------------------------
    # 4. GENERATE FORECAST + INVENTORY RECOMMENDATIONS
    # --------------------------------------------------------

    try:

        recommendation_result = (
            generate_business_recommendations()
        )

    except HTTPException as e:

        raise HTTPException(
            status_code=e.status_code,
            detail={
                "message":
                    "Complete pipeline failed during "
                    "forecast/recommendation generation.",

                "stage":
                    "GENERATE_RECOMMENDATIONS",

                "cause":
                    e.detail,
            },
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail={
                "message":
                    "Complete pipeline failed during "
                    "forecast/recommendation generation.",

                "stage":
                    "GENERATE_RECOMMENDATIONS",

                "cause":
                    str(e),
            },
        )

    # --------------------------------------------------------
    # 5. FINAL PIPELINE STATUS
    # --------------------------------------------------------

    try:

        pipeline_status = (
            get_real_business_pipeline_status()
        )

    except Exception:

        pipeline_status = None

    # --------------------------------------------------------
    # 6. COMPACT RESPONSE
    # --------------------------------------------------------

    return {
        "message":
            "Complete real-business pipeline finished successfully.",

        "mode":
            "real_business",

        "status":
            "COMPLETE",

        "stages": {

            "train_model": {
                "status":
                    "COMPLETED",

                "validation_wape":
                    training_result.get(
                        "wape"
                    ),

                "validation_mae":
                    training_result.get(
                        "mae"
                    ),

                "validation_rmse":
                    training_result.get(
                        "rmse"
                    ),

                "stores":
                    training_result.get(
                        "stores"
                    ),

                "products":
                    training_result.get(
                        "products"
                    ),
            },

            "calibrate_safety_stock": {
                "status":
                    "COMPLETED",

                "service_level":
                    safety_result.get(
                        "service_level"
                    ),

                "recursive_daily_wape":
                    safety_result.get(
                        "recursive_daily_wape"
                    ),

                "recursive_7day_block_wape":
                    safety_result.get(
                        "recursive_7day_block_wape"
                    ),

                "products":
                    safety_result.get(
                        "products"
                    ),
            },

            "generate_recommendations": {
                "status":
                    "COMPLETED",

                "count":
                    recommendation_result.get(
                        "count"
                    ),

                "forecast_start":
                    recommendation_result.get(
                        "forecast_start"
                    ),

                "forecast_end":
                    recommendation_result.get(
                        "forecast_end"
                    ),

                "total_forecast_demand":
                    recommendation_result.get(
                        "total_forecast_demand"
                    ),

                "total_inventory_position":
                    recommendation_result.get(
                        "total_inventory_position"
                    ),

                "total_safety_stock":
                    recommendation_result.get(
                        "total_safety_stock"
                    ),

                "total_recommended_order":
                    recommendation_result.get(
                        "total_recommended_order"
                    ),

                "status_counts":
                    recommendation_result.get(
                        "status_counts"
                    ),
            },
        },

        "pipeline_status":
            pipeline_status,
    }


# ============================================================
# REAL BUSINESS MODE — UPLOAD FUTURE PROMOTION PLAN
# ============================================================

@app.post("/api/business/upload-promotions")
async def upload_real_business_promotions(
    file: UploadFile = File(...)
):

    import io
    import pandas as pd

    from app.business_forecast_engine import (
        SALES_PATH,
        FUTURE_PROMOTION_PATH,
    )

    # --------------------------------------------------------
    # 1. FILE TYPE
    # --------------------------------------------------------

    if not file.filename.lower().endswith(".csv"):

        raise HTTPException(
            status_code=400,
            detail="Only CSV files are allowed."
        )

    # --------------------------------------------------------
    # 2. ACTIVE SALES REQUIRED
    # --------------------------------------------------------

    if not SALES_PATH.exists():

        raise HTTPException(
            status_code=400,
            detail=(
                "Upload and activate sales history before "
                "uploading a future promotion plan."
            )
        )

    # --------------------------------------------------------
    # 3. READ PROMOTION CSV
    # --------------------------------------------------------

    try:

        contents = await file.read()

        df = pd.read_csv(
            io.BytesIO(contents)
        )

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=f"Could not read promotion CSV: {e}"
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
        if column not in df.columns
    ]

    if missing_columns:

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    "Future promotion plan is missing required columns.",

                "missing_columns":
                    missing_columns,
            }
        )

    df = df[
        required_columns
    ].copy()

    if df.empty:

        raise HTTPException(
            status_code=400,
            detail="Future promotion CSV contains no rows."
        )

    # --------------------------------------------------------
    # 4. NORMALIZE + VALIDATE VALUES
    # --------------------------------------------------------

    df["date"] = pd.to_datetime(
        df["date"],
        errors="coerce"
    )

    df["store_id"] = (
        df["store_id"]
        .astype("string")
        .str.strip()
    )

    df["product_id"] = (
        df["product_id"]
        .astype("string")
        .str.strip()
    )

    df["promotion"] = pd.to_numeric(
        df["promotion"],
        errors="coerce"
    )

    if df[
        required_columns
    ].isna().any().any():

        raise HTTPException(
            status_code=400,
            detail=(
                "Future promotion CSV contains blank "
                "or invalid values."
            )
        )

    invalid_promotion = (
        ~df["promotion"].isin(
            [0, 1]
        )
    )

    if invalid_promotion.any():

        invalid_values = (
            df.loc[
                invalid_promotion,
                "promotion"
            ]
            .drop_duplicates()
            .tolist()
        )

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    "promotion must contain only 0 or 1.",

                "invalid_values":
                    invalid_values[:20],
            }
        )

    duplicate_mask = df.duplicated(
        subset=[
            "date",
            "store_id",
            "product_id",
        ],
        keep=False,
    )

    if duplicate_mask.any():

        duplicate_rows = (
            df.index[
                duplicate_mask
            ]
            + 2
        ).tolist()

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    "Duplicate date-store-product promotion rows found.",

                "rows":
                    duplicate_rows[:20],
            }
        )

    # --------------------------------------------------------
    # 5. LOAD ACTIVE SALES FOR WINDOW + PAIR VALIDATION
    # --------------------------------------------------------

    try:

        sales = pd.read_csv(
            SALES_PATH,
            parse_dates=["date"]
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Could not read active sales history: {e}"
        )

    sales["store_id"] = (
        sales["store_id"]
        .astype(str)
        .str.strip()
    )

    sales["product_id"] = (
        sales["product_id"]
        .astype(str)
        .str.strip()
    )

    history_end = sales["date"].max()

    forecast_dates = pd.date_range(
        start=history_end + pd.Timedelta(days=1),
        periods=7,
        freq="D",
    )

    valid_dates = set(
        forecast_dates
    )

    promotion_dates = set(
        df["date"]
    )

    invalid_dates = (
        promotion_dates
        - valid_dates
    )

    if invalid_dates:

        invalid_date_strings = sorted(
            str(
                pd.Timestamp(value).date()
            )
            for value in invalid_dates
        )

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    "Promotion dates must fall inside the next 7-day forecast window.",

                "forecast_start":
                    str(
                        forecast_dates.min().date()
                    ),

                "forecast_end":
                    str(
                        forecast_dates.max().date()
                    ),

                "invalid_dates":
                    invalid_date_strings[:20],
            }
        )

    valid_pairs = set(
        zip(
            sales["store_id"],
            sales["product_id"],
        )
    )

    promotion_pairs = set(
        zip(
            df["store_id"].astype(str),
            df["product_id"].astype(str),
        )
    )

    unknown_pairs = (
        promotion_pairs
        - valid_pairs
    )

    if unknown_pairs:

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    "Promotion plan contains store-product pairs not found in active sales history.",

                "unknown_pairs":
                    [
                        {
                            "store_id":
                                store_id,

                            "product_id":
                                product_id,
                        }
                        for (
                            store_id,
                            product_id
                        ) in sorted(
                            unknown_pairs
                        )[:20]
                    ],
            }
        )

    # --------------------------------------------------------
    # 6. SAVE ACTIVE PROMOTION PLAN
    # --------------------------------------------------------

    FUTURE_PROMOTION_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    df["promotion"] = (
        df["promotion"]
        .astype(int)
    )

    df = df.sort_values(
        [
            "date",
            "store_id",
            "product_id",
        ]
    ).reset_index(
        drop=True
    )

    df.to_csv(
        FUTURE_PROMOTION_PATH,
        index=False,
    )

    # --------------------------------------------------------
    # 7. RESPONSE
    # --------------------------------------------------------

    return {
        "message":
            "Future promotion plan uploaded and activated successfully.",

        "mode":
            "real_business",

        "filename":
            file.filename,

        "active_file":
            str(
                FUTURE_PROMOTION_PATH
            ),

        "rows":
            int(
                len(df)
            ),

        "promotion_rows":
            int(
                (
                    df["promotion"] == 1
                ).sum()
            ),

        "forecast_start":
            str(
                forecast_dates.min().date()
            ),

        "forecast_end":
            str(
                forecast_dates.max().date()
            ),

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

