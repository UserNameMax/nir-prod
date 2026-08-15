"""
Тесты пайплайна признаков.

Главное, что здесь проверяется — КАУЗАЛЬНОСТЬ: признак дня t не должен зависеть от
данных после t. Аудит утечек (NARRATIVE §8) нашёл в G4-кривой look-ahead; тест
`test_*_is_causal` падает, если fit снова начнёт смотреть в будущее.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

import pipeline
import schema
from pipeline import intraday, interday


def make_sensors(days=40, objects=("A", "B"), start="2026-01-01", freq="15min"):
    """Синтетические показания: сезонный ход + суточный профиль с ночным провалом."""
    rows = []
    for obj in objects:
        idx = pd.date_range(start, periods=days * 96, freq=freq)
        hour = idx.hour.to_numpy()
        night = (hour >= 2) & (hour < 3)
        day_num = (idx - idx[0]).days.to_numpy()
        rows.append(pd.DataFrame({
            "object_id": obj,
            "ts_recorded": idx,
            "t_supply": 70.0 - 0.05 * day_num + np.sin(hour / 24 * 2 * np.pi),
            "t_return": 50.0 - 0.02 * day_num,
            "p_supply": 6.0 - 0.3 * night + 0.01 * day_num,
            "p_return": 4.0 + 0.005 * day_num,
        }))
    return pd.concat(rows, ignore_index=True)


def make_weather(days=40, start="2026-01-01"):
    dates = pd.date_range(start, periods=days, freq="D")
    return pd.DataFrame({
        "date": dates,
        "t_out_mean": -10 + 20 * np.linspace(0, 1, days),
    })


# ── контракт колонок ──────────────────────────────────────────────────────────

def test_matrix_has_exact_schema_columns():
    matrix = pipeline.build_matrix(make_sensors(), make_weather())
    assert list(matrix.columns) == [*schema.KEYS, *schema.FEATURES]


def test_schema_has_31_features():
    assert len(schema.FEATURES) == 31
    assert len(set(schema.FEATURES)) == 31


def test_schema_version_deterministic():
    assert schema.version() == schema.version()
    assert len(schema.version()) == 16


def test_empty_input_keeps_contract():
    empty = pd.DataFrame(columns=["object_id", "ts_recorded", "t_supply",
                                  "t_return", "p_supply", "p_return"])
    matrix = pipeline.build_matrix(empty, make_weather())
    assert list(matrix.columns) == [*schema.KEYS, *schema.FEATURES]
    assert matrix.empty


def test_missing_feature_column_filled_with_nan():
    """Контракт колонок соблюдается, даже если признак не посчитался."""
    frame = pd.DataFrame({"object_id": ["A"], "date": [pd.Timestamp("2026-01-01")]})
    out = pipeline.select(frame)
    assert list(out.columns) == [*schema.KEYS, *schema.FEATURES]
    assert out[list(schema.FEATURES)].isna().all().all()


def test_one_row_per_object_day():
    matrix = pipeline.build_matrix(make_sensors(days=10), make_weather(days=10))
    assert not matrix.duplicated(subset=["object_id", "date"]).any()
    assert len(matrix) == 20  # 2 объекта × 10 дней


# ── каузальность ──────────────────────────────────────────────────────────────

def _causality_probe(feature_cols, days=40):
    """Строит матрицу дважды: на полной истории и с изменённым «будущим».

    Признаки прошлого обязаны совпасть — иначе в пайплайне look-ahead.
    """
    sensors = make_sensors(days=days)
    weather = make_weather(days=days)
    cut = pd.Timestamp("2026-01-01") + pd.Timedelta(days=days // 2)

    tampered = sensors.copy()
    future = tampered["ts_recorded"] >= cut
    tampered.loc[future, ["t_supply", "t_return", "p_supply", "p_return"]] *= 3.0

    base = pipeline.build_matrix(sensors, weather)
    other = pipeline.build_matrix(tampered, weather)

    past = base["date"] < cut
    return base.loc[past, feature_cols], other.loc[other["date"] < cut, feature_cols]


@pytest.mark.parametrize("feature", [
    "dt_vs_expected",
    "t_supply_vs_curve_slope_7d",
    "t_supply_vs_curve_slope_30d",
    "p_supply_robust_z",
    "dp_slope_30d",
    "ewma_cross_dp",
    "days_since_last_anomaly",
])
def test_feature_is_causal(feature):
    """Изменение будущих показаний не меняет признаки прошлых дней."""
    before, after = _causality_probe([feature])
    pd.testing.assert_series_equal(before[feature], after[feature],
                                   check_names=False, rtol=1e-9)


def test_chunked_aggregation_matches_single_pass(monkeypatch):
    """Резка внутрисуточного этапа по объектам не меняет результат.

    Чанкование введено, чтобы удержать пик памяти на полной сети; оно допустимо
    только потому, что этап не смотрит за пределы объекта.
    """
    sensors = make_sensors(days=20, objects=("A", "B", "C", "D"))
    weather = make_weather(days=20)

    whole = pipeline.build_matrix(sensors, weather)
    monkeypatch.setattr(pipeline, "CHUNK_OBJECTS", 1)
    chunked = pipeline.build_matrix(sensors, weather)

    pd.testing.assert_frame_equal(whole, chunked)


def test_curve_residual_uses_only_past():
    """G4 напрямую: остаток дня t не зависит от строк после t.

    Именно здесь был найден look-ahead (polyfit по всей истории объекта).
    """
    days = 60
    frame = pd.DataFrame({
        "object_id": "A",
        "date": pd.date_range("2026-01-01", periods=days, freq="D"),
        "t_supply_mean": np.linspace(70, 60, days),
        "t_out_mean": np.linspace(-15, 10, days),
    })
    full = interday.fit_curve_residual(frame, "t_supply_mean").to_numpy()

    cut = 40
    truncated = interday.fit_curve_residual(
        frame.iloc[:cut].copy(), "t_supply_mean").to_numpy()

    np.testing.assert_allclose(full[:cut], truncated, rtol=1e-9)


def test_features_independent_of_batch_composition():
    """Признаки объекта не зависят от того, какие ДРУГИЕ объекты в батче.

    Это и есть train/serve parity: обучение идёт по всей сети, инференс может
    прийти по одному объекту — значения обязаны совпасть. Свойство держится
    заморозкой SCALE_FLOOR (иначе пол считался бы по составу батча).
    """
    weather = make_weather(days=40)
    together = pipeline.build_matrix(make_sensors(days=40, objects=("A", "B")), weather)
    alone = pipeline.build_matrix(make_sensors(days=40, objects=("A",)), weather)

    left = together[together["object_id"] == "A"].reset_index(drop=True)
    pd.testing.assert_frame_equal(left, alone, rtol=1e-9)


def test_curve_residual_nan_before_min_points():
    """До накопления min_pts наблюдений остаток не определён."""
    days = 30
    frame = pd.DataFrame({
        "object_id": "A",
        "date": pd.date_range("2026-01-01", periods=days, freq="D"),
        "y": np.linspace(1, 10, days),
        "t_out_mean": np.linspace(-5, 5, days),
    })
    resid = interday.fit_curve_residual(frame, "y")
    assert resid.iloc[:interday.CURVE_MIN_PTS - 1].isna().all()
    assert resid.iloc[interday.CURVE_MIN_PTS:].notna().any()


# ── внутрисуточные окна ───────────────────────────────────────────────────────

def test_night_window_captures_dip():
    """Ночной провал давления виден в p_drop_night (дневное − ночное)."""
    matrix = intraday.build(make_sensors(days=5))
    assert (matrix["p_drop_night"] > 0.2).all()


def test_n_samples_counts_measurements():
    matrix = intraday.build(make_sensors(days=3, objects=("A",)))
    assert (matrix["n_samples"] == 96).all()


def test_low_coverage_flag():
    from pipeline import daily

    frame = pd.DataFrame({
        "object_id": ["A", "B"],
        "date": [pd.Timestamp("2026-01-01")] * 2,
        "n_samples": [96, 3],
    })
    out = daily.build(frame, make_weather(days=1))
    assert out["low_coverage"].tolist() == [0, 1]


def test_calendar_features_are_cyclic():
    from pipeline import daily

    frame = pd.DataFrame({
        "object_id": ["A"],
        "date": [pd.Timestamp("2026-03-15")],
        "n_samples": [96],
    })
    out = daily.build(frame, make_weather(days=1))
    assert np.isclose(out["sin_month"] ** 2 + out["cos_month"] ** 2, 1.0).all()
    assert np.isclose(out["sin_weekday"] ** 2 + out["cos_weekday"] ** 2, 1.0).all()


def test_features_survive_missing_weather():
    """Без погоды физика не считается, но контракт колонок держится."""
    sensors = make_sensors(days=20)
    no_weather = pd.DataFrame(columns=["date", "t_out_mean"])
    matrix = pipeline.build_matrix(sensors, no_weather)

    assert list(matrix.columns) == [*schema.KEYS, *schema.FEATURES]
    assert matrix["dt_vs_expected"].isna().all()
    assert matrix["dp_std"].notna().any()      # непогодные признаки на месте


def test_no_infinities_in_matrix():
    """Матрица не содержит inf — иначе падает XGBoost на обучении.

    Отношения вида dp_night/dp_day расходятся при нулевом знаменателе;
    контракт требует конечных значений либо NaN.
    """
    frame = pd.DataFrame({
        "object_id": ["A", "A"],
        "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
        "dp_night_ratio": [np.inf, -np.inf],
        "dp_vol_ratio": [np.inf, 1.0],
    })
    out = pipeline.select(frame)

    assert out["dp_night_ratio"].isna().all()
    assert out["dp_vol_ratio"].tolist()[1] == 1.0
    numeric = out.select_dtypes(include=[np.number]).to_numpy(dtype=float)
    assert not np.isinf(numeric).any()


def test_matrix_from_real_shaped_input_is_finite():
    """Сквозной прогон: ни одного inf на выходе пайплайна."""
    sensors = make_sensors(days=30)
    # зануляем дневное окно у объекта B → знаменатель отношения станет нулевым
    night = sensors["ts_recorded"].dt.hour.between(10, 19)
    sensors.loc[night & (sensors.object_id == "B"), ["p_supply", "p_return"]] = 0.0

    matrix = pipeline.build_matrix(sensors, make_weather(days=30))
    numeric = matrix.select_dtypes(include=[np.number])
    assert not np.isinf(numeric.fillna(0).to_numpy(dtype=float)).any()


def test_nan_preserved_not_zero_filled():
    """Пропуски остаются NaN — XGBoost ест их нативно (NARRATIVE §10, Слой 0)."""
    matrix = pipeline.build_matrix(make_sensors(days=10), make_weather(days=10))
    # 30-дневные окна на 10 днях истории не наполняются
    assert matrix["dp_slope_30d"].isna().any()
