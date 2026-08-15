"""
Тесты загрузки бандла (контракт ../MODEL_BUNDLE.md §2).

Главный инвариант — TRAIN/SERVE PARITY: бандл, обученный на одной схеме
признаков, не должен обслуживать другую. Молча отдавать скоры в такой ситуации
опаснее, чем отказать.
"""
import hashlib
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pytest
import xgboost as xgb

sys.path.insert(0, str(Path(__file__).parents[2]))

import loader

SCHEMA_VERSION = "abc123"
FEATURES = ["f1", "f2"]


def _make_bundle(root: Path, *, schema_version=SCHEMA_VERSION, horizon=30,
                 contract="1.0", corrupt=None, drop=None,
                 baseline_days=loader.BASELINE_DAYS):
    for sub in ("acute", "chronic", "explain"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    model = xgb.XGBClassifier(n_estimators=3, max_depth=2)
    model.fit(np.random.RandomState(0).rand(40, 2), np.r_[np.zeros(20), np.ones(20)])
    model.save_model(str(root / "acute/xgb_h30.ubj"))

    for rel, obj in (("acute/isotonic_h30.pkl", {"iso": 1}),
                     ("chronic/rsf.pkl", {"rsf": 1}),
                     ("explain/aft_lognormal.pkl", {"aft": 1})):
        with open(root / rel, "wb") as handle:
            pickle.dump(obj, handle)

    layout = ["acute/xgb_h30.ubj", "acute/isotonic_h30.pkl",
              "chronic/rsf.pkl", "explain/aft_lognormal.pkl"]

    # Суммы считаются от ИСХОДНЫХ файлов — порча вносится после, чтобы
    # проверка действительно ловила расхождение.
    checksums = {rel: "sha256:" + hashlib.sha256((root / rel).read_bytes()).hexdigest()
                 for rel in layout}

    if drop:
        (root / drop).unlink()
        checksums.pop(drop, None)
    if corrupt:
        (root / corrupt).write_bytes(b"tampered")

    manifest = {
        "schema_version": contract,
        "version": "2026-08-15T10:00:00Z",
        "horizon_days": horizon,
        "feature_schema": {"name": "final_h30", "service_version": schema_version,
                           "n_features": len(FEATURES), "columns": FEATURES},
        "alert_threshold": {"raw_score_threshold": 0.7, "alert_rate": 0.02},
        "reporting": {"split": "temporal", "detection": 0.37,
                      "detection_null": 0.35, "detection_lift": 0.02},
        "object_survival_recon": {"baseline_days": baseline_days, "merge_gap": 7},
        "models": {
            "acute": {"file": "acute/xgb_h30.ubj",
                      "calibrator": "acute/isotonic_h30.pkl"},
            "chronic": {"file": "chronic/rsf.pkl"},
            "explain_aft": {"file": "explain/aft_lognormal.pkl"},
        },
        "checksums": checksums,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "trigger_config.json").write_text(
        json.dumps({"default": "ewma10", "cooldown_days": 14,
                    "profiles": {"ewma10": {"type": "ewma", "span": 10,
                                            "threshold": 0.7, "kappa_star": 5.5}}}),
        encoding="utf-8")
    return manifest


def test_loads_valid_bundle(tmp_path):
    _make_bundle(tmp_path)
    bundle = loader.load(str(tmp_path), expected_schema_version=SCHEMA_VERSION)

    assert bundle.feature_columns == FEATURES
    assert bundle.alert_threshold == 0.7
    assert bundle.trigger_config["default"] == "ewma10"
    assert bundle.schema_version == SCHEMA_VERSION


def test_missing_manifest(tmp_path):
    with pytest.raises(loader.BundleError, match="не опубликован"):
        loader.load(str(tmp_path))


def test_schema_mismatch_is_refused(tmp_path):
    """Ядро parity: бандл другой схемы к обслуживанию не допускается."""
    _make_bundle(tmp_path, schema_version="old-schema")
    with pytest.raises(loader.BundleError, match="skew"):
        loader.load(str(tmp_path), expected_schema_version="new-schema")


def test_schema_check_skipped_when_not_requested(tmp_path):
    _make_bundle(tmp_path, schema_version="whatever")
    assert loader.load(str(tmp_path)).schema_version == "whatever"


def test_wrong_horizon_refused(tmp_path):
    """Операционно валиден только H=30 (NARRATIVE §7)."""
    _make_bundle(tmp_path, horizon=14)
    with pytest.raises(loader.BundleError, match="H=30"):
        loader.load(str(tmp_path))


def test_incompatible_contract_major_refused(tmp_path):
    _make_bundle(tmp_path, contract="2.0")
    with pytest.raises(loader.BundleError, match="несовместимая версия"):
        loader.load(str(tmp_path))


def test_missing_artifact_refused(tmp_path):
    _make_bundle(tmp_path, drop="chronic/rsf.pkl")
    with pytest.raises(loader.BundleError, match="отсутствует"):
        loader.load(str(tmp_path))


def test_checksum_mismatch_refused(tmp_path):
    """Подменённый артефакт не должен обслуживаться."""
    _make_bundle(tmp_path, corrupt="chronic/rsf.pkl")
    with pytest.raises(loader.BundleError, match="сумма"):
        loader.load(str(tmp_path))


def test_baseline_days_mismatch_refused(tmp_path):
    """Object-level срез должен считаться так же, как при обучении.

    Иначе хроника и AFT получают признаки не с того окна — скор молча «поедет»,
    оставаясь на вид правдоподобным.
    """
    _make_bundle(tmp_path, baseline_days=loader.BASELINE_DAYS + 5)
    with pytest.raises(loader.BundleError, match="baseline_days"):
        loader.load(str(tmp_path))


def test_bundle_without_recon_section_is_accepted(tmp_path):
    """Старый бандл без секции — не повод отказывать (проверять нечего)."""
    _make_bundle(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    del manifest["object_survival_recon"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert loader.load(str(tmp_path)) is not None


def test_bundle_exposes_manifest_fields(tmp_path):
    _make_bundle(tmp_path)
    bundle = loader.load(str(tmp_path))
    assert bundle.version == "2026-08-15T10:00:00Z"
    assert bundle.manifest["reporting"]["split"] == "temporal"
