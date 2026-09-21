# Intelligent Retail Demand Forecasting & Inventory Optimization System

A Final Year Project for retail demand forecasting, recursive 7-day prediction, safety-stock calibration, inventory optimization, and real-business deployment.

## Main Capabilities

- LightGBM retail demand forecasting
- Chronological validation
- Recursive 7-day prediction
- Promotion-aware forecasting
- Business-specific model retraining
- Safety-stock calibration
- Reorder-point calculation
- Inventory recommendations
- CSV upload/export
- One-click end-to-end pipeline
- SHA-256 freshness protection
- Dashboard + FastAPI
- Favorita and M5 benchmark evaluation

## Real Business Input Schemas

Sales history:

```text
date,store_id,product_id,product_name,category,units_sold,promotion
```

Inventory:

```text
store_id,product_id,product_name,current_stock,on_order,backorders
```

Optional future promotions:

```text
date,store_id,product_id,promotion
```

## Core Inventory Logic

```text
inventory_position = current_stock + on_order - backorders
reorder_point = forecast_demand_7d + safety_stock
recommended_order = max(0, reorder_point - inventory_position)
```

Statuses:

- CRITICAL
- LOW_STOCK
- HEALTHY

## Technology Stack

Backend:
- Python
- FastAPI
- Pandas
- NumPy
- LightGBM
- Joblib
- SQL Server

Frontend:
- HTML
- CSS
- Bootstrap
- JavaScript
- Chart.js

Development:
- VS Code
- Git / GitHub
- PowerShell
- Google Colab

## Research Results

### Favorita

Validation:
- Seasonal-naive WAPE: 18.2814%
- LightGBM WAPE: 11.5859%

Final test:
- MAE: 61.3585
- RMSE: 223.7525
- WAPE: 13.0629%
- Seasonal-naive WAPE: 18.5064%
- Improvement: 29.41%

### M5 External Validation

- Proposed WAPE: 8.9416%
- Seasonal-naive WAPE: 13.9752%
- Improvement: 36.02%

Across Favorita and M5, the approach beat the baseline on all 8 unseen 7-day evaluation blocks.

## Unseen Business Test

The system was also tested on a different business with new stores and products:

Stores:
- BRANCH_A
- BRANCH_B

Products:
- SKU101 — Basmati Rice
- SKU102 — Cooking Oil
- SKU103 — Laundry Soap

Results:

```text
Validation WAPE        = 9.4606%
Recursive Daily WAPE   = 9.6588%
7-Day Block WAPE       = 4.7621%
7-Day Forecast Demand  = 815.11
Inventory Position     = 722
Recommended Order      = 234
```

Status distribution:

```text
CRITICAL   = 3
LOW_STOCK  = 1
HEALTHY    = 2
```

## Evaluation Note

Validation WAPE and Recursive Daily WAPE are daily-granularity metrics and are directly comparable.

7-Day Block WAPE is calculated after weekly aggregation, so daily over- and under-predictions can partially cancel. It should therefore be reported separately.

## Project Structure

```text
Retail_Demand_System_App/
├── app/
│   ├── main.py
│   ├── database.py
│   ├── forecast_engine.py
│   ├── business_data_validator.py
│   ├── business_file_manager.py
│   ├── business_consistency.py
│   ├── business_forecast_engine.py
│   ├── business_safety_stock.py
│   └── business_inventory_engine.py
├── frontend/
│   └── index.html
├── data/
├── models/
├── train_business_model.py
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Installation

Clone repository:

```bash
git clone <https://github.com/najamshah-data-ai/retail-demand-forecasting-inventory-optimization.git>
cd Retail_Demand_System_App
```

Create and activate virtual environment on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and configure SQL Server connection settings.

Run API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Swagger:

```text
http://127.0.0.1:8001/docs
```

Dashboard:

```text
http://127.0.0.1:8001/dashboard
```

## Real Business Workflow

1. Upload sales history.
2. Upload inventory.
3. Optionally upload future promotions.
4. Run complete pipeline.
5. Review model metrics.
6. Review forecasts.
7. Review safety stock and reorder recommendations.
8. Filter recommendations.
9. Export CSV.

## One-Click Pipeline

Endpoint:

```text
POST /api/business/run-pipeline
```

Flow:

```text
Train Business Model
→ Calibrate Safety Stock
→ Generate Recursive 7-Day Forecast
→ Generate Inventory Recommendations
```

Successful state:

```text
status = COMPLETE
next_action = COMPLETE
```

## Important API Endpoints

```text
GET  /api/health
GET  /api/business/pipeline-status
POST /api/business/upload-sales
POST /api/business/upload-inventory
POST /api/business/upload-promotions
POST /api/business/train-model
POST /api/business/calibrate-safety-stock
POST /api/business/run-pipeline
GET  /api/business/recommendations
POST /api/business/recommendations/generate
GET  /api/business/recommendations/export
```

## Production/Data Integrity Guards

The system validates:

- daily time-series continuity
- duplicate date/store/product rows
- sales ↔ inventory pair consistency
- promotion values and dates
- unknown promotion pairs
- model/data freshness
- safety-stock freshness
- recommendation freshness

If inputs change after recommendation generation, stale recommendations are blocked until regenerated.

## Limitations

- Forecast horizon is fixed at 7 days.
- Daily observations are required.
- Zero-sale days must be explicitly represented.
- Cold-start products are not separately modeled.
- Future external variables other than promotions are not currently supported.
- Safety-stock calibration depends on available historical residuals.

## Future Work

- Probabilistic forecasting
- Cold-start models
- Supplier lead-time modeling
- Cost-aware inventory optimization
- Holiday/weather/event features
- Cloud deployment
- Authentication
- Scheduled retraining
- Multi-warehouse optimization

## Version

`v1.0.0`

## Project Type

Final Year Project — BS Information Technology

Domain: Data Science, Machine Learning, Time-Series Forecasting, Retail Analytics, Inventory Optimization
