"""
Тесты решающего слоя: триггеры, схлопывание алертов в наряды, гейтинг.

Свойство, ради которого слой существует (NARRATIVE §10, Принцип 2 и §11):
алерт — это устойчивость, а не разовый выброс; серия алертов объекта в пределах
cooldown — ОДИН наряд, иначе стоимость системы считалась бы неверно.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

import decision


def _scored(scores, object_id="A", start="2026-04-01", freq="D"):
    dates = pd.date_range(start, periods=len(scores), freq=freq)
    return pd.DataFrame({"object_id": object_id, "date": dates, "score": scores})


# ── persist ───────────────────────────────────────────────────────────────────

def test_persist_ignores_single_spike():
    frame = _scored([0.1, 0.9, 0.1, 0.1])
    assert not decision.persist_mask(frame, 0.5, 3).any()


def test_persist_fires_after_n_observations():
    frame = _scored([0.9, 0.9, 0.9, 0.9])
    assert decision.persist_mask(frame, 0.5, 3).tolist() == [False, False, True, True]


def test_persist_resets_after_break():
    frame = _scored([0.9, 0.9, 0.1, 0.9, 0.9])
    assert not decision.persist_mask(frame, 0.5, 3).any()


def test_persist_independent_per_object():
    frame = pd.concat([_scored([0.9, 0.9], "A"), _scored([0.9, 0.9], "B")],
                      ignore_index=True)
    assert not decision.persist_mask(frame, 0.5, 3).any()


def test_persist_counts_observations_not_calendar():
    """Ряды разрежены: «подряд» — по наблюдениям, а не по календарю."""
    frame = pd.DataFrame({
        "object_id": "A",
        "date": pd.to_datetime(["2026-04-01", "2026-04-09", "2026-04-30"]),
        "score": [0.9, 0.9, 0.9],
    })
    assert decision.persist_mask(frame, 0.5, 3).iloc[-1]


# ── EWMA ──────────────────────────────────────────────────────────────────────

def test_ewma_damps_single_spike():
    frame = _scored([0.0, 0.0, 1.0, 0.0])
    assert not decision.ewma_mask(frame, 0.8, 10).any()


def test_ewma_fires_on_sustained_rise():
    frame = _scored([0.9] * 12)
    assert decision.ewma_mask(frame, 0.5, 5).iloc[-1]


# ── наряды и cooldown ─────────────────────────────────────────────────────────

def test_consecutive_alerts_collapse_to_one_order():
    frame = _scored([0.9] * 5)
    orders = decision.to_orders(frame, frame["score"] >= 0.5)

    assert len(orders) == 1
    assert orders.iloc[0]["alert_days"] == 5
    assert orders.iloc[0]["opened_at"] == pd.Timestamp("2026-04-01")


def test_alerts_beyond_cooldown_open_new_order():
    frame = pd.DataFrame({
        "object_id": "A",
        "date": pd.to_datetime(["2026-04-01", "2026-04-02", "2026-05-20"]),
        "score": [0.9, 0.9, 0.9],
    })
    orders = decision.to_orders(frame, frame["score"] >= 0.5, cooldown_days=14)
    assert len(orders) == 2


def test_orders_are_per_object():
    frame = pd.concat([_scored([0.9, 0.9], "A"), _scored([0.9, 0.9], "B")],
                      ignore_index=True)
    orders = decision.to_orders(frame, frame["score"] >= 0.5)
    assert set(orders["object_id"]) == {"A", "B"}
    assert len(orders) == 2


def test_no_alerts_no_orders():
    frame = _scored([0.1, 0.2])
    assert decision.to_orders(frame, frame["score"] >= 0.5).empty


def test_orders_sorted_by_peak_score():
    frame = pd.concat([_scored([0.6], "A"), _scored([0.95], "B")], ignore_index=True)
    orders = decision.to_orders(frame, frame["score"] >= 0.5)
    assert orders.iloc[0]["object_id"] == "B"


# ── очередь ───────────────────────────────────────────────────────────────────

def test_queue_applies_gating():
    frame = pd.concat([_scored([0.9], "A"), _scored([0.9], "B")], ignore_index=True)
    orders = decision.queue(frame, {"type": "baseline"}, 0.5, chronic_top={"A"})
    assert set(orders["object_id"]) == {"A"}


def test_queue_filters_by_date_window():
    """Наряд виден в день открытия и пока не остыл."""
    frame = _scored([0.9] * 3, start="2026-04-01")

    active = decision.queue(frame, {"type": "baseline"}, 0.5,
                            date="2026-04-05", cooldown_days=14)
    stale = decision.queue(frame, {"type": "baseline"}, 0.5,
                           date="2026-06-01", cooldown_days=14)
    future = decision.queue(frame, {"type": "baseline"}, 0.5,
                            date="2026-03-01", cooldown_days=14)

    assert len(active) == 1
    assert stale.empty
    assert future.empty


def test_queue_uses_profile_type():
    frame = _scored([0.9, 0.1, 0.9, 0.1])
    baseline = decision.queue(frame, {"type": "baseline"}, 0.5)
    persistent = decision.queue(frame, {"type": "persist", "n": 3}, 0.5)

    assert len(baseline) > 0
    assert persistent.empty


def test_build_mask_dispatches_by_type():
    frame = _scored([0.9] * 6)
    assert decision.build_mask(frame, {"type": "baseline"}, 0.5).all()
    assert decision.build_mask(frame, {"type": "persist", "n": 3}, 0.5).iloc[-1]
    assert decision.build_mask(frame, {"type": "ewma", "span": 3}, 0.5).iloc[-1]
