"""
E2E тесты ingestion-service — RAR архивы.

RAR генерируется через системную утилиту rar/unar. Если rar не установлен —
тесты пропускаются автоматически.
"""
from __future__ import annotations
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from tests.fixtures.make_xlsx import make_format_a
from tests.e2e.helpers import wait_job_done


def _make_rar(archive_path: Path, xlsx_path: Path) -> bool:
    """Создать RAR архив через системную утилиту rar. Вернуть False если недоступна."""
    if not shutil.which("rar"):
        return False
    result = subprocess.run(
        ["rar", "a", str(archive_path), str(xlsx_path)],
        capture_output=True,
    )
    return result.returncode == 0


@pytest.fixture
def rar_archive(tmp_path):
    xlsx = tmp_path / "export.xlsx"
    make_format_a(xlsx, rows=8)
    archive = tmp_path / "test.rar"
    ok = _make_rar(archive, xlsx)
    if not ok:
        pytest.skip("rar utility not available — skipping RAR e2e tests")
    return archive


def test_upload_rar_completes(ingest_client, rar_archive):
    with open(rar_archive, "rb") as f:
        r = ingest_client.post(
            "/ingest/upload",
            files={"file": ("test.rar", f, "application/octet-stream")},
        )
    assert r.status_code == 200
    job = wait_job_done(ingest_client, r.json()["job_id"])
    assert job["status"] == "done"
    assert job["stats"]["sensors_inserted"] == 8


def test_upload_rar_sensors_in_data_service(ingest_client, data_client, rar_archive):
    with open(rar_archive, "rb") as f:
        r = ingest_client.post(
            "/ingest/upload",
            files={"file": ("test.rar", f, "application/octet-stream")},
        )
    wait_job_done(ingest_client, r.json()["job_id"])

    health = data_client.get("/health").json()
    assert health["sensors_count"] == 8
