"""Слои 2-3: превращение дневного скора в НАРЯД на осмотр.

Семантика перенесена из research `harness/triggers.py` — та же, по которой
training-service выбирал профиль по κ*. Здесь она применяется на инференсе.

Два принципиальных момента (NARRATIVE §10, Принцип 2 и §11):
  * алерт — не разовый выброс, а устойчивость (persist-N или EWMA);
  * серия алертов объекта в пределах cooldown = ОДИН наряд, а не наряд в день:
    открытая заявка не переоткрывается ежедневно, и стоимость считается по нарядам.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_COOLDOWN_DAYS = 14


def _ordered(frame: pd.DataFrame) -> np.ndarray:
    return frame.sort_values(["object_id", "date"]).index.values


def persist_mask(frame: pd.DataFrame, thr: float, n: int) -> pd.Series:
    """Алерт, когда скор выше порога на N подряд идущих НАБЛЮДЕНИЯХ объекта.

    Именно наблюдениях, а не календарных днях: данные разрежены, у большинства
    объектов в ряду есть разрывы.
    """
    idx = _ordered(frame)
    ordered = frame.loc[idx]
    above = ordered["score"].values >= thr
    oid = ordered["object_id"].values

    prev_above = np.concatenate([[False], above[:-1]])
    same_obj = np.concatenate([[False], oid[1:] == oid[:-1]])
    start = above & ~(same_obj & prev_above)
    run_id = np.cumsum(start)
    cum = pd.Series(above.astype(int)).groupby(run_id).cumsum().values

    return pd.Series(above & (cum >= n), index=idx).reindex(frame.index)


def ewma_mask(frame: pd.DataFrame, thr: float, span: int) -> pd.Series:
    """Порог по EWMA-сглаженному скору — гасит одиночные всплески."""
    idx = _ordered(frame)
    ordered = frame.loc[idx]
    smoothed = ordered.groupby("object_id")["score"].transform(
        lambda s: s.ewm(span=span, adjust=False).mean())
    return (smoothed >= thr).reindex(frame.index)


def build_mask(frame: pd.DataFrame, profile: dict, thr: float) -> pd.Series:
    """Маска алертов по профилю триггера из trigger_config."""
    kind = profile.get("type", "baseline")
    if kind == "persist":
        return persist_mask(frame, thr, int(profile["n"]))
    if kind == "ewma":
        return ewma_mask(frame, thr, int(profile["span"]))
    # baseline и gate различаются только последующим гейтингом
    return frame["score"] >= thr


def to_orders(frame: pd.DataFrame, mask: pd.Series,
              cooldown_days: int = DEFAULT_COOLDOWN_DAYS) -> pd.DataFrame:
    """Схлопнуть алерт-дни в наряды: серия внутри cooldown = один наряд.

    Возвращает по строке на наряд: когда открыт, когда последний алерт, пик скора.
    """
    fired = frame.loc[mask.reindex(frame.index).fillna(False).values]
    if fired.empty:
        return pd.DataFrame(columns=["object_id", "opened_at", "last_alert_at",
                                     "alert_days", "peak_score"])

    fired = fired.sort_values(["object_id", "date"]).copy()
    gap = fired.groupby("object_id")["date"].diff().dt.days
    fired["_episode"] = (gap.isna() | (gap > cooldown_days)).cumsum()

    orders = (fired.groupby(["object_id", "_episode"])
                   .agg(opened_at=("date", "min"),
                        last_alert_at=("date", "max"),
                        alert_days=("date", "size"),
                        peak_score=("score", "max"))
                   .reset_index()
                   .drop(columns="_episode"))
    return orders.sort_values("peak_score", ascending=False).reset_index(drop=True)


def queue(scored: pd.DataFrame, profile: dict, thr: float, *,
          date: str | None = None, chronic_top: set | None = None,
          cooldown_days: int = DEFAULT_COOLDOWN_DAYS) -> pd.DataFrame:
    """Очередь нарядов: триггер → наряды → (опц.) гейтинг по хронике.

    `date` фильтрует уже собранные наряды: наряд показывается, если он открыт не
    позже этой даты и ещё не остыл. Схлопывание считается по всей истории, иначе
    один и тот же объект переоткрывался бы каждый день.
    """
    mask = build_mask(scored, profile, thr)
    orders = to_orders(scored, mask, cooldown_days)
    if orders.empty:
        return orders

    if chronic_top is not None:
        orders = orders[orders["object_id"].isin(chronic_top)]

    if date is not None:
        day = pd.Timestamp(date)
        active = ((orders["opened_at"] <= day)
                  & (orders["last_alert_at"] >= day - pd.Timedelta(days=cooldown_days)))
        orders = orders[active]

    return orders.reset_index(drop=True)
