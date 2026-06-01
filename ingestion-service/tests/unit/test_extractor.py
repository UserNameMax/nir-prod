"""
Тесты для pipeline/extractor.py
Покрывает: BUG-005 (unar RAR5 arm64), BUG-006 (дубли xlsx при fallback)
"""
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from pipeline.extractor import _try_unar, _clear_dir, extract


# ── _clear_dir ─────────────────────────────────────────────────────────────────

def test_clear_dir_removes_files(tmp_path):
    """_clear_dir удаляет все файлы кроме keep."""
    archive = tmp_path / "data.rar"
    archive.write_bytes(b"fake rar")
    (tmp_path / "file1.xlsx").write_bytes(b"xlsx1")
    (tmp_path / "file2.xlsx").write_bytes(b"xlsx2")

    _clear_dir(str(tmp_path), keep={archive})

    assert archive.exists()
    assert not (tmp_path / "file1.xlsx").exists()
    assert not (tmp_path / "file2.xlsx").exists()


def test_clear_dir_keeps_archive(tmp_path):
    """BUG-006: первая версия фикса удаляла сам архив перед вызовом unrar."""
    archive = tmp_path / "data.rar"
    archive.write_bytes(b"fake rar")
    (tmp_path / "leftover.xlsx").write_bytes(b"data")

    _clear_dir(str(tmp_path), keep={archive})

    assert archive.exists(), "Архив не должен быть удалён"


def test_clear_dir_removes_subdirs(tmp_path):
    """_clear_dir удаляет вложенные директории (частичный результат unar)."""
    archive = tmp_path / "data.rar"
    archive.write_bytes(b"fake rar")
    subdir = tmp_path / "data"
    subdir.mkdir()
    (subdir / "file.xlsx").write_bytes(b"xlsx")

    _clear_dir(str(tmp_path), keep={archive})

    assert not subdir.exists()
    assert archive.exists()


# ── _try_unar: детектирование Failed! в stdout ────────────────────────────────

def test_unar_exit0_with_failed_in_stdout(tmp_path):
    """BUG-005: unar возвращает код 0 но выводит 'Failed!' — должно считаться ошибкой."""
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "Successfully extracted...\nFailed! Archive.rar\n"
    fake_result.stderr = ""

    with patch("pipeline.extractor.subprocess.run", return_value=fake_result):
        ok, output = _try_unar("dummy.rar", str(tmp_path))

    assert not ok, "unar с 'Failed!' в stdout должен считаться неуспешным"


def test_unar_exit0_without_failed_is_ok(tmp_path):
    """unar код 0 без 'Failed!' → успех."""
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "Successfully extracted 3 files.\n"
    fake_result.stderr = ""

    with patch("pipeline.extractor.subprocess.run", return_value=fake_result):
        ok, _ = _try_unar("dummy.rar", str(tmp_path))

    assert ok


def test_unar_nonzero_exit_is_failure(tmp_path):
    """unar с ненулевым кодом возврата → ошибка."""
    fake_result = MagicMock()
    fake_result.returncode = 1
    fake_result.stdout = ""
    fake_result.stderr = "Error: cannot open archive"

    with patch("pipeline.extractor.subprocess.run", return_value=fake_result):
        ok, _ = _try_unar("dummy.rar", str(tmp_path))

    assert not ok


# ── fallback unar → unrar ──────────────────────────────────────────────────────

def test_fallback_to_unrar_on_unar_failure(tmp_path):
    """BUG-005: unar возвращает Failed! → вызывается unrar, xlsx находятся."""
    archive = tmp_path / "test.rar"
    archive.write_bytes(b"fake rar")

    unar_result = MagicMock(returncode=0, stdout="Failed! test.rar", stderr="")

    def fake_run(cmd, **kwargs):
        if "unar" in str(cmd[0]):
            return unar_result
        else:
            # unrar: создаём файл в out_dir (3-й аргумент команды — путь)
            (tmp_path / "extracted.xlsx").write_bytes(b"fake xlsx")
            return MagicMock(returncode=0, stdout="All OK", stderr="")

    with patch("pipeline.extractor.subprocess.run", side_effect=fake_run), \
         patch("pipeline.extractor.shutil.which", return_value="/usr/bin/unrar"):
        result = extract(str(archive), str(tmp_path))

    assert len(result) >= 1
    assert all(f.suffix.lower() in (".xlsx", ".xls", ".xlsb") for f in result)


