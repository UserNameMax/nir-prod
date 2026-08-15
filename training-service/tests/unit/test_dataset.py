"""
Тесты сборки выборки: разметка горизонта, temporal split, object-level.

Разметка — самое ответственное место: ошибка здесь тихо испортит все метрики.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

import dataset


def _features(objects=("A", "B"), start="2026-01-01", days=60):
    rows = []
    for obj in objects:
        dates = pd.date_range(start, periods=days, freq="D")
        rows.append(pd.DataFrame({"object_id": obj, "date": dates,
                                  "f1": np.linspace(0, 1, days),
                                  "f2": np.arange(days, dtype=float)}))
    return pd.concat(rows, ignore_index=True)


def _incident(obj, when):
    return pd.DataFrame({"object_id": [obj], "incident_ts": [pd.Timestamp(when)]})


# ── разметка ──────────────────────────────────────────────────────────────────

def test_no_incidents_gives_all_negative():
    frame = dataset.add_target(_features(), pd.DataFrame(columns=["object_id", "incident_ts"]))
    assert frame["t_to_failure"].isna().all()
    assert (frame["y"] == 0).all()


def test_hours_until_next_incident():
    """t_to_failure считается от конца дня до аварии."""
    frame = dataset.add_target(_features(objects=("A",), days=10),
                               _incident("A", "2026-01-06"))
    day = frame[frame["date"] == pd.Timestamp("2026-01-01")].iloc[0]
    # с конца 1 января до 6 января — 4 суток
    assert day["t_to_failure"] == pytest.approx(96.0)


def test_incident_within_day_is_small_positive():
    """День самой аварии остаётся предаварийным (попадает в окно детекции)."""
    frame = dataset.add_target(_features(objects=("A",), days=10),
                               _incident("A", "2026-01-05 10:34"))
    day = frame[frame["date"] == pd.Timestamp("2026-01-05")].iloc[0]
    assert 0 < day["t_to_failure"] <= 24


def test_target_horizon():
    frame = dataset.add_target(_features(objects=("A",), days=60),
                               _incident("A", "2026-02-20"))
    inside = frame[frame["t_to_failure"] <= dataset.HORIZON_DAYS * 24]
    assert (inside["y"] == 1).all()
    assert (frame.loc[frame["t_to_failure"] > dataset.HORIZON_DAYS * 24, "y"] == 0).all()


def test_past_incidents_not_counted():
    """Авария в прошлом не размечает последующие дни (смотрим только вперёд)."""
    frame = dataset.add_target(_features(objects=("A",), days=10),
                               _incident("A", "2025-12-01"))
    assert frame["t_to_failure"].isna().all()


def test_labels_are_per_object():
    incidents = _incident("A", "2026-01-06")
    frame = dataset.add_target(_features(objects=("A", "B"), days=10), incidents)
    assert frame[frame.object_id == "A"]["y"].sum() > 0
    assert frame[frame.object_id == "B"]["y"].sum() == 0


def test_nearest_of_several_incidents():
    incidents = pd.concat([_incident("A", "2026-01-20"), _incident("A", "2026-01-06")])
    frame = dataset.add_target(_features(objects=("A",), days=30), incidents)
    day = frame[frame["date"] == pd.Timestamp("2026-01-01")].iloc[0]
    assert day["t_to_failure"] == pytest.approx(96.0)   # ближайшая, не последняя


# ── temporal split ────────────────────────────────────────────────────────────

def test_explicit_cutoffs():
    frame = dataset.temporal_split(_features(objects=("A",), days=90),
                                   val_start="2026-02-01", test_start="2026-03-01")
    assert frame[frame.date < "2026-02-01"]["split"].eq("train").all()
    assert frame[(frame.date >= "2026-02-01") & (frame.date < "2026-03-01")]["split"].eq("val").all()
    assert frame[frame.date >= "2026-03-01"]["split"].eq("test").all()


def test_split_is_pure_function_of_date():
    """Никакой карты объектов: одна и та же дата всегда в одном split."""
    frame = dataset.temporal_split(_features(objects=("A", "B", "C"), days=90))
    per_date = frame.groupby("date")["split"].nunique()
    assert (per_date == 1).all()


def test_default_cutoffs_pick_last_full_month():
    dates = pd.Series(pd.date_range("2025-10-01", "2026-05-31", freq="D"))
    val_start, test_start = dataset.default_cutoffs(dates)
    assert test_start == "2026-05-01"
    assert val_start == "2026-04-01"


def test_default_cutoffs_skip_incomplete_month():
    """Последний месяц оборван — берём предыдущий как test."""
    dates = pd.Series(pd.date_range("2025-10-01", "2026-05-10", freq="D"))
    val_start, test_start = dataset.default_cutoffs(dates)
    assert test_start == "2026-04-01"
    assert val_start == "2026-03-01"


def test_inverted_cutoffs_rejected():
    with pytest.raises(ValueError):
        dataset.temporal_split(_features(), val_start="2026-03-01", test_start="2026-02-01")


# ── object-level ──────────────────────────────────────────────────────────────

def test_object_level_one_row_per_object():
    frame = dataset.add_target(_features(days=60), _incident("A", "2026-02-10"))
    frame = dataset.temporal_split(frame, "2026-02-01", "2026-02-15")
    objects = dataset.object_level(frame, ["f1", "f2"])

    assert len(objects) == 2
    assert set(objects["object_id"]) == {"A", "B"}


def test_object_level_event_and_censoring():
    frame = dataset.add_target(_features(days=60), _incident("A", "2026-02-10"))
    frame = dataset.temporal_split(frame, "2026-02-01", "2026-02-15")
    objects = dataset.object_level(frame, ["f1", "f2"]).set_index("object_id")

    assert objects.loc["A", "event"] == 1
    assert objects.loc["B", "event"] == 0        # без аварии — цензурирован
    assert objects.loc["A", "duration"] == pytest.approx(40.0, abs=1.0)


def test_object_level_baseline_excludes_future():
    """Baseline-признаки берутся только из первых дней, до события."""
    frame = dataset.add_target(_features(objects=("A",), days=60),
                               _incident("A", "2026-02-10"))
    frame = dataset.temporal_split(frame, "2026-02-01", "2026-02-15")
    objects = dataset.object_level(frame, ["f2"], baseline_days=14)

    # f2 = номер дня; медиана первых 14 дней — около 6.5
    assert objects.iloc[0]["f2"] == pytest.approx(6.5, abs=0.5)
