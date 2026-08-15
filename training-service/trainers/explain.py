"""Слой 4 — объяснение: параметрический Log-normal AFT, «срок» до аварии.

Нужен диспетчеру как интерпретируемое время (NARRATIVE §9, рек. 2): в отличие от
скора риска, AFT отдаёт медианный срок в днях. По дискриминации он слабее
нелинейных (C-index ≈0.69 против ≈0.82 у RSF) — берётся ради интерпретируемости,
а не ради ранжирования.

SHAP и прочая research-аналитика в систему НЕ входят — они использовались только
в исследовании.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from lifelines import LogNormalAFTFitter

# Регуляризация: признаков много, объектов мало — без неё фиттер расходится.
PENALIZER = 0.1
MAX_FEATURES = 12


def train(objects: pd.DataFrame, feature_cols: list[str]) -> dict:
    """Обучить Log-normal AFT на object-level кадре.

    Возвращает бандл: фиттер, использованные колонки и медианы для импутации
    (на инференсе объект может прийти с пропусками).
    """
    cols = [c for c in feature_cols if c in objects.columns][:MAX_FEATURES]
    frame = objects[cols].copy()
    medians = frame.median(numeric_only=True)
    frame = frame.fillna(medians)

    # колонки без разброса ломают подгонку
    usable = [c for c in cols if frame[c].std() > 1e-9]
    frame = frame[usable]

    frame["duration"] = objects["duration"].values
    frame["event"] = objects["event"].astype(int).values

    fitter = LogNormalAFTFitter(penalizer=PENALIZER)
    fitter.fit(frame, duration_col="duration", event_col="event")

    return {"fitter": fitter, "columns": usable,
            "medians": medians[usable].to_dict()}


def predict_median_days(bundle: dict, objects: pd.DataFrame) -> np.ndarray:
    """Медианный срок до аварии в днях (то, что показывается диспетчеру)."""
    frame = objects.reindex(columns=bundle["columns"]).fillna(bundle["medians"])
    return bundle["fitter"].predict_median(frame).values
