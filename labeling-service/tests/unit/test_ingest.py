"""Unit-тесты ingest (нормализация схемы, дедуп, разделение CTP/GO)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

import ingest

sys.path.insert(0, str(Path(__file__).parent.parent / "fixtures"))
from make_xlsx import write_sample  # noqa: E402


def _raw_row(**kw):
    base = dict(id_cds_claim=1, name_mr="Тестовск", text_message="txt", t_ov="-10.5",
                d_create="2026-01-05 10:00", d_doklad="2026-01-05 10:30",
                d_close="2026-01-05 14:00", obj_koteln=0, obj_ctp=1, obj_ts=0)
    base.update(kw)
    return base


def test_cast_parses_types():
    df = ingest.cast_frame(pd.DataFrame([_raw_row()]), "f.xlsx")
    assert df.loc[0, "t_ov"] == -10.5           # запятая → float
    assert df.loc[0, "obj_ctp"] is True or bool(df.loc[0, "obj_ctp"])
    assert pd.notna(df.loc[0, "d_create"])
    assert df.loc[0, "id_cds_claim"] == 1
    assert df.loc[0, "source_file"] == "f.xlsx"


def test_cast_missing_columns_raises():
    with pytest.raises(ValueError):
        ingest.cast_frame(pd.DataFrame([{"id_cds_claim": 1}]), "bad.xlsx")


def test_split_dedup_and_ctp_go():
    df = ingest.cast_frame(pd.DataFrame([
        _raw_row(id_cds_claim=1, obj_ctp=1),
        _raw_row(id_cds_claim=1, obj_ctp=1),                       # дубль
        _raw_row(id_cds_claim=2, obj_ctp=0, obj_koteln=1),        # GO
        _raw_row(id_cds_claim=3, obj_ctp=1, text_message=None),   # без текста → drop
    ]), "f.xlsx")
    incidents, go = ingest.split_incidents(df)
    assert set(incidents.id_cds_claim) == {1}       # дубль схлопнут, №3 отброшен
    assert set(go.id_cds_claim) == {2}


def test_run_reads_xlsx_header8(tmp_path):
    xlsx = write_sample(tmp_path / "s.xlsx")
    incidents, go = ingest.run([xlsx], header_row=8)
    assert set(incidents.id_cds_claim) == {1001, 1002}   # 1001 дубль схлопнут
    assert set(go.id_cds_claim) == {2001}
