from __future__ import annotations
from typing import Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class SensorRecord(BaseModel):
    record_id: str
    object_id: str
    ts_measurement: int
    t_supply: float | None = None
    t_return: float | None = None
    p_supply: float | None = None
    p_return: float | None = None
    ts_recorded: int


class ObjectMeta(BaseModel):
    object_id: str
    object_type: str | None = None
    facility_type: str | None = None
    facility_name: str | None = None
    municipality: str | None = None
    rso: str | None = None


class ObjectMetaUpdate(BaseModel):
    object_type: str | None = None
    facility_type: str | None = None
    facility_name: str | None = None
    municipality: str | None = None
    rso: str | None = None


class BulkResult(BaseModel):
    inserted: int
    skipped_duplicates: int


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int
