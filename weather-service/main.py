from __future__ import annotations
import os

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import source
import store
from dependencies import get_weather_dir
from schemas import RefreshRequest, RefreshResult, WeatherSeries

REGION = os.getenv("WEATHER_REGION", "moscow")

app = FastAPI(
    title="weather-service",
    version="0.1.0",
    root_path=os.getenv("ROOT_PATH", ""),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health(weather_dir: str = Depends(get_weather_dir)):
    return {"status": "ok", "region": REGION, **store.health(weather_dir)}


@app.get("/weather", response_model=WeatherSeries, tags=["weather"])
def get_weather(
    date_from: str | None = Query(default=None, description="YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="YYYY-MM-DD"),
    weather_dir: str = Depends(get_weather_dir),
):
    """Дневной ряд наружной температуры из локального кэша.

    Наружу не ходит — отдаёт только загруженное (см. POST /weather/refresh).
    """
    return WeatherSeries(region=REGION, rows=store.read(weather_dir, date_from, date_to))


@app.post("/weather/refresh", response_model=RefreshResult, tags=["weather"])
def refresh(body: RefreshRequest, weather_dir: str = Depends(get_weather_dir)):
    """Догрузить период из внешнего источника.

    По умолчанию тянет только отсутствующие дни; force=true перезапрашивает весь
    период (архив уточняется задним числом).
    """
    if body.date_from > body.date_to:
        raise HTTPException(status_code=400, detail="date_from позже date_to")

    if not body.force and not store.missing_days(weather_dir, body.date_from, body.date_to):
        return RefreshResult(fetched=0, added=0, updated=0, source="cache")

    try:
        rows = source.fetch_daily(body.date_from, body.date_to)
    except source.WeatherSourceError as exc:
        # Кэш остаётся валидным — недоступность источника не ломает выдачу.
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    added, updated = store.upsert(weather_dir, rows)
    return RefreshResult(fetched=len(rows), added=added, updated=updated, source="open-meteo")
