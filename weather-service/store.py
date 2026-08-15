"""Локальный кэш погоды: weather_daily.parquet.

После первого ingest сервис отдаёт T_out без обращения во внешний мир.
Upsert по дате — повторная загрузка того же периода не создаёт дублей,
свежие значения перезаписывают старые (архив может уточняться задним числом).
"""
from __future__ import annotations
import os
import threading
from pathlib import Path

import pandas as pd

_lock = threading.Lock()

COLUMNS = ["date", "t_out_mean", "t_out_min", "t_out_max", "heating_degree"]


def _path(weather_dir: str) -> str:
    return str(Path(weather_dir) / "weather_daily.parquet")


def _empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object" if c == "date" else "float64")
                         for c in COLUMNS})


def _read(weather_dir: str) -> pd.DataFrame:
    path = _path(weather_dir)
    if not os.path.exists(path):
        return _empty()
    return pd.read_parquet(path)


def upsert(weather_dir: str, rows: list[dict]) -> tuple[int, int]:
    """Записать/обновить дни. Возвращает (добавлено новых, обновлено существующих)."""
    if not rows:
        return 0, 0

    incoming = pd.DataFrame(rows)[COLUMNS]
    incoming["date"] = incoming["date"].astype(str)
    incoming = incoming.drop_duplicates(subset=["date"], keep="last")

    with _lock:
        existing = _read(weather_dir)
        known = set(existing["date"]) if not existing.empty else set()
        added = int((~incoming["date"].isin(known)).sum())
        updated = len(incoming) - added

        merged = (pd.concat([existing, incoming], ignore_index=True)
                    .drop_duplicates(subset=["date"], keep="last")
                    .sort_values("date")
                    .reset_index(drop=True))

        path = _path(weather_dir)
        Path(weather_dir).mkdir(parents=True, exist_ok=True)
        merged.to_parquet(path + ".tmp", index=False)
        os.replace(path + ".tmp", path)

    return added, updated


def read(weather_dir: str, date_from: str | None = None,
         date_to: str | None = None) -> list[dict]:
    """Ряд дневной погоды за период. Даты ISO — сравнение лексикографическое."""
    df = _read(weather_dir)
    if df.empty:
        return []

    if date_from:
        df = df[df["date"] >= date_from]
    if date_to:
        df = df[df["date"] <= date_to]

    df = df.sort_values("date")
    return df.where(df.notna(), None).to_dict(orient="records")


def health(weather_dir: str) -> dict:
    df = _read(weather_dir)
    if df.empty:
        return {"cached_days": 0, "date_from": None, "date_to": None}
    return {
        "cached_days": len(df),
        "date_from": df["date"].min(),
        "date_to": df["date"].max(),
    }


def missing_days(weather_dir: str, date_from: str, date_to: str) -> list[str]:
    """Дни периода, которых нет в кэше — чтобы не ходить наружу без нужды."""
    wanted = pd.date_range(date_from, date_to, freq="D").strftime("%Y-%m-%d")
    known = set(_read(weather_dir)["date"])
    return [d for d in wanted if d not in known]
