from fastapi import APIRouter, Query, Depends, BackgroundTasks
from typing import Annotated
import asyncio

from schemas import SensorRecord, Page, ObjectMeta
from storage import reader, writer
from dependencies import get_data_dir

router = APIRouter(prefix="/sensors", tags=["sensors"])

LIMIT_MAX = 10_000

# Очередь записи: батчи обрабатываются последовательно в фоне
_write_queue: asyncio.Queue = asyncio.Queue()
_write_worker_started = False


async def _write_worker():
    """Фоновый воркер — пишет батчи в parquet последовательно."""
    while True:
        data_dir, records = await _write_queue.get()
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, writer.bulk_insert_sensors, data_dir, records)
        except Exception as e:
            print(f"[write_worker] ERROR: {e}", flush=True)
        finally:
            _write_queue.task_done()


def ensure_worker():
    global _write_worker_started
    if not _write_worker_started:
        asyncio.create_task(_write_worker())
        _write_worker_started = True


@router.get("", response_model=Page[SensorRecord])
def get_sensors(
    object_id: Annotated[str, Query()],
    from_ts: int | None = None,
    to_ts: int | None = None,
    offset: int = 0,
    limit: int = Query(default=1000, le=LIMIT_MAX),
    data_dir: str = Depends(get_data_dir),
):
    items, total = reader.read_sensors(data_dir, object_id, from_ts, to_ts, offset, limit)
    return Page(items=items, total=total, offset=offset, limit=limit)


@router.get("/calendar")
def get_calendar(
    object_id: Annotated[str, Query()],
    data_dir: str = Depends(get_data_dir),
):
    dates = reader.read_sensors_calendar(data_dir, object_id)
    return {"dates": dates}


@router.get("/calendar/objects", response_model=Page[ObjectMeta])
def get_objects_by_day(
    date: Annotated[str, Query(description="YYYY-MM-DD")],
    offset: int = 0,
    limit: int = Query(default=100, le=LIMIT_MAX),
    data_dir: str = Depends(get_data_dir),
):
    items, total = reader.read_objects_by_day(data_dir, date, offset, limit)
    return Page(items=items, total=total, offset=offset, limit=limit)


@router.get("/calendar/summary")
def get_calendar_summary(
    from_date: str | None = None,
    to_date: str | None = None,
    data_dir: str = Depends(get_data_dir),
):
    return reader.read_sensors_calendar_summary(data_dir, from_date, to_date)


@router.post("/bulk")
async def bulk_insert(
    records: list[SensorRecord],
    data_dir: str = Depends(get_data_dir),
):
    """Принимает батч, ставит в очередь записи, возвращает сразу."""
    ensure_worker()
    records_list = [r.model_dump() for r in records]
    await _write_queue.put((data_dir, records_list))
    return {}


@router.get("/pending")
async def get_pending():
    """Кол-во батчей ожидающих записи в parquet."""
    return {"pending": _write_queue.qsize()}
