"""Кэш дневной матрицы признаков.

Матрица считается по всей истории сразу (междневные окна и каузальный fit требуют
предыстории) и хранится в parquet. Запрос за период режет уже посчитанный кадр —
пересчитывать окна на каждый запрос нельзя: усечённая история дала бы другие
значения slope/robust_z, чем при обучении.
"""
from __future__ import annotations
import os
import threading
from pathlib import Path

import pandas as pd

import schema

_lock = threading.Lock()


def _path(cache_dir: str) -> str:
    return str(Path(cache_dir) / "daily_features.parquet")


def save(cache_dir: str, matrix: pd.DataFrame) -> int:
    with _lock:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        path = _path(cache_dir)
        matrix.to_parquet(path + ".tmp", index=False)
        os.replace(path + ".tmp", path)
    return len(matrix)


def load(cache_dir: str) -> pd.DataFrame | None:
    path = _path(cache_dir)
    if not os.path.exists(path):
        return None
    return pd.read_parquet(path)


def read(cache_dir: str, date_from: str | None = None, date_to: str | None = None,
         object_ids: list[str] | None = None) -> pd.DataFrame:
    matrix = load(cache_dir)
    if matrix is None:
        return pd.DataFrame(columns=[*schema.KEYS, *schema.FEATURES])

    if date_from:
        matrix = matrix[matrix["date"] >= pd.Timestamp(date_from)]
    if date_to:
        matrix = matrix[matrix["date"] <= pd.Timestamp(date_to)]
    if object_ids:
        matrix = matrix[matrix["object_id"].isin(object_ids)]
    return matrix


def health(cache_dir: str) -> dict:
    matrix = load(cache_dir)
    if matrix is None or matrix.empty:
        return {"cached_object_days": 0, "cached_objects": 0,
                "date_from": None, "date_to": None}
    return {
        "cached_object_days": len(matrix),
        "cached_objects": int(matrix["object_id"].nunique()),
        "date_from": str(matrix["date"].min().date()),
        "date_to": str(matrix["date"].max().date()),
    }
