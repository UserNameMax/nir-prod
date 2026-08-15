"""Слои 1-2: хронический watch-list и острый дневной скор.

Скоры считаются один раз при загрузке бандла и кэшируются: матрица признаков
статична между пересчётами, а слой решений (decision.py) многократно пересобирает
наряды поверх этого кэша.

Порог берётся из бандла и применяется к СЫРОМУ скору (по рангу). Калиброванная
вероятность считается рядом — она только для показа (NARRATIVE §9).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from loader import BASELINE_DAYS, Bundle


def score_daily(bundle: Bundle, features: pd.DataFrame) -> pd.DataFrame:
    """Дневной острый скор + калиброванная вероятность + ранг внутри дня."""
    if features.empty:
        return pd.DataFrame(columns=["object_id", "date", "score",
                                     "calibrated", "rank"])

    matrix = features[bundle.feature_columns]
    raw = bundle.acute.predict_proba(matrix)[:, 1]

    scored = features[["object_id", "date"]].copy()
    scored["score"] = raw
    scored["calibrated"] = bundle.calibrator.transform(raw)
    scored["rank"] = (scored.groupby("date")["score"]
                            .rank(ascending=False, method="min").astype(int))
    return scored.sort_values(["object_id", "date"]).reset_index(drop=True)


def object_baseline(features: pd.DataFrame, feature_columns: list[str],
                    baseline_days: int = BASELINE_DAYS) -> pd.DataFrame:
    """Object-level срез: медиана признаков за первые дни наблюдения объекта.

    Тот же принцип, что при обучении хроники — иначе скор поедет относительно
    того, на чём модель училась.
    """
    frame = features.sort_values(["object_id", "date"])
    first = frame.groupby("object_id")["date"].transform("min")
    window = frame[frame["date"] < first + pd.Timedelta(days=baseline_days)]

    baseline = (window.groupby("object_id")[feature_columns]
                      .median(numeric_only=True)
                      .reset_index())
    return baseline


def score_chronic(bundle: Bundle, baseline: pd.DataFrame) -> pd.DataFrame:
    """Хронический риск объекта (Слой 1) — watch-list для планового ТО.

    На вход идёт готовый object-level срез: тот же кадр нужен слою объяснения
    (AFT), поэтому считается один раз и переиспользуется.
    """
    if baseline.empty:
        return pd.DataFrame(columns=["object_id", "chronic_score", "chronic_rank"])

    prep = bundle.chronic.named_steps["prep"]
    model = bundle.chronic.named_steps["model"]
    scores = model.predict(prep.transform(baseline[bundle.feature_columns]))

    out = baseline[["object_id"]].copy()
    out["chronic_score"] = scores
    out["chronic_rank"] = out["chronic_score"].rank(ascending=False, method="min").astype(int)
    return out.sort_values("chronic_rank").reset_index(drop=True)


def object_thresholds(scored: pd.DataFrame) -> pd.DataFrame:
    """Пообъектные уровни «обычного» и «высокого» риска по дневным скорам."""
    grouped = scored.groupby("object_id")["score"]
    return pd.DataFrame({
        "p75": grouped.quantile(0.75),
        "p90": grouped.quantile(0.90),
    }).reset_index()


def global_thresholds(scored: pd.DataFrame, alert_threshold: float) -> dict:
    scores = scored["score"].values
    return {
        "p50": float(np.quantile(scores, 0.50)),
        "p75": float(np.quantile(scores, 0.75)),
        "p90": float(np.quantile(scores, 0.90)),
        "alert_threshold": float(alert_threshold),
    }
