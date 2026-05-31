from __future__ import annotations
import numpy as np
import pandas as pd

SENSOR_COLS = ["t_supply", "t_return", "p_supply", "p_return"]

BOUNDS: dict[str, tuple[float, float]] = {
    "t_supply": (0.0, 150.0),
    "t_return": (0.0, 150.0),
    "p_supply": (0.0, 25.0),
    "p_return": (0.0, 25.0),
}


def clean_sensors(df: pd.DataFrame) -> pd.DataFrame:
    # Обязательные поля
    df = df.dropna(subset=["record_id", "object_id", "ts_recorded"])

    # Числовые датчики
    for col in SENSOR_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Физические границы → NaN
    for col, (lo, hi) in BOUNDS.items():
        mask = df[col].notna() & ~df[col].between(lo, hi)
        df.loc[mask, col] = np.nan

    # Строки где все 4 датчика NaN — бесполезны
    all_nan = df[SENSOR_COLS].isna().all(axis=1)
    df = df[~all_nan]

    return df.reset_index(drop=True)


def dedup_sensors(df: pd.DataFrame) -> pd.DataFrame:
    """Дедупликация внутри одной выгрузки по record_id."""
    return df.drop_duplicates(subset=["record_id"]).reset_index(drop=True)


def dedup_meta(df: pd.DataFrame) -> pd.DataFrame:
    """Дедупликация по object_id — записи с object_type приоритетнее."""
    return (
        df.sort_values("object_type", na_position="last")
        .drop_duplicates(subset=["object_id"], keep="first")
        .reset_index(drop=True)
    )
