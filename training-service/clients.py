"""Клиенты внутренних сервисов: признаки и метки.

training-service ничего не читает с диска вне бандла — признаки берутся у
feature-service, верифицированные аварии у data-service.
"""
from __future__ import annotations
import io
import os

import httpx
import pandas as pd

FEATURE_SERVICE_URL = os.getenv("FEATURE_SERVICE_URL", "http://feature-service:8002")
DATA_SERVICE_URL = os.getenv("DATA_SERVICE_URL", "http://data-service:8000")
TIMEOUT = float(os.getenv("UPSTREAM_TIMEOUT", "1800"))


class UpstreamError(RuntimeError):
    """Соседний сервис недоступен или вернул ошибку."""


def fetch_schema() -> dict:
    """Контракт признаков feature-service (имена, порядок, версия)."""
    try:
        response = httpx.get(f"{FEATURE_SERVICE_URL}/schema", timeout=TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise UpstreamError(f"feature-service недоступен: {exc}") from exc
    return response.json()


def fetch_features(date_from: str | None = None,
                   date_to: str | None = None) -> pd.DataFrame:
    """Дневная матрица признаков (parquet-поток)."""
    params = {k: v for k, v in {"date_from": date_from, "date_to": date_to}.items() if v}
    try:
        response = httpx.get(f"{FEATURE_SERVICE_URL}/features",
                             params=params, timeout=TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise UpstreamError(f"feature-service недоступен: {exc}") from exc

    matrix = pd.read_parquet(io.BytesIO(response.content))
    matrix["object_id"] = matrix["object_id"].astype(str)
    matrix["date"] = pd.to_datetime(matrix["date"])
    return matrix


def fetch_incidents() -> pd.DataFrame:
    """Верифицированные аварии — метки для разметки горизонта."""
    try:
        response = httpx.get(f"{DATA_SERVICE_URL}/incidents",
                             params={"limit": 100_000}, timeout=TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise UpstreamError(f"data-service недоступен: {exc}") from exc

    items = response.json().get("items", [])
    if not items:
        return pd.DataFrame(columns=["object_id", "incident_ts"])

    incidents = pd.DataFrame(items)
    incidents["object_id"] = incidents["object_id"].astype(str)
    incidents["incident_ts"] = pd.to_datetime(incidents["incident_ts"], unit="s")
    return incidents[["object_id", "incident_ts"]].sort_values("incident_ts")
