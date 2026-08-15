"""
Интеграционный тест полного прогона обучения (соседние сервисы замоканы).

Проверяет, что стадии сходятся вместе и на выходе — валидный бандл по контракту
../MODEL_BUNDLE.md, включая честную отчётность (детекция всегда с полом и lift).
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

import clients
import publish
import run


FEATURES = ["f_trend", "f_noise", "f_season"]


def _synthetic(n_objects=60, days=150, seed=0):
    """Панель с зашитым сигналом: у аварийных объектов f_trend растёт к аварии."""
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2026-01-01", periods=days, freq="D")
    rows, incidents = [], []

    for i in range(n_objects):
        oid = f"obj{i}"
        fails = i % 3 == 0
        trend = rng.normal(0, 1, days)
        if fails:
            fail_day = dates[int(days * 0.75) + (i % 20)]
            ramp = np.clip(1 - (fail_day - dates).days / 40.0, 0, 1)
            trend = trend + 4.0 * ramp
            incidents.append({"object_id": oid, "incident_ts": fail_day})

        rows.append(pd.DataFrame({
            "object_id": oid,
            "date": dates,
            "f_trend": trend,
            "f_noise": rng.normal(0, 1, days),
            "f_season": np.sin(np.arange(days) / 30.0),
        }))

    return pd.concat(rows, ignore_index=True), pd.DataFrame(incidents)


@pytest.fixture
def stubbed(monkeypatch):
    features, incidents = _synthetic()
    monkeypatch.setattr(clients, "fetch_features", lambda *a, **k: features)
    monkeypatch.setattr(clients, "fetch_incidents", lambda *a, **k: incidents)
    monkeypatch.setattr(clients, "fetch_schema", lambda: {
        "name": "final_h30", "version": "test-schema-v1",
        "n_features": len(FEATURES), "columns": FEATURES,
    })
    return features, incidents


def test_full_run_publishes_bundle(tmp_path, stubbed):
    seen = []
    manifest = run.train_bundle(str(tmp_path), val_start="2026-04-01",
                                test_start="2026-05-01",
                                progress=seen.append)

    assert seen == ["fetch", "dataset", "train_acute", "train_chronic",
                    "train_explain", "triggers", "validate", "publish"]
    for rel in publish.LAYOUT.values():
        assert (tmp_path / rel).exists()
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "trigger_config.json").exists()


def test_manifest_contract(tmp_path, stubbed):
    manifest = run.train_bundle(str(tmp_path), val_start="2026-04-01",
                                test_start="2026-05-01")

    assert manifest["horizon_days"] == 30
    assert manifest["feature_schema"]["service_version"] == "test-schema-v1"
    assert manifest["feature_schema"]["columns"] == FEATURES
    assert manifest["alert_threshold"]["alert_rate"] == 0.02
    assert manifest["alert_threshold"]["policy"] == "budget_quantile"
    assert set(manifest["models"]) == {"acute", "chronic", "explain_aft"}
    assert manifest["data_window"]["test"] is not None


def test_reporting_is_temporal_and_has_null(tmp_path, stubbed):
    """Отчётность честная: детекция всегда рядом с полом и lift."""
    manifest = run.train_bundle(str(tmp_path), val_start="2026-04-01",
                                test_start="2026-05-01")
    report = manifest["reporting"]

    assert report["split"] == "temporal"
    for key in ("detection", "detection_null", "detection_lift",
                "lift_p_value", "roc_auc", "n_events"):
        assert key in report, key
    assert report["detection_lift"] == pytest.approx(
        report["detection"] - report["detection_null"], abs=1e-9)


def test_threshold_matches_alert_budget(tmp_path, stubbed):
    manifest = run.train_bundle(str(tmp_path), val_start="2026-04-01",
                                test_start="2026-05-01", alert_rate=0.05)
    assert manifest["alert_threshold"]["alert_rate"] == 0.05
    assert 0.0 <= manifest["alert_threshold"]["raw_score_threshold"] <= 1.0


def test_trigger_config_written(tmp_path, stubbed):
    run.train_bundle(str(tmp_path), val_start="2026-04-01", test_start="2026-05-01")
    with open(tmp_path / "trigger_config.json", encoding="utf-8") as handle:
        config = json.load(handle)

    assert config["default"] in config["profiles"]
    assert config["cooldown_days"] == 14
    assert any(name.startswith("ewma") for name in config["profiles"])
    assert any(name.startswith("gate_") for name in config["profiles"])


def test_signal_is_learned(tmp_path, stubbed):
    """Зашитый сигнал модель должна поймать — иначе пайплайн собран неверно."""
    manifest = run.train_bundle(str(tmp_path), val_start="2026-04-01",
                                test_start="2026-05-01")
    assert manifest["reporting"]["roc_auc"] > 0.6


def test_chronic_c_index_reported(tmp_path, stubbed):
    manifest = run.train_bundle(str(tmp_path), val_start="2026-04-01",
                                test_start="2026-05-01")
    assert manifest["models"]["chronic"]["c_index"] is not None


def test_run_without_incidents_fails_clearly(tmp_path, monkeypatch, stubbed):
    monkeypatch.setattr(clients, "fetch_incidents",
                        lambda *a, **k: pd.DataFrame(columns=["object_id", "incident_ts"]))
    with pytest.raises(ValueError, match="аварий"):
        run.train_bundle(str(tmp_path), val_start="2026-04-01", test_start="2026-05-01")


def test_run_without_features_fails_clearly(tmp_path, monkeypatch, stubbed):
    monkeypatch.setattr(clients, "fetch_features", lambda *a, **k: pd.DataFrame())
    with pytest.raises(ValueError, match="признаки"):
        run.train_bundle(str(tmp_path), val_start="2026-04-01", test_start="2026-05-01")


def test_empty_split_fails_clearly(tmp_path, stubbed):
    """Границы вне периода данных → понятная ошибка, а не пустое обучение."""
    with pytest.raises(ValueError, match="split"):
        run.train_bundle(str(tmp_path), val_start="2027-01-01", test_start="2027-02-01")
