# Environmental Risk Intelligence System (Delhi)

A web-based environmental digital twin that monitors air quality in Delhi using **real** Open-Meteo / Copernicus CAMS data, scores pollution risk, and uses machine learning to **forecast PM2.5 for the next 24 hours**, detect anomalies and explain predictions.

> **No synthetic data is used.** All values come from the Open-Meteo Air Quality and Weather APIs. Note that these are gridded atmospheric-model estimates (CAMS), not readings from physical CPCB sensors. The station names are location labels only.

---

## Features

| Feature | Description |
|---|---|
| Live digital-twin map | Real per-station PM2.5 / NO₂ readings for 5 Delhi locations on a Leaflet map |
| What-if simulation | Traffic and industrial modifier sliders (0.5x to 3.0x) applied on top of real readings |
| Risk scoring | `min(100, 0.6 x PM2.5 + 0.4 x NO2)` with Low / Moderate / High / Critical levels |
| Real history archive | 92 days of hourly data stored in SQLite, growing with every retrain |
| 24-hour PM2.5 forecast | Random Forest vs Gradient Boosting, best model selected automatically, with an 80% prediction interval and a CAMS reference line |
| Anomaly detection | Isolation Forest flags unusual hours and names the main driver |
| Explainability | Permutation feature importance and a model scorecard (MAE, RMSE, R², compared with a persistence baseline) |
| Trends and export | 7-day trend chart and 30-day CSV export |
| PDF reports | Per-station risk report that includes the ML forecast outlook |

## Machine learning

| Algorithm | Purpose |
|---|---|
| Random Forest Regressor | 24-hour PM2.5 forecasting (candidate) |
| Histogram Gradient Boosting Regressor | 24-hour PM2.5 forecasting (candidate) |
| Isolation Forest | Unsupervised anomaly detection |

- **Approach:** direct multi-horizon forecasting, one row per (origin hour, horizon 1 to 24).
- **Features:** current PM2.5 and NO₂, 6 h and 24 h rolling means, 3 h trend, target-hour weather (temperature, humidity, wind, pressure), cyclic hour-of-day, day of week, horizon.
- **Validation:** chronological 80/20 split with a 24-hour gap to prevent leakage. The best model is chosen by RMSE.
- **Uncertainty:** 10th / 90th percentile of held-out residuals gives an approximate 80% interval.

---

## Project structure

```
risk_dashboard_v2/
└── project/
    ├── app.py                      # Flask server and REST API
    ├── data_engine.py              # Live telemetry and per-station readings
    ├── requirements.txt
    ├── database/
    │   ├── database.py             # SQLite layer (history, logs, model runs)
    │   └── telemetry.db            # created automatically
    ├── services/
    │   ├── history_service.py      # Downloads real hourly history
    │   ├── ml_service.py           # Training, forecasting, anomalies, importance
    │   ├── risk.py                 # Shared risk score and level thresholds
    │   └── report_service.py       # PDF report builder (ReportLab)
    ├── models/                     # trained model saved here (created automatically)
    └── static/
        ├── index.html
        ├── css/style.css
        └── js/app.js
```
## API reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/telemetry` | Live city-level weather and pollutants |
| POST | `/api/predict` | Station readings with traffic / industrial modifiers |
| POST | `/api/risk/calculate` | Risk score, level and contributors for a station |
| GET | `/api/risk/area` | Regional risk summary |
| GET | `/api/risk/high-risk-zones` | Stations with risk score >= 70 |
| POST | `/api/risk/report` | Download a PDF risk report |
| GET | `/api/risk/methodology` | Methodology text |
| GET | `/api/ml/forecast` | 24-hour forecast with interval and risk levels |
| GET | `/api/ml/anomalies` | Anomalous hours in the last 96 h |
| GET | `/api/ml/metrics` | Model comparison and feature importance |
| POST | `/api/ml/train` | Start retraining in the background |
| GET | `/api/ml/train/status` | Training status |
| GET | `/api/history/trend?days=7` | Observed PM2.5 / NO₂ history |
| GET | `/api/history/export.csv?days=30` | CSV export of stored history |

ML endpoints return `{"status": "not_trained"}` until the first training run finishes.

## Future work

- Train on multi-year data and predict change relative to the current value
- Validate against CPCB / OpenAQ ground-sensor data
- Per-station forecasting, LSTM / Temporal Fusion Transformer, SHAP explanations
- SMS / email alerts when forecast risk reaches High or Critical
- Satellite data fusion (Sentinel-5P, MODIS) and more pollutants (O₃, PM10, SO₂)

## Tech stack

Python, Flask, SQLite, scikit-learn, pandas, NumPy, joblib, ReportLab, Leaflet.js, Chart.js, Open-Meteo APIs (Copernicus CAMS).
