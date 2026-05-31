import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import sensors, objects

app = FastAPI(title="data-service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sensors.router)
app.include_router(objects.router)


@app.get("/health")
def health():
    from storage import reader
    from dependencies import get_data_dir
    data_dir = get_data_dir()
    info = reader.read_sensors_health(data_dir)
    return {"status": "ok", **info}
