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


def extract(archive_path: str, out_dir: str) -> list[Path]:
    """Распаковать RAR или ZIP. Сначала unar, при ошибке — unrar."""
    ok, output = _try_unar(archive_path, out_dir)

    if not ok:
        ok2, output2 = _try_unrar(archive_path, out_dir)
        if not ok2:
            raise RuntimeError(
                f"unar failed: {output.strip()}\nunrar failed: {output2.strip()}"
            )

    xlsx_files = sorted(Path(out_dir).rglob("*.xlsx"))
    return xlsx_files
