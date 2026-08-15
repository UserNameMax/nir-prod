"""Конфигурация labeling-service — всё через env (12-factor)."""
from __future__ import annotations

import os

# Контур данных
DATA_SERVICE_URL = os.getenv("DATA_SERVICE_URL", "http://data-service:8000")
DATA_DIR = os.getenv("DATA_DIR", "/app/data")

# LLM (Ollama) — единственная внешняя точка сервиса
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434/api/chat")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))

# Разрешение
FUZZY_THRESHOLD = int(os.getenv("FUZZY_THRESHOLD", "85"))
AUTOSAVE_EVERY = int(os.getenv("AUTOSAVE_EVERY", "20"))

# Excel-формат тех.нарушений МО
EXCEL_HEADER_ROW = int(os.getenv("EXCEL_HEADER_ROW", "8"))

# Метка-источник для data-service Incident.source
LABEL_SOURCE = os.getenv("LABEL_SOURCE", "тех.нарушения")


def resolver_cache_path() -> str:
    return os.path.join(DATA_DIR, "resolver_cache.json")
