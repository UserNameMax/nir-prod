"""Генераторы тестовых xlsx-файлов форматов A и B."""
from pathlib import Path
import pandas as pd


def make_format_a(path: Path, rows: int = 5, alt_name_col: bool = False) -> None:
    """Создать xlsx формата A."""
    name_col = "Наименование объекта" if alt_name_col else "Наименование котельной"
    data = {
        "ID":                       [str(100 + i) for i in range(rows)],
        "Дата и время показателей": pd.date_range("2025-11-01", periods=rows, freq="h"),
        "T пр":                     [60.0 + i for i in range(rows)],
        "T обр":                    [50.0 + i for i in range(rows)],
        "P пр":                     [6.0 for _ in range(rows)],
        "P обр":                    [4.0 for _ in range(rows)],
        "Дата и время записи":      pd.date_range("2025-11-01 00:01", periods=rows, freq="h"),
        "ID объекта":               ["OBJ_1" if i < rows // 2 else "OBJ_2" for i in range(rows)],
        "Тип объекта":              ["Богородский г.о." for _ in range(rows)],
        "Котельная/ЦТП":            ["ЦТП" for _ in range(rows)],
        name_col:                   ["Котельная Западная" for _ in range(rows)],
        "Муниципалитет":            ["Богородский г.о." for _ in range(rows)],
        "РСО":                      ["МосОблЕИРЦ" for _ in range(rows)],
    }
    pd.DataFrame(data).to_excel(path, index=False)


def make_format_b(path: Path, rows: int = 5) -> None:
    """Создать xlsx формата B."""
    data = {
        "id":          [str(200 + i) for i in range(rows)],
        "data":        pd.date_range("2025-11-01", periods=rows, freq="h"),
        "t_forward":   [65.0 + i for i in range(rows)],
        "t_revers":    [55.0 + i for i in range(rows)],
        "p_forward":   [7.0 for _ in range(rows)],
        "p_revers":    [5.0 for _ in range(rows)],
        "object_id":   ["OBJ_3" for _ in range(rows)],
        "name_koteln": ["Котельная Восточная" for _ in range(rows)],
        "name_mr":     ["Балашиха г.о." for _ in range(rows)],
    }
    pd.DataFrame(data).to_excel(path, index=False)


def make_format_a_with_bad_rows(path: Path) -> None:
    """Формат A с битыми строками для тестов cleaner."""
    data = {
        "ID":                       ["1", "2", "3", "4", "5"],
        "Дата и время показателей": pd.date_range("2025-11-01", periods=5, freq="h"),
        "T пр":                     [60.0, 200.0, None, 60.0, 60.0],   # 200 — out of range
        "T обр":                    [50.0, 50.0,  None, None, 50.0],
        "P пр":                     [6.0,  6.0,   None, None, 6.0],
        "P обр":                    [4.0,  4.0,   None, None, None],
        "Дата и время записи":      pd.date_range("2025-11-01 00:01", periods=5, freq="h"),
        "ID объекта":               ["OBJ_1", "OBJ_1", None, "OBJ_1", "OBJ_1"],  # row 3: NaN object_id
        "Тип объекта":              ["ЦТП"] * 5,
        "Котельная/ЦТП":            ["ЦТП"] * 5,
        "Наименование котельной":   ["Котельная"] * 5,
        "Муниципалитет":            ["Богородский г.о."] * 5,
        "РСО":                      ["МосОблЕИРЦ"] * 5,
    }
    pd.DataFrame(data).to_excel(path, index=False)
