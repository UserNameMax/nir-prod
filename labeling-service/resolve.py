"""
Resolve: инцидент (текст+район) → object_id через LLM-извлечение + fuzzy-матч.

LLM (Ollama) извлекает номер ЦТП из свободного текста; детерминированное ядро
`fuzzy.match` сопоставляет его со справочником. Checkpoint-кэш по id_cds_claim
делает шаг идемпотентным и возобновляемым (LLM не переспрашивается).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx

import config
from fuzzy import CtpObject, match

SYSTEM_PROMPT = """/no_think
Ты — система извлечения информации из технических заявок об авариях в тепловых сетях.
Из текста заявки извлеки идентификатор ЦТП, который является непосредственной причиной отключения.

Формат ответа: только идентификатор ЦТП — буквы "ЦТП", дефис и номер. Одна строка, ничего лишнего.
Не добавляй: адрес, улицу, район, название микрорайона, скобки, пояснения.
Если в тексте номер ЦТП указан без префикса "ЦТП" — добавь его сам.
Если ЦТП не упомянут как причина отключения — верни: не найдено

Примеры:
Текст: "...отключение в связи с утечкой на ЦТП-1105 по ул. Панфилова..." → ЦТП-1105
Текст: "...ремонтные работы на ЦТП № 1-3-4, без ГВС 5 МКД..." → ЦТП-1-3-4
Текст: "...в мкр. Знамя Октября от ЦТП-23 отключены дома..." → ЦТП-23"""


@dataclass
class Resolution:
    object_id: str | None
    llm_extracted: str
    fuzzy_score: float
    llm_error: str | None = None

    @property
    def resolved(self) -> bool:
        return self.object_id is not None


def ask_llm(text: str, district: str, ollama_url: str, model: str, timeout: int) -> str:
    """Запрос к Ollama. Возвращает первую непустую строку ответа."""
    payload = {
        "model": model, "think": False, "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Район: {district}\nТекст: {text}"},
        ],
    }
    resp = httpx.post(ollama_url, json=payload, timeout=timeout)
    resp.raise_for_status()
    raw = resp.json()["message"]["content"].strip()
    for line in raw.splitlines():
        if line.strip():
            return line.strip()
    return raw


# ── Checkpoint-кэш ──────────────────────────────────────────────────────────

def load_cache(path: str) -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def resolve_one(
    text: str,
    district: str,
    catalog: list[CtpObject],
    *,
    ollama_url: str,
    model: str,
    timeout: int,
    threshold: int,
) -> Resolution:
    """Одно событие: LLM → fuzzy. Ошибки LLM не валят задачу — событие → unresolved."""
    try:
        extracted = ask_llm(text, district, ollama_url, model, timeout)
        llm_error = None
    except httpx.TimeoutException:
        return Resolution(None, "не найдено", 0.0, llm_error="timeout")
    except httpx.HTTPError as exc:
        return Resolution(None, "не найдено", 0.0, llm_error=f"llm:{type(exc).__name__}")

    m = match(extracted, district, catalog, threshold)
    if m is None:
        return Resolution(None, extracted, 0.0, llm_error=llm_error)
    return Resolution(m.object_id, extracted, m.score, llm_error=llm_error)


def resolve_batch(
    incidents,                    # pd.DataFrame: id_cds_claim, name_mr, text_message
    catalog: list[CtpObject],
    cache_path: str,
    *,
    ollama_url: str | None = None,
    model: str | None = None,
    timeout: int | None = None,
    threshold: int | None = None,
    autosave_every: int = 20,
    progress=None,                # callable(done:int, total:int) | None
) -> dict[str, Resolution]:
    """
    Разрешает все инциденты. Кэш по id_cds_claim → resume. Возвращает {claim_id: Resolution}.
    """
    ollama_url = ollama_url or config.OLLAMA_URL
    model = model or config.LLM_MODEL
    timeout = timeout or config.LLM_TIMEOUT
    threshold = threshold if threshold is not None else config.FUZZY_THRESHOLD

    cache = load_cache(cache_path)
    total = len(incidents)
    out: dict[str, Resolution] = {}

    for i, row in enumerate(incidents.itertuples(index=False), 1):
        claim_id = str(row.id_cds_claim)
        if claim_id in cache:
            c = cache[claim_id]
            out[claim_id] = Resolution(
                c.get("object_id"), c.get("llm_extracted", "не найдено"),
                float(c.get("fuzzy_score", 0.0)), c.get("llm_error"),
            )
        else:
            r = resolve_one(
                str(row.text_message), str(row.name_mr), catalog,
                ollama_url=ollama_url, model=model, timeout=timeout, threshold=threshold,
            )
            out[claim_id] = r
            cache[claim_id] = {
                "id_cds_claim": int(row.id_cds_claim),
                "object_id": r.object_id, "llm_extracted": r.llm_extracted,
                "fuzzy_score": r.fuzzy_score, "llm_error": r.llm_error,
            }
            if i % autosave_every == 0:
                save_cache(cache, cache_path)
        if progress is not None:
            progress(i, total)

    save_cache(cache, cache_path)
    return out
