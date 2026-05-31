import sys
from pathlib import Path
import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from pipeline.parser import detect_format, normalize_format_a, normalize_format_b, parse_xlsx
from tests.fixtures.make_xlsx import make_format_a, make_format_b


# ── detect_format ──────────────────────────────────────────────────────────────

def test_detect_format_a():
    df = pd.DataFrame({"T пр": [1], "T обр": [1], "P пр": [1], "P обр": [1]})
    assert detect_format(df) == "A"


def test_detect_format_a_by_id_objecta():
    df = pd.DataFrame({"ID объекта": [1], "T обр": [1]})
    assert detect_format(df) == "A"


def test_detect_format_b():
    df = pd.DataFrame({"t_forward": [1], "t_revers": [1]})
    assert detect_format(df) == "B"


def test_detect_format_unknown():
    df = pd.DataFrame({"col1": [1], "col2": [2]})
    assert detect_format(df) == "UNKNOWN"


# ── normalize_format_a ─────────────────────────────────────────────────────────

def test_normalize_format_a_columns(tmp_path):
    xlsx = tmp_path / "a.xlsx"
    make_format_a(xlsx, rows=3)
    raw = pd.read_excel(xlsx)
    sensors, meta = normalize_format_a(raw)

    expected_sensor_cols = {"record_id", "object_id", "ts_measurement", "t_supply", "t_return", "p_supply", "p_return", "ts_recorded"}
    assert expected_sensor_cols == set(sensors.columns)

    assert sensors["ts_measurement"].dtype == np.int64
    assert sensors["ts_recorded"].dtype == np.int64


def test_normalize_format_a_alt_name_col(tmp_path):
    xlsx = tmp_path / "a_alt.xlsx"
    make_format_a(xlsx, rows=3, alt_name_col=True)
    raw = pd.read_excel(xlsx)
    sensors, meta = normalize_format_a(raw)

    assert "facility_name" in meta.columns
    assert meta["facility_name"].notna().any()


def test_normalize_format_a_values(tmp_path):
    xlsx = tmp_path / "a.xlsx"
    make_format_a(xlsx, rows=3)
    raw = pd.read_excel(xlsx)
    sensors, _ = normalize_format_a(raw)

    assert len(sensors) == 3
    assert (sensors["t_supply"] >= 60.0).all()


# ── normalize_format_b ─────────────────────────────────────────────────────────

def test_normalize_format_b_ts_measurement_equals_ts_recorded(tmp_path):
    xlsx = tmp_path / "b.xlsx"
    make_format_b(xlsx, rows=4)
    raw = pd.read_excel(xlsx)
    sensors, _ = normalize_format_b(raw)

    assert sensors["ts_measurement"].equals(sensors["ts_recorded"])


def test_normalize_format_b_missing_meta_columns(tmp_path):
    xlsx = tmp_path / "b.xlsx"
    make_format_b(xlsx, rows=4)
    raw = pd.read_excel(xlsx)
    _, meta = normalize_format_b(raw)

    assert meta["object_type"].isna().all()
    assert meta["facility_type"].isna().all()


def test_normalize_format_b_columns(tmp_path):
    xlsx = tmp_path / "b.xlsx"
    make_format_b(xlsx, rows=4)
    raw = pd.read_excel(xlsx)
    sensors, meta = normalize_format_b(raw)

    expected_sensor_cols = {"record_id", "object_id", "ts_measurement", "t_supply", "t_return", "p_supply", "p_return", "ts_recorded"}
    assert expected_sensor_cols == set(sensors.columns)


# ── parse_xlsx (интеграция detect + normalize) ─────────────────────────────────

def test_parse_xlsx_format_a(tmp_path):
    xlsx = tmp_path / "a.xlsx"
    make_format_a(xlsx, rows=5)
    result = parse_xlsx(xlsx)
    assert result is not None
    sensors, meta = result
    assert len(sensors) == 5


def test_parse_xlsx_format_b(tmp_path):
    xlsx = tmp_path / "b.xlsx"
    make_format_b(xlsx, rows=5)
    result = parse_xlsx(xlsx)
    assert result is not None
    sensors, _ = result
    assert len(sensors) == 5


def test_parse_xlsx_unknown_returns_none(tmp_path):
    xlsx = tmp_path / "unknown.xlsx"
    pd.DataFrame({"col1": [1, 2], "col2": [3, 4]}).to_excel(xlsx, index=False)
    assert parse_xlsx(xlsx) is None
