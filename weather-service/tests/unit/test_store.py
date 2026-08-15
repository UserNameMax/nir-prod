"""
Тесты кэша погоды: идемпотентность upsert, фильтрация периода, поиск дыр.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

import store


def _rows():
    return [
        {"date": "2026-05-01", "t_out_mean": 12.0, "t_out_min": 6.0,
         "t_out_max": 18.0, "heating_degree": 6.0},
        {"date": "2026-05-02", "t_out_mean": 14.0, "t_out_min": 8.0,
         "t_out_max": 20.0, "heating_degree": 4.0},
        {"date": "2026-05-03", "t_out_mean": 20.0, "t_out_min": 14.0,
         "t_out_max": 26.0, "heating_degree": 0.0},
    ]


def test_read_missing_file(tmp_path):
    assert store.read(str(tmp_path)) == []


def test_health_missing_file(tmp_path):
    assert store.health(str(tmp_path)) == {"cached_days": 0, "date_from": None, "date_to": None}


def test_upsert_creates_file(tmp_path):
    added, updated = store.upsert(str(tmp_path), _rows())
    assert (added, updated) == (3, 0)
    assert (tmp_path / "weather_daily.parquet").exists()


def test_upsert_is_idempotent(tmp_path):
    """Повторная загрузка того же периода не плодит строк."""
    store.upsert(str(tmp_path), _rows())
    added, updated = store.upsert(str(tmp_path), _rows())

    assert (added, updated) == (0, 3)
    assert len(store.read(str(tmp_path))) == 3


def test_upsert_overwrites_existing_day(tmp_path):
    """Архив уточняется задним числом — свежее значение побеждает."""
    store.upsert(str(tmp_path), _rows())
    store.upsert(str(tmp_path), [
        {"date": "2026-05-02", "t_out_mean": 99.0, "t_out_min": 90.0,
         "t_out_max": 100.0, "heating_degree": 0.0},
    ])

    rows = store.read(str(tmp_path))
    assert len(rows) == 3
    assert [r for r in rows if r["date"] == "2026-05-02"][0]["t_out_mean"] == 99.0


def test_upsert_dedups_within_batch(tmp_path):
    rows = _rows() + [dict(_rows()[0], t_out_mean=77.0)]
    added, _ = store.upsert(str(tmp_path), rows)

    assert added == 3
    stored = store.read(str(tmp_path))
    assert [r for r in stored if r["date"] == "2026-05-01"][0]["t_out_mean"] == 77.0


def test_upsert_empty(tmp_path):
    assert store.upsert(str(tmp_path), []) == (0, 0)


def test_read_filters_period(tmp_path):
    store.upsert(str(tmp_path), _rows())

    assert len(store.read(str(tmp_path), date_from="2026-05-02")) == 2
    assert len(store.read(str(tmp_path), date_to="2026-05-02")) == 2
    assert len(store.read(str(tmp_path), "2026-05-02", "2026-05-02")) == 1


def test_read_sorted_by_date(tmp_path):
    store.upsert(str(tmp_path), list(reversed(_rows())))
    dates = [r["date"] for r in store.read(str(tmp_path))]
    assert dates == sorted(dates)


def test_read_nan_becomes_none(tmp_path):
    """Пропуск в источнике → None, JSON-safe."""
    import json

    store.upsert(str(tmp_path), [
        {"date": "2026-05-01", "t_out_mean": None, "t_out_min": None,
         "t_out_max": None, "heating_degree": None},
    ])

    rows = store.read(str(tmp_path))
    assert rows[0]["t_out_mean"] is None
    assert "NaN" not in json.dumps(rows)


def test_health_counts(tmp_path):
    store.upsert(str(tmp_path), _rows())
    assert store.health(str(tmp_path)) == {
        "cached_days": 3, "date_from": "2026-05-01", "date_to": "2026-05-03",
    }


def test_missing_days_on_empty_cache(tmp_path):
    missing = store.missing_days(str(tmp_path), "2026-05-01", "2026-05-03")
    assert missing == ["2026-05-01", "2026-05-02", "2026-05-03"]


def test_missing_days_finds_gap(tmp_path):
    store.upsert(str(tmp_path), _rows())
    assert store.missing_days(str(tmp_path), "2026-05-01", "2026-05-05") == [
        "2026-05-04", "2026-05-05",
    ]


def test_missing_days_none_when_covered(tmp_path):
    store.upsert(str(tmp_path), _rows())
    assert store.missing_days(str(tmp_path), "2026-05-01", "2026-05-03") == []
