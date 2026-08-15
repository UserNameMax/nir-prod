from __future__ import annotations
from pydantic import BaseModel


class RebuildRequest(BaseModel):
    date_from: str | None = None
    date_to: str | None = None


class RebuildResult(BaseModel):
    object_days: int
    objects: int
    sensor_rows: int
    weather_days: int
    schema_version: str
