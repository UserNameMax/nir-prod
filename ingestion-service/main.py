from __future__ import annotations
import asyncio
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

import jobs
from jobs import IngestJob, IngestStats
from pipeline import extractor, parser, cleaner

DATA_SERVICE_URL = os.getenv("DATA_SERVICE_URL", "http://data-service:8000")
BATCH_SIZE = 500_000

app = FastAPI(title="ingestion-service", version="0.1.0")

# Увеличиваем лимит multipart до 2 ГБ (по умолчанию Starlette ставит 1 МБ на поле)
from starlette.formparsers import MultiPartParser
MultiPartParser.max_file_size = 2 * 1024 * 1024 * 1024  # 2 GB

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Очередь задач — обрабатываются по одной
_queue: asyncio.Queue = asyncio.Queue()


@app.on_event("startup")
async def start_worker() -> None:
    asyncio.create_task(_worker())


async def _worker() -> None:
    while True:
        job_id, archive_path, tmp_dir = await _queue.get()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run_pipeline, job_id, archive_path, tmp_dir)
        _queue.task_done()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/ingest/upload")
async def upload(files: list[UploadFile] = File(...)):
    created = []
    for file in files:
        suffix = Path(file.filename).suffix.lower()
        if suffix not in (".rar", ".zip"):
            raise HTTPException(
                status_code=400,
                detail=f"{file.filename}: только .rar и .zip архивы поддерживаются",
            )

        tmp_dir = tempfile.mkdtemp()
        archive_path = str(Path(tmp_dir) / file.filename)
        with open(archive_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):  # читаем по 1 МБ
                f.write(chunk)
        saved_size = os.path.getsize(archive_path)
        print(f"[upload] {file.filename}: saved {saved_size:,} bytes", flush=True)

        job = jobs.create_job(file.filename)
        await _queue.put((job.job_id, archive_path, tmp_dir))
        created.append({"job_id": job.job_id, "status": job.status})

    return created


@app.get("/ingest/jobs/{job_id}", response_model=IngestJob)
def get_job(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/ingest/jobs", response_model=list[IngestJob])
def list_jobs():
    return jobs.list_jobs()


# ── Pipeline ──────────────────────────────────────────────────────────────────

def _run_pipeline(job_id: str, archive_path: str, tmp_dir: str) -> None:
    try:
        _pipeline(job_id, archive_path, tmp_dir)
    except Exception as exc:
        jobs.update_job(job_id, status="error", error=str(exc), finished_at=datetime.utcnow())
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _pipeline(job_id: str, archive_path: str, tmp_dir: str) -> None:
    jobs.update_job(job_id, status="processing")

    # Шаг 1 — распаковка
    xlsx_files = extractor.extract(archive_path, tmp_dir)
    jobs.update_job(job_id, files_total=len(xlsx_files), files_processed=0, rows_processed=0)

    all_sensors: list[pd.DataFrame] = []
    all_meta: list[pd.DataFrame] = []

    # Шаг 2-3 — парсинг и очистка
    for i, xlsx_path in enumerate(xlsx_files):
        jobs.update_job(job_id, current_file=xlsx_path.name)
        result = parser.parse_xlsx(xlsx_path)
        if result is None:
            jobs.update_job(job_id, files_processed=i + 1)
            continue

        sensors_df, meta_df = result
        sensors_df = cleaner.clean_sensors(sensors_df)
        sensors_df = cleaner.dedup_sensors(sensors_df)
        meta_df = cleaner.dedup_meta(meta_df)

        all_sensors.append(sensors_df)
        all_meta.append(meta_df)

        current_rows = sum(len(df) for df in all_sensors)
        jobs.update_job(job_id, files_processed=i + 1, rows_processed=current_rows)

    if not all_sensors:
        jobs.update_job(
            job_id,
            status="done",
            finished_at=datetime.utcnow(),
            current_file=None,
            stats=IngestStats(
                xlsx_files_found=len(xlsx_files),
                sensors_inserted=0,
                sensors_duplicates=0,
                objects_upserted=0,
                period_from=None,
                period_to=None,
                objects_count=0,
            ),
        )
        return

    sensors = pd.concat(all_sensors, ignore_index=True)
    sensors = cleaner.dedup_sensors(sensors)
    meta = pd.concat(all_meta, ignore_index=True)
    meta = cleaner.dedup_meta(meta)

    # Шаг 4 — сохранение через data-service
    total_inserted = 0
    total_skipped = 0
    merge_total = len(sensors)

    jobs.update_job(
        job_id,
        current_file=None,
        merge_total=merge_total,
        merge_processed=0,
    )

    with httpx.Client(base_url=DATA_SERVICE_URL, timeout=120) as client:
        # Sensors батчами — обновляем прогресс мерджа после каждого батча
        for start in range(0, merge_total, BATCH_SIZE):
            batch = sensors.iloc[start: start + BATCH_SIZE]
            records = _sensors_to_payload(batch)
            resp = client.post("/sensors/bulk", json=records)
            resp.raise_for_status()
            data = resp.json()
            total_inserted += data["inserted"]
            total_skipped += data["skipped_duplicates"]
            jobs.update_job(job_id, merge_processed=min(start + BATCH_SIZE, merge_total))

        # Objects
        meta_records = meta.astype(object).where(meta.notna(), other=None).to_dict(orient="records")
        resp = client.post("/objects/bulk", json=meta_records)
        resp.raise_for_status()
        objects_upserted = resp.json()["inserted"]

    ts = pd.to_datetime(sensors["ts_recorded"], unit="s")
    jobs.update_job(
        job_id,
        status="done",
        finished_at=datetime.utcnow(),
        merge_processed=merge_total,
        stats=IngestStats(
            xlsx_files_found=len(xlsx_files),
            sensors_inserted=total_inserted,
            sensors_duplicates=total_skipped,
            objects_upserted=objects_upserted,
            period_from=ts.min().to_pydatetime(),
            period_to=ts.max().to_pydatetime(),
            objects_count=sensors["object_id"].nunique(),
        ),
    )


def _sensors_to_payload(df: pd.DataFrame) -> list[dict]:
    df = df.where(df.notna(), other=None)
    records = df.to_dict(orient="records")
    for r in records:
        for col in ("ts_measurement", "ts_recorded"):
            if r.get(col) is not None:
                r[col] = int(r[col])
    return records
