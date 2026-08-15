from fastapi import APIRouter, Query, Depends, Request, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from typing import Annotated
from pathlib import Path
import asyncio
import shutil
import tempfile

from schemas import SensorRecord, Page, ObjectMeta
from storage import reader, writer
from dependencies import get_data_dir

router = APIRouter(prefix="/sensors", tags=["sensors"])

LIMIT_MAX = 10_000

# Очередь записи: батчи обрабатываются последовательно в фоне
_write_queue: asyncio.Queue = asyncio.Queue()
_write_worker_started = False


async def _write_worker():
    """Фоновый воркер — один merge на весь батч staging-файлов."""
    while True:
        data_dir, payload = await _write_queue.get()
        loop = asyncio.get_event_loop()
        try:
            if isinstance(payload, list) and payload and isinstance(payload[0], str):
                # Список путей к staging parquet файлам
                print(f"[write_worker] merging {len(payload)} staging files", flush=True)
                await loop.run_in_executor(
                    None, writer.bulk_insert_sensors_from_files, data_dir, payload
                )
            else:
                # Fallback: список dict (JSON режим)
                await loop.run_in_executor(None, writer.bulk_insert_sensors, data_dir, payload)
        except Exception as e:
            import traceback
            print(f"[write_worker] ERROR: {e}\n{traceback.format_exc()}", flush=True)
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


@router.get("/export")
def export_sensors(
    date_from: str | None = None,
    date_to: str | None = None,
    background: BackgroundTasks = None,
    data_dir: str = Depends(get_data_dir),
):
    """Показания за период одним parquet-файлом (массовое чтение для признаков).

    Постраничный JSON не годится: матрица признаков строится по всей сети сразу.
    """
    tmp = Path(tempfile.mkdtemp(prefix="export_")) / "sensors.parquet"
    rows = reader.export_sensors(data_dir, str(tmp), date_from, date_to)
    if rows == 0:
        shutil.rmtree(tmp.parent, ignore_errors=True)
        raise HTTPException(status_code=404, detail="Нет данных за период")

    background.add_task(shutil.rmtree, tmp.parent, ignore_errors=True)
    return FileResponse(
        str(tmp),
        media_type="application/vnd.apache.parquet",
        filename="sensors.parquet",
        headers={"X-Rows": str(rows)},
    )


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
async def bulk_insert(request: Request, data_dir: str = Depends(get_data_dir)):
    """Принимает батч через shared-parquet или JSON, ставит в очередь.

    Если тело содержит {"parquet_path": "..."} — читаем файл из shared volume.
    Иначе — сырой JSON список записей.
    Возвращает {} мгновенно.
    """
    ensure_worker()
    body = await request.json()
    if isinstance(body, dict) and "parquet_paths" in body:
        # Список staging файлов — один элемент очереди со всеми путями
        await _write_queue.put((data_dir, body["parquet_paths"]))
    elif isinstance(body, dict) and "parquet_path" in body:
        # Один файл (обратная совместимость)
        await _write_queue.put((data_dir, [body["parquet_path"]]))
    else:
        # Fallback: JSON список
        await _write_queue.put((data_dir, body))
    return {}


@router.get("/pending")
async def get_pending():
    """Кол-во батчей ожидающих записи в parquet."""
    return {"pending": _write_queue.qsize()}
