"""
E2E тесты ingestion-service — ZIP архивы.

Требуют запущенного стека:
  docker-compose -f docker-compose.test.yml up --build -d
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from tests.fixtures.make_archives import (
    make_zip_format_a,
    make_zip_format_b,
    make_zip_two_files,
    make_zip_with_overlap,
)
from tests.e2e.helpers import wait_job_done

BASE_TS = 1_700_000_000


# ── Базовые тесты ──────────────────────────────────────────────────────────────

def test_upload_zip_returns_job_id(ingest_client, tmp_path):
    archive = make_zip_format_a(tmp_path / "test.zip", tmp_path, rows=5)
    with open(archive, "rb") as f:
        r = ingest_client.post("/ingest/upload", files={"file": ("test.zip", f, "application/zip")})
    assert r.status_code == 200
    body = r.json()
    assert "job_id" in body
    assert body["status"] == "processing"
    wait_job_done(ingest_client, body["job_id"])  # ждём чтобы не было race condition с clean_data


def test_job_completes(ingest_client, tmp_path):
    archive = make_zip_format_a(tmp_path / "test.zip", tmp_path, rows=10)
    with open(archive, "rb") as f:
        r = ingest_client.post("/ingest/upload", files={"file": ("test.zip", f, "application/zip")})
    job_id = r.json()["job_id"]

    job = wait_job_done(ingest_client, job_id)
    assert job["status"] == "done"
    assert job["stats"] is not None
    assert job["stats"]["xlsx_files_found"] == 1
    assert job["stats"]["sensors_inserted"] == 10


def test_sensors_saved_to_data_service(ingest_client, data_client, tmp_path):
    archive = make_zip_format_a(tmp_path / "test.zip", tmp_path, rows=5)
    with open(archive, "rb") as f:
        r = ingest_client.post("/ingest/upload", files={"file": ("test.zip", f, "application/zip")})
    wait_job_done(ingest_client, r.json()["job_id"])

    # Берём первый объект из meta и проверяем что его данные есть в sensors
    objects_r = data_client.get("/objects", params={"limit": 1})
    assert objects_r.status_code == 200
    objects_data = objects_r.json()
    assert objects_data["total"] > 0

    obj_id = objects_data["items"][0]["object_id"]
    sensors_r = data_client.get("/sensors", params={"object_id": obj_id})
    assert sensors_r.status_code == 200
    assert sensors_r.json()["total"] > 0


def test_objects_meta_saved(ingest_client, data_client, tmp_path):
    archive = make_zip_format_a(tmp_path / "test.zip", tmp_path, rows=5)
    with open(archive, "rb") as f:
        r = ingest_client.post("/ingest/upload", files={"file": ("test.zip", f, "application/zip")})
    wait_job_done(ingest_client, r.json()["job_id"])

    r = data_client.get("/objects", params={"limit": 10})
    assert r.status_code == 200
    assert r.json()["total"] > 0


def test_two_xlsx_formats_in_one_zip(ingest_client, data_client, tmp_path):
    archive = make_zip_two_files(tmp_path / "test.zip", tmp_path, rows_a=5, rows_b=5)
    with open(archive, "rb") as f:
        r = ingest_client.post("/ingest/upload", files={"file": ("test.zip", f, "application/zip")})
    job = wait_job_done(ingest_client, r.json()["job_id"])

    assert job["status"] == "done"
    assert job["stats"]["xlsx_files_found"] == 2
    assert job["stats"]["sensors_inserted"] == 10


def test_upload_invalid_extension_rejected(ingest_client, tmp_path):
    txt = tmp_path / "data.txt"
    txt.write_text("not an archive")
    with open(txt, "rb") as f:
        r = ingest_client.post("/ingest/upload", files={"file": ("data.txt", f, "text/plain")})
    assert r.status_code == 400


# ── Корректность мёрджа ────────────────────────────────────────────────────────

def test_merge_deduplication(ingest_client, data_client, tmp_path):
    """Повторная загрузка того же архива — данные не дублируются."""
    archive = make_zip_format_a(tmp_path / "test.zip", tmp_path, rows=10)

    for _ in range(2):
        with open(archive, "rb") as f:
            r = ingest_client.post("/ingest/upload", files={"file": ("test.zip", f, "application/zip")})
        wait_job_done(ingest_client, r.json()["job_id"])

    health = data_client.get("/health").json()
    assert health["sensors_count"] == 10  # не 20


def test_merge_deduplication_second_job_stats(ingest_client, tmp_path):
    """Второй upload того же архива: inserted=0, duplicates=N."""
    archive = make_zip_format_a(tmp_path / "test.zip", tmp_path, rows=10)

    with open(archive, "rb") as f:
        r = ingest_client.post("/ingest/upload", files={"file": ("test.zip", f, "application/zip")})
    wait_job_done(ingest_client, r.json()["job_id"])

    with open(archive, "rb") as f:
        r = ingest_client.post("/ingest/upload", files={"file": ("test.zip", f, "application/zip")})
    job2 = wait_job_done(ingest_client, r.json()["job_id"])

    assert job2["stats"]["sensors_inserted"] == 0
    assert job2["stats"]["sensors_duplicates"] == 10


def test_merge_new_records_added(ingest_client, data_client, tmp_path):
    """Два архива с непересекающимися record_id — суммируются."""
    # Архив A: record_id 100..104, объекты OBJ_1 и OBJ_2
    archive_a = make_zip_format_a(tmp_path / "a.zip", tmp_path, rows=5, filename="a.xlsx")

    # Архив B: record_id 200..204, объект OBJ_3
    archive_b = make_zip_format_b(tmp_path / "b.zip", tmp_path, rows=5, filename="b.xlsx")

    for archive in (archive_a, archive_b):
        with open(archive, "rb") as f:
            name = archive.name
            r = ingest_client.post("/ingest/upload", files={"file": (name, f, "application/zip")})
        wait_job_done(ingest_client, r.json()["job_id"])

    health = data_client.get("/health").json()
    assert health["sensors_count"] == 10


def test_merge_partial_overlap(ingest_client, data_client, tmp_path):
    """Частичное перекрытие: 5 старых record_id + 5 новых → inserted=5, duplicates=5."""
    base = [
        {"record_id": str(i), "object_id": "OBJ_1",
         "ts_measurement": BASE_TS + i * 60,
         "ts_recorded": BASE_TS + i * 60 + 5}
        for i in range(5)
    ]
    new = [
        {"record_id": str(i + 5), "object_id": "OBJ_1",
         "ts_measurement": BASE_TS + (i + 5) * 60,
         "ts_recorded": BASE_TS + (i + 5) * 60 + 5}
        for i in range(5)
    ]

    # Первый архив: только base (record_id 0..4)
    archive1 = make_zip_with_overlap(tmp_path / "first.zip", tmp_path, base, [], filename="first.xlsx")
    with open(archive1, "rb") as f:
        r = ingest_client.post("/ingest/upload", files={"file": ("first.zip", f, "application/zip")})
    wait_job_done(ingest_client, r.json()["job_id"])

    # Второй архив: base (0..4) + new (5..9) — перекрытие 5 строк
    archive2 = make_zip_with_overlap(tmp_path / "second.zip", tmp_path, base, new, filename="second.xlsx")
    with open(archive2, "rb") as f:
        r = ingest_client.post("/ingest/upload", files={"file": ("second.zip", f, "application/zip")})
    job2 = wait_job_done(ingest_client, r.json()["job_id"])

    assert job2["stats"]["sensors_inserted"] == 5
    assert job2["stats"]["sensors_duplicates"] == 5

    health = data_client.get("/health").json()
    assert health["sensors_count"] == 10
