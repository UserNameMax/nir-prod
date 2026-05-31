import os

_DATA_DIR: str = os.getenv("DATA_DIR", "/app/data")


def get_data_dir() -> str:
    return _DATA_DIR


def override_data_dir(path: str) -> None:
    """Используется в тестах для подмены директории данных."""
    global _DATA_DIR
    _DATA_DIR = path
