"""Рабочее состояние сервиса: загруженный бандл и предвычисленные скоры.

Смена состояния атомарна: новый бандл собирается целиком в локальных переменных
и лишь затем подменяет текущий. Пока новый не собрался, обслуживание идёт на
старом — битая публикация не должна ронять сервис.
"""
from __future__ import annotations
import threading
from dataclasses import dataclass

import pandas as pd

import clients
import loader
import scoring
from loader import Bundle

_lock = threading.Lock()
_state: "Runtime | None" = None


@dataclass
class Runtime:
    bundle: Bundle
    daily: pd.DataFrame          # object_id, date, score, calibrated, rank
    chronic: pd.DataFrame        # object_id, chronic_score, chronic_rank
    baseline: pd.DataFrame       # object-level срез признаков (для хроники и AFT)
    thresholds: pd.DataFrame     # пообъектные p75/p90
    globals_: dict
    objects: pd.DataFrame        # справочник (может быть пуст)

    @property
    def dates(self) -> list[str]:
        return sorted(self.daily["date"].dt.strftime("%Y-%m-%d").unique())

    def chronic_top(self, fraction: float) -> set:
        if self.chronic.empty:
            return set()
        cutoff = max(int(len(self.chronic) * fraction), 1)
        return set(self.chronic.nsmallest(cutoff, "chronic_rank")["object_id"])


def current() -> Runtime:
    if _state is None:
        raise loader.BundleError("бандл не загружен — вызовите POST /reload")
    return _state


def loaded() -> bool:
    return _state is not None


def reload(bundle_dir: str) -> Runtime:
    """Перечитать бандл и пересчитать кэш скоров.

    Версия схемы признаков сверяется с feature-service ДО применения — бандл,
    обученный на другой схеме, к обслуживанию не допускается.
    """
    global _state

    schema_version = clients.fetch_schema_version()
    bundle = loader.load(bundle_dir, expected_schema_version=schema_version)

    features = clients.fetch_features()
    if features.empty:
        raise loader.BundleError("feature-service не отдал признаки")

    daily = scoring.score_daily(bundle, features)
    # object-level срез считается один раз: он нужен и хронике (Слой 1), и AFT (Слой 4)
    baseline = scoring.object_baseline(features, bundle.feature_columns)
    chronic = scoring.score_chronic(bundle, baseline)

    try:
        objects = clients.fetch_objects()
    except clients.UpstreamError:
        objects = pd.DataFrame(columns=["object_id"])   # справочник не критичен

    runtime = Runtime(
        bundle=bundle,
        daily=daily,
        chronic=chronic,
        baseline=baseline,
        thresholds=scoring.object_thresholds(daily),
        globals_=scoring.global_thresholds(daily, bundle.alert_threshold),
        objects=objects,
    )

    with _lock:
        _state = runtime
    return runtime


def reset() -> None:
    """Сброс состояния (используется в тестах)."""
    global _state
    with _lock:
        _state = None
