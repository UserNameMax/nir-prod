from __future__ import annotations
import os

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import jobs
import publish
import run
from dependencies import get_bundle_dir
from schemas import TrainJob, TrainRequest

app = FastAPI(
    title="training-service",
    version="0.1.0",
    root_path=os.getenv("ROOT_PATH", ""),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _runner(request: TrainRequest, progress) -> dict:
    return run.train_bundle(
        get_bundle_dir(),
        val_start=request.val_start,
        test_start=request.test_start,
        alert_rate=request.alert_rate,
        progress=progress,
    )


@app.on_event("startup")
async def startup():
    jobs.ensure_worker(_runner)


@app.get("/health")
def health(bundle_dir: str = Depends(get_bundle_dir)):
    manifest = publish.read_manifest(bundle_dir)
    return {
        "status": "ok",
        "bundle_version": manifest.get("version") if manifest else None,
        "feature_schema_version": (manifest or {}).get("feature_schema", {}).get("service_version"),
        "active_jobs": sum(1 for j in jobs.recent() if j.status in ("queued", "processing")),
    }


@app.post("/train", response_model=TrainJob, tags=["training"])
async def start_training(body: TrainRequest):
    """Поставить обучение в очередь. Очередь последовательная — публикация
    бандла допускает только одного писателя."""
    job = jobs.create(body)
    await jobs.submit(job)
    return job


@app.get("/train/jobs", response_model=list[TrainJob], tags=["training"])
def list_jobs():
    return jobs.recent()


@app.get("/train/jobs/{job_id}", response_model=TrainJob, tags=["training"])
def get_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return job


@app.get("/bundle/manifest", tags=["bundle"])
def get_manifest(bundle_dir: str = Depends(get_bundle_dir)):
    """Манифест опубликованного бандла (то, что читает ml-service)."""
    manifest = publish.read_manifest(bundle_dir)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Бандл ещё не опубликован")
    return manifest
