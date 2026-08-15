"""
Publish: разрешённые инциденты → записи Incident для data-service.

Контракт метки (data-service `Incident`):
  incident_id : str        уникальный id аварии (= id_cds_claim)
  object_id   : str        разрешённый ЦТП
  incident_ts : int        unix seconds — ОТКРЫТИЕ (d_create), якорь времени аварии
  close_ts    : int | None закрытие (d_close), None если не закрыта
  source      : str        источник метки
"""
from __future__ import annotations

import pandas as pd

from resolve import Resolution


def _epoch(ts) -> int | None:
    if ts is None or pd.isna(ts):
        return None
    return int(pd.Timestamp(ts).timestamp())


def build_incident_records(
    incidents: pd.DataFrame,
    resolutions: dict[str, Resolution],
    source: str,
) -> list[dict]:
    """Только разрешённые события → payload для POST /incidents/bulk."""
    records: list[dict] = []
    for row in incidents.itertuples(index=False):
        claim_id = str(row.id_cds_claim)
        res = resolutions.get(claim_id)
        if res is None or not res.resolved:
            continue
        ts_open = _epoch(getattr(row, "d_create", None))
        if ts_open is None:
            continue  # без времени открытия метка бесполезна
        records.append({
            "incident_id": claim_id,
            "object_id": str(res.object_id),
            "incident_ts": ts_open,
            "close_ts": _epoch(getattr(row, "d_close", None)),
            "source": source,
        })
    return records
