"""Unit-тесты publish (сборка Incident-записей)."""
from __future__ import annotations

import pandas as pd

import publish
from resolve import Resolution


def _incidents():
    return pd.DataFrame([
        dict(id_cds_claim=1, d_create=pd.Timestamp("2026-01-05 10:00"),
             d_close=pd.Timestamp("2026-01-05 14:00")),
        dict(id_cds_claim=2, d_create=pd.Timestamp("2026-01-06 09:00"), d_close=pd.NaT),
        dict(id_cds_claim=3, d_create=pd.NaT, d_close=pd.NaT),   # без открытия → skip
    ])


def test_only_resolved_with_open_time():
    res = {
        "1": Resolution("100", "ЦТП-1", 100.0),
        "2": Resolution(None, "не найдено", 0.0),     # не разрешён → skip
        "3": Resolution("300", "ЦТП-3", 100.0),       # нет d_create → skip
    }
    recs = publish.build_incident_records(_incidents(), res, source="тех.нарушения")
    assert len(recs) == 1
    r = recs[0]
    assert r["incident_id"] == "1" and r["object_id"] == "100"
    assert r["incident_ts"] == int(pd.Timestamp("2026-01-05 10:00").timestamp())
    assert r["close_ts"] == int(pd.Timestamp("2026-01-05 14:00").timestamp())
    assert r["source"] == "тех.нарушения"


def test_close_ts_none_when_not_closed():
    res = {"2": Resolution("200", "ЦТП-2", 100.0)}
    recs = publish.build_incident_records(_incidents(), res, source="s")
    got = [r for r in recs if r["incident_id"] == "2"]
    assert got and got[0]["close_ts"] is None
