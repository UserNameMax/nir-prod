"""Клиент data-service: справочник ЦТП (вход) + публикация меток (выход)."""
from __future__ import annotations

import httpx

from fuzzy import CtpObject

_TIMEOUT = httpx.Timeout(connect=10, read=120, write=30, pool=10)


def fetch_ctp_catalog(base_url: str) -> list[CtpObject]:
    """GET /objects → только ЦТП с непустыми municipality и facility_name."""
    catalog: list[CtpObject] = []
    offset, limit = 0, 5000
    with httpx.Client(base_url=base_url, timeout=_TIMEOUT) as client:
        while True:
            resp = client.get("/objects", params={"offset": offset, "limit": limit})
            resp.raise_for_status()
            payload = resp.json()
            items = payload["items"] if isinstance(payload, dict) else payload
            if not items:
                break
            for o in items:
                if o.get("facility_type") == "ЦТП" and o.get("facility_name") and o.get("municipality"):
                    catalog.append(CtpObject(
                        object_id=str(o["object_id"]),
                        facility_name=str(o["facility_name"]),
                        municipality=str(o["municipality"]),
                    ))
            if len(items) < limit:
                break
            offset += limit
    return catalog


def publish_incidents(base_url: str, records: list[dict]) -> tuple[int, int]:
    """POST /incidents/bulk → (inserted, skipped_duplicates)."""
    if not records:
        return 0, 0
    with httpx.Client(base_url=base_url, timeout=_TIMEOUT) as client:
        resp = client.post("/incidents/bulk", json=records)
        resp.raise_for_status()
        body = resp.json()
    return int(body.get("inserted", 0)), int(body.get("skipped_duplicates", 0))
