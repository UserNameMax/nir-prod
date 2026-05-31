from fastapi import APIRouter, Query, Depends, HTTPException

from schemas import ObjectMeta, ObjectMetaUpdate, BulkResult, Page
from storage import reader, writer
from dependencies import get_data_dir

router = APIRouter(prefix="/objects", tags=["objects"])

LIMIT_MAX = 10_000


@router.get("", response_model=Page[ObjectMeta])
def get_objects(
    municipality: str | None = None,
    facility_type: str | None = None,
    q: str | None = None,
    offset: int = 0,
    limit: int = Query(default=100, le=LIMIT_MAX),
    data_dir: str = Depends(get_data_dir),
):
    items, total = reader.read_objects(data_dir, municipality, facility_type, q, offset, limit)
    return Page(items=items, total=total, offset=offset, limit=limit)


@router.get("/{object_id}", response_model=ObjectMeta)
def get_object(object_id: str, data_dir: str = Depends(get_data_dir)):
    obj = reader.read_object_by_id(data_dir, object_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Object not found")
    return obj


@router.put("/{object_id}", response_model=ObjectMeta)
def update_object(
    object_id: str,
    body: ObjectMetaUpdate,
    data_dir: str = Depends(get_data_dir),
):
    result = writer.update_object(data_dir, object_id, body.model_dump(exclude_none=True))
    if result is None:
        raise HTTPException(status_code=404, detail="Object not found")
    return result


@router.post("/bulk", response_model=BulkResult)
def bulk_upsert(
    records: list[ObjectMeta],
    data_dir: str = Depends(get_data_dir),
):
    inserted, skipped = writer.bulk_upsert_objects(
        data_dir, [r.model_dump() for r in records]
    )
    return BulkResult(inserted=inserted, skipped_duplicates=skipped)
