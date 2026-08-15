from __future__ import annotations
from pydantic import BaseModel


class WeatherDay(BaseModel):
    date: str
    t_out_mean: float | None = None
    t_out_min: float | None = None
    t_out_max: float | None = None
    heating_degree: float | None = None


class WeatherSeries(BaseModel):
    region: str
    rows: list[WeatherDay]


class RefreshRequest(BaseModel):
    date_from: str
    date_to: str
    force: bool = False


class RefreshResult(BaseModel):
    fetched: int
    added: int
    updated: int
    source: str
