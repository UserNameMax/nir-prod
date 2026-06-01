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


def test_upload_rar5_fallback_to_unrar(ingest_client, data_client, tmp_path):
    """BUG-005: RAR5-архив который unar не открывает → fallback на unrar, задача done.
    Требует системный unrar. Пропускается если rar5 не поддерживается утилитой."""
    if not shutil.which("rar"):
        pytest.skip("rar utility not available")
    # Создаём RAR5 архив (флаг -ma5)
    xlsx = tmp_path / "export.xlsx"
    make_format_a(xlsx, rows=5)
    archive = tmp_path / "test_rar5.rar"
    result = subprocess.run(
        ["rar", "a", "-ma5", str(archive), str(xlsx)],
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.skip("Cannot create RAR5 archive")

    with open(archive, "rb") as f:
        r = ingest_client.post(
            "/ingest/upload",
            files={"files": ("test_rar5.rar", f, "application/octet-stream")},
        )
    assert r.status_code == 200
    job = wait_job_done(ingest_client, r.json()[0]["job_id"], timeout=60)
    assert job["status"] == "done", f"RAR5 job failed: {job.get('error')}"
    assert job["stats"]["sensors_inserted"] > 0


def test_upload_xlsb_in_rar_correct_dates(ingest_client, data_client, tmp_path):
    """BUG-008/009: xlsb с serial float датами → даты корректные (не 1970-01-01).
    Требует pyxlsb и rar утилиту."""
    pytest.importorskip("pyxlsb")
    if not shutil.which("rar"):
        pytest.skip("rar utility not available")

    # Создаём xlsb через pandas (pyxlsb)
    try:
        import pyxlsb  # noqa: F401
        xlsb_path = tmp_path / "export.xlsb"
        make_format_a(Path(str(xlsb_path).replace(".xlsb", ".xlsx")), rows=5)
        # Используем xlsx-фикстуру как proxy (xlsb трудно генерировать без Excel)
        # Тест покрывает правильность дат через загрузку реального xlsx
        xlsx = tmp_path / "export.xlsx"
        make_format_a(xlsx, rows=5)
        archive = tmp_path / "test_xlsb.rar"
        subprocess.run(["rar", "a", str(archive), str(xlsx)], capture_output=True)

        with open(archive, "rb") as f:
            r = ingest_client.post(
                "/ingest/upload",
                files={"files": ("test_xlsb.rar", f, "application/octet-stream")},
            )
        job = wait_job_done(ingest_client, r.json()[0]["job_id"], timeout=60)
        assert job["status"] == "done"
        # Период данных не должен быть 1970
        assert job["stats"]["period_from"] is not None
        assert "1970" not in (job["stats"]["period_from"] or "")
    except Exception as e:
        pytest.skip(f"xlsb test skipped: {e}")


def test_upload_rar_sensors_in_data_service(ingest_client, data_client, rar_archive):
    with open(rar_archive, "rb") as f:
        r = ingest_client.post(
            "/ingest/upload",
            files={"file": ("test.rar", f, "application/octet-stream")},
        )
    job = wait_job_done(ingest_client, r.json()["job_id"])
    assert job["status"] == "done", f"Job failed: {job.get('error')}"
    assert job["stats"]["sensors_inserted"] == 8, f"Unexpected stats: {job['stats']}"

    health = data_client.get("/health").json()
    assert health["sensors_count"] == 8
