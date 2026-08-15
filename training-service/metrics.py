"""Протокол оценки: detection при фиксированном бюджете + нулевой пол.

Перенесено из research `model_benchmark/harness/evaluate.py` (production не
импортирует код вне себя). Оставлено то, что нужно для отчётности бандла.

ГЛАВНОЕ (NARRATIVE §6, п.6): абсолютный detection нельзя читать как успех — у
метрики высокий НУЛЕВОЙ ПОЛ, потому что засчитывается «сработал ли алерт хоть раз
за десятки предаварийных дней». Поэтому здесь всегда считаются `detection_null`
(случайное алертирование при том же бюджете) и `detection_lift`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

LEAD_CAP_DAYS = 60      # окно, в котором алерт засчитывается как пойманная авария


def target(df: pd.DataFrame, horizon_days: int) -> np.ndarray:
    return (df["t_to_failure"] <= horizon_days * 24).fillna(False).astype(int).values


def discrimination(df: pd.DataFrame, horizon_days: int) -> dict:
    y = target(df, horizon_days)
    score = df["score"].values
    if y.sum() == 0 or y.sum() == len(y):
        return {"roc_auc": None, "pr_auc": None, "base_rate": float(y.mean())}
    return {
        "roc_auc": float(roc_auc_score(y, score)),
        "pr_auc": float(average_precision_score(y, score)),
        "base_rate": float(y.mean()),
    }


def budget_threshold(scores: np.ndarray, alert_rate: float) -> float:
    """Порог под бюджет алертов — квантиль скоров (по РАНГУ, не по калибровке)."""
    return float(np.quantile(scores, 1 - alert_rate))


def _object_detection(test: pd.DataFrame, thr: float,
                      cap_days: int = LEAD_CAP_DAYS) -> dict:
    """Для каждого аварийного объекта: пойман ли, сколько было шансов сработать."""
    cap = cap_days * 24
    out = {}
    for oid, g in test.groupby("object_id"):
        window = g[(g["t_to_failure"] > 0) & (g["t_to_failure"] <= cap)]
        if window.empty:
            continue
        fired = window[window["score"].values >= thr]
        leads = (fired["t_to_failure"].max() / 24) if not fired.empty else None
        out[oid] = {"detected": not fired.empty, "opportunities": len(window), "lead": leads}
    return out


def detection(test: pd.DataFrame, thr: float, horizon_days: int,
              cap_days: int = LEAD_CAP_DAYS) -> dict:
    """Детекция + аналитический нулевой пол + lift + раннесть.

    Пол: при бюджете p и `opp` шансах случайное алертирование ловит объект с
    вероятностью 1-(1-p)^opp. Усреднение по аварийным объектам и есть пол.
    """
    per_object = _object_detection(test, thr, cap_days)
    if not per_object:
        return {"fail_objects": 0, "detected": 0, "detection": None}

    detected = np.array([v["detected"] for v in per_object.values()], float)
    opportunities = np.array([v["opportunities"] for v in per_object.values()], float)
    leads = np.array([v["lead"] for v in per_object.values() if v["lead"] is not None])

    p = float((test["score"].values >= thr).mean())
    null = float(np.mean(1.0 - (1.0 - p) ** opportunities))
    rate = float(detected.mean())

    return {
        "fail_objects": int(len(detected)),
        "detected": int(detected.sum()),
        "detection": rate,
        "detection_null": null,
        "detection_lift": rate - null,
        "opp_median": float(np.median(opportunities)),
        "lead_median": float(np.median(leads)) if len(leads) else None,
        # sharpness: доля пойманных, чей первый алерт попал в горизонт
        "lead_within_H": float(np.mean(leads <= horizon_days)) if len(leads) else None,
        "alerts_per_day": float((test["score"].values >= thr).sum() / test["date"].nunique()),
    }


def permutation_null(test: pd.DataFrame, thr: float, B: int = 400, seed: int = 0,
                     cap_days: int = LEAD_CAP_DAYS) -> dict:
    """Пол перестановкой: раскидать то же число алертов случайно и пересчитать.

    `p_value` — доля перестановок, где случайное алертирование не хуже реального.
    """
    per_object = _object_detection(test, thr, cap_days)
    if not per_object:
        return {"p_value": None}

    scores = test["score"].values
    k = int((scores >= thr).sum())
    n = len(test)
    real = float(np.mean([v["detected"] for v in per_object.values()]))

    cap = cap_days * 24
    in_window = (test["t_to_failure"].values > 0) & (test["t_to_failure"].values <= cap)
    oids = test["object_id"].values
    rows_by = {o: np.where((oids == o) & in_window)[0] for o in per_object}

    rng = np.random.RandomState(seed)
    nulls = []
    for _ in range(B):
        fire = np.zeros(n, bool)
        fire[rng.choice(n, k, replace=False)] = True
        nulls.append(np.mean([fire[rows].any() for rows in rows_by.values()]))
    nulls = np.array(nulls)

    return {
        "null_mean": float(nulls.mean()),
        "null_lo": float(np.percentile(nulls, 2.5)),
        "null_hi": float(np.percentile(nulls, 97.5)),
        "lift": float(real - nulls.mean()),
        "p_value": float((nulls >= real).mean()),
        "B": B,
    }


def bootstrap_detection(test: pd.DataFrame, thr: float, B: int = 500, seed: int = 0,
                        cap_days: int = LEAD_CAP_DAYS) -> dict:
    """Object-bootstrap 95% CI детекции (ресэмплинг аварийных объектов)."""
    per_object = _object_detection(test, thr, cap_days)
    if not per_object:
        return {}
    detected = np.array([v["detected"] for v in per_object.values()], float)
    rng = np.random.RandomState(seed)
    draws = [detected[rng.randint(0, len(detected), len(detected))].mean() for _ in range(B)]
    return {"detection_lo": float(np.percentile(draws, 2.5)),
            "detection_hi": float(np.percentile(draws, 97.5))}


def bootstrap_roc(test: pd.DataFrame, horizon_days: int, B: int = 500,
                  seed: int = 0) -> dict:
    """Object-bootstrap 95% CI для ROC-AUC (ресэмплинг объектов, не строк)."""
    y = target(test, horizon_days)
    scores = test["score"].values
    oids = test["object_id"].values
    unique = np.unique(oids)
    rows_by = {o: np.where(oids == o)[0] for o in unique}

    rng = np.random.RandomState(seed)
    values = []
    for _ in range(B):
        sample = rng.choice(unique, size=len(unique), replace=True)
        idx = np.concatenate([rows_by[o] for o in sample])
        yb = y[idx]
        if yb.sum() == 0 or yb.sum() == len(yb):
            continue
        values.append(roc_auc_score(yb, scores[idx]))
    if not values:
        return {}
    return {"roc_lo": float(np.percentile(values, 2.5)),
            "roc_hi": float(np.percentile(values, 97.5))}


def c_index(duration: np.ndarray, event: np.ndarray, score: np.ndarray) -> float | None:
    """C-index для object-level ранжирования (больший скор = раньше событие)."""
    from sksurv.metrics import concordance_index_censored
    try:
        return float(concordance_index_censored(event.astype(bool), duration, score)[0])
    except Exception:
        return None
