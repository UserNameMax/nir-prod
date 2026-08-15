"""
Тесты протокола оценки.

Смысловой центр — НУЛЕВОЙ ПОЛ детекции (NARRATIVE §6, п.6): случайный скор на
длинном предаварийном окне даёт высокую «детекцию». Тесты фиксируют, что пол
считается и что lift у случайного скора около нуля.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

import metrics


def _panel(n_objects=40, days=60, seed=0, informative=True):
    """Панель объект-день: часть объектов аварийные, скор опционально сигнальный."""
    rng = np.random.RandomState(seed)
    rows = []
    for i in range(n_objects):
        oid = f"obj{i}"
        dates = pd.date_range("2026-04-01", periods=days, freq="D")
        fails = i % 4 == 0
        if fails:
            fail_day = dates[-1] + pd.Timedelta(days=1)
            ttf = (fail_day - dates).days * 24.0
        else:
            ttf = np.full(days, np.nan)
        score = rng.rand(days)
        if informative and fails:
            score = score * 0.5 + 0.5      # аварийным поднимаем скор
        rows.append(pd.DataFrame({"object_id": oid, "date": dates,
                                  "t_to_failure": ttf, "score": score}))
    return pd.concat(rows, ignore_index=True)


def test_budget_threshold_matches_rate():
    scores = np.linspace(0, 1, 1000)
    thr = metrics.budget_threshold(scores, 0.02)
    assert (scores >= thr).mean() == pytest.approx(0.02, abs=0.005)


def test_detection_reports_null_and_lift():
    panel = _panel()
    thr = metrics.budget_threshold(panel["score"].values, 0.02)
    result = metrics.detection(panel, thr, 30)

    assert result["fail_objects"] > 0
    assert result["detection_null"] is not None
    assert result["detection_lift"] == pytest.approx(
        result["detection"] - result["detection_null"])


def test_random_score_has_near_zero_lift():
    """Случайный скор ловит аварии за счёт геометрии окна — но lift ≈ 0.

    Это и есть нулевой пол: абсолютная детекция без пола ничего не значит.
    """
    panel = _panel(informative=False, seed=3)
    thr = metrics.budget_threshold(panel["score"].values, 0.05)
    result = metrics.detection(panel, thr, 30)

    assert abs(result["detection_lift"]) < 0.15
    assert result["detection"] > 0.5          # абсолютная детекция высока...
    assert result["detection_null"] > 0.5     # ...но и пол тоже


def _mean_lift(informative: bool, alert_rate: float, seeds: int = 15) -> float:
    """Средний lift по нескольким панелям.

    Усреднение обязательно: аварийных объектов десятки, поэтому одиночное
    сравнение шумит — та же причина, по которой в NARRATIVE выводы делаются по
    bootstrap/McNemar, а не по одной точке.
    """
    lifts = []
    for seed in range(seeds):
        panel = _panel(informative=informative, seed=seed)
        thr = metrics.budget_threshold(panel["score"].values, alert_rate)
        lifts.append(metrics.detection(panel, thr, 30)["detection_lift"])
    return float(np.mean(lifts))


def test_informative_score_beats_random_by_lift():
    """Сигнальный скор даёт больший средний lift, чем случайный.

    Бюджет намеренно жёсткий: при щедром бюджете метрика насыщается и различить
    сигнал от случая нельзя (см. test_metric_saturates_at_loose_budget).
    """
    assert _mean_lift(True, 0.005) > _mean_lift(False, 0.005)


def test_metric_saturates_at_loose_budget():
    """При щедром бюджете разрыв «сигнал − случай» схлопывается.

    Обе панели ловят почти всё, lift упирается в общий потолок, и различающая
    способность метрики падает в разы. Довод в пользу жёсткой ставки алертов и
    отчётности по lift, а не по абсолютной детекции.
    """
    tight = _mean_lift(True, 0.005) - _mean_lift(False, 0.005)
    loose = _mean_lift(True, 0.05) - _mean_lift(False, 0.05)

    assert loose < tight / 3


def test_lift_ceiling_is_limited_by_null():
    """Геометрия окна ограничивает достижимый lift сверху.

    60 шансов сработать при бюджете 5% дают пол ≈1-(0.95)^60 ≈ 0.95 — даже
    идеальная модель поднимется над ним лишь на ~0.05. Это и есть причина, по
    которой абсолютный detection не показатель (NARRATIVE §6, п.6).
    """
    panel = _panel(informative=True, seed=1)
    thr = metrics.budget_threshold(panel["score"].values, 0.05)
    result = metrics.detection(panel, thr, 30)

    assert result["detection_null"] > 0.9
    assert result["detection_lift"] < 1.0 - result["detection_null"] + 1e-9


def test_permutation_null_p_value():
    panel = _panel(informative=True, seed=2)
    thr = metrics.budget_threshold(panel["score"].values, 0.05)
    result = metrics.permutation_null(panel, thr, B=100)

    assert 0.0 <= result["p_value"] <= 1.0
    assert result["null_lo"] <= result["null_mean"] <= result["null_hi"]


def test_permutation_null_random_score_not_significant():
    panel = _panel(informative=False, seed=5)
    thr = metrics.budget_threshold(panel["score"].values, 0.05)
    assert metrics.permutation_null(panel, thr, B=100)["p_value"] > 0.05


def test_bootstrap_detection_interval_contains_estimate():
    panel = _panel()
    thr = metrics.budget_threshold(panel["score"].values, 0.05)
    point = metrics.detection(panel, thr, 30)["detection"]
    ci = metrics.bootstrap_detection(panel, thr, B=200)

    assert ci["detection_lo"] <= point <= ci["detection_hi"]


def test_bootstrap_roc_interval():
    panel = _panel(informative=True)
    ci = metrics.bootstrap_roc(panel, 30, B=100)
    assert ci["roc_lo"] < ci["roc_hi"]


def test_discrimination_on_degenerate_panel():
    """Без аварий метрики дискриминации не считаются — но и не падают."""
    panel = _panel(n_objects=4, days=5)
    panel["t_to_failure"] = np.nan
    result = metrics.discrimination(panel, 30)
    assert result["roc_auc"] is None


def test_lead_within_horizon_reported():
    panel = _panel(informative=True)
    thr = metrics.budget_threshold(panel["score"].values, 0.1)
    result = metrics.detection(panel, thr, 30)
    assert 0.0 <= result["lead_within_H"] <= 1.0
