# data-service — Спецификация тестов

## Стек

- `pytest`
- `pandas` + `pyarrow` для создания тестовых parquet-фикстур
- `duckdb`

---

## Unit-тесты

### `tests/unit/test_reader.py`

#### `test_sanitize_nan_becomes_none`
**Что:** `_sanitize` заменяет `float('nan')` → `None`.  
**Assert:** `result[0]['field'] is None`

#### `test_sanitize_inf_becomes_none`
**Что:** `_sanitize` заменяет `float('inf')` и `float('-inf')` → `None`.  
**Assert:** оба случая → `None`

#### `test_sanitize_valid_values_unchanged`
**Что:** числа, строки, `None` проходят `_sanitize` без изменений.  
**Assert:** значения идентичны входным

#### `test_sanitize_multiple_rows`
**Что:** `_sanitize` корректно обрабатывает список из нескольких записей.  
**Assert:** NaN в каждой строке → `None`, остальные значения сохранены

#### `test_read_objects_with_nan_string_fields`
**Что:** parquet с NaN в `object_type` и `facility_name` → `read_objects` возвращает записи с `None`, не падает.  
**Фикстура:** создать `objects_meta.parquet` с NaN через pandas в `tmp_path`.  
**Assert:** `items[0]['object_type'] is None`, `items[0]['facility_name'] is None`

#### `test_read_objects_all_nan_fields`
**Что:** все строковые поля NaN — ни одно не должно быть `float('nan')`.  
**Assert:** для каждого поля кроме `object_id` — значение либо не float, либо `None`

#### `test_read_objects_returns_none_not_nan_is_json_safe`
**Что:** результат `read_objects` сериализуется в JSON без ошибок.  
**Assert:** `json.dumps(items)` не бросает исключений, `"NaN"` отсутствует в строке

#### `test_read_sensors_with_nan_sensor_values`
**Что:** parquet с NaN в `t_supply` → `read_sensors` возвращает записи с `None`, не падает.  
**Assert:** `items[0]['t_supply'] is None`

#### `test_read_sensors_nan_is_json_safe`
**Что:** сенсорные данные с NaN сериализуются в JSON без ошибок.  
**Assert:** `"NaN"` отсутствует в сериализованном результате

#### `test_read_sensors_with_int64_record_id`
**Что:** parquet где `record_id` хранится как `int64` (старый формат до исправления ingestion) — `read_sensors` возвращает записи без 500 ошибки.  
**Баг:** BUG-004 — реальные parquet-файлы содержали `record_id: int64`. Pydantic-схема ожидает `str` → `Input should be a valid string`.  
**Фикстура:** создать `sensors.parquet` с `record_id` типа `int64` через pandas.  
**Assert:** `read_sensors()` возвращает записи, `items[0]['record_id']` — строка или int, `json.dumps(items)` не бросает исключений.

#### `test_read_sensors_with_int64_object_id`
**Что:** аналогично BUG-004 для `object_id: int64`.  
**Assert:** `read_sensors()` не падает, `items[0]['object_id']` — строка.
