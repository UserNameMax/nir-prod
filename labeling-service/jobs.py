"""In-memory реестр задач разметки (house-паттерн, как ingestion-service)."""
from __future__ import annotations

import uuid
from collections import OrderedDict
from datetime import datetime

from schemas import LabelJob

MAX_JOBS = 50

_store: OrderedDict[str, LabelJob] = OrderedDict()


def create_job(filename: str) -> LabelJob:
    job = LabelJob(
        job_id=str(uuid.uuid4()),
        filename=filename,
        status="queued",
        created_at=datetime.utcnow(),
    )
    _store[job.job_id] = job
    if len(_store) > MAX_JOBS:
        _store.popitem(last=False)
    return job


def get_job(job_id: str) -> LabelJob | None:
    return _store.get(job_id)


def list_jobs() -> list[LabelJob]:
    return list(reversed(list(_store.values())))


def update_job(job_id: str, **kwargs) -> None:
    job = _store.get(job_id)
    if job is None:
        return
    _store[job_id] = job.model_copy(update=kwargs)
