"""ML layer: 24h PM2.5 forecasting (Random Forest vs Gradient Boosting) + anomaly detection (Isolation Forest).

All training data is REAL hourly Open-Meteo observations stored in SQLite (no synthetic data).
"""

import threading
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor, IsolationForest, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from database.database import load_history, upsert_history, log_model_run
from services.history_service import fetch_hourly, now_local
from services.risk import risk_score, risk_level

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_PATH = MODEL_DIR / "pm25_bundle.joblib"
HORIZONS = list(range(1, 25))

FEATURES = ["horizon", "pm25_now", "pm25_mean6", "pm25_mean24", "pm25_delta3", "no2_now",
            "t_temp", "t_hum", "t_wind", "t_pres", "t_hour_sin", "t_hour_cos", "t_dow"]

FEATURE_LABELS = {
    "horizon": "Forecast horizon (h)", "pm25_now": "Current PM2.5", "pm25_mean6": "6h avg PM2.5",
    "pm25_mean24": "24h avg PM2.5", "pm25_delta3": "3h PM2.5 trend", "no2_now": "Current NO2",
    "t_temp": "Target-hour temperature", "t_hum": "Target-hour humidity", "t_wind": "Target-hour wind speed",
    "t_pres": "Target-hour pressure", "t_hour_sin": "Hour of day (sin)", "t_hour_cos": "Hour of day (cos)",
    "t_dow": "Day of week",
}

ANOMALY_COLS = ["pm25", "no2", "temperature", "humidity", "wind_speed", "pm25_delta1", "pm25_vs_24h"]


# ----------------------------------------------------------------- feature engineering
def build_samples(df: pd.DataFrame) -> pd.DataFrame:
    """Direct multi-horizon dataset: one row per (origin hour, horizon).
    Origin features come from the past; weather features come from the target hour
    (observed in training, Open-Meteo forecast at inference)."""
    df = df.asfreq("h")
    base = pd.DataFrame(index=df.index)
    base["pm25_now"] = df["pm25"]
    base["pm25_mean6"] = df["pm25"].rolling(6, min_periods=6).mean()
    base["pm25_mean24"] = df["pm25"].rolling(24, min_periods=24).mean()
    base["pm25_delta3"] = df["pm25"] - df["pm25"].shift(3)
    base["no2_now"] = df["no2"]

    frames = []
    for h in HORIZONS:
        f = base.copy()
        tgt = df.index + pd.Timedelta(hours=h)
        f["horizon"] = h
        f["t_temp"] = df["temperature"].shift(-h)
        f["t_hum"] = df["humidity"].shift(-h)
        f["t_wind"] = df["wind_speed"].shift(-h)
        f["t_pres"] = df["pressure"].shift(-h)
        f["t_hour_sin"] = np.sin(2 * np.pi * tgt.hour / 24)
        f["t_hour_cos"] = np.cos(2 * np.pi * tgt.hour / 24)
        f["t_dow"] = tgt.dayofweek
        f["target"] = df["pm25"].shift(-h)
        f["target_no2"] = df["no2"].shift(-h)
        f["target_time"] = tgt
        f["origin"] = df.index
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


def anomaly_frame(df: pd.DataFrame) -> pd.DataFrame:
    a = df[["pm25", "no2", "temperature", "humidity", "wind_speed"]].copy()
    a["pm25_delta1"] = df["pm25"].diff()
    a["pm25_vs_24h"] = df["pm25"] - df["pm25"].rolling(24, min_periods=12).mean()
    return a.dropna()


def _metrics(y, p):
    return {"mae": round(float(mean_absolute_error(y, p)), 2),
            "rmse": round(float(np.sqrt(mean_squared_error(y, p))), 2),
            "r2": round(float(r2_score(y, p)), 3)}


