import sys
from pathlib import Path
import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from pipeline.cleaner import clean_sensors, dedup_sensors, dedup_meta


def _make_row(**kwargs) -> dict:
    base = {
        "record_id": "1",
        "object_id": "OBJ_1",
        "ts_measurement": 1700000000,
        "ts_recorded": 1700000060,
        "t_supply": 60.0,
        "t_return": 50.0,
        "p_supply": 6.0,
        "p_return": 4.0,
    }
    base.update(kwargs)
    return base


def _df(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


# ── Физические границы → NaN ───────────────────────────────────────────────────

def test_out_of_range_to_nan():
    df = _df(_make_row(t_supply=200.0))  # выше 150
    result = clean_sensors(df)
    assert len(result) == 1  # строка остаётся
    assert pd.isna(result.loc[0, "t_supply"])


def test_in_range_stays():
    df = _df(_make_row(t_supply=80.0, p_supply=10.0))
    result = clean_sensors(df)
    assert result.loc[0, "t_supply"] == 80.0
    assert result.loc[0, "p_supply"] == 10.0


def test_negative_pressure_to_nan():
    df = _df(_make_row(p_supply=-1.0))
    result = clean_sensors(df)
    assert pd.isna(result.loc[0, "p_supply"])


# ── Удаление строк ─────────────────────────────────────────────────────────────

def test_drop_row_all_sensors_nan():
    df = _df(_make_row(t_supply=None, t_return=None, p_supply=None, p_return=None))
    result = clean_sensors(df)
    assert len(result) == 0


def test_keep_row_partial_nan():
    df = _df(_make_row(p_return=None))  # только p_return NaN
    result = clean_sensors(df)
    assert len(result) == 1


def test_drop_missing_record_id():
    df = _df(_make_row(record_id=None))
    result = clean_sensors(df)
    assert len(result) == 0


def test_drop_missing_object_id():
    df = _df(_make_row(object_id=None))
    result = clean_sensors(df)
    assert len(result) == 0


def test_drop_missing_ts_recorded():
    df = _df(_make_row(ts_recorded=None))
    result = clean_sensors(df)
    assert len(result) == 0


# ── Дедупликация ───────────────────────────────────────────────────────────────

def test_dedup_by_record_id():
    df = _df(_make_row(record_id="42"), _make_row(record_id="42"))
    result = dedup_sensors(df)
    assert len(result) == 1


def test_dedup_keeps_different_ids():
    df = _df(_make_row(record_id="1"), _make_row(record_id="2"))
    result = dedup_sensors(df)
    assert len(result) == 2


def test_dedup_meta_prefers_non_null_object_type():
    df = pd.DataFrame([
        {"object_id": "OBJ_1", "object_type": None, "facility_type": None, "facility_name": None, "municipality": None, "rso": None},
        {"object_id": "OBJ_1", "object_type": "ЦТП", "facility_type": "ЦТП", "facility_name": "Котельная", "municipality": "МО", "rso": None},
    ])
    result = dedup_meta(df)
    assert len(result) == 1
    assert result.iloc[0]["object_type"] == "ЦТП"


# ── BUG-009: NaT → NaN (не 0) ─────────────────────────────────────────────────

def test_drop_row_ts_recorded_nan_from_invalid_date():
    """BUG-009: строка с ts_recorded=NaN (от невалидной даты) удаляется cleaner-ом.
    Старый _to_unix делал fillna(0) — строки с ts=0 проходили насквозь."""
    df = _df(_make_row(ts_recorded=float("nan")))
    result = clean_sensors(df)
    assert len(result) == 0, "Строка с ts_recorded=NaN должна быть удалена"


def test_drop_row_ts_recorded_zero_not_dropped():
    """ts_recorded=0 (если явно передан) не удаляется cleaner-ом.
    Cleaner проверяет isna(), а не == 0. Удаление ts<=0 — ответственность writer."""
    df = _df(_make_row(ts_recorded=0))
    result = clean_sensors(df)
    # ts=0 технически невалиден, но cleaner его НЕ удаляет (это не NaN)
    # Документируем текущее поведение
    assert len(result) == 1


# ── BUG-011: object_id=pd.NA удаляется cleaner-ом ─────────────────────────────

def test_object_id_na_drops_row():
    """BUG-011: строка с object_id=pd.NA (от пустой ячейки Excel) удаляется.
    До _clean_str — astype(str) давал 'nan', который проходил как валидный."""
    import pandas as pd
    df = pd.DataFrame([_make_row(object_id=pd.NA)])
    result = clean_sensors(df)
    assert len(result) == 0, "Строка с object_id=pd.NA должна быть удалена"


def test_dedup_meta_keeps_different_objects():
    df = pd.DataFrame([
        {"object_id": "OBJ_1", "object_type": "ЦТП", "facility_type": None, "facility_name": None, "municipality": None, "rso": None},
        {"object_id": "OBJ_2", "object_type": "ЦТП", "facility_type": None, "facility_name": None, "municipality": None, "rso": None},
    ])
    result = dedup_meta(df)
    assert len(result) == 2
