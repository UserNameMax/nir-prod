from fastapi import APIRouter, Query, Depends

from schemas import Incident, BulkResult, Page
from storage import reader, writer
from dependencies import get_data_dir

router = APIRouter(prefix="/incidents", tags=["incidents"])

LIMIT_MAX = 100_000


@router.get("", response_model=Page[Incident])
def get_incidents(
    object_id: str | None = None,
    from_ts: int | None = None,
    to_ts: int | None = None,
    offset: int = 0,
    limit: int = Query(default=1000, le=LIMIT_MAX),
    data_dir: str = Depends(get_data_dir),
):
    items, total = reader.read_incidents(data_dir, object_id, from_ts, to_ts, offset, limit)
    return Page(items=items, total=total, offset=offset, limit=limit)


@router.get("/objects", response_model=list[str])
def get_incident_objects(data_dir: str = Depends(get_data_dir)):
    """object_id, у которых есть хотя бы одна авария."""
    return reader.read_incident_object_ids(data_dir)


@router.post("/bulk", response_model=BulkResult)
def bulk_insert(
    records: list[Incident],
    data_dir: str = Depends(get_data_dir),
):
    inserted, skipped = writer.bulk_insert_incidents(
        data_dir, [r.model_dump() for r in records]
    )
    return BulkResult(inserted=inserted, skipped_duplicates=skipped)
