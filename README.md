# Retail Demand Forecasting & Inventory Optimization System

Final Year Project for intelligent retail demand forecasting and inventory optimization using Machine Learning, FastAPI, SQL Server, and a web dashboard.

## Core Features

- 7-day retail demand forecasting
- LightGBM production forecasting model
- Store + product-family level predictions
- Inventory safety stock calculation
- Reorder point calculation
- Automatic order recommendations
- Critical / Low Stock / Healthy classification
- Bulk inventory CSV upload
- Recommendation export
- Cross-dataset research validation
- Interactive dashboard

## Production Model

Model: LightGBM Retail Demand  
Version: v3-final  
Dataset: Favorita  
Forecast Horizon: 7 Days  

Validation WAPE: 11.5859%  
Final Test WAPE: 13.0629%

The model outperformed the 7-day Seasonal Naive baseline by approximately 29.41%.

## External Validation

Dataset: M5  
Final Test WAPE: 8.9416%  
Seasonal Naive WAPE: 13.9752%  
Improvement: approximately 36.02%

## Technology Stack

- Python
- LightGBM
- Pandas
- NumPy
- FastAPI
- SQL Server
- PyODBC
- HTML
- CSS
- Bootstrap
- JavaScript
- Chart.js

## Project Structure

```text
Retail_Demand_System_App/
│
├── app/
│   ├── __init__.py
│   ├── database.py
│   ├── forecast_engine.py
│   └── main.py
│
├── data/
│   └── forecast_inputs/
│
├── frontend/
│   └── index.html
│
├── models/
│   ├── FINAL_lightgbm_retail_model.joblib
│   └── FINAL_lightgbm_model_metadata.json
│
├── requirements.txt
├── .env
├── .env.example
├── save_live_forecast.py
└── README.md