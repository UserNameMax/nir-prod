from __future__ import annotations
import uuid
from collections import OrderedDict
from datetime import datetime
from typing import Literal
from pydantic import BaseModel

MAX_JOBS = 50


class IngestStats(BaseModel):
    xlsx_files_found: int
    sensors_inserted: int
    sensors_duplicates: int
    objects_upserted: int
    period_from: datetime | None
    period_to: datetime | None
    objects_count: int


class IngestJob(BaseModel):
    job_id: str
    filename: str
    status: Literal["queued", "processing", "done", "error"]
    created_at: datetime
    finished_at: datetime | None = None
    stats: IngestStats | None = None
    error: str | None = None
    # прогресс парсинга
    files_total: int | None = None
    files_processed: int | None = None
    current_file: str | None = None
    rows_processed: int | None = None
    # прогресс мерджа
    merge_total: int | None = None
    merge_processed: int | None = None


_store: OrderedDict[str, IngestJob] = OrderedDict()


def create_job(filename: str) -> IngestJob:
    job = IngestJob(
        job_id=str(uuid.uuid4()),
        filename=filename,
        status="queued",
        created_at=datetime.utcnow(),
    )
    _store[job.job_id] = job
    if len(_store) > MAX_JOBS:
        _store.popitem(last=False)
    return job


def get_job(job_id: str) -> IngestJob | None:
    return _store.get(job_id)


def list_jobs() -> list[IngestJob]:
    return list(reversed(list(_store.values())))


def update_job(job_id: str, **kwargs) -> None:
    job = _store.get(job_id)
    if job is None:
        return
    _store[job_id] = job.model_copy(update=kwargs)
