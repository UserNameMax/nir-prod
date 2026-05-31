# История багов

---

## BUG-004 — record_id и object_id хранятся как int64 → 500 при GET /sensors

**Обнаружен:** прод (реальные данные)  
**Сервис:** data-service  
**Файл:** `storage/reader.py`

**Причина:** `sensors.parquet` из реальной выгрузки хранит `record_id` и `object_id` как `int64`. Pydantic-схема `SensorRecord` ожидает `str` — валидация ответа падала с `Input should be a valid string`.

**Фикс:** после чтения через DuckDB явно кастим `rows["record_id"].astype(str)` и `rows["object_id"].astype(str)` в `read_sensors` перед возвратом.

**Тест:** покрывается существующим `test_read_sensors_with_nan_sensor_values` (добавить вариант с int-колонками при следующем обновлении тестов).

---

## BUG-001 — NaN в meta payload вызывал 500 при POST /objects/bulk

**Обнаружен:** e2e тесты  
**Сервис:** ingestion-service  
**Файл:** `main.py`

**Причина:** формат B не содержит `object_type` и `facility_type` — поля заполняются `np.nan`. При конвертации `df.where(df.notna(), other=None).to_dict()` pandas конвертирует `None` обратно в `NaN` для float-колонок. FastAPI сериализует ответ с `allow_nan=False` и падает с `ValueError: Out of range float values are not JSON compliant: nan`.

**Фикс:** `meta.astype(object).where(meta.notna(), other=None).to_dict(orient="records")` — приведение к `object` dtype перед заменой предотвращает обратную конвертацию.

**Тест:** `ingestion-service/tests/unit/test_meta_payload.py`

---

## BUG-002 — NaN в строковых колонках parquet вызывал 500 при GET /objects

**Обнаружен:** e2e тесты  
**Сервис:** data-service  
**Файл:** `storage/reader.py`

**Причина:** `objects_meta.parquet` содержит `NaN` в строковых колонках (нормальная ситуация для объектов из format B). DuckDB читает их как `float('nan')`. FastAPI пытается сериализовать и падает.

**Фикс:** добавлена функция `_sanitize(records)` которая заменяет `float('nan')` и `float('inf')` на `None` во всех возвращаемых словарях. Применяется в `read_objects`, `read_sensors`, `read_object_by_id`.

**Тест:** `data-service/tests/unit/test_reader.py`

---

## BUG-003 — _sanitize не применялась к read_sensors

**Обнаружен:** unit тесты BUG-002 (в процессе написания)  
**Сервис:** data-service  
**Файл:** `storage/reader.py`

**Причина:** при реализации фикса BUG-002 `_sanitize` была добавлена в `read_objects` и `read_object_by_id`, но пропущена в `read_sensors`. Датчики с битыми значениями (все NaN после физических границ) вызвали бы crash при запросе `GET /sensors`.

**Фикс:** добавлен вызов `_sanitize` в `read_sensors`.

**Тест:** `data-service/tests/unit/test_reader.py::test_read_sensors_with_nan_sensor_values`
