"""
Тесты API feature-service. Соседние сервисы замоканы — тесты никуда не ходят.
"""
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[2]))

import cache
import client
import dependencies
import schema

from .test_pipeline import make_sensors, make_weather


@pytest.fixture
def app_client(tmp_path):
    dependencies.override_cache_dir(str(tmp_path))
    import main
    return TestClient(main.app)


@pytest.fixture
def stubbed(monkeypatch):
    monkeypatch.setattr(client, "fetch_sensors", lambda a=None, b=None: make_sensors(days=40))
    monkeypatch.setattr(client, "fetch_weather", lambda a=None, b=None: make_weather(days=40))


def _matrix(response) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(response.content))


# ── схема ─────────────────────────────────────────────────────────────────────

def test_schema_endpoint(app_client):
    body = app_client.get("/schema").json()
    assert body["name"] == "final_h30"
    assert body["n_features"] == 31
    assert body["columns"] == list(schema.FEATURES)
    assert body["horizon_days"] == 30


def test_schema_version_matches_module(app_client):
    assert app_client.get("/schema").json()["version"] == schema.version()


def test_health_empty(app_client):
    body = app_client.get("/health").json()
    assert body["status"] == "ok"
    assert body["cached_object_days"] == 0


# ── пересчёт и выдача ─────────────────────────────────────────────────────────

def test_rebuild_then_features(app_client, stubbed):
    body = app_client.post("/features/rebuild", json={}).json()
    assert body["objects"] == 2
    assert body["object_days"] == 80          # 2 объекта × 40 дней
    assert body["schema_version"] == schema.version()

    matrix = _matrix(app_client.get("/features"))
    assert list(matrix.columns) == [*schema.KEYS, *schema.FEATURES]
    assert len(matrix) == 80


def test_features_before_rebuild_is_empty_but_typed(app_client):
    """До пересчёта — пустая матрица, но с полным контрактом колонок."""
    matrix = _matrix(app_client.get("/features"))
    assert list(matrix.columns) == [*schema.KEYS, *schema.FEATURES]
    assert matrix.empty


def test_features_filters_by_date(app_client, stubbed):
    app_client.post("/features/rebuild", json={})
    matrix = _matrix(app_client.get("/features", params={
        "date_from": "2026-01-05", "date_to": "2026-01-06"}))

    assert set(matrix["date"].dt.strftime("%Y-%m-%d")) == {"2026-01-05", "2026-01-06"}


def test_features_filters_by_object(app_client, stubbed):
    app_client.post("/features/rebuild", json={})
    matrix = _matrix(app_client.get("/features", params={"object_ids": "A"}))
    assert set(matrix["object_id"]) == {"A"}


def test_features_headers_report_rows_and_schema(app_client, stubbed):
    app_client.post("/features/rebuild", json={})
    response = app_client.get("/features")
    assert response.headers["X-Rows"] == "80"
    assert response.headers["X-Schema-Version"] == schema.version()


def test_health_after_rebuild(app_client, stubbed):
    app_client.post("/features/rebuild", json={})
    body = app_client.get("/health").json()
    assert body["cached_object_days"] == 80
    assert body["cached_objects"] == 2


# ── отказы соседей ────────────────────────────────────────────────────────────

def test_rebuild_upstream_down_returns_502(app_client, monkeypatch):
    def _down(a=None, b=None):
        raise client.UpstreamError("data-service недоступен")

    monkeypatch.setattr(client, "fetch_sensors", _down)
    response = app_client.post("/features/rebuild", json={})
    assert response.status_code == 502


def test_rebuild_without_data_returns_404(app_client, monkeypatch):
    monkeypatch.setattr(client, "fetch_sensors",
                        lambda a=None, b=None: pd.DataFrame(
                            columns=["object_id", "ts_recorded", "t_supply",
                                     "t_return", "p_supply", "p_return"]))
    monkeypatch.setattr(client, "fetch_weather", lambda a=None, b=None: make_weather(days=1))

    assert app_client.post("/features/rebuild", json={}).status_code == 404


def test_cache_survives_failed_rebuild(app_client, stubbed, monkeypatch):
    """Неудачный пересчёт не стирает уже посчитанную матрицу."""
    app_client.post("/features/rebuild", json={})

    def _down(a=None, b=None):
        raise client.UpstreamError("упал")

    monkeypatch.setattr(client, "fetch_sensors", _down)
    app_client.post("/features/rebuild", json={})

    assert len(_matrix(app_client.get("/features"))) == 80
