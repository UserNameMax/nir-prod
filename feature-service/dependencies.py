import os

_CACHE_DIR: str = os.getenv("FEATURE_DIR", "/app/data")


def get_cache_dir() -> str:
    return _CACHE_DIR


def override_cache_dir(path: str) -> None:
    """Используется в тестах для подмены директории кэша."""
    global _CACHE_DIR
    _CACHE_DIR = path
