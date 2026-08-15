"""Unit-тесты детерминированного ядра разрешения (fuzzy.py)."""
from __future__ import annotations

from fuzzy import CtpObject, clean_municipality, match, normalize_ctp

CATALOG = [
    CtpObject("100", "ЦТП-1", "Тестовск"),
    CtpObject("101", "ЦТП-1-3-4", "Тестовск"),
    CtpObject("102", "ЦТП-63", "Тестовск"),
    CtpObject("200", "ЦТП-1", "Другой"),          # тот же номер, другой район
]


def test_normalize_number_only():
    assert normalize_ctp("ЦТП-1105") == "1105"
    assert normalize_ctp("ЦТП № 1-3-4") == "1-3-4"
    assert normalize_ctp("цтп1105") == "1105"
    assert normalize_ctp("ЦТП-1-21-2") == "1-21-2"


def test_clean_municipality():
    assert clean_municipality("Химки г.о.") == "Химки"
    assert clean_municipality("Мытищи г.") == "Мытищи"


def test_exact_match_within_district():
    m = match("ЦТП-1", "Тестовск г.о.", CATALOG, threshold=85)
    assert m is not None and m.object_id == "100" and m.score == 100.0


def test_district_filter_disambiguates_same_number():
    # 'ЦТП-1' есть в двух районах — фильтр по муниципалитету выбирает правильный
    m = match("ЦТП-1", "Другой", CATALOG, threshold=85)
    assert m is not None and m.object_id == "200"


def test_strict_ratio_rejects_close_numbers():
    # '63' против '1' и '1-3-4' — ниже порога → нет матча в этом районе, кроме ЦТП-63
    m = match("ЦТП-63", "Тестовск", CATALOG, threshold=85)
    assert m is not None and m.object_id == "102"


def test_unknown_number_below_threshold():
    assert match("ЦТП-999", "Тестовск", CATALOG, threshold=85) is None


def test_not_found_and_empty():
    assert match("не найдено", "Тестовск", CATALOG, 85) is None
    assert match("", "Тестовск", CATALOG, 85) is None
    assert match(None, "Тестовск", CATALOG, 85) is None


def test_empty_catalog():
    assert match("ЦТП-1", "Тестовск", [], 85) is None
