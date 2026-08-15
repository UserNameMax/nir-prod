"""Клиент внешнего источника погоды (open-meteo archive).

Единственная точка production, обращающаяся во внешний мир. Всё остальное
работает с локальным кэшем (store.py).
"""
from __future__ import annotations
import os

import httpx

API_URL = os.getenv("WEATHER_API_URL", "https://archive-api.open-meteo.com/v1/archive")
LAT = float(os.getenv("WEATHER_LAT", "55.7558"))
LON = float(os.getenv("WEATHER_LON", "37.6173"))
TIMEZONE = os.getenv("WEATHER_TZ", "Europe/Moscow")
TIMEOUT = float(os.getenv("WEATHER_TIMEOUT", "30"))

# База отопительного периода: heating_degree = max(0, BASE - T_out_mean)
HEATING_BASE = 18.0

DAILY_METRICS = "temperature_2m_mean,temperature_2m_min,temperature_2m_max"


class WeatherSourceError(RuntimeError):
    """Внешний источник недоступен или вернул некорректный ответ."""


def fetch_daily(date_from: str, date_to: str) -> list[dict]:
    """Дневные температуры за период [date_from, date_to] (YYYY-MM-DD).

    Возвращает список строк: date, t_out_mean, t_out_min, t_out_max, heating_degree.
    Кидает WeatherSourceError, если источник недоступен или ответ без данных.
    """
    params = {
        "latitude": LAT,
        "longitude": LON,
        "start_date": date_from,
        "end_date": date_to,
        "daily": DAILY_METRICS,
        "timezone": TIMEZONE,
    }

    try:
        response = httpx.get(API_URL, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise WeatherSourceError(f"источник погоды недоступен: {exc}") from exc

    daily = payload.get("daily")
    if not daily or "time" not in daily:
        raise WeatherSourceError(f"ответ без блока daily: {payload.get('reason', payload)}")

    rows = []
    for i, day in enumerate(daily["time"]):
        mean = daily["temperature_2m_mean"][i]
        rows.append({
            "date": day,
            "t_out_mean": mean,
            "t_out_min": daily["temperature_2m_min"][i],
            "t_out_max": daily["temperature_2m_max"][i],
            "heating_degree": None if mean is None else max(0.0, HEATING_BASE - mean),
        })
    return rows
