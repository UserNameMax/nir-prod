from __future__ import annotations
import io
import os

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

import cache
import client
import pipeline
import schema
from dependencies import get_cache_dir
from schemas import RebuildRequest, RebuildResult

app = FastAPI(
    title="feature-service",
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
def health(cache_dir: str = Depends(get_cache_dir)):
    return {"status": "ok", "schema_version": schema.version(),
            **cache.health(cache_dir)}


@app.get("/schema", tags=["schema"])
def get_schema():
    """Контракт признаков. ml-service и training-service сверяют `version`
    с manifest.feature_schema.service_version — иначе train/serve skew."""
    return schema.describe()


@app.get("/features", tags=["features"])
def get_features(
    date_from: str | None = Query(default=None, description="YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="YYYY-MM-DD"),
    object_ids: str | None = Query(default=None, description="через запятую"),
    cache_dir: str = Depends(get_cache_dir),
):
    """Дневная матрица признаков в parquet.

    Отдаёт посчитанное (см. POST /features/rebuild). Колонки — строго
    (object_id, date) + 31 признак final_h30 в зафиксированном порядке.
    """
    ids = [o.strip() for o in object_ids.split(",")] if object_ids else None
    matrix = cache.read(cache_dir, date_from, date_to, ids)

    buffer = io.BytesIO()
    matrix.to_parquet(buffer, index=False)
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.apache.parquet",
        headers={"X-Rows": str(len(matrix)), "X-Schema-Version": schema.version()},
    )


@app.post("/features/rebuild", response_model=RebuildResult, tags=["features"])
def rebuild(body: RebuildRequest, cache_dir: str = Depends(get_cache_dir)):
    """Пересчитать матрицу из сырья data-service и погоды weather-service.

    Считается по всей запрошенной истории целиком: междневные окна и каузальный
    fit температурного графика требуют предыстории объекта.
    """
    try:
        sensors = client.fetch_sensors(body.date_from, body.date_to)
        weather = client.fetch_weather(body.date_from, body.date_to)
    except client.UpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if sensors.empty:
        raise HTTPException(status_code=404, detail="Нет показаний за период")

    matrix = pipeline.build_matrix(sensors, weather)
    cache.save(cache_dir, matrix)

    return RebuildResult(
        object_days=len(matrix),
        objects=int(matrix["object_id"].nunique()) if not matrix.empty else 0,
        sensor_rows=len(sensors),
        weather_days=len(weather),
        schema_version=schema.version(),
    )
