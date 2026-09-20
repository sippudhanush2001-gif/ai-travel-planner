"""Weather tool (Research Agent's second tool).

Backend ``openmeteo`` uses the free, keyless Open-Meteo API (geocoding +
daily forecast). On any failure — or when ``WEATHER_PROVIDER=mock`` — it
returns deterministic seasonal data so planning still works offline.
"""

from __future__ import annotations

import json
from datetime import date

import requests
from langchain_core.tools import tool

_WMO_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Light rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light showers",
    81: "Moderate showers",
    82: "Violent showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


def _openmeteo(location: str, start_date: str, end_date: str) -> dict:
    geocode = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": location, "count": 1},
        timeout=15,
    )
    geocode.raise_for_status()
    geo = geocode.json().get("results") or [{}]
    lat = float(geo[0].get("latitude", 0))
    lon = float(geo[0].get("longitude", 0))
    if not lat and not lon:
        raise RuntimeError(f"Could not geocode '{location}'")

    forecast = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": "weathercode,temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max",
            "timezone": "auto",
            "start_date": start_date,
            "end_date": end_date,
        },
        timeout=15,
    )
    forecast.raise_for_status()
    payload = forecast.json()
    daily = payload.get("daily", {})
    days = daily.get("time", [])

    notes = [
        f"Forecast source: Open-Meteo ({geo[0].get('name', location)})",
    ]
    if not days:
        raise RuntimeError("Weather API returned no daily data")

    forecasts = []
    for i, day in enumerate(days):
        code = daily.get("weathercode", [0])[i]
        forecasts.append(
            {
                "date": day,
                "temp_min": daily.get("temperature_2m_min", [0])[i],
                "temp_max": daily.get("temperature_2m_max", [0])[i],
                "precipitation_chance": daily.get(
                    "precipitation_probability_max", [0]
                )[i],
                "condition": _WMO_CODES.get(code, f"Code {code}"),
            }
        )
    return {"forecast": forecasts, "notes": notes, "source": "open-meteo"}


# Seasonal baseline temp ranges by hemisphere-ish grouping (temperate).
_SEASON_RANGE = {
    "spring": (-4, 14, 18, 26),
    "summer": (13, 24, 26, 35),
    "fall": (-2, 10, 12, 22),
    "winter": (-6, 6, 2, 16),
}


def _mock_weather(location: str, start_date: str, end_date: str) -> dict:
    try:
        first = date.fromisoformat(start_date)
    except (ValueError, TypeError):
        first = date.today()
    try:
        last = date.fromisoformat(end_date)
    except (ValueError, TypeError):
        last = first

    month = first.month
    season = "winter"
    if month in (3, 4, 5):
        season = "spring"
    elif month in (6, 7, 8):
        season = "summer"
    elif month in (9, 10, 11):
        season = "fall"

    lo_a, lo_b, hi_a, hi_b = _SEASON_RANGE[season]
    forecasts = []
    cursor = first
    while cursor <= last:
        lo = round(lo_a + ((cursor.month * 7) % 5), 1)
        hi = round(hi_a + ((cursor.month * 5) % 6), 1)
        precip = (hash((location, cursor.isoformat())) % 40) + 5
        forecasts.append(
            {
                "date": cursor.isoformat(),
                "temp_min": lo,
                "temp_max": hi,
                "precipitation_chance": precip,
                "condition": "Mock seasonal forecast",
            }
        )
        cursor = cursor.__class__.fromordinal(cursor.toordinal() + 1)

    return {
        "forecast": forecasts,
        "notes": [f"Generated seasonal estimate for {season} (no API key configured)."],
        "source": "mock",
    }


@tool
def weather_forecast(location: str, start_date: str, end_date: str) -> str:
    """Get the daily weather forecast for the destination over the trip dates.
    Returns a JSON string with per-day temperatures, precipitation chance and
    conditions.

    Args:
        location: Destination (city) name.
        start_date: First day of the trip, ISO format (YYYY-MM-DD).
        end_date: Last day of the trip, ISO format (YYYY-MM-DD).
    """
    from app.config import get_settings

    settings = get_settings()
    try:
        if settings.weather_provider == "openmeteo":
            payload = _openmeteo(location, start_date, end_date)
        else:
            payload = _mock_weather(location, start_date, end_date)
    except Exception as exc:  # noqa: BLE001 - graceful degradation
        payload = _mock_weather(location, start_date, end_date)
        payload["fallback_reason"] = f"{type(exc).__name__}: {exc}"
    return json.dumps(payload, ensure_ascii=False)


__all__ = ["weather_forecast"]