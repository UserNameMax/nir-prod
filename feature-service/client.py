"""Клиенты внутренних сервисов: сырьё датчиков и наружная температура.

feature-service ничего не читает с диска вне своего кэша и не ходит во внешний мир —
сенсоры берутся у data-service, погода у weather-service.
"""
from __future__ import annotations
import io
import os

import httpx
import pandas as pd

DATA_SERVICE_URL = os.getenv("DATA_SERVICE_URL", "http://data-service:8000")
WEATHER_SERVICE_URL = os.getenv("WEATHER_SERVICE_URL", "http://weather-service:8003")
TIMEOUT = float(os.getenv("UPSTREAM_TIMEOUT", "600"))


class UpstreamError(RuntimeError):
    """Соседний сервис недоступен или вернул ошибку."""


def fetch_sensors(date_from: str | None = None,
                  date_to: str | None = None) -> pd.DataFrame:
    """Показания датчиков за период одним parquet-потоком.

    Возвращает пустой кадр, если данных за период нет (data-service отвечает 404).
    """
    params = {k: v for k, v in {"date_from": date_from, "date_to": date_to}.items() if v}
    try:
        response = httpx.get(f"{DATA_SERVICE_URL}/sensors/export",
                             params=params, timeout=TIMEOUT)
        if response.status_code == 404:
            return pd.DataFrame(columns=["object_id", "ts_measurement", "ts_recorded",
                                         "t_supply", "t_return", "p_supply", "p_return"])
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise UpstreamError(f"data-service недоступен: {exc}") from exc

    sensors = pd.read_parquet(io.BytesIO(response.content))
    # data-service хранит время как unix-секунды — пайплайн работает с datetime.
    if not pd.api.types.is_datetime64_any_dtype(sensors["ts_recorded"]):
        sensors["ts_recorded"] = pd.to_datetime(sensors["ts_recorded"], unit="s")
    return sensors


def fetch_weather(date_from: str | None = None,
                  date_to: str | None = None) -> pd.DataFrame:
    """Дневная наружная температура. Пустой кадр, если погода не загружена."""
    params = {k: v for k, v in {"date_from": date_from, "date_to": date_to}.items() if v}
    try:
        response = httpx.get(f"{WEATHER_SERVICE_URL}/weather",
                             params=params, timeout=TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise UpstreamError(f"weather-service недоступен: {exc}") from exc

    rows = response.json().get("rows", [])
    if not rows:
        return pd.DataFrame(columns=["date", "t_out_mean"])

    weather = pd.DataFrame(rows)
    weather["date"] = pd.to_datetime(weather["date"])
    return weather[["date", "t_out_mean"]]
