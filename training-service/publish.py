"""Атомарная публикация модельного бандла (контракт ../MODEL_BUNDLE.md).

Протокол: всё пишется в `_tmp/<run_id>/`, проверяется самопроверкой, затем
атомарно переносится на место, а `manifest.json` — ПОСЛЕДНИМ. Его появление и
есть сигнал «бандл целостен»: ml-service, увидев новый manifest, знает, что все
файлы уже на месте.
"""
from __future__ import annotations
import hashlib
import json
import os
import pickle
import shutil
from pathlib import Path

SCHEMA_VERSION = "1.0"

LAYOUT = {
    "acute_model": "acute/xgb_h30.ubj",
    "acute_calibrator": "acute/isotonic_h30.pkl",
    "chronic_model": "chronic/rsf.pkl",
    "explain_aft": "explain/aft_lognormal.pkl",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def publish(bundle_dir: str, run_id: str, *, acute_model, acute_calibrator,
            chronic_model, explain_aft, manifest: dict,
            trigger_config: dict) -> dict:
    """Записать бандл атомарно. Возвращает manifest с контрольными суммами."""
    root = Path(bundle_dir)
    staging = root / "_tmp" / run_id
    if staging.exists():
        shutil.rmtree(staging)
    for sub in ("acute", "chronic", "explain"):
        (staging / sub).mkdir(parents=True, exist_ok=True)

    acute_model.save_model(str(staging / LAYOUT["acute_model"]))
    for key, obj in (("acute_calibrator", acute_calibrator),
                     ("chronic_model", chronic_model),
                     ("explain_aft", explain_aft)):
        with open(staging / LAYOUT[key], "wb") as handle:
            pickle.dump(obj, handle)

    manifest = dict(manifest)
    manifest["schema_version"] = SCHEMA_VERSION
    manifest["run_id"] = run_id
    manifest["checksums"] = {rel: _sha256(staging / rel) for rel in LAYOUT.values()}

    with open(staging / "trigger_config.json", "w", encoding="utf-8") as handle:
        json.dump(trigger_config, handle, ensure_ascii=False, indent=2)
    with open(staging / "manifest.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    _selfcheck(staging, manifest)
    _promote(staging, root)
    shutil.rmtree(staging.parent, ignore_errors=True)
    return manifest


def _selfcheck(staging: Path, manifest: dict) -> None:
    """Бандл не публикуется, если он неполон — старый остаётся валидным."""
    for rel in LAYOUT.values():
        path = staging / rel
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError(f"самопроверка: пустой или отсутствующий артефакт {rel}")
        if manifest["checksums"][rel] != _sha256(path):
            raise RuntimeError(f"самопроверка: контрольная сумма не сходится для {rel}")

    schema = manifest.get("feature_schema", {})
    if len(schema.get("columns", [])) != schema.get("n_features"):
        raise RuntimeError("самопроверка: список признаков не совпадает с n_features")
    if manifest.get("horizon_days") != 30:
        raise RuntimeError("самопроверка: операционно валиден только горизонт H=30")


def _promote(staging: Path, root: Path) -> None:
    """Перенести артефакты на место; manifest.json — последним."""
    for sub in ("acute", "chronic", "explain"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    for rel in [*LAYOUT.values(), "trigger_config.json"]:
        os.replace(staging / rel, root / rel)
    os.replace(staging / "manifest.json", root / "manifest.json")


def read_manifest(bundle_dir: str) -> dict | None:
    path = Path(bundle_dir) / "manifest.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)
