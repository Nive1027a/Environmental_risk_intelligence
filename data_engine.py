"""Data Engine: live air quality + weather, now with REAL per-station readings."""

import requests

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WX_URL = "https://api.open-meteo.com/v1/forecast"

STATIONS = [
    {"grid_id": "STATION_CPCB_ANAND_VIHAR", "lat": 28.6469, "lon": 77.3160},
    {"grid_id": "STATION_CPCB_RK_PURAM", "lat": 28.5632, "lon": 77.1869},
    {"grid_id": "STATION_CPCB_PUNJABI_BAGH", "lat": 28.6683, "lon": 77.1167},
    {"grid_id": "STATION_CPCB_ITO", "lat": 28.6286, "lon": 77.2410},
    {"grid_id": "STATION_CPCB_DWARKA", "lat": 28.5921, "lon": 77.0460},
]


class DataEngine:
    def __init__(self):
        self.latitude = 28.6139
        self.longitude = 77.2090

    def fetch_live_telemetry(self):
        try:
            w = requests.get(WX_URL, params={
                "latitude": self.latitude, "longitude": self.longitude,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m"}, timeout=8).json()
            a = requests.get(AQ_URL, params={
                "latitude": self.latitude, "longitude": self.longitude,
                "current": "pm2_5,nitrogen_dioxide,dust,uv_index"}, timeout=8).json()
            wc, ac = w.get("current", {}), a.get("current", {})
            return {
                "status": "success", "source": "Open-Meteo Live API",
                "temperature": float(wc.get("temperature_2m") or 0.0),
                "humidity": float(wc.get("relative_humidity_2m") or 0.0),
                "wind_speed": round(float(wc.get("wind_speed_10m") or 0.0) / 3.6, 2),
                "base_pm25": float(ac.get("pm2_5") or 0.0),
                "base_no2": float(ac.get("nitrogen_dioxide") or 0.0),
                "dust": float(ac.get("dust") or 0.0),
                "uv_index": float(ac.get("uv_index") or 0.0),
            }
        except Exception as e:
            print(f"[DataEngine Error] {e}")
            return {"status": "error", "message": str(e), "temperature": 0.0, "humidity": 0.0,
                    "wind_speed": 0.0, "base_pm25": 0.0, "base_no2": 0.0}

    def _station_air_quality(self):
        """One batched request: real pollutant values at each station's own coordinates."""
        res = requests.get(AQ_URL, params={
            "latitude": ",".join(str(s["lat"]) for s in STATIONS),
            "longitude": ",".join(str(s["lon"]) for s in STATIONS),
            "current": "pm2_5,nitrogen_dioxide"}, timeout=10).json()
        if isinstance(res, dict):
            res = [res]
        return [r.get("current", {}) for r in res]

    def get_ground_stations(self, traffic_mod=1.0, ind_mod=1.0):
        """Per-station real readings; modifiers are what-if scenario multipliers on top."""
        telemetry = self.fetch_live_telemetry()
        try:
            readings = self._station_air_quality()
        except Exception as e:
            print(f"[DataEngine Error] station fetch failed: {e}")
            readings = [{"pm2_5": telemetry["base_pm25"], "nitrogen_dioxide": telemetry["base_no2"]}] * len(STATIONS)

        out = []
        for st, r in zip(STATIONS, readings):
            pm = float(r.get("pm2_5") or 0.0)
            no2 = float(r.get("nitrogen_dioxide") or 0.0)
            out.append({
                "grid_id": st["grid_id"], "lat": st["lat"], "lon": st["lon"],
                "pm25": round(pm * ((traffic_mod + ind_mod) / 2.0), 2),
                "no2": round(no2 * traffic_mod, 2),
                "features": {"temperature": telemetry["temperature"],
                             "wind_speed": telemetry["wind_speed"],
                             "humidity": telemetry["humidity"]},
            })
        return out
