from __future__ import annotations
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import sensors, objects, incidents

app = FastAPI(title="data-service", version="0.1.0")


@app.on_event("startup")
async def startup():
    sensors.ensure_worker()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sensors.router)
app.include_router(objects.router)
app.include_router(incidents.router)


@app.get("/health")
def health():
    from storage import reader
    from dependencies import get_data_dir
    data_dir = get_data_dir()
    info = reader.read_sensors_health(data_dir)
    return {"status": "ok", **info, **reader.read_incidents_health(data_dir)}


@app.delete("/_test/reset", include_in_schema=False)
def test_reset():
    """Удаляет parquet-файлы. Только для тестовой среды."""
    from dependencies import get_data_dir
    data_dir = get_data_dir()
    for name in ("sensors.parquet", "objects_meta.parquet", "incidents.parquet"):
        p = Path(data_dir) / name
        if p.exists():
            p.unlink()
    return {"reset": True}
