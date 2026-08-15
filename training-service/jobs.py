"""Очередь обучения: строго последовательная (публикация бандла — один writer).

Статусы хранятся в памяти, как в ingestion-service: осознанное ограничение ВКР.
"""
from __future__ import annotations
import asyncio
import traceback
import uuid
from datetime import datetime, timezone

from schemas import TrainJob, TrainRequest

MAX_HISTORY = 50

_jobs: dict[str, TrainJob] = {}
_order: list[str] = []
_queue: asyncio.Queue | None = None
_worker_started = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create(request: TrainRequest) -> TrainJob:
    job = TrainJob(job_id=str(uuid.uuid4()), status="queued", created_at=_now(),
                   request=request)
    _jobs[job.job_id] = job
    _order.append(job.job_id)
    for stale in _order[:-MAX_HISTORY]:
        _jobs.pop(stale, None)
    del _order[:-MAX_HISTORY]
    return job


def get(job_id: str) -> TrainJob | None:
    return _jobs.get(job_id)


def recent() -> list[TrainJob]:
    return [_jobs[j] for j in reversed(_order) if j in _jobs]


def ensure_worker(runner) -> None:
    """Поднять фонового воркера (одного) при старте сервиса."""
    global _queue, _worker_started
    if _worker_started:
        return
    _queue = asyncio.Queue()
    asyncio.create_task(_worker(runner))
    _worker_started = True


async def submit(job: TrainJob) -> None:
    await _queue.put(job.job_id)


async def _worker(runner) -> None:
    loop = asyncio.get_event_loop()
    while True:
        job_id = await _queue.get()
        job = _jobs.get(job_id)
        if job is None:
            _queue.task_done()
            continue

        job.status = "processing"
        try:
            def _progress(stage: str) -> None:
                job.stage = stage

            manifest = await loop.run_in_executor(None, runner, job.request, _progress)
            job.status = "done"
            job.stats = _stats(manifest)
        except Exception as exc:
            job.status = "error"
            job.error = f"{type(exc).__name__}: {exc}"
            print(f"[training] job {job_id} failed:\n{traceback.format_exc()}", flush=True)
        finally:
            job.stage = None
            job.finished_at = _now()
            _queue.task_done()


def _stats(manifest: dict) -> dict:
    report = manifest.get("reporting", {})
    return {
        "run_id": manifest.get("run_id"),
        "bundle_version": manifest.get("version"),
        "data_window": manifest.get("data_window"),
        "detection": report.get("detection"),
        "detection_null": report.get("detection_null"),
        "detection_lift": report.get("detection_lift"),
        "lift_p_value": report.get("lift_p_value"),
        "roc_auc": report.get("roc_auc"),
        "n_events": report.get("n_events"),
    }
