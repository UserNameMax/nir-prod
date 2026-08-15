"""
Ingest: Excel тех.нарушений → нормализованные инциденты.

Читает журналы тех.нарушений (формат МО, header=8), нормализует схему,
дедуплицирует по id_cds_claim, делит поток:
  obj_ctp=True                      → кандидаты в аварии ЦТП (размечаются)
  (obj_koteln|obj_ts) & ~obj_ctp    → GO-события (котельные/сети, НЕ размечаются)

Чистая функция от путей к .xlsx — без сети и без записи наружу.
Портирован из чернового `labler/lib/ingester.py`; трансформерная ветка удалена.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

REQUIRED_COLS = [
    "id_cds_claim", "name_mr", "text_message", "t_ov",
    "d_create", "d_doklad", "d_close",
    "obj_koteln", "obj_ctp", "obj_ts",
]


def _parse_float(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val) if pd.notna(val) else None
    m = re.search(r"-?\d+\.?\d*", str(val))
    return float(m.group()) if m else None


def cast_frame(df: pd.DataFrame, source_file: str) -> pd.DataFrame:
    """Нормализует сырой лист Excel к канонической схеме инцидентов."""
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(
            f"{source_file}: не найдены колонки {missing}. "
            f"Доступные: {df.columns.tolist()[:30]}"
        )

    df = df[REQUIRED_COLS].copy()
    df["t_ov"] = df["t_ov"].apply(_parse_float)
    for col in ("d_create", "d_doklad", "d_close"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in ("obj_koteln", "obj_ctp", "obj_ts"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(bool)
    df["id_cds_claim"] = pd.to_numeric(df["id_cds_claim"], errors="coerce")
    df = df.dropna(subset=["id_cds_claim"])
    df["id_cds_claim"] = df["id_cds_claim"].astype("int64")
    df["source_file"] = source_file
    return df


def split_incidents(combined: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Дедуп по id_cds_claim + разделение на CTP-кандидатов и GO-события."""
    combined = combined.drop_duplicates(subset=["id_cds_claim"], keep="last")
    combined = combined.dropna(subset=["text_message", "d_create"])
    incidents = combined[combined["obj_ctp"]].reset_index(drop=True)
    go_events = combined[
        (combined["obj_koteln"] | combined["obj_ts"]) & ~combined["obj_ctp"]
    ].reset_index(drop=True)
    return incidents, go_events


def run(xlsx_paths: list[Path], header_row: int = 8) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Список .xlsx → (incidents_ctp, go_events)."""
    if not xlsx_paths:
        raise FileNotFoundError("Нет .xlsx файлов тех.нарушений")
    frames: list[pd.DataFrame] = []
    for path in xlsx_paths:
        raw = pd.read_excel(path, header=header_row, dtype=object)
        frames.append(cast_frame(raw, Path(path).name))
    combined = pd.concat(frames, ignore_index=True)
    return split_incidents(combined)
