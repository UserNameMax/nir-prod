from fastapi import APIRouter, Query, Depends
from typing import Annotated

from schemas import SensorRecord, BulkResult, Page
from storage import reader, writer
from dependencies import get_data_dir

router = APIRouter(prefix="/sensors", tags=["sensors"])

LIMIT_MAX = 10_000


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


@router.get("/calendar/summary")
def get_calendar_summary(
    from_date: str | None = None,
    to_date: str | None = None,
    data_dir: str = Depends(get_data_dir),
):
    return reader.read_sensors_calendar_summary(data_dir, from_date, to_date)


@router.post("/bulk", response_model=BulkResult)
def bulk_insert(
    records: list[SensorRecord],
    data_dir: str = Depends(get_data_dir),
):
    inserted, skipped = writer.bulk_insert_sensors(
        data_dir, [r.model_dump() for r in records]
    )
    return BulkResult(inserted=inserted, skipped_duplicates=skipped)
