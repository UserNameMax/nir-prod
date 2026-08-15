"""
Тесты слоёв скоринга и объяснения.

Отдельно проверяется, что выходы ОБЪЕКТО-СПЕЦИФИЧНЫ: и хроника, и AFT-срок
должны различаться между объектами. Ошибка «всем вернулась популяционная
медиана» выглядит как рабочий ответ и молча обесценивает Слой 4.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

import explain
import scoring

FEATURES = ["f1", "f2"]


class _FakeAcute:
    def predict_proba(self, matrix):
        score = np.clip(matrix["f1"].to_numpy(dtype=float) / 10.0, 0, 1)
        return np.column_stack([1 - score, score])


class _FakeCalibrator:
    def transform(self, raw):
        return np.asarray(raw) * 0.1


class _FakePrep:
    def transform(self, frame):
        return np.nan_to_num(frame.to_numpy(dtype=float))


class _FakeChronicModel:
    def predict(self, matrix):
        return matrix[:, 0]


class _FakePipeline:
    def __init__(self):
        self.named_steps = {"prep": _FakePrep(), "model": _FakeChronicModel()}


class _FakeFitter:
    """Медиана зависит от f1 — как у настоящей AFT."""

    def predict_median(self, frame):
        return pd.Series(100.0 + 10.0 * frame["f1"].to_numpy(dtype=float))


class _FakeBundle:
    def __init__(self):
        self.acute = _FakeAcute()
        self.calibrator = _FakeCalibrator()
        self.chronic = _FakePipeline()
        self.aft = {"fitter": _FakeFitter(), "columns": FEATURES,
                    "medians": {"f1": 0.0, "f2": 0.0}}
        self.feature_columns = FEATURES
        self.alert_threshold = 0.5


def _features(objects=("A", "B", "C"), days=20):
    rows = []
    for i, obj in enumerate(objects):
        dates = pd.date_range("2026-04-01", periods=days, freq="D")
        rows.append(pd.DataFrame({
            "object_id": obj, "date": dates,
            "f1": np.linspace(i, i + 5, days),
            "f2": np.full(days, float(i)),
        }))
    return pd.concat(rows, ignore_index=True)


# ── дневной скоринг ───────────────────────────────────────────────────────────

def test_score_daily_shape_and_rank():
    scored = scoring.score_daily(_FakeBundle(), _features())

    assert set(scored.columns) == {"object_id", "date", "score", "calibrated", "rank"}
    day = scored[scored["date"] == scored["date"].max()]
    assert sorted(day["rank"]) == list(range(1, len(day) + 1))


def test_score_daily_empty_keeps_columns():
    scored = scoring.score_daily(_FakeBundle(), pd.DataFrame())
    assert list(scored.columns) == ["object_id", "date", "score", "calibrated", "rank"]


def test_rank_is_within_day():
    """Ранг считается внутри дня, а не по всей истории."""
    scored = scoring.score_daily(_FakeBundle(), _features())
    per_day = scored.groupby("date")["rank"].min()
    assert (per_day == 1).all()


# ── object-level срез ─────────────────────────────────────────────────────────

def test_object_baseline_one_row_per_object():
    baseline = scoring.object_baseline(_features(), FEATURES)
    assert len(baseline) == 3
    assert list(baseline.columns) == ["object_id", *FEATURES]


def test_object_baseline_uses_first_days_only():
    """Срез берётся по первым дням наблюдения — как при обучении хроники."""
    features = _features(objects=("A",), days=60)
    early = scoring.object_baseline(features, FEATURES, baseline_days=5)
    late = scoring.object_baseline(features, FEATURES, baseline_days=60)
    assert early.iloc[0]["f1"] < late.iloc[0]["f1"]


# ── объекто-специфичность ─────────────────────────────────────────────────────

def test_chronic_scores_differ_between_objects():
    baseline = scoring.object_baseline(_features(), FEATURES)
    chronic = scoring.score_chronic(_FakeBundle(), baseline)

    assert chronic["chronic_score"].nunique() > 1
    assert sorted(chronic["chronic_rank"]) == list(range(1, len(chronic) + 1))


def test_aft_median_differs_between_objects():
    """Регрессия: AFT должна получать ПРИЗНАКИ объекта.

    Если подать кадр без нужных колонок, reindex заполнит их медианами и все
    объекты получат одинаковый срок — ответ выглядит рабочим, но бессмыслен.
    """
    bundle = _FakeBundle()
    baseline = scoring.object_baseline(_features(), FEATURES)

    values = [explain.aft_median_days(bundle.aft, baseline[baseline.object_id == oid])
              for oid in ("A", "B", "C")]

    assert all(v is not None for v in values)
    assert len(set(values)) == len(values)


def test_aft_on_unknown_object_returns_none():
    bundle = _FakeBundle()
    empty = pd.DataFrame(columns=["object_id", *FEATURES])
    assert explain.aft_median_days(bundle.aft, empty) is None


# ── пороги ────────────────────────────────────────────────────────────────────

def test_object_thresholds_per_object():
    scored = scoring.score_daily(_FakeBundle(), _features())
    thresholds = scoring.object_thresholds(scored)

    assert len(thresholds) == 3
    assert (thresholds["p90"] >= thresholds["p75"]).all()


def test_global_thresholds_include_alert_level():
    scored = scoring.score_daily(_FakeBundle(), _features())
    globals_ = scoring.global_thresholds(scored, 0.42)

    assert globals_["alert_threshold"] == 0.42
    assert globals_["p50"] <= globals_["p75"] <= globals_["p90"]
