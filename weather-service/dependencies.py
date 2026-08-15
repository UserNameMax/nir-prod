import os

_WEATHER_DIR: str = os.getenv("WEATHER_DIR", "/app/data")


def get_weather_dir() -> str:
    return _WEATHER_DIR


def override_weather_dir(path: str) -> None:
    """Используется в тестах для подмены директории данных."""
    global _WEATHER_DIR
    _WEATHER_DIR = path
