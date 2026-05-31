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
    status: Literal["processing", "done", "error"]
    created_at: datetime
    finished_at: datetime | None = None
    stats: IngestStats | None = None
    error: str | None = None
    files_total: int | None = None
    files_processed: int | None = None
    current_file: str | None = None
    rows_processed: int | None = None


# OrderedDict сохраняет порядок вставки — легко обрезать старые записи
_store: OrderedDict[str, IngestJob] = OrderedDict()


def create_job(filename: str) -> IngestJob:
    job = IngestJob(
        job_id=str(uuid.uuid4()),
        filename=filename,
        status="processing",
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
    updated = job.model_copy(update=kwargs)
    _store[job_id] = updated
