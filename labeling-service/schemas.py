"""Pydantic-схемы labeling-service."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class LabelStats(BaseModel):
    """Итог одной задачи разметки — воронка от инцидентов к опубликованным меткам."""
    xlsx_files: int
    incidents_ctp: int           # строк с obj_ctp=True (кандидаты в аварии ЦТП)
    go_events: int               # котельные/тепловые сети (не размечаются)
    llm_extracted: int           # LLM вернул номер (не «не найдено»)
    resolved: int                # сопоставлено с object_id (fuzzy ≥ threshold)
    unresolved: int              # номер есть, но нет в справочнике / «не найдено»
    published: int               # реально вставлено в data-service (после дедупа)
    duplicates: int              # уже были в data-service
    period_from: datetime | None
    period_to: datetime | None


class LabelJob(BaseModel):
    job_id: str
    filename: str
    status: Literal["queued", "processing", "done", "error"]
    created_at: datetime
    finished_at: datetime | None = None
    stats: LabelStats | None = None
    error: str | None = None
    # прогресс
    stage: str | None = None            # ingest | resolve | publish
    incidents_total: int | None = None
    incidents_processed: int | None = None
