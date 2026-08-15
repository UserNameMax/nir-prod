"""
Сравнение продакшен-разметчика с черновым (labler/).

Что проверяем: продакшен-ядро (ingest + fuzzy + publish) на ТЕХ ЖЕ входах и ТЕХ ЖЕ
извлечениях LLM воспроизводит разметку черновика ровно. LLM изолируем, переиспользуя
кэш чернового резолвера (`labler/data/resolver_cache.json`) — сравнение детерминированно
и запускается без Ollama.

Пороговое ядро одно и то же → ожидаем 100% паритет. Любое расхождение печатается.

Запуск:  python compare_draft.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import config
import ingest
import publish
from fuzzy import CtpObject, match
from resolve import Resolution

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]                      # .../вкр
LABLER = ROOT / "labler"
META = ROOT / "data" / "objects_meta.parquet"
THRESHOLD = config.FUZZY_THRESHOLD


def load_catalog() -> list[CtpObject]:
    meta = pd.read_parquet(META)
    meta = meta[meta.facility_type == "ЦТП"].dropna(subset=["facility_name", "municipality"])
    return [
        CtpObject(str(r.object_id), str(r.facility_name), str(r.municipality))
        for r in meta.itertuples(index=False)
    ]


def main() -> int:
    incidents = pd.read_csv(LABLER / "data" / "incidents.csv", parse_dates=["d_create", "d_close"])
    incidents["id_cds_claim"] = pd.to_numeric(incidents["id_cds_claim"], errors="coerce")
    incidents = incidents.dropna(subset=["id_cds_claim"])
    incidents["id_cds_claim"] = incidents["id_cds_claim"].astype("int64")

    cache = json.load(open(LABLER / "data" / "resolver_cache.json", encoding="utf-8"))
    catalog = load_catalog()
    print(f"инцидентов: {len(incidents)} | справочник ЦТП: {len(catalog)} | порог: {THRESHOLD}")

    # draft object_id = из resolved.csv (авторитетный выход черновика)
    draft_res = pd.read_csv(LABLER / "data" / "resolved.csv")
    draft_res["id_cds_claim"] = pd.to_numeric(draft_res["id_cds_claim"], errors="coerce").astype("Int64")
    draft_map = {str(int(c)): str(o) for c, o in
                 zip(draft_res.id_cds_claim.dropna(), draft_res.object_id) if pd.notna(o)}

    # прод: прогоняем кэшированные извлечения LLM через продакшен-fuzzy
    resolutions: dict[str, Resolution] = {}
    prod_map: dict[str, str] = {}
    both_agree = both_unres = disagree = prod_only = draft_only = 0
    diffs = []
    for row in incidents.itertuples(index=False):
        cid = str(row.id_cds_claim)
        extracted = str(cache.get(cid, {}).get("llm_extracted", "не найдено"))
        m = match(extracted, str(row.name_mr), catalog, THRESHOLD)
        prod_oid = m.object_id if m else None
        resolutions[cid] = Resolution(prod_oid, extracted, m.score if m else 0.0)
        draft_oid = draft_map.get(cid)
        if prod_oid:
            prod_map[cid] = prod_oid
        if prod_oid and draft_oid:
            if prod_oid == draft_oid:
                both_agree += 1
            else:
                disagree += 1
                diffs.append((cid, extracted, str(row.name_mr), prod_oid, draft_oid))
        elif prod_oid and not draft_oid:
            prod_only += 1
            diffs.append((cid, extracted, str(row.name_mr), prod_oid, "—"))
        elif draft_oid and not prod_oid:
            draft_only += 1
            diffs.append((cid, extracted, str(row.name_mr), "—", draft_oid))
        else:
            both_unres += 1

    total_res_prod = len(prod_map)
    total_res_draft = len(draft_map)
    print("\n── Паритет разрешения ──────────────────────────────")
    print(f"  оба разрешили, object_id совпал:  {both_agree}")
    print(f"  оба НЕ разрешили:                 {both_unres}")
    print(f"  РАСХОЖДЕНИЕ object_id:            {disagree}")
    print(f"  только продакшен разрешил:        {prod_only}")
    print(f"  только черновик разрешил:         {draft_only}")
    agree_rate = both_agree / max(total_res_draft, 1)
    print(f"\n  прод resolved={total_res_prod} | draft resolved={total_res_draft} | "
          f"agreement={agree_rate:.4f}")

    if diffs:
        print("\n── Расхождения (до 20) ─────────────────────────────")
        for cid, ext, mr, p, d in diffs[:20]:
            print(f"  claim={cid} | LLM='{ext}' | {mr} | prod={p} draft={d}")

    # прод publish payload (Incident-записи)
    records = publish.build_incident_records(incidents, resolutions, config.LABEL_SOURCE)
    print(f"\n── Публикация ──────────────────────────────────────")
    print(f"  прод построил Incident-записей: {len(records)} (черновик resolved: {total_res_draft})")
    if records:
        print(f"  пример: {records[0]}")

    ok = (disagree == 0 and prod_only == 0 and draft_only == 0)
    print("\n" + ("✅ ПАРИТЕТ: продакшен воспроизводит черновик ровно."
                  if ok else "⚠️ Есть расхождения — см. выше."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
