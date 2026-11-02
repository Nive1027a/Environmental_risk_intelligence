"""Pulls REAL hourly air-quality + weather observations from Open-Meteo."""

import pandas as pd
import requests

LAT, LON = 28.6139, 77.2090   # Delhi
TZ = "Asia/Kolkata"
AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WX_URL = "https://api.open-meteo.com/v1/forecast"


def now_local() -> pd.Timestamp:
    return pd.Timestamp.now(tz=TZ).tz_localize(None).floor("h")


def fetch_hourly(lat=LAT, lon=LON, past_days=92, forecast_days=1) -> pd.DataFrame:
    """Returns hourly df: pm25, no2, temperature, humidity, wind_speed(m/s), pressure.
    Future rows (if forecast_days>1) hold Open-Meteo/CAMS forecasts."""
    common = {"latitude": lat, "longitude": lon, "past_days": past_days,
              "forecast_days": forecast_days, "timezone": TZ}
    aq = requests.get(AQ_URL, params={**common, "hourly": "pm2_5,nitrogen_dioxide"}, timeout=30)
    wx = requests.get(WX_URL, params={**common, "hourly":
                      "temperature_2m,relative_humidity_2m,wind_speed_10m,surface_pressure"}, timeout=30)
    aq.raise_for_status()
    wx.raise_for_status()

    a = pd.DataFrame(aq.json()["hourly"])
    w = pd.DataFrame(wx.json()["hourly"])
    df = a.merge(w, on="time", how="inner")
    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time").rename(columns={
        "pm2_5": "pm25", "nitrogen_dioxide": "no2", "temperature_2m": "temperature",
        "relative_humidity_2m": "humidity", "wind_speed_10m": "wind_speed",
        "surface_pressure": "pressure"})
    df["wind_speed"] = df["wind_speed"] / 3.6   # km/h -> m/s
    return df
