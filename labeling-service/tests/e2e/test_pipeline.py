"""
Интеграция ingest → resolve → publish без Ollama и без docker.

data-service замокан respx (GET /objects, POST /incidents/bulk); LLM — monkeypatch.
"""
from __future__ import annotations

import httpx
import pytest
import respx

import config
import jobs
import main
from make_xlsx import write_sample

DATA_URL = config.DATA_SERVICE_URL


def _fake_llm(text, district, url, model, timeout):
    if "ЦТП-999" in text:
        return "ЦТП-999"
    if "ЦТП-1" in text:
        return "ЦТП-1"
    return "не найдено"


@pytest.mark.e2e
@respx.mock
def test_full_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main.resolve, "ask_llm", _fake_llm)

    respx.get(f"{DATA_URL}/objects").mock(return_value=httpx.Response(200, json={
        "items": [{"object_id": "100", "facility_type": "ЦТП",
                   "facility_name": "ЦТП-1", "municipality": "Тестовск"}],
        "total": 1, "offset": 0, "limit": 5000,
    }))
    publish_route = respx.post(f"{DATA_URL}/incidents/bulk").mock(
        return_value=httpx.Response(200, json={"inserted": 1, "skipped_duplicates": 0}))

    xlsx = write_sample(tmp_path / "tech.xlsx")
    job = jobs.create_job("tech.xlsx")
    main._pipeline(job.job_id, [xlsx])

    done = jobs.get_job(job.job_id)
    assert done.status == "done"
    s = done.stats
    assert s.incidents_ctp == 2          # 1001 (дубль схлопнут) + 1002
    assert s.go_events == 1              # котельная
    assert s.resolved == 1              # только ЦТП-1 (1002=ЦТП-999 нет в справочнике)
    assert s.unresolved == 1
    assert s.published == 1

    # проверяем payload, ушедший в data-service
    assert publish_route.called
    sent = publish_route.calls.last.request
    import json
    body = json.loads(sent.content)
    assert body[0]["object_id"] == "100"
    assert body[0]["incident_id"] == "1001"
    assert body[0]["source"] == config.LABEL_SOURCE


@pytest.mark.e2e
@respx.mock
def test_pipeline_llm_failure_marks_unresolved(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))

    def boom(*a, **k):
        raise httpx.ConnectError("ollama down")
    monkeypatch.setattr(main.resolve, "ask_llm", boom)

    respx.get(f"{DATA_URL}/objects").mock(return_value=httpx.Response(200, json={
        "items": [{"object_id": "100", "facility_type": "ЦТП",
                   "facility_name": "ЦТП-1", "municipality": "Тестовск"}], "total": 1,
        "offset": 0, "limit": 5000}))
    respx.post(f"{DATA_URL}/incidents/bulk").mock(
        return_value=httpx.Response(200, json={"inserted": 0, "skipped_duplicates": 0}))

    xlsx = write_sample(tmp_path / "tech.xlsx")
    job = jobs.create_job("tech.xlsx")
    main._pipeline(job.job_id, [xlsx])

    done = jobs.get_job(job.job_id)
    assert done.status == "done"        # ошибка LLM не валит задачу
    assert done.stats.resolved == 0
    assert done.stats.published == 0
