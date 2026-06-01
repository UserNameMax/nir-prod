# История багов

---

## BUG-013 — JSON body 33 МБ не проходит через Docker overlay на macOS

**Обнаружен:** прод (macOS Docker Desktop)  
**Сервис:** ingestion-service → data-service  
**Файлы:** `ingestion-service/main.py`, `data-service/routers/sensors.py`, `data-service/storage/writer.py`

**Причина:** JSON-сериализация 200k записей = 33 МБ. Передача через Docker overlay на macOS (VirtioFS/gVisor) работает на скорости ~0.5-1 МБ/с → 30+ секунд → httpx timeout. Pydantic-валидация 200k объектов SensorRecord также добавляла 30+ секунд.

**Цепочка попыток:**
1. BATCH_SIZE 500k → 200k → 50k (меньше = меньше тело, но всё равно 8 МБ = 12 сек)
2. Убрана Pydantic-валидация (`request.json()` вместо `list[SensorRecord]`) — помогло частично
3. Async queue + POST возвращает {} — но накопление 25 батчей в очереди = CPU 101%, event loop заблокирован

**Фикс:** shared Docker volume `incoming`. Ingestion пишет все батчи как parquet файлы, отправляет только список путей (56 байт JSON). Data-service воркер читает все файлы через `pd.concat`, делает ОДИН `_duckdb_append`, удаляет staging файлы. HTTP body = 56 байт, response мгновенный.

**Тест:** `test_ingest_zip.py::test_sensors_saved_to_data_service` (покрывает end-to-end путь).

---

## BUG-012 — httpx timeout при записи больших батчей в data-service

**Обнаружен:** прод (sensors.parquet > 1 ГБ)  
**Сервис:** ingestion-service → data-service  
**Файлы:** `data-service/routers/sensors.py`, `ingestion-service/main.py`

**Причина:** `POST /sensors/bulk` выполнял DuckDB COPY синхронно — читал весь parquet (1+ ГБ) и писал tmp-файл той же величины. При 42M+ строк это занимало >120 сек. httpx ждал ответа и падал с `timed out`. Дополнительно мешала нехватка места на диске (ENOSPC при создании tmp-файла).

**Фикс:**
- `POST /sensors/bulk` теперь кладёт данные в `asyncio.Queue` и возвращает `{}` немедленно
- Фоновый воркер (`_write_worker`) пишет батчи последовательно через `run_in_executor`
- `GET /sensors/pending` — ingestion-service ждёт опустошения очереди
- Подсчёт inserted: `sensors_after - sensors_before` через `GET /health`
- BATCH_SIZE: 500k → 200k, httpx timeout: 120 → 30 сек (POST мгновенный)

**Тест:** `test_ingest_zip.py::test_sensors_saved_to_data_service` — проверить что после done данные видны (неявно покрывает pending-ожидание).

---

## BUG-008 — xlsb-файлы не распознавались и давали нулевые даты

**Обнаружен:** прод (реальные данные, архив 18.12-24.12.rar)  
**Сервис:** ingestion-service  
**Файлы:** `pipeline/extractor.py`, `pipeline/parser.py`

**Причина 1 — файлы не находились:** `rglob("*.xlsx")` не захватывает `.xlsb` — `xlsx_files_found: 0`, задача завершалась без ошибок и без данных.

**Причина 2 — неверные даты после фикса поиска:** `.xlsb` хранит даты как float (Excel serial: дней с 30.12.1899). `pd.to_datetime(float, errors='coerce')` трактует значение как наносекунды → все даты = 1970-01-01 (unix 0). В parquet записалось 1.08M строк с `ts_recorded = 0`.

**Фикс:**
1. `extractor.py`: ищем `.xlsx`, `.xls`, `.xlsb`; движок `pyxlsb` для чтения
2. `parser.py`: добавлена `_to_datetime(series)` — при числовом типе применяет `unit='D', origin='1899-12-30'`
3. Строки с `ts_recorded < 86400` удалены из parquet через DuckDB точечно (без пересоздания всей базы)

**Тест:** `test_parser.py::test_xlsb_serial_float_dates_parsed_correctly`, `test_ingest_rar.py::test_upload_xlsb_in_rar_correct_dates`.

**Подбаг BUG-008b:** pandas 2.x требует numeric dtype при `pd.to_datetime(series, unit="D")`. С `dtype=object` серия содержит float-значения в object-обёртке — pandas кидает `"series is not compatible with origin; it must be numeric"`. Фикс: `pd.to_numeric(series, errors="coerce")` перед `pd.to_datetime`.

---

## BUG-009 — `_to_unix` заменял NaT на 0 (эпоха 1970), строки проходили cleaner

**Обнаружен:** прод (после фикса BUG-008)  
**Сервис:** ingestion-service  
**Файл:** `pipeline/parser.py`, `main.py`

**Причина:** `_to_unix` делал `fillna(pd.Timestamp(0))` перед `astype("int64")`. Строки с невалидными датами получали `ts_recorded = 0`. Cleaner удаляет строки где `ts_recorded` **is NaN** — но 0 это не NaN, строки проходили. `period_from` = min(ts_recorded) = 1970-01-01.

**Фикс:**
1. `_to_unix` теперь возвращает `float64`: `unix.where(dt.notna())` — NaT → `NaN`. Cleaner корректно удаляет такие строки.
2. `period_from/to` в `main.py` фильтрует `ts_recorded > 0` перед `min/max`.
3. 130k строк с ts~0 удалены из parquet точечным DuckDB-скриптом.

**Тест:** `test_cleaner.py::test_drop_row_ts_recorded_nan_from_invalid_date`, `test_parser.py::test_invalid_date_string_becomes_nan`.

---

## BUG-010 — `"Тип ��бъекта"` — битый символ в rename dict → все object_type NULL

**Обнаружен:** сравнение OLD vs NEW parquet  
**Сервис:** ingestion-service  
**Файл:** `pipeline/parser.py`

**Причина:** в rename dict для формата A ключ `"Тип объекта"` содержал битый символ (replacement character). Rename не срабатывал → ветка `if col not in df.columns: df[col] = np.nan` заполняла весь столбец NaN. В NEW parquet: `null object_type: 4,559 (все!)` vs OLD: `null: 10`.

**Фикс:** исправлен ключ на корректный `"Тип объекта"`.

**Тест:** `test_parser.py::test_object_type_column_populated`, `test_ingest_zip.py::test_object_type_not_null_after_ingest`.

---

## BUG-011 — `astype(str)` на NaN давал строку `"nan"` вместо null

**Обнаружен:** сравнение OLD vs NEW parquet + 422 на /objects/bulk  
**Сервис:** ingestion-service  
**Файл:** `pipeline/parser.py`, `main.py`

**Причина:** `df["object_id"].astype(str)` превращал пустые ячейки Excel (NaN) в строку `"nan"`. Это приводило к двум проблемам:
1. В базу записывался объект с `object_id="nan"` — мусорная запись
2. После замены на `_clean_str` (`pd.NA`): `meta.to_dict()` давал `{"object_id": None}` → Pydantic 422 (поле обязательное)

**Фикс:**
1. `_clean_str(series)`: `astype(str).str.strip()` + замена `"nan"/"None"/""` → `pd.NA`
2. `main.py`: `meta.dropna(subset=["object_id"])` перед отправкой на `/objects/bulk`
3. Cleaner корректно удаляет строки с `pd.NA` в `object_id` через `dropna`

**Тест:** `test_parser.py::test_object_id_nan_becomes_pd_na`, `test_meta_payload.py::test_null_object_id_filtered_before_bulk`.

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
