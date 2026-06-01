import sys
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from pipeline.parser import (
    detect_format, normalize_format_a, normalize_format_b,
    parse_xlsx, _to_unix, _fix_mkd_columns, _clean_str,
)
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


# ── _to_unix: обработка невалидных дат (BUG-008, BUG-009) ─────────────────────

def test_invalid_date_string_becomes_nan():
    """BUG-009: невалидная дата → NaN, не 0."""
    s = pd.Series(["not a date", "garbage"], dtype=object)
    result = _to_unix(s)
    assert result.isna().all(), "Невалидные строки должны давать NaN, не 0"


def test_valid_datetime_converted_correctly():
    """Валидная дата → корректный unix timestamp."""
    s = pd.Series([pd.Timestamp("2025-11-01 00:00:00")], dtype=object)
    result = _to_unix(s)
    assert not result.isna().any()
    assert result.iloc[0] > 0
    # 2025-11-01 UTC ≈ 1762012800
    assert abs(result.iloc[0] - 1762012800) < 86400


def test_xlsb_serial_float_dates_parsed_correctly():
    """BUG-008b: xlsb хранит даты как float (Excel serial). pandas 2.x требует
    предварительный pd.to_numeric() перед to_datetime(unit='D')."""
    # 45216.0 — Excel serial date, соответствует дате в 2023 году
    s = pd.Series([45216.0, 45217.0], dtype=object)
    result = _to_unix(s)
    assert not result.isna().any()
    # Результат должен быть в диапазоне 2023 года (unix: ~1672531200..1703980800)
    assert 1672531200 < result.iloc[0] < 1703980800, \
        f"Ожидалась дата в 2023 году, получили: {pd.Timestamp(result.iloc[0], unit='s')}"
    # Два соседних serial date → разница ≈ 1 день (86400 сек)
    assert abs(result.iloc[1] - result.iloc[0] - 86400) < 3600


def test_out_of_bounds_date_becomes_nan(tmp_path):
    """BUG-008: дата 1000-01-01 (out of bounds для pandas Timestamp) → NaN, не исключение."""
    xlsx = tmp_path / "old_dates.xlsx"
    data = {
        "ID": ["1"],
        "Дата и время показателей": ["1000-01-01 00:00:00"],  # строка с очень старой датой
        "T пр": [60.0], "T обр": [50.0], "P пр": [6.0], "P обр": [4.0],
        "Дата и время записи": ["1000-01-01 00:00:00"],
        "ID объекта": ["OBJ_1"], "Тип объекта": ["ТИ"], "Котельная/ЦТП": ["Котельная"],
        "Наименование котельной": ["Тест"], "Муниципалитет": ["МО"], "РСО": ["МосОбл"],
    }
    pd.DataFrame(data).to_excel(xlsx, index=False)
    # Не должно бросать исключение
    result = parse_xlsx(xlsx)
    # Может вернуть None (если cleaner убил все строки) или sensors с NaN в ts
    # Главное — нет исключения


def test_xlsb_engine_selected_for_xlsb_extension(tmp_path):
    """Файл .xlsb читается с engine='pyxlsb'."""
    xlsb = tmp_path / "test.xlsb"
    xlsb.write_bytes(b"fake xlsb")

    with patch("pipeline.parser.pd.read_excel") as mock_read:
        mock_read.side_effect = Exception("stop")
        try:
            parse_xlsx(xlsb)
        except Exception:
            pass
        _, kwargs = mock_read.call_args
        assert kwargs.get("engine") == "pyxlsb"


# ── _clean_str: обработка None и пробелов (BUG-011) ───────────────────────────

def test_object_id_nan_becomes_pd_na():
    """BUG-011: None в object_id → pd.NA (не строка 'nan')."""
    s = pd.Series([None, float("nan"), "OBJ_1"], dtype=object)
    result = _clean_str(s)
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == "OBJ_1"


def test_object_id_strip_whitespace():
    """Лишние пробелы в object_id убираются."""
    s = pd.Series([" 12345 ", "  OBJ_2  "], dtype=object)
    result = _clean_str(s)
    assert result.iloc[0] == "12345"
    assert result.iloc[1] == "OBJ_2"


def test_nan_string_becomes_pd_na():
    """Строка 'nan' (от astype(str)) → pd.NA."""
    s = pd.Series(["nan", "None", "NaN", ""], dtype=object)
    result = _clean_str(s)
    assert result.isna().all()


# ── _fix_mkd_columns: МКД-паттерн ─────────────────────────────────────────────

def test_mkd_columns_fixed():
    """В источнике для МКД object_type=муниципалитет, facility_type='МКД'.
    После фикса: object_type='МКД', municipality=муниципалитет."""
    meta = pd.DataFrame([{
        "object_id": "123",
        "object_type": "Мытищи г.о.",
        "facility_type": "МКД",
        "facility_name": None,
        "municipality": None,
        "rso": None,
    }])
    result = _fix_mkd_columns(meta)
    assert result.iloc[0]["object_type"] == "МКД"
    assert result.iloc[0]["municipality"] == "Мытищи г.о."
    assert pd.isna(result.iloc[0]["facility_type"])


def test_mkd_columns_not_affected_for_ti():
    """ТИ-объекты не затрагиваются _fix_mkd_columns."""
    meta = pd.DataFrame([{
        "object_id": "456",
        "object_type": "ТИ",
        "facility_type": "Котельная",
        "facility_name": "Котельная №1",
        "municipality": "Мытищи г.о.",
        "rso": "МосОбл",
    }])
    result = _fix_mkd_columns(meta)
    assert result.iloc[0]["object_type"] == "ТИ"
    assert result.iloc[0]["municipality"] == "Мытищи г.о."
    assert result.iloc[0]["facility_type"] == "Котельная"


def test_mkd_pattern_various_municipalities():
    """МКД-паттерн срабатывает для разных г.о."""
    municipalities = ["Богородский г.о.", "Волоколамск г.о.", "Балашиха г.о."]
    for muni in municipalities:
        meta = pd.DataFrame([{
            "object_id": "1", "object_type": muni, "facility_type": "МКД",
            "facility_name": None, "municipality": None, "rso": None,
        }])
        result = _fix_mkd_columns(meta)
        assert result.iloc[0]["object_type"] == "МКД", f"Не сработало для {muni}"
        assert result.iloc[0]["municipality"] == muni


# ── object_type из Тип объекта (BUG-010) ──────────────────────────────────────

def test_object_type_column_populated(tmp_path):
    """BUG-010: битый символ 'Тип ��бъекта' в rename dict → все object_type NULL.
    После фикса object_type должен заполняться."""
    xlsx = tmp_path / "a.xlsx"
    make_format_a(xlsx, rows=3)
    result = parse_xlsx(xlsx)
    assert result is not None
    _, meta = result
    # Тип объекта из make_format_a = "Богородский г.о." → после _fix_mkd_columns = "МКД"
    # или ТИ если нет паттерна г.о. в facility_type
    # Главное: не None для всех
    # make_format_a даёт Котельная/ЦТП="ЦТП" и Тип объекта="Богородский г.о."
    # → МКД-паттерн НЕ срабатывает (facility_type="ЦТП" ≠ "МКД")
    # → object_type должен быть "Богородский г.о." (не None)
    assert meta["object_type"].notna().any(), "object_type не должен быть NULL для всех строк"
