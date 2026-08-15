"""Слой 1 — хроническая модель: Random Survival Forest, watch-list для планового ТО.

Единица анализа A (одна строка на объект, время до первой аварии) — независимость
субъектов восстановлена, поэтому survival-метод корректен.

Гиперпараметры из research `02_survival.ipynb`. Подаётся как «класс нелинейных
моделей», НЕ «чемпион RSF»: CI C-index перекрывается с GBS и Dynamic-DeepHit
(NARRATIVE §6, п.3).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sksurv.ensemble import RandomSurvivalForest
from sksurv.util import Surv

SEED = 42

PARAMS = dict(
    n_estimators=200,
    min_samples_leaf=20,
    max_features="sqrt",
    n_jobs=-1,
    random_state=SEED,
)


def train(objects: pd.DataFrame, feature_cols: list[str]) -> Pipeline:
    """Обучить RSF на object-level кадре (duration, event, признаки)."""
    cols = [c for c in feature_cols if c in objects.columns]
    prep = Pipeline([("impute", SimpleImputer(strategy="median")),
                     ("scale", StandardScaler())])
    X = prep.fit_transform(objects[cols])
    y = Surv.from_arrays(objects["event"].astype(bool).values,
                         objects["duration"].values)

    forest = RandomSurvivalForest(**PARAMS).fit(X, y)
    return Pipeline([("prep", prep), ("model", forest)])


def predict(pipeline: Pipeline, objects: pd.DataFrame,
            feature_cols: list[str]) -> np.ndarray:
    """Риск-скор объекта: больше — раньше ожидается авария."""
    cols = [c for c in feature_cols if c in objects.columns]
    X = pipeline.named_steps["prep"].transform(objects[cols])
    return pipeline.named_steps["model"].predict(X)


def holdout_c_index(objects: pd.DataFrame, feature_cols: list[str],
                    holdout_fraction: float = 0.25, seed: int = SEED) -> float | None:
    """Честная оценка ранжирования: обучение на части объектов, замер на остальных.

    Считать C-index на тех же объектах, на которых обучался лес, нельзя — оценка
    получается оптимистичной (RSF почти идеально ранжирует обучающую выборку).
    Финальная модель бандла всё равно учится на всех объектах; здесь только оценка.
    """
    from sksurv.metrics import concordance_index_censored

    rng = np.random.RandomState(seed)
    mask = rng.rand(len(objects)) >= holdout_fraction
    train_part, test_part = objects[mask], objects[~mask]
    if test_part["event"].sum() < 2 or train_part["event"].sum() < 2:
        return None

    pipeline = train(train_part, feature_cols)
    scores = predict(pipeline, test_part, feature_cols)
    try:
        return float(concordance_index_censored(
            test_part["event"].astype(bool).values,
            test_part["duration"].values, scores)[0])
    except Exception:
        return None


def top_objects(objects: pd.DataFrame, scores: np.ndarray, fraction: float) -> set:
    """Множество object_id из верхней доли хроники — для гейтинга (Слой 3)."""
    if len(scores) == 0:
        return set()
    cutoff = np.quantile(scores, 1 - fraction)
    return set(objects.loc[scores >= cutoff, "object_id"].astype(str))
