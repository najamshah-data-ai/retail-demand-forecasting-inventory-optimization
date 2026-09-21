# Final FYP Documentation Structure

## Chapter 1 — Introduction
- Background
- Problem Statement
- Aim
- Objectives
- Research Questions
- Scope
- Limitations

Suggested research questions:
1. Can LightGBM outperform a seasonal-naive baseline on unseen 7-day retail demand windows?
2. Does the methodology generalize across different retail datasets?
3. Can recursive deployment forecasting maintain acceptable error compared with holdout evaluation?
4. Can forecast residuals support practical safety-stock calibration?
5. Can the system adapt to an unseen business without hardcoded store/product IDs?

## Chapter 2 — Literature Review
- Retail Demand Forecasting
- Time-Series Feature Engineering
- Gradient Boosting / LightGBM
- Recursive Multi-Step Forecasting
- Inventory Optimization
- Safety Stock and Service Level
- MAE, RMSE, WAPE
- Chronological Evaluation and Leakage
- External Validation
- Research Gap

## Chapter 3 — Methodology
- Research Design
- Favorita Dataset
- M5 External Validation
- Real Business Test Data
- Data Preprocessing
- Chronological Splitting
- Feature Engineering
- Seasonal-Naive Baseline
- LightGBM Training
- Production Full-History Refit
- Recursive 7-Day Forecasting
- Evaluation Metrics
- Safety-Stock Calibration
- Inventory Optimization Logic
- Real Business Mode
- SHA-256 Freshness Protection
- System Architecture

Feature set:
- promotion
- lag_1, lag_7, lag_14, lag_28
- rolling_mean_7, rolling_mean_14, rolling_mean_28
- rolling_std_7, rolling_std_28
- day_of_week
- day_of_month
- month
- week_of_year
- is_weekend
- categorical business identifiers

## Chapter 4 — System Design and Implementation
- Overall Architecture
- FastAPI Backend
- SQL Server
- Forecast Engine
- Safety-Stock Engine
- Inventory Engine
- Dashboard
- Upload Validation
- One-Click Pipeline
- CSV Export
- Stale-Result Protection

## Chapter 5 — Results and Evaluation

### Favorita
- Validation baseline WAPE: 18.2814%
- Validation LightGBM WAPE: 11.5859%
- Test MAE: 61.3585
- Test RMSE: 223.7525
- Test WAPE: 13.0629%
- Test baseline WAPE: 18.5064%
- Improvement: 29.41%

### M5
- Proposed WAPE: 8.9416%
- Baseline WAPE: 13.9752%
- Improvement: 36.02%

### Cross-Dataset
- Proposed approach beat the baseline on all 8 unseen 7-day blocks.

### Unseen Business B
- Validation WAPE: 9.4606%
- Recursive Daily WAPE: 9.6588%
- 7-Day Block WAPE: 4.7621%
- Forecast Demand: 815.11
- Inventory Position: 722
- Recommended Order: 234
- CRITICAL: 3
- LOW_STOCK: 1
- HEALTHY: 2

Important reporting caution:
- Daily validation WAPE and recursive daily WAPE are directly comparable.
- 7-day block WAPE is aggregated and must be reported separately.
- 95% safety-stock level is a calibration target, not an independent 95% coverage guarantee.

## Chapter 6 — Discussion
Discuss:
- why LightGBM performed well
- effect of lag/rolling features
- importance of recursive evaluation
- promotion effects
- external validation
- unseen-business adaptation
- prediction-to-decision integration
- freshness controls

## Chapter 7 — Conclusion and Future Work
- Final Findings
- Contributions
- Limitations
- Future Work

## Appendices
- CSV Schemas
- API Endpoint Table
- Dashboard Screenshots
- Swagger Screenshots
- Key Code Snippets
- GitHub Repository
- Tag: v1.0.0

## Recommended Defense Demo
1. Open dashboard.
2. Explain pipeline status.
3. Upload fresh sales.
4. Upload matching inventory.
5. Upload optional promotions.
6. Show validation checks.
7. Run Complete Pipeline.
8. Explain Validation WAPE.
9. Explain Recursive Daily WAPE.
10. Show forecast demand.
11. Show safety stock.
12. Show recommendations.
13. Explain CRITICAL / LOW_STOCK / HEALTHY.
14. Filter by store/status.
15. Export CSV.
16. Show Favorita/M5 benchmark results.
17. Explain stale recommendation protection.
18. Conclude with unseen-business adaptation.