def test_unar_error_and_unrar_also_fails_raises(tmp_path):
    """Оба инструмента падают → RuntimeError с выводом обоих."""
    archive = tmp_path / "test.rar"
    archive.write_bytes(b"fake rar")

    unar_result = MagicMock(returncode=1, stdout="Failed!", stderr="unar error msg")
    unrar_result = MagicMock(returncode=1, stdout="", stderr="unrar error msg")

    with patch("pipeline.extractor.subprocess.run", side_effect=[unar_result, unrar_result]), \
         patch("pipeline.extractor.shutil.which", return_value="/usr/bin/unrar"):
        with pytest.raises(RuntimeError) as exc_info:
            extract(str(archive), str(tmp_path))

    assert "unar failed" in str(exc_info.value)
    assert "unrar failed" in str(exc_info.value)


# ── Поддержка расширений xlsx / xls / xlsb ────────────────────────────────────

def test_xlsb_found_by_extractor(tmp_path):
    """BUG-008: rglob('*.xlsx') не захватывал .xlsb — теперь ищем все форматы."""
    archive = tmp_path / "data.zip"
    xlsb_file = tmp_path / "export.xlsb"
    xlsb_file.write_bytes(b"fake xlsb content")

    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(xlsb_file, "export.xlsb")

    unar_result = MagicMock(returncode=0, stdout="Extracted 1 file.", stderr="")
    with patch("pipeline.extractor.subprocess.run", return_value=unar_result):
        result = extract(str(archive), str(tmp_path))

    suffixes = {f.suffix.lower() for f in result}
    assert ".xlsb" in suffixes, "xlsb должен быть найден extractor-ом"


def test_xls_found_by_extractor(tmp_path):
    """Extractor находит .xls файлы."""
    archive = tmp_path / "data.zip"
    xls_file = tmp_path / "export.xls"
    xls_file.write_bytes(b"fake xls content")

    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(xls_file, "export.xls")

    unar_result = MagicMock(returncode=0, stdout="Extracted 1 file.", stderr="")
    with patch("pipeline.extractor.subprocess.run", return_value=unar_result):
        result = extract(str(archive), str(tmp_path))

    suffixes = {f.suffix.lower() for f in result}
    assert ".xls" in suffixes


def test_no_duplicate_xlsx_after_fallback(tmp_path):
    """BUG-006: после fallback unar→unrar в out_dir не должно быть дублей."""
    archive = tmp_path / "data.rar"
    archive.write_bytes(b"fake rar")

    # Имитируем частичную распаковку unar: создаём файл в поддиректории
    subdir = tmp_path / "data"
    subdir.mkdir()
    (subdir / "file.xlsx").write_bytes(b"partial")

    # unar падает, _clear_dir вычищает subdir, unrar кладёт файл напрямую
    xlsx = tmp_path / "file.xlsx"

    unar_result = MagicMock(returncode=0, stdout="Failed!", stderr="")
    unrar_result = MagicMock(returncode=0, stdout="All OK", stderr="")

    def fake_run(cmd, **kwargs):
        if "unar" in cmd[0]:
            return unar_result
        # unrar — создаём финальный файл
        xlsx.write_bytes(b"real data")
        return unrar_result

    with patch("pipeline.extractor.subprocess.run", side_effect=fake_run), \
         patch("pipeline.extractor.shutil.which", return_value="/usr/bin/unrar"):
        result = extract(str(archive), str(tmp_path))

    # Только один файл — не (subdir/file.xlsx + file.xlsx)
    assert len(result) == 1, f"Ожидался 1 файл, найдено {len(result)}: {result}"
