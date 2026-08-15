"""Этап 3 — междневная динамика: температурный график, робастные z, тренды, история.

Перенесено из research `features/03_3_interday.ipynb`.

КАУЗАЛЬНОСТЬ — главное требование этапа. Признаки на день t считаются только по
данным <= t. Аудит утечек (NARRATIVE §8) нашёл здесь look-ahead: коэффициенты
температурного графика фитились по ВСЕЙ истории объекта (включая будущее).
Исправлено на expanding-fit через кумулятивные суммы. Не заменять на обычный
polyfit по группе — это вернёт утечку.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Несущие сигналы, по которым считаются тренды.
CARRIERS = ["p_supply_mean", "dp_mean", "dt_mean", "dp_night", "t_supply_vs_curve"]
ROBUST_Z_COLS = ["p_supply_mean", "dp_mean", "dt_mean", "dp_night", "t_supply_mean"]
VOL_RATIO_COLS = ["p_supply_mean", "dp_mean"]

ANOMALY_Z = 3.0        # |robust_z| выше — день считается аномальным
CURVE_MIN_PTS = 15     # меньше точек — остаток не определён

# Пол масштаба для робастной нормировки: 5% глобального std сигнала.
# ЗАМОРОЖЕН константой (значения посчитаны по эталонной панели research,
# 747127 объект-дней). В research пол брался как np.nanstd по всему кадру —
# это (а) look-ahead: глобальная статистика включает будущее, (б) хуже того,
# ломает train/serve parity: один и тот же объект-день получал РАЗНЫЙ z в
# зависимости от того, что ещё попало в батч. Константа снимает оба эффекта
# и воспроизводит эталонные значения на полной панели.
SCALE_FLOOR = {
    "p_supply_mean": 0.09227330088615418,
    "dp_mean": 0.06446541547775268,
    "dt_mean": 0.5118538856506348,
    "dp_night": 0.0646605670452118,
    "t_supply_mean": 0.7851322650909425,
}


def fit_curve_residual(df: pd.DataFrame, ycol: str, xcol: str = "t_out_mean",
                       min_pts: int = CURVE_MIN_PTS) -> pd.Series:
    """Остаток от эмпирического температурного графика f(T_out) на объект.

    КАУЗАЛЬНО: на день t коэффициенты подобраны только по строкам <= t
    (кумулятивные суммы, O(n)). residual = факт − ожидание.
    """
    x = df[xcol].to_numpy(float)
    y = df[ycol].to_numpy(float)
    v = ~(np.isnan(x) | np.isnan(y))

    acc = pd.DataFrame({
        "g": df["object_id"].to_numpy(),
        "v": v.astype(float),
        "sx": np.where(v, x, 0.0),
        "sy": np.where(v, y, 0.0),
        "sxx": np.where(v, x * x, 0.0),
        "sxy": np.where(v, x * y, 0.0),
    })
    cs = acc.groupby("g", sort=False).cumsum()      # накопление ТОЛЬКО прошлого+текущего
    n, Sx, Sy = cs["v"].to_numpy(), cs["sx"].to_numpy(), cs["sy"].to_numpy()
    Sxx, Sxy = cs["sxx"].to_numpy(), cs["sxy"].to_numpy()

    denom = n * Sxx - Sx ** 2
    with np.errstate(divide="ignore", invalid="ignore"):
        b = (n * Sxy - Sx * Sy) / denom
        a = (Sy - b * Sx) / n
        resid = y - (a + b * x)
    resid[(n < min_pts) | (np.abs(denom) < 1e-9) | (~v)] = np.nan
    return pd.Series(resid, index=df.index, dtype="float64")


def robust_z_30d(df: pd.DataFrame, col: str) -> np.ndarray:
    """Робастная нормировка на объект: (x − median30d) / (IQR30d / 1.349).

    Пол на масштаб: у зарегулированных ЦТП IQR≈0 (давление постоянно) → без пола
    z взрывается. Пол берётся из SCALE_FLOOR (константа, не статистика батча —
    см. комментарий там), итог клипуется в [-10, 10].
    """
    r = df.groupby("object_id", sort=True).rolling("30D", on="date", min_periods=5)[col]
    med = r.median().to_numpy()
    q1 = r.quantile(0.25).to_numpy()
    q3 = r.quantile(0.75).to_numpy()

    scale = (q3 - q1) / 1.349                      # робастная оценка sigma через IQR
    floor = SCALE_FLOOR[col]                       # пол против near-constant сигнала
    scale = np.where(scale < floor, floor, scale)
    z = (df[col].to_numpy() - med) / scale
    return np.clip(z, -10, 10)


def roll_slope(df: pd.DataFrame, col: str, window: str) -> np.ndarray:
    """Наклон тренда в трейлинг-окне через суммовую формулу МНК (без apply)."""
    ok = df[col].notna()
    tmp = pd.DataFrame({
        "object_id": df["object_id"],
        "date": df["date"],
        "_x": df[col],
        "_t": df["_ord"].where(ok),
        "_xt": df[col] * df["_ord"],
        "_tt": (df["_ord"] ** 2).where(ok),
    })
    r = tmp.groupby("object_id", sort=True).rolling(window, on="date", min_periods=3)
    n = r["_x"].count().to_numpy()
    Sx = r["_x"].sum().to_numpy()
    St = r["_t"].sum().to_numpy()
    Stt = r["_tt"].sum().to_numpy()
    Sxt = r["_xt"].sum().to_numpy()

    denom = n * Stt - St ** 2
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = (n * Sxt - St * Sx) / denom
    slope[np.abs(denom) < 1e-9] = np.nan
    return slope


def _roll_std(df: pd.DataFrame, col: str, window: str) -> np.ndarray:
    r = df.groupby("object_id", sort=True).rolling(window, on="date", min_periods=3)[col]
    return r.std().to_numpy()


def build(daily: pd.DataFrame) -> pd.DataFrame:
    """Достроить междневные признаки поверх дневной базы."""
    df = daily.copy()
    df["object_id"] = df["object_id"].astype(str)
    df = df.sort_values(["object_id", "date"]).reset_index(drop=True)
    # Абсолютный порядковый день (от фиксированной эпохи, а не от минимума кадра):
    # наклон инвариантен к сдвигу начала отсчёта, но абсолютная шкала гарантирует,
    # что значение не зависит от того, какой период попал в пересчёт.
    df["_ord"] = (df["date"] - pd.Timestamp("1970-01-01")).dt.days.astype(float)

    # G4 — температурный график (каузальный expanding-fit)
    df["t_supply_vs_curve"] = fit_curve_residual(df, "t_supply_mean")
    df["dt_vs_expected"] = fit_curve_residual(df, "dt_mean")

    # G5 — робастная нормировка на объект
    for col in ROBUST_Z_COLS:
        df[col.replace("_mean", "") + "_robust_z"] = robust_z_30d(df, col)

    # G6 — тренды и ускорение
    for col in CARRIERS:
        base = col.replace("_mean", "")
        s7 = roll_slope(df, col, "7D")
        s30 = roll_slope(df, col, "30D")
        df[f"{base}_slope_7d"] = s7
        df[f"{base}_slope_30d"] = s30
        df[f"{base}_accel"] = s7 - s30

    # рост разброса перед отказом
    for col in VOL_RATIO_COLS:
        base = col.replace("_mean", "")
        s30 = _roll_std(df, col, "30D")
        s30[s30 == 0] = np.nan
        df[f"{base}_vol_ratio"] = _roll_std(df, col, "7D") / s30

    # G7 — история событий
    anom = (df["p_supply_robust_z"].abs() > ANOMALY_Z) | (df["dp_robust_z"].abs() > ANOMALY_Z)
    df["_anom"] = anom.astype("float32")

    anom_date = df["date"].where(anom)
    df["_last_anom_date"] = anom_date.groupby(df["object_id"]).ffill()
    df["days_since_last_anomaly"] = (df["date"] - df["_last_anom_date"]).dt.days

    r14 = df.groupby("object_id", sort=True).rolling("14D", on="date", min_periods=3)["_anom"].mean()
    df["dp_exceed_freq_14d"] = r14.to_numpy()

    # EWMA-crossover перепада давления (смена режима)
    gdp = df.groupby("object_id")["dp_mean"]
    fast = gdp.transform(lambda s: s.ewm(span=3, min_periods=1).mean())
    slow = gdp.transform(lambda s: s.ewm(span=14, min_periods=1).mean())
    df["ewma_cross_dp"] = fast - slow

    return df.drop(columns=["_ord", "_anom", "_last_anom_date"], errors="ignore")
