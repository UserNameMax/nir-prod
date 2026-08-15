"""Загрузка модельного бандла и сверка контракта (../MODEL_BUNDLE.md §2).

Инварианты проверяются ДО того, как бандл станет рабочим. Ключевой из них —
совпадение версии схемы признаков с feature-service: бандл, обученный на одной
схеме, к другой не подходит (train/serve skew), и молча обслуживать такой
запрос нельзя.

Старый бандл держится в памяти, пока новый не загрузился целиком: битая
публикация не должна ронять обслуживание.
"""
from __future__ import annotations
import hashlib
import json
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import xgboost as xgb

SUPPORTED_SCHEMA_MAJOR = "1"
REQUIRED_HORIZON = 30

# Окно object-level среза (Слои 1 и 4). Должно совпадать с тем, на чём обучались
# хроника и AFT: манифест несёт значение training-service, и расхождение здесь —
# это train/serve skew, который иначе прошёл бы молча.
BASELINE_DAYS = 30


class BundleError(RuntimeError):
    """Бандл отсутствует, неполон или несовместим."""


@dataclass
class Bundle:
    manifest: dict
    trigger_config: dict
    acute: xgb.XGBClassifier
    calibrator: object
    chronic: object
    aft: dict
    feature_columns: list[str] = field(default_factory=list)

    @property
    def version(self) -> str:
        return self.manifest.get("version", "")

    @property
    def schema_version(self) -> str:
        return self.manifest.get("feature_schema", {}).get("service_version", "")

    @property
    def alert_threshold(self) -> float:
        return float(self.manifest["alert_threshold"]["raw_score_threshold"])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _read_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _unpickle(path: Path):
    with open(path, "rb") as handle:
        return pickle.load(handle)


def load(bundle_dir: str, *, expected_schema_version: str | None = None) -> Bundle:
    """Прочитать бандл и проверить инварианты. Кидает BundleError при несоответствии."""
    root = Path(bundle_dir)
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise BundleError("бандл не опубликован: нет manifest.json")

    manifest = _read_json(manifest_path)

    schema_version = str(manifest.get("schema_version", ""))
    if schema_version.split(".")[0] != SUPPORTED_SCHEMA_MAJOR:
        raise BundleError(
            f"несовместимая версия контракта бандла: {schema_version!r}, "
            f"поддерживается major {SUPPORTED_SCHEMA_MAJOR}")

    if manifest.get("horizon_days") != REQUIRED_HORIZON:
        raise BundleError(
            f"операционно валиден только горизонт H={REQUIRED_HORIZON}, "
            f"в бандле {manifest.get('horizon_days')}")

    trained_baseline = manifest.get("object_survival_recon", {}).get("baseline_days")
    if trained_baseline is not None and int(trained_baseline) != BASELINE_DAYS:
        raise BundleError(
            "train/serve skew в object-level срезе: бандл обучен на "
            f"baseline_days={trained_baseline}, сервис считает по {BASELINE_DAYS}")

    if expected_schema_version is not None:
        actual = manifest.get("feature_schema", {}).get("service_version")
        if actual != expected_schema_version:
            raise BundleError(
                "train/serve skew: бандл обучен на схеме признаков "
                f"{actual!r}, а feature-service отдаёт {expected_schema_version!r}")

    models = manifest.get("models", {})
    files = {key: root / spec["file"] for key, spec in models.items() if "file" in spec}
    calibrator_rel = models.get("acute", {}).get("calibrator")
    if calibrator_rel:
        files["acute_calibrator"] = root / calibrator_rel

    for name, path in files.items():
        if not path.exists() or path.stat().st_size == 0:
            raise BundleError(f"артефакт отсутствует или пуст: {name} ({path.name})")

    for rel, expected in manifest.get("checksums", {}).items():
        actual = _sha256(root / rel)
        if actual != expected:
            raise BundleError(f"контрольная сумма не сходится: {rel}")

    acute = xgb.XGBClassifier()
    acute.load_model(str(files["acute"]))

    trigger_path = root / "trigger_config.json"
    trigger_config = _read_json(trigger_path) if trigger_path.exists() else {}

    return Bundle(
        manifest=manifest,
        trigger_config=trigger_config,
        acute=acute,
        calibrator=_unpickle(files["acute_calibrator"]),
        chronic=_unpickle(files["chronic"]),
        aft=_unpickle(files["explain_aft"]),
        feature_columns=list(manifest["feature_schema"]["columns"]),
    )
