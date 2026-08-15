"""Оркестрация обучения: от сырья соседних сервисов до опубликованного бандла.

Порядок стадий соответствует SPEC: fetch → dataset → train_* → triggers →
validate → publish.

Честность отчётности (NARRATIVE §7, §9): в manifest идут ТОЛЬКО temporal-числа
своего прогона — detection вместе с нулевым полом и lift. Абсолютный detection
без пола не показывается нигде.
"""
from __future__ import annotations
import datetime as dt
import os

import numpy as np
import pandas as pd

import clients
import dataset
import metrics
import publish
import triggers
from trainers import acute, chronic, explain

ALERT_RATE = float(os.getenv("ALERT_RATE", "0.02"))
HORIZON_DAYS = 30           # операционно валиден только месячный горизонт
CHRONIC_TOP_FRACTIONS = {"top30": 0.30, "top50": 0.50}


def train_bundle(bundle_dir: str, *, val_start: str | None = None,
                 test_start: str | None = None, alert_rate: float = ALERT_RATE,
                 progress=lambda stage: None) -> dict:
    """Полный прогон обучения. Возвращает опубликованный manifest."""
    run_id = f"train_{dt.datetime.now():%Y%m%d_%H%M%S}"

    # --- fetch -------------------------------------------------------------
    progress("fetch")
    schema = clients.fetch_schema()
    feature_cols = list(schema["columns"])
    features = clients.fetch_features()
    incidents = clients.fetch_incidents()
    if features.empty:
        raise ValueError("feature-service не отдал признаки — сначала /features/rebuild")
    if incidents.empty:
        raise ValueError("нет верифицированных аварий — обучать не на чем")

    # --- dataset -----------------------------------------------------------
    progress("dataset")
    frame = dataset.add_target(features, incidents)
    frame = dataset.temporal_split(frame, val_start, test_start)
    train_df, val_df, test_df = dataset.splits(frame)
    for name, part in (("train", train_df), ("val", val_df), ("test", test_df)):
        if part.empty:
            raise ValueError(f"пустой split {name} — проверьте границы периодов")

    # --- острая модель (Слой 2) --------------------------------------------
    progress("train_acute")
    model, calibrator = acute.train(train_df, val_df, feature_cols)
    val_scores = acute.predict(model, val_df, feature_cols)
    test_scores = acute.predict(model, test_df, feature_cols)
    threshold = metrics.budget_threshold(val_scores, alert_rate)
    scored_test = test_df.assign(score=test_scores)

    # --- хроника (Слой 1): учим строго на событиях ДО тестового окна --------
    progress("train_chronic")
    history = frame[frame["split"] != "test"]
    objects = dataset.object_level(history, feature_cols)
    chronic_pipeline = chronic.train(objects, feature_cols)
    chronic_scores = chronic.predict(chronic_pipeline, objects, feature_cols)
    chronic_top = {name: chronic.top_objects(objects, chronic_scores, frac)
                   for name, frac in CHRONIC_TOP_FRACTIONS.items()}
    # оценка ранжирования — на отложенных объектах (in-sample C-index завышен)
    chronic_c_index = chronic.holdout_c_index(objects, feature_cols)

    # --- объяснение (Слой 4) ------------------------------------------------
    progress("train_explain")
    aft = explain.train(objects, feature_cols)

    # --- решающий слой (Слой 2/3): κ*-фронтир --------------------------------
    progress("triggers")
    trigger_config = triggers.build_profiles(scored_test, HORIZON_DAYS, chronic_top)

    # --- валидация: только temporal ------------------------------------------
    progress("validate")
    reporting = _reporting(scored_test, threshold)

    # --- публикация -----------------------------------------------------------
    progress("publish")
    manifest = _manifest(
        run_id=run_id, schema=schema, alert_rate=alert_rate, threshold=threshold,
        reporting=reporting, frame=frame, chronic_c_index=chronic_c_index,
    )
    return publish.publish(
        bundle_dir, run_id,
        acute_model=model, acute_calibrator=calibrator,
        chronic_model=chronic_pipeline, explain_aft=aft,
        manifest=manifest, trigger_config=trigger_config,
    )


def _reporting(scored_test: pd.DataFrame, threshold: float) -> dict:
    """Операционные числа: детекция ВСЕГДА рядом с полом и lift."""
    report = {"split": "temporal"}
    report.update(metrics.discrimination(scored_test, HORIZON_DAYS))
    report.update(metrics.detection(scored_test, threshold, HORIZON_DAYS))

    permutation = metrics.permutation_null(scored_test, threshold)
    report["lift_p_value"] = permutation.get("p_value")
    report["null_permutation"] = permutation.get("null_mean")
    report.update(metrics.bootstrap_detection(scored_test, threshold))
    report.update(metrics.bootstrap_roc(scored_test, HORIZON_DAYS))
    report["n_events"] = report.get("fail_objects")
    return report


def _manifest(*, run_id: str, schema: dict, alert_rate: float, threshold: float,
              reporting: dict, frame: pd.DataFrame,
              chronic_c_index: float | None) -> dict:
    bounds = frame.groupby("split")["date"].agg(["min", "max"])

    def window(split: str) -> str | None:
        if split not in bounds.index:
            return None
        row = bounds.loc[split]
        return f"{row['min']:%Y-%m-%d}..{row['max']:%Y-%m-%d}"

    return {
        "version": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_by": f"training-service/{run_id}",
        "horizon_days": HORIZON_DAYS,
        "feature_schema": {
            "name": schema["name"],
            "service_version": schema["version"],
            "n_features": schema["n_features"],
            "columns": list(schema["columns"]),
        },
        "alert_threshold": {
            "policy": "budget_quantile",
            "alert_rate": alert_rate,
            "raw_score_threshold": threshold,
            "note": "порог по РАНГУ сырого скора; калибровка на него не влияет",
        },
        "reporting": reporting,
        "models": {
            "acute": {
                "file": publish.LAYOUT["acute_model"], "family": "xgb-binary", "unit": "C",
                "objective": "binary:logistic", "output": "P(отказ за 30д), сырой",
                "calibrator": publish.LAYOUT["acute_calibrator"],
            },
            "chronic": {
                "file": publish.LAYOUT["chronic_model"], "family": "survival-A", "unit": "A",
                "c_index": chronic_c_index,
                "c_index_estimate": "holdout 25% объектов (не in-sample)",
                "trained_on": "события строго ДО тестового окна",
                "note": "класс нелинейных моделей, НЕ «чемпион RSF»",
            },
            "explain_aft": {
                "file": publish.LAYOUT["explain_aft"], "family": "aft-A", "unit": "A",
                "output": "медианный срок до аварии, дни",
            },
        },
        "object_survival_recon": {"baseline_days": dataset.BASELINE_DAYS,
                                  "merge_gap": dataset.MERGE_GAP_DAYS},
        "data_window": {s: window(s) for s in ("train", "val", "test")},
    }
