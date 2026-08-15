"""
labeling-service — детерминированный разметчик аварий ЦТП (LLM + fuzzy), без трансформера.

Job-API (house-паттерн): загрузка Excel тех.нарушений → фоновая задача
ingest → resolve → publish → метки в data-service (POST /incidents/bulk).
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.formparsers import MultiPartParser

import clients
import config
import ingest
import jobs
import publish
import resolve
from jobs import LabelJob
from schemas import LabelStats

MultiPartParser.max_file_size = 2 * 1024 * 1024 * 1024  # 2 GB

app = FastAPI(title="labeling-service", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_queue: "asyncio.Queue" = asyncio.Queue()


@app.on_event("startup")
async def _start_worker() -> None:
    asyncio.create_task(_worker())


async def _worker() -> None:
    while True:
        job_id, paths, tmp_dir = await _queue.get()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run, job_id, paths, tmp_dir)
        _queue.task_done()


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/label/upload")
async def upload(files: list[UploadFile] = File(...)):
    saved: list[Path] = []
    tmp_dir = tempfile.mkdtemp()
    names: list[str] = []
    for file in files:
        if Path(file.filename).suffix.lower() not in (".xlsx", ".xls", ".xlsb"):
            raise HTTPException(400, f"{file.filename}: только .xlsx/.xls/.xlsb")
        dst = Path(tmp_dir) / file.filename
        with open(dst, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                f.write(chunk)
        saved.append(dst)
        names.append(file.filename)
    job = jobs.create_job(", ".join(names))
    await _queue.put((job.job_id, saved, tmp_dir))
    return {"job_id": job.job_id, "status": job.status}


@app.get("/label/jobs/{job_id}", response_model=LabelJob)
def get_job(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/label/jobs", response_model=list[LabelJob])
def list_jobs():
    return jobs.list_jobs()


@app.get("/health")
def health():
    return {"status": "ok", "service": "labeling-service"}


# ── Pipeline ─────────────────────────────────────────────────────────────────

def _run(job_id: str, xlsx_paths: list[Path], tmp_dir: str) -> None:
    try:
        _pipeline(job_id, xlsx_paths)
    except Exception as exc:
        import traceback
        print(f"[label] ERROR {job_id}: {exc}\n{traceback.format_exc()}", flush=True)
        jobs.update_job(job_id, status="error", error=str(exc), finished_at=datetime.utcnow())
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _pipeline(job_id: str, xlsx_paths: list[Path]) -> None:
    jobs.update_job(job_id, status="processing", stage="ingest")

    incidents, go_events = ingest.run(xlsx_paths, header_row=config.EXCEL_HEADER_ROW)
    jobs.update_job(job_id, incidents_total=len(incidents), incidents_processed=0)

    # Справочник ЦТП из data-service (единственный источник объектов)
    jobs.update_job(job_id, stage="resolve")
    catalog = clients.fetch_ctp_catalog(config.DATA_SERVICE_URL)

    def _progress(done: int, total: int) -> None:
        jobs.update_job(job_id, incidents_processed=done)

    resolutions = resolve.resolve_batch(
        incidents, catalog, config.resolver_cache_path(),
        autosave_every=config.AUTOSAVE_EVERY, progress=_progress,
    )

    # Публикация меток
    jobs.update_job(job_id, stage="publish")
    records = publish.build_incident_records(incidents, resolutions, config.LABEL_SOURCE)
    inserted, duplicates = clients.publish_incidents(config.DATA_SERVICE_URL, records)

    n_llm = sum(1 for r in resolutions.values() if str(r.llm_extracted).strip().lower() != "не найдено")
    n_res = sum(1 for r in resolutions.values() if r.resolved)
    ts = pd.to_datetime(incidents["d_create"], errors="coerce").dropna()
    jobs.update_job(
        job_id, status="done", stage=None, finished_at=datetime.utcnow(),
        incidents_processed=len(incidents),
        stats=LabelStats(
            xlsx_files=len(xlsx_paths),
            incidents_ctp=len(incidents), go_events=len(go_events),
            llm_extracted=n_llm, resolved=n_res, unresolved=len(incidents) - n_res,
            published=inserted, duplicates=duplicates,
            period_from=ts.min().to_pydatetime() if not ts.empty else None,
            period_to=ts.max().to_pydatetime() if not ts.empty else None,
        ),
    )
