"""Генераторы тестовых ZIP-архивов с xlsx-файлами для e2e тестов."""
from __future__ import annotations
import zipfile
from pathlib import Path
import pandas as pd

from tests.fixtures.make_xlsx import make_format_a, make_format_b


def make_zip_format_a(
    archive_path: Path,
    tmp_dir: Path,
    rows: int = 10,
    filename: str = "export_part_1.xlsx",
) -> Path:
    xlsx = tmp_dir / filename
    make_format_a(xlsx, rows=rows)
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.write(xlsx, arcname=filename)
    return archive_path


def make_zip_format_b(
    archive_path: Path,
    tmp_dir: Path,
    rows: int = 10,
    filename: str = "outfile_part_1.xlsx",
) -> Path:
    xlsx = tmp_dir / filename
    make_format_b(xlsx, rows=rows)
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.write(xlsx, arcname=filename)
    return archive_path


def make_zip_two_files(
    archive_path: Path,
    tmp_dir: Path,
    rows_a: int = 5,
    rows_b: int = 5,
) -> Path:
    """ZIP с двумя xlsx: формат A (объекты 1,2) и формат B (объект 3)."""
    xlsx_a = tmp_dir / "export_part_1.xlsx"
    xlsx_b = tmp_dir / "outfile_part_1.xlsx"
    make_format_a(xlsx_a, rows=rows_a)
    make_format_b(xlsx_b, rows=rows_b)
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.write(xlsx_a, arcname=xlsx_a.name)
        zf.write(xlsx_b, arcname=xlsx_b.name)
    return archive_path


def make_zip_with_overlap(
    archive_path: Path,
    tmp_dir: Path,
    base_records: list[dict],
    new_records: list[dict],
    filename: str = "export_part_overlap.xlsx",
) -> Path:
    """ZIP с файлом содержащим переданные строки (уже нормализованные в формат A)."""
    data = {
        "ID":                       [r["record_id"] for r in base_records + new_records],
        "Дата и время показателей": pd.to_datetime(
            [r["ts_measurement"] for r in base_records + new_records], unit="s"
        ),
        "T пр":   [r.get("t_supply", 60.0) for r in base_records + new_records],
        "T обр":  [r.get("t_return", 50.0) for r in base_records + new_records],
        "P пр":   [r.get("p_supply", 6.0) for r in base_records + new_records],
        "P обр":  [r.get("p_return", 4.0) for r in base_records + new_records],
        "Дата и время записи": pd.to_datetime(
            [r["ts_recorded"] for r in base_records + new_records], unit="s"
        ),
        "ID объекта":             [r["object_id"] for r in base_records + new_records],
        "Тип объекта":            ["ЦТП"] * (len(base_records) + len(new_records)),
        "Котельная/ЦТП":         ["ЦТП"] * (len(base_records) + len(new_records)),
        "Наименование котельной": ["Котельная Тест"] * (len(base_records) + len(new_records)),
        "Муниципалитет":          ["Тест г.о."] * (len(base_records) + len(new_records)),
        "РСО":                    ["Тест"] * (len(base_records) + len(new_records)),
    }
    xlsx = tmp_dir / filename
    pd.DataFrame(data).to_excel(xlsx, index=False)
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.write(xlsx, arcname=filename)
    return archive_path
