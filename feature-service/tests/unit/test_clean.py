"""
Тесты очистки сырья (перенос `features/01_dedup.ipynb`).

Без этого этапа дневные агрегаты считались по грязному потоку: нули от
отключённых датчиков выглядели как обвалы давления и ломали всю физику набора.
Эксперимент показал, что именно этот шаг определял операционное качество модели.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

import pipeline
from pipeline import clean

from .test_pipeline import make_sensors, make_weather


def _rows(ts, **over):
    base = {"object_id": "A", "t_supply": 70.0, "t_return": 50.0,
            "p_supply": 6.0, "p_return": 4.0}
    base.update(over)
    return pd.DataFrame({**{k: [v] * len(ts) for k, v in base.items()},
                         "ts_recorded": pd.to_datetime(ts, format="mixed")})


# ── битые метки времени ───────────────────────────────────────────────────────

def test_drops_pre_2025_rows():
    df = _rows(["1970-01-01", "2026-01-01"])
    out = clean.run(df)
    assert len(out) == 1
    assert out["ts_recorded"].iloc[0].year == 2026


def test_keeps_all_valid_timestamps():
    df = _rows(["2025-10-01", "2026-05-27"])
    assert len(clean.run(df)) == 2


# ── физические границы ────────────────────────────────────────────────────────

@pytest.mark.parametrize("col", ["t_supply", "t_return", "p_supply", "p_return"])
def test_zero_becomes_nan(col):
    """Ноль — это «датчик offline», а не измерение.

    Именно выжившие нули ломали признаки просадки давления.
    """
    df = _rows(["2026-01-01"], **{col: 0.0})
    assert pd.isna(clean.run(df)[col].iloc[0])


def test_out_of_range_becomes_nan():
    df = _rows(["2026-01-01", "2026-01-01 00:15"])
    df.loc[0, "t_supply"] = 999.0
    df.loc[1, "p_supply"] = 100.0
    out = clean.run(df).sort_values("ts_recorded").reset_index(drop=True)
    assert pd.isna(out["t_supply"].iloc[0])
    assert pd.isna(out["p_supply"].iloc[1])


def test_valid_values_untouched():
    df = _rows(["2026-01-01"])
    out = clean.run(df)
    assert out["t_supply"].iloc[0] == 70.0
    assert out["p_supply"].iloc[0] == 6.0


def test_row_is_kept_when_one_sensor_invalid():
    """Плохое значение обнуляется, но строка остаётся — другие датчики полезны."""
    df = _rows(["2026-01-01"], p_supply=0.0)
    out = clean.run(df)
    assert len(out) == 1
    assert out["t_supply"].iloc[0] == 70.0


# ── дедупликация ──────────────────────────────────────────────────────────────

def test_duplicates_collapse_to_one_row():
    df = _rows(["2026-01-01", "2026-01-01"])
    assert len(clean.run(df)) == 1


def test_duplicates_are_averaged():
    """Дубли усредняются, как в research, а не «берём первый»."""
    df = _rows(["2026-01-01", "2026-01-01"])
    df.loc[1, "t_supply"] = 80.0
    assert clean.run(df)["t_supply"].iloc[0] == pytest.approx(75.0)


def test_average_skips_nan():
    df = _rows(["2026-01-01", "2026-01-01"])
    df.loc[1, "t_supply"] = 0.0          # уйдёт в NaN и не должен тянуть среднее вниз
    assert clean.run(df)["t_supply"].iloc[0] == pytest.approx(70.0)


def test_dedup_key_is_measurement_time():
    """Дубли схлопываются по моменту ИЗМЕРЕНИЯ, а не записи в систему.

    Одно физическое показание попадает в перекрывающиеся выгрузки с разным
    ts_recorded. Дедуп по времени записи такие дубли не ловит — на боевых данных
    это давало 49.1 млн строк вместо 43.1 млн и разрушало операционное качество
    модели (lift −0.04 против +0.21).
    """
    df = _rows(["2026-01-01 00:00", "2026-01-01 06:00"])   # запись в разное время
    df["ts_measurement"] = 1767225600                       # одно и то же измерение
    df.loc[1, "t_supply"] = 80.0

    out = clean.run(df)

    assert len(out) == 1
    assert out["t_supply"].iloc[0] == pytest.approx(75.0)


def test_dedup_keeps_first_recorded_time():
    """ts_recorded берётся первым — он задаёт сутки и часовые окна дальше."""
    df = _rows(["2026-01-01 00:00", "2026-01-01 06:00"])
    df["ts_measurement"] = 1767225600

    out = clean.run(df)
    assert out["ts_recorded"].iloc[0] == pd.Timestamp("2026-01-01 00:00")


def test_distinct_measurements_survive_same_record_time():
    """Разные измерения с одинаковым ts_recorded не схлопываются."""
    df = _rows(["2026-01-01 00:00", "2026-01-01 00:00"])
    df["ts_measurement"] = [1767225600, 1767226500]

    assert len(clean.run(df)) == 2


def test_dedup_is_per_object():
    df = pd.concat([_rows(["2026-01-01"]), _rows(["2026-01-01"], object_id="B")],
                   ignore_index=True)
    assert len(clean.run(df)) == 2


def test_distinct_timestamps_preserved():
    df = _rows(["2026-01-01", "2026-01-01 00:15", "2026-01-01 00:30"])
    assert len(clean.run(df)) == 3


def test_empty_input():
    assert clean.run(pd.DataFrame()).empty


# ── интеграция с пайплайном ───────────────────────────────────────────────────

def test_pipeline_applies_cleaning():
    """Грязные строки не доезжают до агрегатов."""
    sensors = make_sensors(days=20, objects=("A",))
    dirty = sensors.copy()
    dirty.loc[dirty.index[:50], "p_supply"] = 0.0          # «датчик offline»

    clean_matrix = pipeline.build_matrix(sensors, make_weather(days=20))
    dirty_matrix = pipeline.build_matrix(dirty, make_weather(days=20))

    first_day = clean_matrix["date"].min()
    a = clean_matrix[clean_matrix.date == first_day]["p_drop_night"].iloc[0]
    b = dirty_matrix[dirty_matrix.date == first_day]["p_drop_night"].iloc[0]
    # нули отброшены, а не приняты за обвал давления
    assert not (pd.notna(b) and abs(b) > abs(a) * 10)


def test_cleaning_survives_chunking(monkeypatch):
    sensors = make_sensors(days=15, objects=("A", "B", "C"))
    weather = make_weather(days=15)

    whole = pipeline.build_matrix(sensors, weather)
    monkeypatch.setattr(pipeline, "CHUNK_OBJECTS", 1)
    chunked = pipeline.build_matrix(sensors, weather)

    pd.testing.assert_frame_equal(whole, chunked)


def test_duplicated_input_gives_same_features():
    """Дублирование потока не должно менять признаки — иначе агрегаты «плывут»."""
    sensors = make_sensors(days=15, objects=("A",))
    doubled = pd.concat([sensors, sensors], ignore_index=True)
    weather = make_weather(days=15)

    pd.testing.assert_frame_equal(
        pipeline.build_matrix(sensors, weather),
        pipeline.build_matrix(doubled, weather),
    )
