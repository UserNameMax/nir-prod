"""Этап 0 — очистка сырья датчиков перед агрегацией.

Перенесено из research `features/01_dedup.ipynb`. Без этого шага дневные
агрегаты считаются по «грязному» потоку, и физика набора признаков рушится:
вся она построена на просадках давления (`p_drop_night`, `dp`,
`p_supply_drop_depth_intraday`, `skew`), а миллионы нулей от отключённых
датчиков выглядят как настоящие обвалы давления.

Три шага, ровно как в research:
  1. отбросить строки с битой меткой времени (год < 2025);
  2. вывести физически невозможные значения в NaN — ВКЛЮЧАЯ НУЛИ:
     ноль давления/температуры означает «датчик offline», а не измерение;
  3. схлопнуть дубли по (object_id, ts) усреднением (mean пропускает NaN).

Ingestion-service чистит мягче (t ∈ [0,150], p ∈ [0,25]) и дедуплицирует по
`record_id` — одно и то же измерение из перекрывающихся выгрузок приходит с
разными record_id и дубли переживают приём. Поэтому очистка нужна здесь.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Год, раньше которого метка времени считается битой (у таких строк в источнике
# в поля датчиков попадал сырой unix-таймстемп).
MIN_YEAR = 2025

# Физические границы: значение вне диапазона → NaN. Нижние границы намеренно
# выше нуля — нулевое давление/температура физически невозможны на работающем ЦТП.
BOUNDS = {
    "t_supply": (1.0, 150.0),
    "t_return": (1.0, 150.0),
    "p_supply": (0.1, 40.0),
    "p_return": (0.1, 40.0),
}

SENSORS = tuple(BOUNDS)


def run(sensors: pd.DataFrame) -> pd.DataFrame:
    """Очистить поток измерений. Вход/выход: object_id, ts_recorded, 4 датчика."""
    df = sensors
    if df.empty:
        return df

    df = _drop_broken_timestamps(df)
    df = _bounds_to_nan(df)
    return _dedup(df)


def _drop_broken_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["ts_recorded"].dt.year >= MIN_YEAR]


def _bounds_to_nan(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col, (low, high) in BOUNDS.items():
        if col in df.columns:
            outside = (df[col] < low) | (df[col] > high)
            df.loc[outside, col] = np.nan
    return df


def _dedup(df: pd.DataFrame) -> pd.DataFrame:
    """Одна строка на (object_id, ts_measurement); дубли усредняются.

    Ключ — момент ИЗМЕРЕНИЯ, а не записи в систему: одно и то же физическое
    показание попадает в перекрывающиеся выгрузки с разным `ts_recorded`, и
    дедуп по времени записи такие дубли не схлопывает (на боевых данных
    разница 49.1 млн против 43.1 млн строк). `ts_recorded` берётся первым —
    он задаёт сутки и часовые окна на следующем этапе.
    """
    key = "ts_measurement" if "ts_measurement" in df.columns else "ts_recorded"
    present = [c for c in SENSORS if c in df.columns]

    grouped = df.groupby(["object_id", key], observed=True, sort=False)
    if len(grouped) == len(df):
        return df                       # дублей нет — не пересобираем кадр

    agg = {c: "mean" for c in present}
    if key != "ts_recorded":
        agg["ts_recorded"] = "first"
    return grouped.agg(agg).reset_index()
