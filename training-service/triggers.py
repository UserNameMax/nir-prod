"""Решающий слой: правила превращения дневного скора в наряд на осмотр.

Перенесено из research `model_benchmark/harness/triggers.py` (NARRATIVE §11).

Идея: модель упирается в потолок сигнала, поэтому операционную выгоду поднимает
не переобучение, а ПРАВИЛО. Здесь только трансформации правила.

Persistence считается по ПОСЛЕДОВАТЕЛЬНОСТИ наблюдений объекта (не по календарным
дням): данные разрежены, ~99% объектов имеют разрывы дат.

Стоимость — число ИНСПЕКЦИЙ (нарядов), а не алерт-дней: подряд идущие алерты
объекта в пределах cooldown = один наряд (открытая заявка не переоткрывается).
κ* = инспекции / пойманные аварии = «во сколько раз авария должна быть дороже
осмотра, чтобы система окупилась».
"""
from __future__ import annotations

import numpy as np
import pandas as pd

COOLDOWN_DAYS = 14
LEAD_CAP_DAYS = 60


def _ordered(df: pd.DataFrame) -> np.ndarray:
    return df.sort_values(["object_id", "date"]).index.values


def baseline_mask(df: pd.DataFrame, thr: float) -> pd.Series:
    """Тривиальное правило: алерт, если скор выше порога."""
    return df["score"] >= thr


def persist_mask(df: pd.DataFrame, thr: float, n: int) -> pd.Series:
    """Sustained-N: алерт, когда скор выше порога на N подряд идущих наблюдениях.

    Режет одиночные всплески — остаётся только устойчивая деградация.
    """
    idx = _ordered(df)
    d = df.loc[idx]
    above = d["score"].values >= thr
    oid = d["object_id"].values

    prev_above = np.concatenate([[False], above[:-1]])
    same_obj = np.concatenate([[False], oid[1:] == oid[:-1]])
    start = above & ~(same_obj & prev_above)          # первый элемент каждой серии
    run_id = np.cumsum(start)
    cum = pd.Series(above.astype(int)).groupby(run_id).cumsum().values

    return pd.Series(above & (cum >= n), index=idx).reindex(df.index)


def ewma_score(df: pd.DataFrame, span: int) -> pd.Series:
    """EWMA-сглаженный скор по объекту (span наблюдений)."""
    idx = _ordered(df)
    d = df.loc[idx]
    smoothed = d.groupby("object_id")["score"].transform(
        lambda s: s.ewm(span=span, adjust=False).mean())
    return smoothed.reindex(df.index)


def gate_mask(df: pd.DataFrame, thr: float, chronic_top: set) -> pd.Series:
    """Гейтинг: острый сигнал И объект в top-K хроники (независимая модель)."""
    return (df["score"] >= thr) & df["object_id"].isin(chronic_top)


def inspections(df: pd.DataFrame, mask: pd.Series,
                cooldown_days: int = COOLDOWN_DAYS) -> int:
    """Число нарядов: серия алертов объекта в пределах cooldown = один наряд."""
    fired = df.loc[mask.reindex(df.index).fillna(False).values]
    if fired.empty:
        return 0
    fired = fired.sort_values(["object_id", "date"])
    gap = fired.groupby("object_id")["date"].diff().dt.days
    return int((gap.isna() | (gap > cooldown_days)).sum())


def eval_rule(test: pd.DataFrame, mask: pd.Series, horizon_days: int,
              cap_days: int = LEAD_CAP_DAYS,
              cooldown_days: int = COOLDOWN_DAYS) -> dict:
    """Оценка правила: бюджет, детекция, раннесть, κ*."""
    m = mask.reindex(test.index).fillna(False)
    cap = cap_days * 24
    window = test[(test["t_to_failure"] > 0) & (test["t_to_failure"] <= cap)]
    fired = window[m.loc[window.index].values]

    fail_objects = int(window["object_id"].nunique())
    detected = int(fired["object_id"].nunique())
    leads = ((fired.groupby("object_id")["t_to_failure"].max() / 24).values
             if detected else np.array([]))
    orders = inspections(test, m, cooldown_days)

    return {
        "alert_days": int(m.sum()),
        "inspections": orders,
        "fail_objects": fail_objects,
        "detected": detected,
        "detection": detected / max(fail_objects, 1),
        "lead_median": float(np.median(leads)) if len(leads) else None,
        "lead_within_H": float(np.mean(leads <= horizon_days)) if len(leads) else None,
        "kappa_star": float(orders / detected) if detected else float("inf"),
    }