# ----------------------------------------------------------------- service
class MLService:
    _lock = threading.Lock()
    _bundle = None

    # ---------- training
    @classmethod
    def train(cls):
        with cls._lock:
            raw = fetch_hourly(past_days=92, forecast_days=1)
            observed = raw[raw.index <= now_local()].dropna(subset=["pm25", "no2"])
            upsert_history(observed)

            df = load_history()
            samples = build_samples(df).dropna(subset=FEATURES + ["target"]).sort_values("origin")
            if len(samples) < 2000:
                raise ValueError(f"Not enough real history to train ({len(samples)} rows).")

            # Chronological split with a 24h gap to prevent leakage
            cut = samples["origin"].quantile(0.8)
            train = samples[samples["origin"] < cut - pd.Timedelta(hours=24)]
            test = samples[samples["origin"] >= cut]
            Xtr, ytr, Xte, yte = train[FEATURES], train["target"], test[FEATURES], test["target"]

            candidates = {
                "Random Forest": RandomForestRegressor(
                    n_estimators=100, max_depth=12, min_samples_leaf=10, n_jobs=-1, random_state=42),
                "Gradient Boosting": HistGradientBoostingRegressor(
                    max_iter=300, learning_rate=0.06, max_depth=8, l2_regularization=1.0, random_state=42),
            }
            results, fitted = [], {}
            for name, mdl in candidates.items():
                mdl.fit(Xtr, ytr)
                fitted[name] = mdl
                results.append({"name": name, **_metrics(yte, mdl.predict(Xte))})

            baseline = {"name": "Persistence baseline", **_metrics(yte, test["pm25_now"])}
            best = min(results, key=lambda r: r["rmse"])
            best_name = best["name"]
            best_model = fitted[best_name]

            # Residual band (10th/90th percentile) -> ~80% prediction interval
            resid = yte.values - best_model.predict(Xte)
            q10, q90 = float(np.quantile(resid, 0.10)), float(np.quantile(resid, 0.90))

            # Explainability: permutation importance on held-out data
            sub = test.sample(min(2000, len(test)), random_state=42)
            pi = permutation_importance(best_model, sub[FEATURES], sub["target"], n_repeats=3,
                                        random_state=42, n_jobs=-1, scoring="neg_mean_absolute_error")
            imp = np.clip(pi.importances_mean, 0, None)
            tot = imp.sum() or 1.0
            importance = sorted(
                [{"feature": FEATURE_LABELS[f], "importance": round(float(v / tot * 100), 1)}
                 for f, v in zip(FEATURES, imp)], key=lambda d: -d["importance"])

            # Refit best on ALL data for deployment
            final = clone(candidates[best_name]).fit(samples[FEATURES], samples["target"])

            # Isolation Forest (unsupervised anomaly detector) on observed history
            af = anomaly_frame(df)
            iso = Pipeline([("scale", StandardScaler()),
                            ("iso", IsolationForest(n_estimators=200, contamination=0.02, random_state=42))])
            iso.fit(af[ANOMALY_COLS])

            bundle = {
                "model": final, "best_name": best_name, "iso": iso,
                "metrics": {"models": results, "baseline": baseline, "best": best_name,
                            "skill_vs_persistence_pct": round(
                                (1 - best["rmse"] / baseline["rmse"]) * 100, 1)},
                "importance": importance, "q10": q10, "q90": q90,
                "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "n_hours": int(len(df)), "n_samples": int(len(samples)),
                "data_from": str(df.index.min()), "data_to": str(df.index.max()),
                "n_train": int(len(train)), "n_test": int(len(test)),
            }
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            joblib.dump(bundle, MODEL_PATH)
            cls._bundle = bundle
            log_model_run(best_name, best["mae"], best["rmse"], best["r2"], len(samples))
            return cls.summary()

    @classmethod
    def is_ready(cls):
        return cls._bundle is not None or MODEL_PATH.exists()

    @classmethod
    def _get(cls):
        if cls._bundle is None:
            if MODEL_PATH.exists():
                cls._bundle = joblib.load(MODEL_PATH)
            else:
                cls.train()
        return cls._bundle

    @classmethod
    def summary(cls):
        b = cls._get()
        return {k: b[k] for k in ("metrics", "importance", "trained_at", "n_hours",
                                  "n_samples", "data_from", "data_to", "n_train", "n_test")}

    # ---------- forecasting
    @classmethod
    def forecast(cls):
        b = cls._get()
        df = fetch_hourly(past_days=3, forecast_days=2)
        now = now_local()
        valid = df[(df.index <= now) & df["pm25"].notna()]
        origin = valid.index.max()

        samples = build_samples(df)
        sel = samples[samples["origin"] == origin].dropna(subset=FEATURES)
        if sel.empty:
            raise ValueError("Insufficient recent data to build forecast features.")

        pred = np.clip(b["model"].predict(sel[FEATURES]), 0, None)
        lo = np.clip(pred + b["q10"], 0, None)
        hi = np.clip(pred + b["q90"], 0, None)

        points = []
        for i, (_, row) in enumerate(sel.iterrows()):
            p = float(pred[i])
            no2 = row["target_no2"]
            no2 = 0.0 if pd.isna(no2) else float(no2)
            cams = row["target"]
            sc = risk_score(p, no2)
            points.append({
                "time": row["target_time"].strftime("%Y-%m-%dT%H:%M"),
                "horizon": int(row["horizon"]),
                "pm25_pred": round(p, 1), "pm25_low": round(float(lo[i]), 1), "pm25_high": round(float(hi[i]), 1),
                "pm25_cams": None if pd.isna(cams) else round(float(cams), 1),
                "no2": round(no2, 1), "risk_score": sc, "risk_level": risk_level(sc),
            })

        peak = max(points, key=lambda p: p["risk_score"])
        return {
            "status": "success", "model": b["best_name"], "origin": str(origin),
            "mae": next(m["mae"] for m in b["metrics"]["models"] if m["name"] == b["best_name"]),
            "points": points,
            "summary": {
                "peak_risk": peak["risk_score"], "peak_level": peak["risk_level"], "peak_time": peak["time"],
                "hours_high_or_critical": sum(1 for p in points if p["risk_level"] in ("HIGH", "CRITICAL")),
                "avg_pm25_pred": round(float(np.mean([p["pm25_pred"] for p in points])), 1),
            },
        }

    # ---------- anomalies
    @classmethod
    def anomalies(cls, hours=96):
        b = cls._get()
        df = fetch_hourly(past_days=5, forecast_days=1)
        df = df[(df.index <= now_local())].dropna(subset=["pm25", "no2"])
        af = anomaly_frame(df).tail(hours)
        pipe = b["iso"]
        X = af[ANOMALY_COLS]
        flags = pipe.predict(X)
        scores = pipe.decision_function(X)
        z = pipe.named_steps["scale"].transform(X)

        out = []
        for i, (t, row) in enumerate(af.iterrows()):
            if flags[i] == -1:
                j = int(np.argmax(np.abs(z[i])))
                out.append({
                    "time": t.strftime("%Y-%m-%d %H:%M"), "pm25": round(float(row["pm25"]), 1),
                    "no2": round(float(row["no2"]), 1), "anomaly_score": round(float(scores[i]), 3),
                    "main_driver": ANOMALY_COLS[j], "direction": "high" if z[i][j] > 0 else "low",
                })
        out.sort(key=lambda d: d["time"], reverse=True)
        return {"status": "success", "checked_hours": int(len(af)), "anomalies": out}
