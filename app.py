"""Flask Web Application Server - Environmental Risk Intelligence + ML endpoints."""

import io
import threading
from flask import Flask, jsonify, request, send_from_directory, send_file, Response
from database.database import init_sqlite_db, log_telemetry, log_risk_assessment, load_history
from data_engine import DataEngine
from services.report_service import ReportService
from services.ml_service import MLService
from services.risk import risk_score, risk_level

app = Flask(__name__, static_folder="static")
init_sqlite_db()
engine = DataEngine()
_train_state = {"running": False, "error": None}


@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/css/<path:path>")
def send_css(path):
    return send_from_directory("static/css", path)

@app.route("/js/<path:path>")
def send_js(path):
    return send_from_directory("static/js", path)


# ------------------------------------------------------------------ existing endpoints
@app.route("/api/telemetry", methods=["GET"])
def get_telemetry():
    data = engine.fetch_live_telemetry()
    if data.get("status") == "success":
        log_telemetry(data["base_pm25"], data["base_no2"], data["temperature"],
                      data["humidity"], data["wind_speed"])
    return jsonify(data)

@app.route("/api/predict", methods=["POST"])
def run_simulation():
    body = request.get_json() or {}
    traffic = float(body.get("traffic_modifier", 1.0))
    industrial = float(body.get("industrial_modifier", 1.0))
    return jsonify({"predictions": engine.get_ground_stations(traffic, industrial)})

@app.route("/api/risk/calculate", methods=["POST"])
def calculate_risk():
    body = request.get_json() or {}
    grid_id = body.get("grid_id", "UNKNOWN")
    no2 = float(body.get("no2", 0))
    pm25 = float(body.get("pm25", 0))

    score = risk_score(pm25, no2)
    level = risk_level(score)
    d = score if score > 0 else 1
    result = {"status": "success", "risk_assessment": {
        "risk_score": score, "risk_level": level,
        "contributors": [
            {"factor": "PM2.5 Concentration", "contribution": round(pm25 * 0.6 / d * 100, 1)},
            {"factor": "NO2 Concentration", "contribution": round(no2 * 0.4 / d * 100, 1)}]}}
    log_risk_assessment(grid_id, score, level, result)
    return jsonify(result)

@app.route("/api/risk/area", methods=["GET"])
def get_regional_risk():
    stations = engine.get_ground_stations()
    if not stations:
        return jsonify({"status": "error", "message": "No active stations found"})
    avg_pm = sum(s["pm25"] for s in stations) / len(stations)
    avg_no2 = sum(s["no2"] for s in stations) / len(stations)
    high = sum(1 for s in stations if risk_score(s["pm25"], s["no2"]) >= 70)
    return jsonify({"status": "success", "summary": {
        "avg_risk": risk_score(avg_pm, avg_no2), "avg_no2": round(avg_no2, 1),
        "high_risk_zones": high, "low_risk_zones": len(stations) - high}})

@app.route("/api/risk/high-risk-zones", methods=["GET"])
def get_high_risk_zones():
    stations = engine.get_ground_stations()
    return jsonify({"status": "success",
                    "high_risk_zones": [s for s in stations if risk_score(s["pm25"], s["no2"]) >= 70]})

@app.route("/api/risk/report", methods=["POST"])
def generate_pdf_report():
    try:
        payload = request.get_json() or {}
        pdf_buffer = ReportService.generate_pdf_report(payload)
        zone = str(payload.get("location", {}).get("name", "Zone")).replace(" ", "_")
        return send_file(pdf_buffer, mimetype="application/pdf", as_attachment=True,
                         download_name=f"Risk_Report_{zone}.pdf")
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/risk/methodology", methods=["GET"])
def get_methodology():
    return jsonify({
        "assessment_type": "Multi-Pollutant Linear Health Risk Model + ML Forecasting",
        "model": "Random Forest / Gradient Boosting (24h PM2.5 forecast) + Isolation Forest (anomaly detection)",
        "scoring_methodology": "Weighted sum of PM2.5 (60%) and NO2 (40%). Levels: <40 Low, <70 Moderate, <85 High, else Critical.",
        "disclaimer": "All data is real: Open-Meteo / CAMS air-quality and weather observations (92-day hourly archive, "
                      "stored locally and grown on every retrain). No synthetic data is used. Gridded model data is "
                      "not a substitute for regulatory ground-sensor measurements."})


# ------------------------------------------------------------------ NEW: ML / history endpoints
@app.route("/api/ml/forecast", methods=["GET"])
def ml_forecast():
    if not MLService.is_ready():
        return jsonify({"status": "not_trained"})
    try:
        return jsonify(MLService.forecast())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/ml/anomalies", methods=["GET"])
def ml_anomalies():
    if not MLService.is_ready():
        return jsonify({"status": "not_trained"})
    try:
        return jsonify(MLService.anomalies())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/ml/metrics", methods=["GET"])
def ml_metrics():
    if not MLService.is_ready():
        return jsonify({"status": "not_trained"})
    try:
        return jsonify({"status": "success", **MLService.summary()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/ml/train", methods=["POST"])
def ml_train():
    """Retrain in a background thread so the request returns immediately."""
    if _train_state["running"]:
        return jsonify({"status": "running"})

    def job():
        _train_state.update(running=True, error=None)
        try:
            MLService.train()
        except Exception as e:
            _train_state["error"] = str(e)
        finally:
            _train_state["running"] = False

    threading.Thread(target=job, daemon=True).start()
    return jsonify({"status": "started"})

@app.route("/api/ml/train/status", methods=["GET"])
def ml_train_status():
    return jsonify(_train_state)

@app.route("/api/history/trend", methods=["GET"])
def history_trend():
    days = max(1, min(int(request.args.get("days", 7)), 92))
    df = load_history()
    if df.empty:
        return jsonify({"status": "empty", "message": "No history yet. Train the models first."})
    df = df[df.index >= df.index.max() - __import__("pandas").Timedelta(days=days)]
    return jsonify({"status": "success", "time": [t.strftime("%Y-%m-%dT%H:%M") for t in df.index],
                    "pm25": [None if v != v else round(v, 1) for v in df["pm25"]],
                    "no2": [None if v != v else round(v, 1) for v in df["no2"]]})

@app.route("/api/history/export.csv", methods=["GET"])
def history_export():
    days = max(1, min(int(request.args.get("days", 30)), 365))
    df = load_history()
    if not df.empty:
        df = df[df.index >= df.index.max() - __import__("pandas").Timedelta(days=days)]
    return Response(df.to_csv(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=air_quality_history_{days}d.csv"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
