"""Слой 4 — объяснение для диспетчера.

Три вещи, и ни одной лишней: интерпретируемый СРОК (AFT), калиброванная
вероятность ДЛЯ ПОКАЗА и сырой суточный профиль давления/температуры.

Калиброванная вероятность сопровождается явной оговоркой: изотоника при слабом
сигнале схлопывается к базовой ставке (BSS≈0), поэтому она годится как «честная
средняя вероятность», но не как основание для порога — порог берётся по рангу
сырого скора (NARRATIVE §9).

SHAP и прочая research-аналитика сюда не входят.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CALIBRATION_NOTE = ("вероятность для ориентира: изотоника при слабом сигнале "
                    "схлопывается к базовой ставке; порог берётся по рангу сырого скора")


def aft_median_days(bundle_aft: dict, baseline_row: pd.DataFrame) -> float | None:
    """Медианный срок до аварии в днях по параметрической AFT."""
    if baseline_row.empty:
        return None
    frame = baseline_row.reindex(columns=bundle_aft["columns"]).fillna(bundle_aft["medians"])
    try:
        return float(bundle_aft["fitter"].predict_median(frame).iloc[0])
    except Exception:
        return None


def object_card(runtime, object_id: str, date: str | None = None) -> dict:
    """Карточка объекта: риск, срок, пороги, ранги, метаданные."""
    daily = runtime.daily
    history = daily[daily["object_id"] == object_id]
    if history.empty:
        return {}

    row = (history[history["date"] == pd.Timestamp(date)] if date else history.tail(1))
    if row.empty:
        row = history.tail(1)
    row = row.iloc[0]

    thresholds = runtime.thresholds
    own = thresholds[thresholds["object_id"] == object_id]
    chronic = runtime.chronic[runtime.chronic["object_id"] == object_id]
    meta = runtime.objects[runtime.objects["object_id"] == object_id]

    return {
        "object_id": object_id,
        "date": row["date"].strftime("%Y-%m-%d"),
        "raw_score": float(row["score"]),
        "calibrated_prob": float(row["calibrated"]),
        "calibration_note": CALIBRATION_NOTE,
        "alert_threshold": float(runtime.bundle.alert_threshold),
        "rank": int(row["rank"]),
        "p75": float(own["p75"].iloc[0]) if len(own) else None,
        "p90": float(own["p90"].iloc[0]) if len(own) else None,
        "chronic_rank": int(chronic["chronic_rank"].iloc[0]) if len(chronic) else None,
        "meta": (meta.iloc[0].where(meta.iloc[0].notna(), None).to_dict()
                 if len(meta) else {}),
    }
