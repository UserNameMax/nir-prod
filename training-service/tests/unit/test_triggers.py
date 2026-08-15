"""
Тесты решающего слоя (NARRATIVE §11).

Ключевые свойства: persistence режет одиночные всплески, серия алертов в пределах
cooldown считается ОДНИМ нарядом (стоимостный знаменатель κ*), гейтинг сужает
алерты до хронически рисковых объектов.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

import triggers


def _frame(scores, object_id="A", start="2026-04-01"):
    dates = pd.date_range(start, periods=len(scores), freq="D")
    return pd.DataFrame({"object_id": object_id, "date": dates,
                         "score": scores, "t_to_failure": np.nan})


# ── persistence ───────────────────────────────────────────────────────────────

def test_persist_ignores_single_spike():
    frame = _frame([0.1, 0.9, 0.1, 0.1])
    assert not triggers.persist_mask(frame, 0.5, 3).any()


def test_persist_fires_on_sustained_run():
    frame = _frame([0.1, 0.9, 0.9, 0.9, 0.9])
    mask = triggers.persist_mask(frame, 0.5, 3)
    # срабатывает с третьего наблюдения серии и держится
    assert mask.tolist() == [False, False, False, True, True]


def test_persist_resets_after_break():
    frame = _frame([0.9, 0.9, 0.1, 0.9, 0.9])
    assert not triggers.persist_mask(frame, 0.5, 3).any()


def test_persist_does_not_leak_across_objects():
    """Серия одного объекта не продолжает серию другого."""
    a = _frame([0.9, 0.9], object_id="A")
    b = _frame([0.9, 0.9], object_id="B")
    frame = pd.concat([a, b], ignore_index=True)
    assert not triggers.persist_mask(frame, 0.5, 3).any()


def test_persist_counts_observations_not_calendar_days():
    """Данные разрежены: «подряд» — по наблюдениям, а не по датам."""
    frame = pd.DataFrame({
        "object_id": "A",
        "date": pd.to_datetime(["2026-04-01", "2026-04-10", "2026-04-25"]),
        "score": [0.9, 0.9, 0.9],
        "t_to_failure": np.nan,
    })
    assert triggers.persist_mask(frame, 0.5, 3).iloc[-1]


# ── EWMA ──────────────────────────────────────────────────────────────────────

def test_ewma_smooths_spike():
    frame = _frame([0.0, 0.0, 1.0, 0.0, 0.0])
    smoothed = triggers.ewma_score(frame, span=5)
    assert smoothed.max() < 1.0
    assert smoothed.iloc[2] > smoothed.iloc[0]


def test_ewma_is_per_object():
    a = _frame([1.0, 1.0], object_id="A")
    b = _frame([0.0, 0.0], object_id="B")
    frame = pd.concat([a, b], ignore_index=True)
    smoothed = triggers.ewma_score(frame, span=3)
    assert smoothed[frame.object_id == "B"].max() == 0.0


# ── наряды и cooldown ─────────────────────────────────────────────────────────

def test_consecutive_alerts_are_one_inspection():
    frame = _frame([0.9] * 5)
    mask = triggers.baseline_mask(frame, 0.5)
    assert triggers.inspections(frame, mask, cooldown_days=14) == 1


def test_alerts_beyond_cooldown_are_separate_inspections():
    frame = pd.DataFrame({
        "object_id": "A",
        "date": pd.to_datetime(["2026-04-01", "2026-04-02", "2026-05-20"]),
        "score": [0.9, 0.9, 0.9],
        "t_to_failure": np.nan,
    })
    mask = triggers.baseline_mask(frame, 0.5)
    assert triggers.inspections(frame, mask, cooldown_days=14) == 2


def test_inspections_counted_per_object():
    a = _frame([0.9, 0.9], object_id="A")
    b = _frame([0.9, 0.9], object_id="B")
    frame = pd.concat([a, b], ignore_index=True)
    mask = triggers.baseline_mask(frame, 0.5)
    assert triggers.inspections(frame, mask) == 2


def test_no_alerts_no_inspections():
    frame = _frame([0.1, 0.1])
    assert triggers.inspections(frame, triggers.baseline_mask(frame, 0.5)) == 0


# ── гейтинг ───────────────────────────────────────────────────────────────────

def test_gate_restricts_to_chronic_top():
    a = _frame([0.9], object_id="A")
    b = _frame([0.9], object_id="B")
    frame = pd.concat([a, b], ignore_index=True)
    mask = triggers.gate_mask(frame, 0.5, {"A"})
    assert mask.tolist() == [True, False]


# ── κ* ────────────────────────────────────────────────────────────────────────

def _panel_with_failures(n=24, days=40, seed=0):
    rng = np.random.RandomState(seed)
    rows = []
    for i in range(n):
        oid = f"obj{i}"
        dates = pd.date_range("2026-04-01", periods=days, freq="D")
        fails = i % 3 == 0
        ttf = ((dates[-1] + pd.Timedelta(days=1) - dates).days * 24.0
               if fails else np.full(days, np.nan))
        score = rng.rand(days) * (0.6 if not fails else 1.0)
        rows.append(pd.DataFrame({"object_id": oid, "date": dates,
                                  "t_to_failure": ttf, "score": score}))
    return pd.concat(rows, ignore_index=True)


def test_eval_rule_kappa_is_inspections_per_catch():
    panel = _panel_with_failures()
    mask = triggers.baseline_mask(panel, 0.8)
    result = triggers.eval_rule(panel, mask, 30)

    assert result["kappa_star"] == pytest.approx(
        result["inspections"] / result["detected"])


def test_eval_rule_no_detection_gives_infinite_kappa():
    panel = _panel_with_failures()
    result = triggers.eval_rule(panel, triggers.baseline_mask(panel, 10.0), 30)
    assert result["kappa_star"] == float("inf")


def test_sweep_returns_frontier():
    panel = _panel_with_failures()
    grid = np.quantile(panel["score"], [0.9, 0.95, 0.99])
    frontier = triggers.sweep(panel, lambda t: triggers.baseline_mask(panel, t), grid, 30)

    assert len(frontier) == 3
    assert {"detection", "kappa_star", "inspections", "threshold"} <= set(frontier.columns)


def test_build_profiles_picks_cheapest_default():
    panel = _panel_with_failures()
    chronic = {"top30": {f"obj{i}" for i in range(0, 24, 3)}}
    config = triggers.build_profiles(panel, 30, chronic, target_detection=0.3)

    assert config["default"] in config["profiles"]
    assert "cooldown_days" in config
    usable = {k: v["kappa_star"] for k, v in config["profiles"].items()
              if v.get("kappa_star") is not None}
    assert usable[config["default"]] == min(usable.values())
