"""Unit-тесты resolve (оркестрация LLM+fuzzy, кэш/resume). LLM замокан."""
from __future__ import annotations

import json

import pandas as pd

import resolve
from fuzzy import CtpObject

CATALOG = [CtpObject("100", "ЦТП-1", "Тестовск"), CtpObject("102", "ЦТП-63", "Тестовск")]


def test_resolve_one_resolved(monkeypatch):
    monkeypatch.setattr(resolve, "ask_llm", lambda *a, **k: "ЦТП-1")
    r = resolve.resolve_one("txt", "Тестовск", CATALOG,
                            ollama_url="x", model="m", timeout=1, threshold=85)
    assert r.resolved and r.object_id == "100"


def test_resolve_one_unresolved_unknown_number(monkeypatch):
    monkeypatch.setattr(resolve, "ask_llm", lambda *a, **k: "ЦТП-999")
    r = resolve.resolve_one("txt", "Тестовск", CATALOG,
                            ollama_url="x", model="m", timeout=1, threshold=85)
    assert not r.resolved and r.llm_extracted == "ЦТП-999"


def test_resolve_one_llm_timeout(monkeypatch):
    import httpx

    def boom(*a, **k):
        raise httpx.TimeoutException("t")
    monkeypatch.setattr(resolve, "ask_llm", boom)
    r = resolve.resolve_one("txt", "Тестовск", CATALOG,
                            ollama_url="x", model="m", timeout=1, threshold=85)
    assert not r.resolved and r.llm_error == "timeout"


def test_batch_uses_cache_no_llm_recall(monkeypatch, tmp_path):
    # предзаполненный кэш → ask_llm не должен вызываться
    cache_path = str(tmp_path / "cache.json")
    json.dump({"5": {"id_cds_claim": 5, "object_id": "100",
                     "llm_extracted": "ЦТП-1", "fuzzy_score": 100.0, "llm_error": None}},
              open(cache_path, "w"))

    def fail(*a, **k):
        raise AssertionError("LLM не должен вызываться для кэшированного id")
    monkeypatch.setattr(resolve, "ask_llm", fail)

    incidents = pd.DataFrame([{"id_cds_claim": 5, "name_mr": "Тестовск", "text_message": "t"}])
    out = resolve.resolve_batch(incidents, CATALOG, cache_path, threshold=85)
    assert out["5"].resolved and out["5"].object_id == "100"


def test_batch_writes_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(resolve, "ask_llm", lambda *a, **k: "ЦТП-1")
    cache_path = str(tmp_path / "c.json")
    incidents = pd.DataFrame([{"id_cds_claim": 7, "name_mr": "Тестовск", "text_message": "t"}])
    resolve.resolve_batch(incidents, CATALOG, cache_path, threshold=85)
    saved = json.load(open(cache_path))
    assert saved["7"]["object_id"] == "100"
