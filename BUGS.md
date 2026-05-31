# История багов

---

## BUG-005 — unar на arm64/Linux не может распаковать некоторые RAR5

**Обнаружен:** прод (реальные данные)  
**Сервис:** ingestion-service  
**Файл:** `pipeline/extractor.py`

**Причина:** unar 1.10.x на Debian arm64 падает с `Attempted to read more data than was available` на RAR5-архивах с определённым методом сжатия. Та же версия на macOS открывает их без ошибок.

**Фикс:** добавлен fallback на `unrar` (non-free): сначала пробуем unar, при `Failed!` в выводе — чистим частично распакованные файлы и запускаем unrar.

**Тест:** нужен unit-тест `test_extractor.py::test_fallback_to_unrar_on_unar_failure` — мокируем unar как падающий, проверяем что вызывается unrar.

---

## BUG-006 — Частичная распаковка unar + fallback unrar давала дубликаты xlsx

**Обнаружен:** прод (реальные данные)  
**Сервис:** ingestion-service  
**Файл:** `pipeline/extractor.py`

**Причина:** unar распаковывает N-1 файлов в `out_dir/archive_name/`, потом unrar распаковывает все N в `out_dir/`. `rglob("*.xlsx")` находит (N-1) + N файлов → дубли, двойная обработка данных.

**Фикс:** перед запуском unrar очищаем `out_dir` кроме самого архива (`_clear_dir(out_dir, keep={Path(archive_path)})`).

**Тест:** нужен unit-тест `test_extractor.py::test_no_duplicate_xlsx_after_fallback`.

---

## BUG-007 — Архив обрезается при загрузке через браузер (>400 МБ)

**Обнаружен:** прод (реальные данные)  
**Сервис:** ingestion-service  
**Файл:** `main.py`

**Причина:** `await file.read()` читал весь файл одним куском — при больших файлах браузер обрывал соединение до завершения. Файл сохранялся обрезанным, unar падал на последнем xlsx.

**Фикс:** заменено на чтение по 1 МБ чанкам: `while chunk := await file.read(1024 * 1024)`. Добавлен `--timeout-keep-alive 300` в uvicorn.

**Тест:** нужен e2e-тест `test_ingest_zip.py::test_large_archive_upload_complete` — проверять что `os.path.getsize` совпадает с `Content-Length`.

---

## BUG-004 — record_id и object_id хранятся как int64 → 500 при GET /sensors

**Обнаружен:** прод (реальные данные)  
**Сервис:** data-service  
**Файл:** `storage/reader.py`

**Причина:** `sensors.parquet` из реальной выгрузки хранит `record_id` и `object_id` как `int64`. Pydantic-схема `SensorRecord` ожидает `str` — валидация ответа падала с `Input should be a valid string`.

**Фикс:** `parser.py` уже делает `astype(str)` для `record_id` и `object_id` при нормализации форматов A и B — данные загруженные через ingestion-service всегда строки. Временный каст в `reader.py` убран. Старые parquet-файлы нужно перезалить через сервис.

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
