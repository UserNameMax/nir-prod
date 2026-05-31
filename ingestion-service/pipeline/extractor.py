import subprocess
from pathlib import Path


def extract(archive_path: str, out_dir: str) -> list[Path]:
    """Распаковать RAR или ZIP через unar, вернуть список xlsx-файлов."""
    result = subprocess.run(
        ["unar", "-o", out_dir, "-f", archive_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"unar failed: {result.stderr.strip()}")

    xlsx_files = sorted(Path(out_dir).rglob("*.xlsx"))
    return xlsx_files
