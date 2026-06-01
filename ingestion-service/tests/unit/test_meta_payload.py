"""
Регрессионные тесты для конвертации meta DataFrame в JSON-payload.

BUG-001: формат B не заполняет object_type/facility_type → np.nan в DataFrame.
df.to_dict() превращает NaN в float('nan'). json.dumps падает с ValueError.
Фикс: meta.astype(object).where(meta.notna(), other=None) перед to_dict().
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from pipeline.parser import normalize_format_b
from pipeline.cleaner import dedup_meta
from tests.fixtures.make_xlsx import make_format_b


def _meta_to_payload(meta: pd.DataFrame) -> list[dict]:
    """Та же логика что в main.py — конвертация с защитой от NaN."""
    return meta.astype(object).where(meta.notna(), other=None).to_dict(orient="records")


def _meta_to_payload_buggy(meta: pd.DataFrame) -> list[dict]:
    """Воспроизводит баг — без astype(object)."""
    return meta.where(meta.notna(), other=None).to_dict(orient="records")


# ── BUG-001 воспроизведение и фикс ────────────────────────────────────────────

def test_meta_nan_to_none_format_b(tmp_path):
    """
    BUG-001: format B не имеет object_type/facility_type → NaN.
    После фикса конвертация в payload не содержит float NaN.
    """
    xlsx = tmp_path / "b.xlsx"
    make_format_b(xlsx, rows=4)
    raw = pd.read_excel(xlsx)
    _, meta = normalize_format_b(raw)
    meta = dedup_meta(meta)

    payload = _meta_to_payload(meta)

    for row in payload:
        for key, val in row.items():
            assert not (isinstance(val, float) and math.isnan(val)), \
                f"Field '{key}' contains NaN in payload"


def test_meta_nan_to_none_is_json_serializable(tmp_path):
    """После фикса payload сериализуется в JSON без ошибок."""
    xlsx = tmp_path / "b.xlsx"
    make_format_b(xlsx, rows=4)
    raw = pd.read_excel(xlsx)
    _, meta = normalize_format_b(raw)

    payload = _meta_to_payload(meta)

    # Не должно бросать ValueError
    result = json.dumps(payload)
    assert "NaN" not in result


def test_meta_nan_bug_reproduced(tmp_path):
    """
    Подтверждаем что баг реально существовал — без фикса json.dumps падает.
    """
    xlsx = tmp_path / "b.xlsx"
    make_format_b(xlsx, rows=2)
    raw = pd.read_excel(xlsx)
    _, meta = normalize_format_b(raw)

    buggy_payload = _meta_to_payload_buggy(meta)

    # FastAPI использует allow_nan=False — воспроизводим то же поведение
    with pytest.raises(ValueError, match="not JSON compliant"):
        json.dumps(buggy_payload, allow_nan=False)


def test_meta_nan_to_none_mixed(tmp_path):
    """
    DataFrame с частично заполненными полями:
    некоторые строки имеют object_type, другие — NaN.
    Заполненные поля сохраняются, NaN → None.
    """
    meta = pd.DataFrame([
        {"object_id": "OBJ_1", "object_type": "ЦТП",  "facility_type": "МКД",
         "facility_name": "Котельная", "municipality": "МО", "rso": "РСО"},
        {"object_id": "OBJ_2", "object_type": np.nan,  "facility_type": np.nan,
         "facility_name": np.nan, "municipality": np.nan, "rso": np.nan},
    ])

    payload = _meta_to_payload(meta)

    assert payload[0]["object_type"] == "ЦТП"
    assert payload[0]["facility_name"] == "Котельная"
    assert payload[1]["object_type"] is None
    assert payload[1]["facility_name"] is None


def test_null_object_id_filtered_before_bulk(tmp_path):
    """BUG-011: строки с object_id=pd.NA не попадают в payload для /objects/bulk.
    Pydantic требует str для object_id — None вызывал 422 Unprocessable Entity."""
    meta = pd.DataFrame([
        {"object_id": "OBJ_1", "object_type": "ТИ", "facility_type": "Котельная",
         "facility_name": "Тест", "municipality": "МО", "rso": None},
        {"object_id": pd.NA,   "object_type": None, "facility_type": None,
         "facility_name": None, "municipality": None, "rso": None},
    ])
    # Фильтрация как в main.py перед POST /objects/bulk
    meta_clean = meta.dropna(subset=["object_id"])
    payload = _meta_to_payload(meta_clean)

    assert len(payload) == 1, "Строка с pd.NA object_id должна быть отфильтрована"
    assert payload[0]["object_id"] == "OBJ_1"


def test_meta_nan_none_value_preserved(tmp_path):
    """Уже существующие None не превращаются во что-то другое."""
    meta = pd.DataFrame([
        {"object_id": "OBJ_1", "object_type": None, "facility_type": None,
         "facility_name": "Котельная", "municipality": None, "rso": None},
    ])

    payload = _meta_to_payload(meta)

    assert payload[0]["object_type"] is None
    assert payload[0]["facility_name"] == "Котельная"
