"""
Тесты для incidents — верифицированные аварии (метки обучения предиктивных моделей).

Контракт: дедупликация по incident_id (идемпотентность), фильтр по объекту и
окну открытия инцидента, close_ts может отсутствовать (авария не закрыта).
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from storage.reader import read_incidents, read_incident_object_ids, read_incidents_health
from storage.writer import bulk_insert_incidents


def _rows() -> list[dict]:
    return [
        {"incident_id": "i1", "object_id": "7566", "incident_ts": 1778000000,
         "close_ts": 1778030000, "source": "заявки"},
        {"incident_id": "i2", "object_id": "7566", "incident_ts": 1779000000,
         "close_ts": None, "source": "тех нарушения"},
        {"incident_id": "i3", "object_id": "9533", "incident_ts": 1778500000,
         "close_ts": 1778510000, "source": "заявки"},
    ]


# ── пустое хранилище ──────────────────────────────────────────────────────────

def test_read_incidents_missing_file(tmp_path):
    """Файла аварий ещё нет → пустой результат, не исключение."""
    items, total = read_incidents(str(tmp_path))
    assert items == []
    assert total == 0


def test_incident_objects_missing_file(tmp_path):
    assert read_incident_object_ids(str(tmp_path)) == []


def test_health_missing_file(tmp_path):
    assert read_incidents_health(str(tmp_path)) == {"incidents_count": 0, "incidents_objects": 0}


# ── запись и дедупликация ─────────────────────────────────────────────────────

def test_bulk_insert_creates_file(tmp_path):
    inserted, skipped = bulk_insert_incidents(str(tmp_path), _rows())
    assert (inserted, skipped) == (3, 0)
    assert (tmp_path / "incidents.parquet").exists()


def test_bulk_insert_is_idempotent(tmp_path):
    """Повторная загрузка тех же аварий не создаёт дублей."""
    bulk_insert_incidents(str(tmp_path), _rows())
    inserted, skipped = bulk_insert_incidents(str(tmp_path), _rows())

    assert (inserted, skipped) == (0, 3)
    _, total = read_incidents(str(tmp_path))
    assert total == 3


def test_bulk_insert_dedups_within_batch(tmp_path):
    """Дубли внутри одной партии схлопываются по incident_id."""
    rows = _rows() + [_rows()[0]]
    inserted, _ = bulk_insert_incidents(str(tmp_path), rows)
    assert inserted == 3


def test_bulk_insert_appends_new(tmp_path):
    bulk_insert_incidents(str(tmp_path), _rows())
    inserted, skipped = bulk_insert_incidents(str(tmp_path), [
        {"incident_id": "i4", "object_id": "1010", "incident_ts": 1780000000,
         "close_ts": None, "source": "заявки"},
    ])
    assert (inserted, skipped) == (1, 0)
    _, total = read_incidents(str(tmp_path))
    assert total == 4


def test_bulk_insert_empty(tmp_path):
    assert bulk_insert_incidents(str(tmp_path), []) == (0, 0)


def test_timestamp_schema_stable_across_batches(tmp_path):
    """Партия, где все аварии не закрыты (close_ts=None), не превращает
    колонку в float — схема parquet остаётся целочисленной."""
    bulk_insert_incidents(str(tmp_path), [
        {"incident_id": "a", "object_id": "1", "incident_ts": 100,
         "close_ts": 200, "source": "заявки"},
    ])
    bulk_insert_incidents(str(tmp_path), [
        {"incident_id": "b", "object_id": "1", "incident_ts": 300,
         "close_ts": None, "source": "заявки"},
    ])

    df = pd.read_parquet(tmp_path / "incidents.parquet")
    assert str(df["incident_ts"].dtype) == "Int64"
    assert str(df["close_ts"].dtype) == "Int64"

    items, _ = read_incidents(str(tmp_path))
    assert items[0]["close_ts"] == 200
    assert items[1]["close_ts"] is None


# ── чтение и фильтры ──────────────────────────────────────────────────────────

def test_read_filters_by_object(tmp_path):
    bulk_insert_incidents(str(tmp_path), _rows())
    items, total = read_incidents(str(tmp_path), object_id="7566")
    assert total == 2
    assert {i["object_id"] for i in items} == {"7566"}


def test_read_filters_by_window(tmp_path):
    """Окно фильтрует по времени ОТКРЫТИЯ инцидента."""
    bulk_insert_incidents(str(tmp_path), _rows())
    _, after = read_incidents(str(tmp_path), from_ts=1778400000)
    _, before = read_incidents(str(tmp_path), to_ts=1778400000)
    assert after == 2
    assert before == 1


def test_read_orders_by_incident_ts(tmp_path):
    bulk_insert_incidents(str(tmp_path), _rows())
    items, _ = read_incidents(str(tmp_path))
    assert [i["incident_ts"] for i in items] == sorted(i["incident_ts"] for i in items)


def test_read_preserves_open_incident(tmp_path):
    """Незакрытая авария: close_ts=None сохраняется (не NaN, JSON-safe)."""
    import json

    bulk_insert_incidents(str(tmp_path), _rows())
    items, _ = read_incidents(str(tmp_path), object_id="7566")
    open_one = [i for i in items if i["incident_id"] == "i2"][0]

    assert open_one["close_ts"] is None
    assert "NaN" not in json.dumps(items)


def test_read_pagination(tmp_path):
    bulk_insert_incidents(str(tmp_path), _rows())
    items, total = read_incidents(str(tmp_path), offset=1, limit=1)
    assert total == 3
    assert len(items) == 1


def test_incident_object_ids(tmp_path):
    bulk_insert_incidents(str(tmp_path), _rows())
    assert read_incident_object_ids(str(tmp_path)) == ["7566", "9533"]


def test_health_counts(tmp_path):
    bulk_insert_incidents(str(tmp_path), _rows())
    assert read_incidents_health(str(tmp_path)) == {"incidents_count": 3, "incidents_objects": 2}


def test_object_id_quote_is_escaped(tmp_path):
    """Кавычка в object_id не ломает SQL."""
    bulk_insert_incidents(str(tmp_path), _rows())
    items, total = read_incidents(str(tmp_path), object_id="7566' OR '1'='1")
    assert (items, total) == ([], 0)
