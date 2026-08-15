"""
Тесты клиента соседних сервисов — граница, где контракт чужой.

Регрессия: data-service отдаёт ts_recorded как unix-секунды (DOUBLE), а пайплайн
работает с datetime. Синтетика в тестах пайплайна уже была datetime, поэтому
несовпадение всплывало только на живом сервисе — здесь оно закрыто тестом.
"""
import io
import sys
from pathlib import Path

import httpx
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

import client


def _parquet_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False)
    return buffer.getvalue()


def _sensor_frame(ts_values) -> pd.DataFrame:
    return pd.DataFrame({
        "object_id": ["A"] * len(ts_values),
        "ts_recorded": ts_values,
        "t_supply": [60.0] * len(ts_values),
        "t_return": [50.0] * len(ts_values),
        "p_supply": [6.0] * len(ts_values),
        "p_return": [4.0] * len(ts_values),
    })


def _stub_get(monkeypatch, *, content=b"", status=200, json_body=None):
    def _get(url, params=None, timeout=None):
        request = httpx.Request("GET", url)
        if json_body is not None:
            return httpx.Response(status, json=json_body, request=request)
        return httpx.Response(status, content=content, request=request)

    monkeypatch.setattr(httpx, "get", _get)


def test_unix_seconds_converted_to_datetime(monkeypatch):
    """Числовые unix-секунды приводятся к datetime — иначе .dt в пайплайне падает."""
    unix = [1777593600.0, 1777594500.0]
    _stub_get(monkeypatch, content=_parquet_bytes(_sensor_frame(unix)))

    sensors = client.fetch_sensors()

    assert pd.api.types.is_datetime64_any_dtype(sensors["ts_recorded"])
    assert sensors["ts_recorded"].iloc[0] == pd.Timestamp("2026-05-01")


def test_datetime_passthrough(monkeypatch):
    stamps = pd.date_range("2026-05-01", periods=2, freq="15min")
    _stub_get(monkeypatch, content=_parquet_bytes(_sensor_frame(stamps)))

    sensors = client.fetch_sensors()
    assert sensors["ts_recorded"].iloc[1] == pd.Timestamp("2026-05-01 00:15")


def test_missing_period_returns_empty_frame(monkeypatch):
    """404 у data-service — это «нет данных», не отказ."""
    _stub_get(monkeypatch, status=404)
    assert client.fetch_sensors("2030-01-01", "2030-01-02").empty


def test_upstream_error_raised(monkeypatch):
    def _boom(url, params=None, timeout=None):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", _boom)
    with pytest.raises(client.UpstreamError):
        client.fetch_sensors()


def test_weather_parsed(monkeypatch):
    _stub_get(monkeypatch, json_body={"region": "moscow", "rows": [
        {"date": "2026-05-01", "t_out_mean": 5.2, "t_out_min": 1.3,
         "t_out_max": 9.0, "heating_degree": 12.8},
    ]})

    weather = client.fetch_weather()

    assert list(weather.columns) == ["date", "t_out_mean"]
    assert weather["date"].iloc[0] == pd.Timestamp("2026-05-01")


def test_weather_empty(monkeypatch):
    _stub_get(monkeypatch, json_body={"region": "moscow", "rows": []})
    assert client.fetch_weather().empty
