"""Клиенты соседних сервисов: признаки и сырьё для суточного профиля."""
from __future__ import annotations
import io
import os

import httpx
import pandas as pd

FEATURE_SERVICE_URL = os.getenv("FEATURE_SERVICE_URL", "http://feature-service:8002")
DATA_SERVICE_URL = os.getenv("DATA_SERVICE_URL", "http://data-service:8000")
TIMEOUT = float(os.getenv("UPSTREAM_TIMEOUT", "1800"))


class UpstreamError(RuntimeError):
    """Соседний сервис недоступен."""


def fetch_schema_version() -> str:
    """Версия схемы признаков — сверяется с бандлом при загрузке (parity)."""
    try:
        response = httpx.get(f"{FEATURE_SERVICE_URL}/schema", timeout=TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise UpstreamError(f"feature-service недоступен: {exc}") from exc
    return response.json()["version"]


def fetch_features() -> pd.DataFrame:
    try:
        response = httpx.get(f"{FEATURE_SERVICE_URL}/features", timeout=TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise UpstreamError(f"feature-service недоступен: {exc}") from exc

    matrix = pd.read_parquet(io.BytesIO(response.content))
    matrix["object_id"] = matrix["object_id"].astype(str)
    matrix["date"] = pd.to_datetime(matrix["date"])
    return matrix


def fetch_objects() -> pd.DataFrame:
    """Справочник объектов — для заголовков в интерфейсе."""
    try:
        response = httpx.get(f"{DATA_SERVICE_URL}/objects",
                             params={"limit": 10_000}, timeout=TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise UpstreamError(f"data-service недоступен: {exc}") from exc

    items = response.json().get("items", [])
    if not items:
        return pd.DataFrame(columns=["object_id"])
    meta = pd.DataFrame(items)
    meta["object_id"] = meta["object_id"].astype(str)
    return meta


def fetch_daily_profile(object_id: str, date: str) -> list[dict]:
    """Сырые почасовые показания за день — визуальное подтверждение физики."""
    start = pd.Timestamp(date)
    params = {
        "object_id": object_id,
        "from_ts": int(start.timestamp()),
        "to_ts": int((start + pd.Timedelta(days=1)).timestamp()),
        "limit": 2000,
    }
    try:
        response = httpx.get(f"{DATA_SERVICE_URL}/sensors", params=params, timeout=TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise UpstreamError(f"data-service недоступен: {exc}") from exc

    rows = response.json().get("items", [])
    return [{
        "ts": pd.Timestamp(r["ts_recorded"], unit="s").isoformat(),
        "t_supply": r.get("t_supply"), "t_return": r.get("t_return"),
        "p_supply": r.get("p_supply"), "p_return": r.get("p_return"),
    } for r in rows]
