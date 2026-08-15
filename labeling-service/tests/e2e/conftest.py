"""Фикстуры интеграционных тестов labeling-service."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "fixtures"))


@pytest.fixture(autouse=True)
def _reset_jobs():
    import jobs
    jobs._store.clear()
    yield
    jobs._store.clear()
