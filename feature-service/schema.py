"""Набор признаков final_h30 — зафиксирован исследованием (H=30).

Список перенесён копией из research (`feature_cols_final_h30.json`): production не
читает файлы вне себя. Порядок колонок значим — модель обучается и применяется
строго в нём, поэтому список упорядоченный и менять его нельзя без переобучения
(см. MODEL_BUNDLE.md: manifest.feature_schema).
"""
from __future__ import annotations
import hashlib

NAME = "final_h30"
HORIZON_DAYS = 30

# Версия логики пайплайна. Меняется при любой правке формул признаков —
# входит в хеш схемы, поэтому старый бандл перестанет подходить к новым признакам.
PIPELINE_VERSION = "1"

FEATURES: tuple[str, ...] = (
    "t_supply_std",
    "t_return_mean",
    "p_return_max",
    "dp_std",
    "p_supply_skew",
    "dp_skew",
    "dp_night",
    "dt_night",
    "n_samples",
    "dp_night_ratio",
    "dt_night_ratio",
    "p_drop_night",
    "p_supply_drop_depth_intraday",
    "sin_month",
    "cos_month",
    "sin_weekday",
    "cos_weekday",
    "low_coverage",
    "dt_vs_expected",
    "p_supply_robust_z",
    "t_supply_robust_z",
    "p_supply_accel",
    "dp_slope_30d",
    "dt_slope_30d",
    "dt_accel",
    "t_supply_vs_curve_slope_7d",
    "t_supply_vs_curve_slope_30d",
    "dp_vol_ratio",
    "days_since_last_anomaly",
    "dp_exceed_freq_14d",
    "ewma_cross_dp",
)

KEYS = ("object_id", "date")


def version() -> str:
    """Детерминированный хеш схемы: набор признаков + версия пайплайна.

    ml-service и training-service сверяют его с manifest.feature_schema.service_version —
    расхождение означает train/serve skew, бандл к таким признакам не подходит.
    """
    payload = "|".join((NAME, PIPELINE_VERSION, *FEATURES))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def describe() -> dict:
    return {
        "name": NAME,
        "version": version(),
        "pipeline_version": PIPELINE_VERSION,
        "n_features": len(FEATURES),
        "columns": list(FEATURES),
        "keys": list(KEYS),
        "horizon_days": HORIZON_DAYS,
    }
