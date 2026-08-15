"""Этап 1 — внутрисуточные агрегаты: 15-мин показания → строка «объект-день».

Перенесено из research `features/03_1_intraday.ipynb`. Физика (Фролов, Кориков):
ночное окно минимального потребления 02–03 против дневного 10–20 — просадка
давления и рост ночного перепада маркируют утечку.
"""
from __future__ import annotations

import pandas as pd

SIGNALS = ["t_supply", "t_return", "p_supply", "p_return", "dp", "dt"]

NIGHT_FROM, NIGHT_TO = 2, 3
DAY_FROM, DAY_TO = 10, 20


def build(sensors: pd.DataFrame) -> pd.DataFrame:
    """Дневные агрегаты по объекту. Вход: object_id, ts_recorded (datetime), 4 датчика."""
    df = sensors.copy()
    df["object_id"] = df["object_id"].astype(str)

    df["dp"] = df["p_supply"] - df["p_return"]   # перепад давления (гидравл. нагрузка)
    df["dt"] = df["t_supply"] - df["t_return"]   # перепад температуры (теплосъём)

    df["date"] = df["ts_recorded"].dt.floor("D")
    hour = df["ts_recorded"].dt.hour
    night = (hour >= NIGHT_FROM) & (hour < NIGHT_TO)
    day = (hour >= DAY_FROM) & (hour < DAY_TO)

    # Маскированные колонки под оконные средние (mean пропустит NaN).
    df["dp_night"] = df["dp"].where(night)
    df["dp_day"] = df["dp"].where(day)
    df["dt_night"] = df["dt"].where(night)
    df["dt_day"] = df["dt"].where(day)
    df["ps_night"] = df["p_supply"].where(night)
    df["ps_day"] = df["p_supply"].where(day)

    agg = {}
    for s in SIGNALS:
        agg[f"{s}_mean"] = (s, "mean")
        agg[f"{s}_std"] = (s, "std")
        agg[f"{s}_min"] = (s, "min")
        agg[f"{s}_max"] = (s, "max")
    # форма распределения
    agg["p_supply_median"] = ("p_supply", "median")
    agg["p_supply_skew"] = ("p_supply", "skew")
    agg["dp_skew"] = ("dp", "skew")
    # ночное / дневное окна
    agg["dp_night"] = ("dp_night", "mean")
    agg["dp_day"] = ("dp_day", "mean")
    agg["dt_night"] = ("dt_night", "mean")
    agg["dt_day"] = ("dt_day", "mean")
    agg["ps_night"] = ("ps_night", "mean")
    agg["ps_day"] = ("ps_day", "mean")
    # контроль покрытия
    agg["n_samples"] = ("ts_recorded", "size")

    g = (df.groupby(["object_id", "date"], observed=True, sort=True)
           .agg(**agg)
           .reset_index())

    # Производные признаки на дневном уровне.
    g["dp_night_ratio"] = g["dp_night"] / g["dp_day"]      # в норме <1, растёт при утечке
    g["dt_night_ratio"] = g["dt_night"] / g["dt_day"]
    g["p_drop_night"] = g["ps_day"] - g["ps_night"]        # ночная просадка давления
    g["p_supply_range"] = g["p_supply_max"] - g["p_supply_min"]
    g["p_supply_min_to_mean"] = g["p_supply_min"] / g["p_supply_mean"]
    g["p_supply_drop_depth_intraday"] = g["p_supply_median"] - g["p_supply_min"]
    g["dp_range"] = g["dp_max"] - g["dp_min"]

    g = g.drop(columns=["ps_night", "ps_day"])
    return g.sort_values(["object_id", "date"]).reset_index(drop=True)
