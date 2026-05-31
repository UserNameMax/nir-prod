"""
Регрессионные тесты для storage/reader.py

BUG-002: NaN в строковых колонках parquet вызывал ValueError при JSON-сериализации.
Фикс: _sanitize() заменяет float NaN/Inf → None.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from storage.reader import _sanitize, read_objects, read_sensors


# ── _sanitize ──────────────────────────────────────────────────────────────────

def test_sanitize_nan_becomes_none():
    records = [{"field": float("nan"), "other": "ok"}]
    result = _sanitize(records)
    assert result[0]["field"] is None
    assert result[0]["other"] == "ok"


def test_sanitize_inf_becomes_none():
    records = [{"pos": float("inf"), "neg": float("-inf")}]
    result = _sanitize(records)
    assert result[0]["pos"] is None
    assert result[0]["neg"] is None


def test_sanitize_valid_values_unchanged():
    records = [{"i": 42, "f": 3.14, "s": "hello", "n": None}]
    result = _sanitize(records)
    assert result[0]["i"] == 42
    assert result[0]["f"] == 3.14
    assert result[0]["s"] == "hello"
    assert result[0]["n"] is None


def test_sanitize_multiple_rows():
    records = [
        {"a": float("nan"), "b": 1.0},
        {"a": 2.0,          "b": float("nan")},
    ]
    result = _sanitize(records)
    assert result[0]["a"] is None
    assert result[0]["b"] == 1.0
    assert result[1]["a"] == 2.0
    assert result[1]["b"] is None


# ── read_objects — BUG-002 ──────────────────────────────────────────────────────

def _write_meta_parquet(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_parquet(path, index=False)


def test_read_objects_with_nan_string_fields(tmp_path):
    """
    BUG-002: parquet с NaN в строковых полях → read_objects не падает,
    возвращает None вместо NaN.
    """
    meta_path = tmp_path / "objects_meta.parquet"
    _write_meta_parquet(meta_path, [
        {
            "object_id": "OBJ_1",
            "object_type": np.nan,       # NaN в строковом поле
            "facility_type": np.nan,
            "facility_name": "Котельная",
            "municipality": np.nan,
            "rso": np.nan,
        }
    ])

    items, total = read_objects(str(tmp_path))

    assert total == 1
    assert items[0]["object_type"] is None
    assert items[0]["facility_type"] is None
    assert items[0]["municipality"] is None
    assert items[0]["facility_name"] == "Котельная"


def test_read_objects_all_nan_fields(tmp_path):
    """Все строковые поля NaN — ни одно не должно быть float('nan')."""
    meta_path = tmp_path / "objects_meta.parquet"
    _write_meta_parquet(meta_path, [
        {
            "object_id": "OBJ_2",
            "object_type": np.nan,
            "facility_type": np.nan,
            "facility_name": np.nan,
            "municipality": np.nan,
            "rso": np.nan,
        }
    ])

    items, _ = read_objects(str(tmp_path))

    for key, val in items[0].items():
        if key != "object_id":
            assert val is None or not (isinstance(val, float) and math.isnan(val)), \
                f"Field '{key}' contains NaN: {val}"


def test_read_objects_returns_none_not_nan_is_json_safe(tmp_path):
    """Результат read_objects можно сериализовать в JSON без ошибок."""
    import json

    meta_path = tmp_path / "objects_meta.parquet"
    _write_meta_parquet(meta_path, [
        {"object_id": "OBJ_3", "object_type": np.nan, "facility_type": np.nan,
         "facility_name": np.nan, "municipality": np.nan, "rso": np.nan}
    ])

    items, _ = read_objects(str(tmp_path))

    # Не должно бросать ValueError
    serialized = json.dumps(items)
    assert "NaN" not in serialized


# ── read_sensors — NaN в числовых полях ───────────────────────────────────────

def _write_sensors_parquet(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_parquet(path, index=False)


def test_read_sensors_with_nan_sensor_values(tmp_path):
    """NaN в числовых колонках датчиков → возвращается None, не float('nan')."""
    sensors_path = tmp_path / "sensors.parquet"
    _write_sensors_parquet(sensors_path, [
        {
            "record_id": "1",
            "object_id": "OBJ_1",
            "ts_measurement": 1700000000,
            "t_supply": np.nan,       # датчик не работал
            "t_return": 50.0,
            "p_supply": np.nan,
            "p_return": 4.0,
            "ts_recorded": 1700000060,
        }
    ])

    items, total = read_sensors(str(tmp_path), object_id="OBJ_1")

    assert total == 1
    assert items[0]["t_supply"] is None
    assert items[0]["p_supply"] is None
    assert items[0]["t_return"] == 50.0


def test_read_sensors_nan_is_json_safe(tmp_path):
    """Сенсорные NaN → JSON сериализуется без ошибок."""
    import json

    sensors_path = tmp_path / "sensors.parquet"
    _write_sensors_parquet(sensors_path, [
        {"record_id": "1", "object_id": "OBJ_1", "ts_measurement": 1700000000,
         "t_supply": np.nan, "t_return": np.nan, "p_supply": np.nan, "p_return": np.nan,
         "ts_recorded": 1700000060}
    ])

    items, _ = read_sensors(str(tmp_path), object_id="OBJ_1")
    serialized = json.dumps(items)
    assert "NaN" not in serialized