def sweep(test: pd.DataFrame, mask_fn, thresholds, horizon_days: int,
          cooldown_days: int = COOLDOWN_DAYS) -> pd.DataFrame:
    """Прогон правила по сетке порогов → фронтир κ*(detection)."""
    rows = []
    for thr in thresholds:
        row = eval_rule(test, mask_fn(thr), horizon_days, cooldown_days=cooldown_days)
        row["threshold"] = float(thr)
        rows.append(row)
    return pd.DataFrame(rows)


def kappa_at_detection(frontier: pd.DataFrame, target: float) -> float:
    """Минимальный κ* среди точек фронтира с детекцией не ниже target."""
    ok = frontier[frontier["detection"] >= target]
    return float(ok["kappa_star"].min()) if len(ok) else float("nan")


def build_profiles(test: pd.DataFrame, horizon_days: int, chronic_top: dict[str, set],
                   target_detection: float = 0.3,
                   cooldown_days: int = COOLDOWN_DAYS) -> dict:
    """Свипнуть все правила и собрать trigger_config: κ* и лучший профиль.

    chronic_top — множества объектов из top-K% хроники (для гейтинга).
    Профиль-победитель = минимальный κ* при детекции не ниже target_detection.
    """
    grid = np.quantile(test["score"].values, np.linspace(0.90, 0.999, 25))
    profiles: dict[str, dict] = {}

    profiles["baseline"] = {
        "type": "baseline",
        "frontier": sweep(test, lambda t: baseline_mask(test, t), grid,
                          horizon_days, cooldown_days),
    }
    for n in (3, 5, 7):
        profiles[f"persist{n}"] = {
            "type": "persist", "n": n,
            "frontier": sweep(test, lambda t, n=n: persist_mask(test, t, n), grid,
                              horizon_days, cooldown_days),
        }
    for span in (5, 10):
        smoothed = ewma_score(test, span)
        ewma_grid = np.quantile(smoothed.values, np.linspace(0.90, 0.999, 25))
        frame = test.assign(score=smoothed.values)
        profiles[f"ewma{span}"] = {
            "type": "ewma", "span": span,
            "frontier": sweep(frame, lambda t: frame["score"] >= t, ewma_grid,
                              horizon_days, cooldown_days),
        }
    for name, members in chronic_top.items():
        profiles[f"gate_{name}"] = {
            "type": "gate", "chronic_top": name,
            "frontier": sweep(test, lambda t, m=members: gate_mask(test, t, m), grid,
                              horizon_days, cooldown_days),
        }

    config = {"cooldown_days": cooldown_days, "target_detection": target_detection,
              "profiles": {}}
    for name, spec in profiles.items():
        frontier = spec.pop("frontier")
        kappa = kappa_at_detection(frontier, target_detection)
        best = frontier[frontier["detection"] >= target_detection]
        spec["kappa_star"] = None if np.isnan(kappa) else round(kappa, 2)
        if len(best):
            row = best.loc[best["kappa_star"].idxmin()]
            spec["threshold"] = round(float(row["threshold"]), 6)
            spec["detection"] = round(float(row["detection"]), 4)
            spec["inspections"] = int(row["inspections"])
            spec["lead_within_H"] = (round(float(row["lead_within_H"]), 4)
                                     if row["lead_within_H"] is not None else None)
        config["profiles"][name] = spec

    usable = {k: v for k, v in config["profiles"].items()
              if v.get("kappa_star") is not None}
    config["default"] = (min(usable, key=lambda k: usable[k]["kappa_star"])
                         if usable else "baseline")
    return config
