"""
Детерминированное ядро разрешения ЦТП: нормализация имени + fuzzy-матч по справочнику.

Полностью отделено от LLM и от I/O — чистая функция, покрывается unit-тестами
и используется в сравнении с черновым разметчиком (labler/) для проверки паритета.

Логика намеренно повторяет черновой `labler/lib/resolver.py` (number-only нормализация,
строгий `fuzz.ratio`, фильтр по муниципалитету), чтобы продакшен воспроизводил
разметку черновика ровно.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz, process

_NOT_FOUND = "не найдено"


def normalize_ctp(name: str) -> str:
    """Имя ЦТП → только числовая часть: 'ЦТП-1-3-4' → '1-3-4', 'цтп1105' → '1105'."""
    name = str(name).lower()
    name = re.sub(r"[№#\s]", "", name)     # убираем пробелы и спецсимволы
    name = re.sub(r"-+", "-", name)         # двойные дефисы → один
    m = re.match(r"цтп-?(.+)", name)
    return m.group(1).strip("-") if m else name


def clean_municipality(mr: str) -> str:
    """'Химки г.о.' → 'Химки' (убираем суффиксы г.о./г. для фильтра справочника)."""
    return re.sub(r"\s*(г\.о\.|г\.)\s*", "", str(mr)).strip()


@dataclass(frozen=True)
class CtpObject:
    """Запись справочника ЦТП с телеметрией."""
    object_id: str
    facility_name: str
    municipality: str

    @property
    def norm(self) -> str:
        return normalize_ctp(self.facility_name)


@dataclass(frozen=True)
class MatchResult:
    object_id: str
    matched_name: str
    municipality: str
    score: float


def match(
    extracted: str | None,
    district: str,
    catalog: list[CtpObject],
    threshold: int = 85,
) -> MatchResult | None:
    """
    Сопоставляет извлечённое LLM имя ЦТП с записью справочника.

    Возвращает MatchResult при score ≥ threshold, иначе None (→ unresolved).
    Приоритет поиска — внутри муниципалитета; при пустом подмножестве fallback на весь
    справочник (риск ложного матча выше, но событие не теряется).
    """
    if not extracted or str(extracted).strip().lower() == _NOT_FOUND:
        return None

    district_clean = clean_municipality(district)
    subset = [o for o in catalog if district_clean and district_clean.lower() in o.municipality.lower()]
    if not subset:
        subset = catalog
    if not subset:
        return None

    norm_query = normalize_ctp(extracted)
    names_norm = [o.norm for o in subset]
    result = process.extractOne(
        norm_query,
        names_norm,
        scorer=fuzz.ratio,          # строгое посимвольное: '63' ≉ '3'
        score_cutoff=threshold,
    )
    if result is None:
        return None

    _, score, idx = result
    obj = subset[idx]
    return MatchResult(
        object_id=str(obj.object_id),
        matched_name=obj.facility_name,
        municipality=obj.municipality,
        score=float(score),
    )
