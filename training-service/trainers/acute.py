"""Слой 2 — острая модель: бинарный XGBoost как дискретный hazard, H=30.

Единица анализа C (объект-день): дискретное время, факторизация правдоподобия —
это КОРРЕКТНАЯ survival-постановка для панели с повторными авариями, а не
псевдорепликация (NARRATIVE §2). Непрерывный Cox на countdown-панели невалиден.

Гиперпараметры перенесены из research `12_temporal_holdout.ipynb` (temporal-прогон).
Калибровка isotonic — ТОЛЬКО для показа средней вероятности диспетчеру; на порог
она не влияет, порог берётся по рангу сырого скора (NARRATIVE §9).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.isotonic import IsotonicRegression

SEED = 42

PARAMS = dict(
    n_estimators=1000,
    max_depth=4,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=5,
    reg_lambda=1.0,
    tree_method="hist",
    eval_metric="aucpr",
    early_stopping_rounds=50,
    n_jobs=-1,
    random_state=SEED,
)


def train(train_df: pd.DataFrame, val_df: pd.DataFrame,
          feature_cols: list[str]) -> tuple[xgb.XGBClassifier, IsotonicRegression]:
    """Обучить модель на train с ранней остановкой по val + изотоническую калибровку."""
    y_train = train_df["y"].values
    positives = max(int((y_train == 1).sum()), 1)
    scale_pos_weight = float((y_train == 0).sum() / positives)

    model = xgb.XGBClassifier(scale_pos_weight=scale_pos_weight, **PARAMS)
    model.fit(
        train_df[feature_cols], y_train,
        eval_set=[(val_df[feature_cols], val_df["y"].values)],
        verbose=False,
    )

    # isotonic на val — вероятность «для показа», не для порога
    val_scores = predict(model, val_df, feature_cols)
    calibrator = IsotonicRegression(out_of_bounds="clip").fit(val_scores, val_df["y"].values)
    return model, calibrator


def predict(model: xgb.XGBClassifier, df: pd.DataFrame,
            feature_cols: list[str]) -> np.ndarray:
    """Сырой скор P(отказ в горизонте). Больше — рискованнее."""
    return model.predict_proba(df[feature_cols])[:, 1]
