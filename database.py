"""SQLite Database Layer for Risk Intelligence Logging + real historical archive."""

import sqlite3
import json
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent / "telemetry.db"


def _conn():
    return sqlite3.connect(str(DB_PATH))


def init_sqlite_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS telemetry_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        pm25 REAL, no2 REAL, temperature REAL, humidity REAL, wind_speed REAL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS risk_assessments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        grid_id TEXT, risk_score REAL, risk_level TEXT, payload TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS generated_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        location_name TEXT, risk_score REAL, report_data TEXT)""")
    # NEW: real hourly archive (Open-Meteo) used as ML training data
    c.execute("""CREATE TABLE IF NOT EXISTS hourly_history (
        time TEXT PRIMARY KEY,
        pm25 REAL, no2 REAL, temperature REAL, humidity REAL,
        wind_speed REAL, pressure REAL)""")
    # NEW: audit trail of every model training run
    c.execute("""CREATE TABLE IF NOT EXISTS model_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        best_model TEXT, mae REAL, rmse REAL, r2 REAL, n_rows INTEGER)""")
    conn.commit()
    conn.close()


def log_telemetry(pm25, no2, temp, humidity, wind_speed):
    try:
        conn = _conn()
        conn.execute("""INSERT INTO telemetry_logs (pm25, no2, temperature, humidity, wind_speed)
                        VALUES (?, ?, ?, ?, ?)""", (pm25, no2, temp, humidity, wind_speed))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Database Error] Failed to log telemetry: {e}")


def log_risk_assessment(grid_id, risk_score, risk_level, payload):
    try:
        conn = _conn()
        conn.execute("""INSERT INTO risk_assessments (grid_id, risk_score, risk_level, payload)
                        VALUES (?, ?, ?, ?)""", (grid_id, risk_score, risk_level, json.dumps(payload)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Database Error] Failed to log risk assessment: {e}")


def _f(v):
    return None if pd.isna(v) else float(v)


def upsert_history(df: pd.DataFrame) -> int:
    """Insert/replace hourly rows. df index = naive local datetime."""
    rows = [
        (t.strftime("%Y-%m-%d %H:%M:%S"), _f(r.pm25), _f(r.no2), _f(r.temperature),
         _f(r.humidity), _f(r.wind_speed), _f(r.pressure))
        for t, r in df.iterrows()
    ]
    conn = _conn()
    conn.executemany("""INSERT OR REPLACE INTO hourly_history
        (time, pm25, no2, temperature, humidity, wind_speed, pressure)
        VALUES (?, ?, ?, ?, ?, ?, ?)""", rows)
    conn.commit()
    conn.close()
    return len(rows)


def load_history() -> pd.DataFrame:
    conn = _conn()
    df = pd.read_sql_query("SELECT * FROM hourly_history ORDER BY time", conn)
    conn.close()
    if df.empty:
        return df
    df["time"] = pd.to_datetime(df["time"])
    return df.set_index("time")


def log_model_run(best, mae, rmse, r2, n_rows):
    conn = _conn()
    conn.execute("INSERT INTO model_runs (best_model, mae, rmse, r2, n_rows) VALUES (?,?,?,?,?)",
                 (best, mae, rmse, r2, n_rows))
    conn.commit()
    conn.close()
