import os

_BUNDLE_DIR: str = os.getenv("MODEL_BUNDLE_DIR", "/models")


def get_bundle_dir() -> str:
    return _BUNDLE_DIR


def override_bundle_dir(path: str) -> None:
    """Используется в тестах для подмены каталога бандла."""
    global _BUNDLE_DIR
    _BUNDLE_DIR = path
