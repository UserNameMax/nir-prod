from __future__ import annotations
import os

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import clients
import decision
import explain
import loader
import state
from dependencies import get_bundle_dir

app = FastAPI(
    title="ml-service",
    version="0.1.0",
    root_path=os.getenv("ROOT_PATH", ""),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    """Бандла может ещё не быть — сервис поднимается и ждёт /reload."""
    try:
        state.reload(get_bundle_dir())
    except Exception as exc:      # noqa: BLE001 — старт не должен падать
        print(f"[ml-service] бандл не загружен при старте: {exc}", flush=True)


def _runtime() -> state.Runtime:
    try:
        return state.current()
    except loader.BundleError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ── system ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    if not state.loaded():
        return {"status": "no_bundle"}
    runtime = state.current()
    return {
        "status": "ok",
        "bundle_version": runtime.bundle.version,
        "feature_schema_version": runtime.bundle.schema_version,
        "horizon_days": runtime.bundle.manifest.get("horizon_days"),
        "trigger_default": runtime.bundle.trigger_config.get("default"),
        "cached_objects": int(runtime.daily["object_id"].nunique()),
        "cached_dates": len(runtime.dates),
    }


@app.post("/reload", tags=["system"])
def reload_bundle(bundle_dir: str = Depends(get_bundle_dir)):
    """Перечитать бандл. Пока новый не собрался, обслуживание идёт на старом."""
    try:
        runtime = state.reload(bundle_dir)
    except (loader.BundleError, clients.UpstreamError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"reloaded": True, "bundle_version": runtime.bundle.version}


# ── Слой 1: хронический watch-list ────────────────────────────────────────────

@app.get("/risk/watchlist", tags=["watchlist"])
def watchlist(top_n: int = Query(default=50, le=1000)):
    """Пообъектный хронический риск для планового ТО.

    Это «класс нелинейных моделей», а не «чемпион RSF»: доверительные интервалы
    C-index перекрываются с другими нелинейными (NARRATIVE §6, п.3).
    """
    runtime = _runtime()
    items = runtime.chronic.head(top_n)
    return {
        "total_objects": int(len(runtime.chronic)),
        "model_note": "класс нелинейных моделей (RSF), CI перекрывается с GBS/DDH",
        "items": [{"rank": int(r.chronic_rank), "object_id": r.object_id,
                   "chronic_score": float(r.chronic_score)}
                  for r in items.itertuples()],
    }


# ── Слои 1+2: скоринг ─────────────────────────────────────────────────────────

@app.get("/risk/dates", tags=["risk"])
def risk_dates():
    return _runtime().dates


@app.get("/risk/thresholds", tags=["risk"])
def risk_thresholds():
    return _runtime().globals_


@app.get("/risk/ranking", tags=["risk"])
def risk_ranking(date: str | None = None, top_n: int = Query(default=50, le=1000)):
    runtime = _runtime()
    daily = runtime.daily
    day = date or runtime.dates[-1]
    subset = daily[daily["date"] == day].nsmallest(top_n, "rank")

    return {
        "date": day,
        "total_objects": int(daily[daily["date"] == day]["object_id"].nunique()),
        "items": [{"rank": int(r.rank), "object_id": r.object_id,
                   "risk_score": float(r.score), "calibrated": float(r.calibrated)}
                  for r in subset.itertuples()],
    }


@app.get("/risk/object/{object_id}", tags=["risk"])
def risk_object(object_id: str, date_from: str | None = None,
                date_to: str | None = None):
    runtime = _runtime()
    history = runtime.daily[runtime.daily["object_id"] == object_id]
    if history.empty:
        raise HTTPException(status_code=404, detail="Объект не найден")
    if date_from:
        history = history[history["date"] >= date_from]
    if date_to:
        history = history[history["date"] <= date_to]

    return {
        "object_id": object_id,
        "timeline": [{"date": r.date.strftime("%Y-%m-%d"),
                      "risk_score": float(r.score),
                      "calibrated": float(r.calibrated),
                      "rank": int(r.rank)} for r in history.itertuples()],
    }


@app.get("/risk/object/{object_id}/thresholds", tags=["risk"])
def object_thresholds(object_id: str):
    runtime = _runtime()
    own = runtime.thresholds[runtime.thresholds["object_id"] == object_id]
    if own.empty:
        raise HTTPException(status_code=404, detail="Объект не найден")
    return {"p75": float(own["p75"].iloc[0]), "p90": float(own["p90"].iloc[0])}


# ── Слои 2+3: очередь нарядов ─────────────────────────────────────────────────

@app.get("/alerts/config", tags=["alerts"])
def alerts_config():
    """Профили триггеров и их κ* — как их выбрал training-service."""
    return _runtime().bundle.trigger_config


@app.get("/alerts/queue", tags=["alerts"])
def alerts_queue(date: str | None = None, profile: str | None = None,
                 gate: bool = False, top_n: int = Query(default=100, le=2000)):
    """Наряды на осмотр: триггер устойчивости + cooldown + (опц.) гейтинг.

    Серия алертов объекта в пределах cooldown — ОДИН наряд, а не наряд в день.
    """
    runtime = _runtime()
    config = runtime.bundle.trigger_config
    profiles = config.get("profiles", {})
    name = profile or config.get("default", "baseline")
    if name not in profiles:
        raise HTTPException(status_code=400, detail=f"Неизвестный профиль: {name}")

    spec = profiles[name]
    thr = float(spec.get("threshold") or runtime.bundle.alert_threshold)
    cooldown = int(config.get("cooldown_days", decision.DEFAULT_COOLDOWN_DAYS))

    chronic_top = None
    if gate or spec.get("type") == "gate":
        fraction = 0.30 if str(spec.get("chronic_top", "top30")).endswith("30") else 0.50
        chronic_top = runtime.chronic_top(fraction)

    orders = decision.queue(runtime.daily, spec, thr, date=date,
                            chronic_top=chronic_top, cooldown_days=cooldown)
    chronic_rank = dict(zip(runtime.chronic["object_id"], runtime.chronic["chronic_rank"]))

    return {
        "date": date,
        "profile": name,
        "cooldown_days": cooldown,
        "kappa_star": spec.get("kappa_star"),
        "total_orders": int(len(orders)),
        "orders": [{
            "object_id": r.object_id,
            "opened_at": r.opened_at.strftime("%Y-%m-%d"),
            "last_alert_at": r.last_alert_at.strftime("%Y-%m-%d"),
            "alert_days": int(r.alert_days),
            "peak_score": float(r.peak_score),
            "chronic_rank": int(chronic_rank.get(r.object_id, 0)) or None,
        } for r in orders.head(top_n).itertuples()],
    }


# ── Слой 4: объяснение ────────────────────────────────────────────────────────

@app.get("/explain/{object_id}", tags=["explain"])
def explain_object(object_id: str, date: str | None = None,
                   with_profile: bool = True):
    """Карточка объекта: риск, срок AFT, пороги и суточный профиль."""
    runtime = _runtime()
    card = explain.object_card(runtime, object_id, date)
    if not card:
        raise HTTPException(status_code=404, detail="Объект не найден")

    # AFT считается по object-level признакам объекта, а не по его скорам —
    # иначе всем объектам вернулась бы одна и та же популяционная медиана.
    baseline = runtime.baseline[runtime.baseline["object_id"] == object_id]
    card["aft_median_days"] = explain.aft_median_days(runtime.bundle.aft, baseline)

    card["daily_profile"] = []
    if with_profile:
        try:
            card["daily_profile"] = clients.fetch_daily_profile(object_id, card["date"])
        except clients.UpstreamError:
            card["daily_profile"] = []
    return card


# ── KPI ───────────────────────────────────────────────────────────────────────

@app.get("/kpi", tags=["kpi"])
def kpi():
    """Отчётность бандла — ТОЛЬКО temporal-форкаст.

    Абсолютный detection не показывается без нулевого пола и lift: метрика
    насыщается геометрией окна (NARRATIVE §6, п.6).
    """
    runtime = _runtime()
    report = dict(runtime.bundle.manifest.get("reporting", {}))
    report["note"] = ("операционные числа — только temporal-форкаст; "
                      "detection читать вместе с detection_null и detection_lift")
    return report
