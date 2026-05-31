from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd


def _to_datetime(series: pd.Series) -> pd.Series:
    """Parse datetime column regardless of source format.

    - xlsx/xls (dtype=object): строки или Python datetime → pd.to_datetime
    - xlsb: float (Excel serial days since 1899-12-30) → unit='D'
    """
    # Проверяем первый непустой элемент: если float — xlsb serial date
    sample = series.dropna().iloc[0] if not series.dropna().empty else None
    if isinstance(sample, float):
        return pd.to_datetime(series, unit="D", origin="1899-12-30", errors="coerce")
    return pd.to_datetime(series, errors="coerce")


def _to_unix(series: pd.Series) -> pd.Series:
    """Конвертировать datetime series в unix seconds (float64). NaT → NaN."""
    dt = _to_datetime(series)
    unix = dt.astype("int64") // 10**9
    # iNaT (от NaT) → NaN; результат float64, cleaner удалит NaN-строки
    return unix.where(dt.notna())


def detect_format(df: pd.DataFrame) -> str:
    cols = set(df.columns)
    if "t_forward" in cols or "p_forward" in cols:
        return "B"
    if "T пр" in cols or "ID объекта" in cols:
        return "A"
    return "UNKNOWN"


def normalize_format_a(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "#" in df.columns:
        df = df.drop(columns=["#"])

    if "Наименование объекта" in df.columns and "Наименование котельной" not in df.columns:
        df = df.rename(columns={"Наименование объекта": "Наименование котельной"})

    rename = {
        "ID":                       "record_id",
        "Дата и время показателей": "ts_measurement_dt",
        "T пр":                     "t_supply",
        "T обр":                    "t_return",
        "P пр":                     "p_supply",
        "P обр":                    "p_return",
        "Дата и время записи":      "ts_recorded_dt",
        "ID объекта":               "object_id",
        "Тип ��бъекта":              "object_type",
        "Котельная/ЦТП":            "facility_type",
        "Наименование котельной":   "facility_name",
        "Муниципалитет":            "municipality",
        "РСО":                      "rso",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    for col in ("object_type", "facility_type", "facility_name", "municipality", "rso"):
        if col not in df.columns:
            df[col] = np.nan

    df["ts_recorded"] = _to_unix(df["ts_recorded_dt"])
    df["ts_measurement"] = _to_unix(df["ts_measurement_dt"])
    df["object_id"] = df["object_id"].astype(str)
    df["record_id"] = df["record_id"].astype(str)
    for col in ("t_supply", "t_return", "p_supply", "p_return"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    sensors = df[
        ["record_id", "object_id", "ts_measurement", "t_supply", "t_return", "p_supply", "p_return", "ts_recorded"]
    ].copy()
    meta = df[
        ["object_id", "object_type", "facility_type", "facility_name", "municipality", "rso"]
    ].copy()
    return sensors, meta


def normalize_format_b(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rename = {
        "id":          "record_id",
        "data":        "ts_recorded_dt",
        "t_forward":   "t_supply",
        "t_revers":    "t_return",
        "p_forward":   "p_supply",
        "p_revers":    "p_return",
        "name_koteln": "facility_name",
        "name_mr":     "municipality",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    df["ts_recorded"] = _to_unix(df["ts_recorded_dt"])
    df["ts_measurement"] = df["ts_recorded"]
    df["object_id"] = df["object_id"].astype(str)
    df["record_id"] = df["record_id"].astype(str)
    for col in ("t_supply", "t_return", "p_supply", "p_return"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["object_type"] = np.nan
    df["facility_type"] = np.nan

    for col in ("facility_name", "municipality", "rso"):
        if col not in df.columns:
            df[col] = np.nan

    sensors = df[
        ["record_id", "object_id", "ts_measurement", "t_supply", "t_return", "p_supply", "p_return", "ts_recorded"]
    ].copy()
    meta = df[
        ["object_id", "object_type", "facility_type", "facility_name", "municipality", "rso"]
    ].copy()
    return sensors, meta


def parse_xlsx(path: Path) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Прочитать xlsx или xls, определить формат, нормализовать. None если формат неизвестен."""
    suffix = path.suffix.lower()
    if suffix == ".xls":
        engine = "xlrd"
    elif suffix == ".xlsb":
        engine = "pyxlsb"
    else:
        engine = None
    try:
        raw = pd.read_excel(path, engine=engine, dtype=object)
    except Exception as exc:
        print(f"[parser] failed to read {path.name}: {exc}", flush=True)
        return None
    fmt = detect_format(raw)
    print(f"[parser] {path.name}: format={fmt}, rows={len(raw)}", flush=True)
    if fmt == "A":
        return normalize_format_a(raw)
    if fmt == "B":
        return normalize_format_b(raw)
    print(f"[parser] {path.name}: UNKNOWN format, columns={list(raw.columns)[:10]}", flush=True)
    return None
