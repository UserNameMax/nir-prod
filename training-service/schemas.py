from __future__ import annotations
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Stage = Literal["fetch", "dataset", "train_acute", "train_chronic",
                "train_explain", "triggers", "validate", "publish"]


class TrainRequest(BaseModel):
    val_start: str | None = None
    test_start: str | None = None
    alert_rate: float = 0.02


class TrainJob(BaseModel):
    job_id: str
    status: Literal["queued", "processing", "done", "error"]
    created_at: datetime
    request: TrainRequest
    finished_at: datetime | None = None
    stage: Stage | None = None
    error: str | None = None
    stats: dict | None = None
