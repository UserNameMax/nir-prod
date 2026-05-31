import subprocess
import shutil
from pathlib import Path


def _try_unar(archive_path: str, out_dir: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["unar", "-o", out_dir, "-f", archive_path],
        capture_output=True, text=True,
    )
    output = result.stdout + result.stderr
    ok = result.returncode == 0 and "Failed!" not in output
    return ok, output


def _try_unrar(archive_path: str, out_dir: str) -> tuple[bool, str]:
    if not shutil.which("unrar"):
        return False, "unrar not found"
    result = subprocess.run(
        ["unrar", "x", "-y", archive_path, out_dir + "/"],
        capture_output=True, text=True,
    )
    output = result.stdout + result.stderr
    ok = result.returncode == 0
    return ok, output


def _clear_dir(directory: str, keep: set[Path]) -> None:
    """Удалить содержимое каталога кроме файлов из keep."""
    p = Path(directory)
    for child in p.iterdir():
        if child in keep:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def extract(archive_path: str, out_dir: str) -> list[Path]:
    """Распаковать RAR или ZIP. Сначала unar, при ошибке — unrar."""
    ok, output = _try_unar(archive_path, out_dir)

    if not ok:
        # Чистим то что unar успел распаковать, но сохраняем сам архив
        _clear_dir(out_dir, keep={Path(archive_path)})
        ok2, output2 = _try_unrar(archive_path, out_dir)
        if not ok2:
            raise RuntimeError(
                f"unar failed: {output.strip()}\nunrar failed: {output2.strip()}"
            )

    all_files = sorted(Path(out_dir).rglob("*"))
    xls_files = [f for f in all_files if f.suffix.lower() in (".xlsx", ".xls", ".xlsb") and f.is_file()]
    non_xls = [f.name for f in all_files if f.is_file() and f.suffix.lower() not in (".xlsx", ".xls", ".xlsb", ".rar", ".zip")]
    print(f"[extractor] found {len(xls_files)} excel files in {out_dir}", flush=True)
    if non_xls:
        print(f"[extractor] non-excel files: {non_xls[:10]}", flush=True)
    return xls_files
