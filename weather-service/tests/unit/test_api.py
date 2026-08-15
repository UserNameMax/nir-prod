"""
Тесты API weather-service. Внешний источник замокан — наружу тесты не ходят.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[2]))

import dependencies
import source
import store


@pytest.fixture
def client(tmp_path):
    dependencies.override_weather_dir(str(tmp_path))
    import main
    return TestClient(main.app)


def _fake_rows(days):
    return [
        {"date": d, "t_out_mean": 10.0, "t_out_min": 5.0,
         "t_out_max": 15.0, "heating_degree": 8.0}
        for d in days
    ]


def test_health_empty(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["cached_days"] == 0


def test_weather_empty_cache(client):
    body = client.get("/weather").json()
    assert body["rows"] == []
    assert body["region"]


def test_refresh_fetches_and_caches(client, monkeypatch, tmp_path):
    monkeypatch.setattr(source, "fetch_daily",
                        lambda a, b: _fake_rows(["2026-05-01", "2026-05-02"]))

    body = client.post("/weather/refresh",
                       json={"date_from": "2026-05-01", "date_to": "2026-05-02"}).json()

    assert body == {"fetched": 2, "added": 2, "updated": 0, "source": "open-meteo"}
    assert len(client.get("/weather").json()["rows"]) == 2


def test_refresh_skips_when_cached(client, monkeypatch):
    """Период уже в кэше → наружу не идём."""
    monkeypatch.setattr(source, "fetch_daily",
                        lambda a, b: _fake_rows(["2026-05-01"]))
    client.post("/weather/refresh", json={"date_from": "2026-05-01", "date_to": "2026-05-01"})

    def _boom(a, b):
        raise AssertionError("не должно ходить наружу — период закэширован")

    monkeypatch.setattr(source, "fetch_daily", _boom)
    body = client.post("/weather/refresh",
                       json={"date_from": "2026-05-01", "date_to": "2026-05-01"}).json()

    assert body == {"fetched": 0, "added": 0, "updated": 0, "source": "cache"}


def test_refresh_force_refetches(client, monkeypatch):
    monkeypatch.setattr(source, "fetch_daily", lambda a, b: _fake_rows(["2026-05-01"]))
    client.post("/weather/refresh", json={"date_from": "2026-05-01", "date_to": "2026-05-01"})

    body = client.post("/weather/refresh",
                       json={"date_from": "2026-05-01", "date_to": "2026-05-01",
                             "force": True}).json()

    assert body["source"] == "open-meteo"
    assert body["updated"] == 1


def test_refresh_source_down_returns_502(client, monkeypatch):
    def _down(a, b):
        raise source.WeatherSourceError("connection refused")

    monkeypatch.setattr(source, "fetch_daily", _down)
    response = client.post("/weather/refresh",
                           json={"date_from": "2026-05-01", "date_to": "2026-05-02"})

    assert response.status_code == 502
    assert "connection refused" in response.json()["detail"]


def test_cache_survives_source_outage(client, monkeypatch):
    """Загруженные дни отдаются, даже когда источник лёг."""
    monkeypatch.setattr(source, "fetch_daily", lambda a, b: _fake_rows(["2026-05-01"]))
    client.post("/weather/refresh", json={"date_from": "2026-05-01", "date_to": "2026-05-01"})

    def _down(a, b):
        raise source.WeatherSourceError("down")

    monkeypatch.setattr(source, "fetch_daily", _down)
    client.post("/weather/refresh", json={"date_from": "2026-05-02", "date_to": "2026-05-02"})

    assert len(client.get("/weather").json()["rows"]) == 1


def test_refresh_rejects_inverted_range(client):
    response = client.post("/weather/refresh",
                           json={"date_from": "2026-05-05", "date_to": "2026-05-01"})
    assert response.status_code == 400


def test_weather_filters_period(client, monkeypatch):
    monkeypatch.setattr(source, "fetch_daily",
                        lambda a, b: _fake_rows(["2026-05-01", "2026-05-02", "2026-05-03"]))
    client.post("/weather/refresh", json={"date_from": "2026-05-01", "date_to": "2026-05-03"})

    rows = client.get("/weather", params={"date_from": "2026-05-02",
                                          "date_to": "2026-05-02"}).json()["rows"]
    assert [r["date"] for r in rows] == ["2026-05-02"]
