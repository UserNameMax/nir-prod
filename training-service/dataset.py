"""Сборка обучающей выборки: разметка горизонта, temporal split, object-level.

Разметка (`t_to_failure`) строится ЗДЕСЬ из аварий data-service — в research она
приходила уже посчитанной в сыром паркете. Единица анализа — «объект-день»
(unit C по NARRATIVE §2): дискретное время, факторизация правдоподобия, НЕ
псевдорепликация.

Split — ТОЛЬКО temporal (чистая функция от даты). Object-split из research
(`split_map.parquet`) в production не используется: он отвечал на вопрос
«обобщается ли на новые объекты», а операционно важен форкаст (NARRATIVE §7),
и он не требует внешнего файла-карты.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZON_DAYS = 30
# Реконструкция object-level (unit A) — параметры из research harness/data.py.
# BASELINE_DAYS поднят с 14 до 30: каузальному fit температурного графика нужно
# >= 15 наблюдений (feature-service CURVE_MIN_PTS), поэтому на 14-дневном срезе
# физика (dt_vs_expected, t_supply_vs_curve_slope_*) была пуста у ВСЕХ объектов и
# object-level модели её не видели. Значение обязано совпадать с
# ml-service/scoring.BASELINE_DAYS — иначе train/serve skew.
BASELINE_DAYS = 30
MERGE_GAP_DAYS = 7


def add_target(features: pd.DataFrame, incidents: pd.DataFrame) -> pd.DataFrame:
    """Добавить `t_to_failure` (часы до ближайшей будущей аварии) и `y`.

    Отсчёт ведётся от КОНЦА объект-дня: в research цель бралась как минимум по
    15-минутным строкам дня, а он достигается на последней строке. Авария внутри
    самого дня даёт малое положительное значение (день остаётся «предаварийным»).
    NaN — аварии впереди нет; трактуется как отрицательный класс.
    """
    df = features.copy()
    df["object_id"] = df["object_id"].astype(str)
    df["date"] = pd.to_datetime(df["date"])

    if incidents.empty:
        df["t_to_failure"] = np.nan
        df["y"] = 0
        return df

    day_start = df["date"]
    day_end = day_start + pd.Timedelta(days=1)

    left = pd.DataFrame({
        "object_id": df["object_id"].values,
        "_start": day_start.values,
        "_end": day_end.values,
        "_row": np.arange(len(df)),
    }).sort_values("_start")

    right = (incidents[["object_id", "incident_ts"]]
             .dropna()
             .sort_values("incident_ts")
             .rename(columns={"incident_ts": "_next"}))

    # первая авария объекта, начавшаяся не раньше начала дня
    merged = pd.merge_asof(left, right, left_on="_start", right_on="_next",
                           by="object_id", direction="forward")

    hours = (merged["_next"] - merged["_end"]).dt.total_seconds() / 3600.0
    # авария внутри самого дня → часы отрицательны; оставляем малым положительным,
    # чтобы день попал в предаварийное окно (совпадает с минимумом по строкам дня)
    hours = hours.where(hours > 0, other=np.where(merged["_next"].notna(), 0.01, np.nan))

    ordered = pd.Series(hours.values, index=merged["_row"].values).sort_index()
    df["t_to_failure"] = ordered.values
    df["y"] = (df["t_to_failure"] <= HORIZON_DAYS * 24).fillna(False).astype(int)
    return df


def temporal_split(df: pd.DataFrame, val_start: str | None = None,
                   test_start: str | None = None) -> pd.DataFrame:
    """Разметить split по дате: train < val_start <= val < test_start <= test.

    Без cutoffs действует правило по умолчанию: последний полный месяц данных —
    test, предыдущий — val, остальное — train. Это делает rolling-переобучение
    (борьба с дрейфом, NARRATIVE §10) чистой функцией от календаря.
    """
    df = df.copy()
    if val_start is None or test_start is None:
        auto_val, auto_test = default_cutoffs(df["date"])
        val_start = val_start or auto_val
        test_start = test_start or auto_test

    val_ts, test_ts = pd.Timestamp(val_start), pd.Timestamp(test_start)
    if val_ts >= test_ts:
        raise ValueError("val_start должен быть раньше test_start")

    df["split"] = np.select(
        [df["date"] < val_ts, df["date"] < test_ts],
        ["train", "val"],
        default="test",
    )
    return df


def default_cutoffs(dates: pd.Series) -> tuple[str, str]:
    """Границы по умолчанию: test = последний полный месяц, val = предыдущий."""
    last = pd.Timestamp(dates.max())
    test_start = (last.replace(day=1) - pd.offsets.MonthBegin(0))
    # если последний месяц неполный, отступаем на месяц назад
    if last.day < 28:
        test_start = test_start - pd.offsets.MonthBegin(1)
    val_start = test_start - pd.offsets.MonthBegin(1)
    return val_start.strftime("%Y-%m-%d"), test_start.strftime("%Y-%m-%d")


def splits(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (df[df.split == "train"], df[df.split == "val"], df[df.split == "test"])


def object_level(df: pd.DataFrame, feature_cols: list[str],
                 baseline_days: int = BASELINE_DAYS,
                 merge_gap: int = MERGE_GAP_DAYS) -> pd.DataFrame:
    """Object-level (unit A) кадр для survival-моделей: одна строка на объект.

    Время до ПЕРВОЙ аварии + baseline-признаки (медиана за первые `baseline_days`
    дней, строго ДО первого события → без утечки). Перенесено из research
    harness/data.py: события реконструируются из t_to_failure, близкие сливаются.
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])

    known = df.loc[df["t_to_failure"].notna(), ["object_id", "date", "t_to_failure"]].copy()
    known["fail_day"] = (known["date"]
                         + pd.to_timedelta(known["t_to_failure"], unit="h")).dt.floor("D")

    def _merge(days) -> list:
        out = []
        for d in sorted(pd.unique(days)):
            if not out or (d - out[-1]) / np.timedelta64(1, "D") > merge_gap:
                out.append(d)
        return out

    first_event = (known.groupby("object_id")["fail_day"]
                        .apply(lambda s: _merge(s)[0]).to_dict()) if len(known) else {}
    entry = df.groupby("object_id")["date"].min()
    last = df.groupby("object_id")["date"].max()
    cols = [c for c in feature_cols if c in df.columns]

    rows = []
    for oid, g in df.groupby("object_id"):
        start = entry[oid]
        event_day = first_event.get(oid)
        upper = start + pd.Timedelta(days=baseline_days)
        if event_day is not None:
            upper = min(upper, event_day)

        window = g[(g["date"] >= start) & (g["date"] < upper)]
        if window.empty:
            window = g.iloc[:1]

        end = event_day if event_day is not None else last[oid]
        duration = (end - start) / np.timedelta64(1, "D")
        rows.append({
            "object_id": oid,
            "split": g["split"].iloc[0] if "split" in g.columns else "train",
            "duration": max(float(duration), 1.0),
            "event": 1 if event_day is not None else 0,
            **window[cols].median(numeric_only=True).to_dict(),
        })
    return pd.DataFrame(rows)
