# data-service — Спецификация тестов

## Стек

- `pytest`
- `pandas` + `pyarrow` для создания тестовых parquet-фикстур
- `duckdb`

---

## Unit-тесты

### `tests/unit/test_reader.py`

---

## Регрессионные тесты (баги найденные в e2e)

### BUG-002 — NaN в строковых колонках parquet → crash при JSON-сериализации

**Воспроизведение:** `objects_meta.parquet` содержит `NaN` в строковых колонках (`object_type`, `facility_name` и др.) — это нормально, так как ingestion-service format B не заполняет эти поля. DuckDB читает их как `float('nan')`. FastAPI пытается сериализовать ответ в JSON и падает с `ValueError: Out of range float values are not JSON compliant: nan`. В итоге `GET /objects` возвращает 500.

**Фикс:** функция `_sanitize(records)` в `reader.py` заменяет `float('nan')` и `float('inf')` на `None` во всех возвращаемых словарях.

#### `test_sanitize_nan_becomes_none`
**Что:** `_sanitize` заменяет `float('nan')` → `None`.  
**Assert:** `result[0]['field'] is None`

#### `test_sanitize_inf_becomes_none`
**Что:** `_sanitize` заменяет `float('inf')` и `float('-inf')` → `None`.  
**Assert:** оба случая → `None`

#### `test_sanitize_valid_values_unchanged`
**Что:** числа, строки, `None` проходят `_sanitize` без изменений.  
**Assert:** значения идентичны входным

#### `test_read_objects_with_nan_string_fields`
**Что:** parquet с NaN в `object_type` и `facility_name` → `read_objects` возвращает записи с `None` в этих полях, не падает.  
**Фикстура:** создать `objects_meta.parquet` с NaN через pandas в `tmp_path`.  
**Assert:** `items[0]['object_type'] is None`, `items[0]['facility_name'] is None`

#### `test_read_sensors_with_nan_sensor_values`
**Что:** parquet с NaN в `t_supply` → `read_sensors` возвращает записи с `None`, не падает.  
**Assert:** `items[0]['t_supply'] is None`
