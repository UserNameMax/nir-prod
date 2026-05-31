"""
E2E инфраструктура.

Поднимает data-service и ingestion-service через docker-compose.test.yml
один раз на всю сессию pytest. Перед каждым тестом очищает данные
(удаляет parquet-файлы внутри контейнера через DELETE-эндпоинт или
пересоздаёт volume).

Переменные окружения:
  DATA_SERVICE_URL   — если задан, тесты используют уже запущенный стек
                       (CI или ручной docker-compose up)
  INGEST_SERVICE_URL — аналогично
"""
from __future__ import annotations

import os
import time

import httpx
import pytest

DATA_URL = os.getenv("DATA_SERVICE_URL", "http://localhost:18000")
INGEST_URL = os.getenv("INGEST_SERVICE_URL", "http://localhost:18001")

STARTUP_TIMEOUT = 60  # секунд


def _wait_ready(url: str, timeout: int = STARTUP_TIMEOUT) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{url}/health", timeout=2)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f"Service not ready: {url}")


@pytest.fixture(scope="session", autouse=True)
def services():
    """Ждём готовности обоих сервисов (запущены снаружи или в CI)."""
    _wait_ready(DATA_URL)
    # ingestion-service не имеет /health — проверяем /ingest/jobs
    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        try:
            r = httpx.get(f"{INGEST_URL}/ingest/jobs", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        raise RuntimeError(f"Ingestion service not ready: {INGEST_URL}")
    yield


@pytest.fixture(autouse=True)
def clean_data():
    """Очищаем parquet перед каждым тестом через специальный эндпоинт."""
    httpx.delete(f"{DATA_URL}/_test/reset", timeout=10)
    yield


@pytest.fixture
def data_client() -> httpx.Client:
    with httpx.Client(base_url=DATA_URL, timeout=30) as c:
        yield c


@pytest.fixture
def ingest_client() -> httpx.Client:
    with httpx.Client(base_url=INGEST_URL, timeout=30) as c:
        yield c


def wait_job_done(client: httpx.Client, job_id: str, timeout: int = 60) -> dict:
    """Polling до status=done|error."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/ingest/jobs/{job_id}")
        r.raise_for_status()
        job = r.json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(1)
    raise TimeoutError(f"Job {job_id} did not finish in {timeout}s")
