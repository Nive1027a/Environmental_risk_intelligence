"""Shared risk scoring so every endpoint uses identical thresholds."""


def risk_score(pm25: float, no2: float) -> float:
    return min(100.0, round((pm25 * 0.6) + (no2 * 0.4), 1))


def risk_level(score: float) -> str:
    if score < 40:
        return "LOW"
    if score < 70:
        return "MODERATE"
    if score < 85:
        return "HIGH"
    return "CRITICAL"
