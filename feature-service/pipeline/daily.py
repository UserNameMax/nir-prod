"""Этап 2 — сборка дневной базы: агрегаты + погода + календарь.

Перенесено из research `features/03_2_build_daily.ipynb`. В отличие от research,
цель (`t_to_failure`) здесь НЕ строится: метки живут в data-service, а разметку под
горизонт делает training-service. feature-service отдаёт только признаки.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# День считается неполным, если снятых отсчётов меньше этого порога.
LOW_COVERAGE_SAMPLES = 6


def build(features: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    """Приклеить наружную температуру и календарные признаки."""
    df = features.merge(weather, on="date", how="left")

    mon = df["date"].dt.month
    wd = df["date"].dt.weekday
    df["sin_month"] = np.sin(2 * np.pi * mon / 12)
    df["cos_month"] = np.cos(2 * np.pi * mon / 12)
    df["sin_weekday"] = np.sin(2 * np.pi * wd / 7)
    df["cos_weekday"] = np.cos(2 * np.pi * wd / 7)

    df["low_coverage"] = (df["n_samples"] < LOW_COVERAGE_SAMPLES).astype(int)
    return df
