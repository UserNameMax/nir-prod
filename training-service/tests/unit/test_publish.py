"""
Тесты публикации бандла (контракт ../MODEL_BUNDLE.md).

Главное свойство — АТОМАРНОСТЬ: manifest.json появляется последним и только если
все артефакты на месте. ml-service ориентируется именно на него, поэтому
неполный бандл не должен становиться видимым.
"""
import json
import pickle
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

import publish


class _FakeModel:
    """Заглушка XGBoost: умеет только save_model."""

    def __init__(self, payload=b"model-bytes"):
        self.payload = payload

    def save_model(self, path):
        Path(path).write_bytes(self.payload)


def _manifest(**over):
    base = {
        "version": "2026-08-15T10:00:00Z",
        "horizon_days": 30,
        "feature_schema": {"name": "final_h30", "service_version": "abc",
                           "n_features": 2, "columns": ["f1", "f2"]},
        "reporting": {"split": "temporal", "detection": 0.48,
                      "detection_null": 0.28, "detection_lift": 0.20},
        "models": {},
    }
    base.update(over)
    return base


def _publish(tmp_path, manifest=None, model=None):
    return publish.publish(
        str(tmp_path), "run_1",
        acute_model=model or _FakeModel(),
        acute_calibrator={"iso": 1},
        chronic_model={"rsf": 1},
        explain_aft={"aft": 1},
        manifest=manifest or _manifest(),
        trigger_config={"default": "ewma10", "cooldown_days": 14},
    )


def test_publish_writes_all_artifacts(tmp_path):
    _publish(tmp_path)
    for rel in publish.LAYOUT.values():
        assert (tmp_path / rel).exists()
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "trigger_config.json").exists()


def test_staging_removed_after_publish(tmp_path):
    _publish(tmp_path)
    assert not (tmp_path / "_tmp").exists()


def test_manifest_gets_checksums_and_run_id(tmp_path):
    manifest = _publish(tmp_path)
    assert manifest["run_id"] == "run_1"
    assert manifest["schema_version"] == publish.SCHEMA_VERSION
    assert set(manifest["checksums"]) == set(publish.LAYOUT.values())
    assert all(v.startswith("sha256:") for v in manifest["checksums"].values())


def test_checksums_match_written_files(tmp_path):
    manifest = _publish(tmp_path)
    for rel, digest in manifest["checksums"].items():
        assert publish._sha256(tmp_path / rel) == digest


def test_artifacts_are_loadable(tmp_path):
    _publish(tmp_path)
    with open(tmp_path / publish.LAYOUT["chronic_model"], "rb") as handle:
        assert pickle.load(handle) == {"rsf": 1}


def test_trigger_config_readable(tmp_path):
    _publish(tmp_path)
    with open(tmp_path / "trigger_config.json", encoding="utf-8") as handle:
        assert json.load(handle)["default"] == "ewma10"


def test_read_manifest_roundtrip(tmp_path):
    published = _publish(tmp_path)
    assert publish.read_manifest(str(tmp_path))["version"] == published["version"]


def test_read_manifest_absent(tmp_path):
    assert publish.read_manifest(str(tmp_path)) is None


# ── самопроверка: неполный бандл не публикуется ───────────────────────────────

def test_empty_artifact_blocks_publish(tmp_path):
    with pytest.raises(RuntimeError, match="пустой"):
        _publish(tmp_path, model=_FakeModel(payload=b""))
    assert not (tmp_path / "manifest.json").exists()


def test_wrong_horizon_blocks_publish(tmp_path):
    with pytest.raises(RuntimeError, match="H=30"):
        _publish(tmp_path, manifest=_manifest(horizon_days=14))
    assert not (tmp_path / "manifest.json").exists()


def test_feature_count_mismatch_blocks_publish(tmp_path):
    broken = _manifest()
    broken["feature_schema"]["n_features"] = 99
    with pytest.raises(RuntimeError, match="признаков"):
        _publish(tmp_path, manifest=broken)
    assert not (tmp_path / "manifest.json").exists()


def test_failed_publish_keeps_previous_bundle(tmp_path):
    """Провал новой публикации не портит уже работающий бандл."""
    first = _publish(tmp_path)

    with pytest.raises(RuntimeError):
        publish.publish(
            str(tmp_path), "run_2",
            acute_model=_FakeModel(payload=b""),
            acute_calibrator={}, chronic_model={}, explain_aft={},
            manifest=_manifest(version="broken"),
            trigger_config={},
        )

    assert publish.read_manifest(str(tmp_path))["version"] == first["version"]


def test_republish_replaces_bundle(tmp_path):
    _publish(tmp_path)
    second = publish.publish(
        str(tmp_path), "run_2",
        acute_model=_FakeModel(payload=b"new-model"),
        acute_calibrator={"iso": 2}, chronic_model={"rsf": 2}, explain_aft={"aft": 2},
        manifest=_manifest(version="2026-08-16T10:00:00Z"),
        trigger_config={"default": "persist5"},
    )

    assert publish.read_manifest(str(tmp_path))["version"] == second["version"]
    assert (tmp_path / publish.LAYOUT["acute_model"]).read_bytes() == b"new-model"
