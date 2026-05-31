# ingestion-service — Спецификация тестов

## Стек

- `pytest` + `pytest-asyncio`
- `httpx.AsyncClient` для запросов к сервису в e2e
- `respx` для мокирования HTTP-вызовов к data-service в unit-тестах
- `openpyxl` для генерации тестовых xlsx-фикстур
- `pytest-tmp-path` (встроен в pytest) для временных директорий

---

## Тестовая инфраструктура

E2E тесты поднимают **изолированный стек** — data-service и ingestion-service указывают на временные parquet-файлы, не на `../data/`.

```
tests/
├── fixtures/
│   ├── make_xlsx.py         генераторы тестовых xlsx (форматы A и B)
│   ├── sample_format_a.xlsx маленький эталонный файл формата A (10 строк)
│   └── sample_format_b.xlsx маленький эталонный файл формата B (10 строк)
├── unit/
│   ├── test_parser.py
│   ├── test_cleaner.py
│   └── test_meta_payload.py  тесты BUG-001
└── e2e/
    ├── conftest.py           session-фикстура services + autouse clean_data
    ├── helpers.py            wait_job_done(client, job_id, timeout)
    ├── test_ingest_zip.py
    └── test_ingest_rar.py
```

> `conftest.py` намеренно лежит в `tests/e2e/` (не в `tests/`), чтобы `autouse`-фикстура `clean_data` не применялась к unit-тестам.

### Изоляция данных

`conftest.py` создаёт `tmp_path/data/` с пустыми parquet-файлами перед каждым e2e-тестом и удаляет после. data-service запускается с `DATA_DIR=<tmp_path>/data`.

```
docker-compose.test.yml
  data-service:
    environment:
      DATA_DIR: /tmp/test-data     ← bind-mount из tmp_path хоста
  ingestion-service:
    environment:
      DATA_SERVICE_URL: http://data-service:8000
```

Альтернатива без Docker (быстрее): запускать оба сервиса как subprocess через `uvicorn` прямо в pytest с `--port` из свободного диапазона.

---

## Unit-тесты

### `test_extractor.py` — распаковка архивов (BUG-005, BUG-006, BUG-007)

#### `test_fallback_to_unrar_on_unar_failure`
**Что:** если unar возвращает `Failed!` в stdout — вызывается unrar как fallback.  
**Фикстура:** мокируем `_try_unar` → возвращает `(False, "Failed!")`, мокируем `_try_unrar` → возвращает `(True, "All OK")`.  
**Assert:** `_try_unrar` был вызван; xlsx-файлы найдены.

#### `test_no_duplicate_xlsx_after_fallback`
**Что:** после fallback unar→unrar в out_dir нет дублей xlsx.  
**Фикстура:** создаём `out_dir` с несколькими xlsx (имитируем частичную распаковку unar), потом вызываем `_clear_dir(out_dir, keep={archive_path})`.  
**Assert:** после очистки в out_dir только архив, xlsx удалены.

#### `test_clear_dir_keeps_archive`
**Что:** `_clear_dir` удаляет распакованные файлы но не трогает архив.  
**Assert:** архив на месте, остальные файлы удалены.

#### `test_xlsb_found_by_extractor`
**Что:** `extract()` на архиве с `.xlsb` файлами возвращает их в списке.  
**Фикстура:** ZIP с `export.xlsb`.  
**Assert:** `len(result) == 1`, `result[0].suffix == ".xlsb"`.

#### `test_unar_error_and_unrar_also_fails_raises`
**Что:** оба инструмента падают → `RuntimeError` содержит вывод обоих.  
**Assert:** `raises(RuntimeError)`, в сообщении есть `unar failed` и `unrar failed`.

---

### `test_parser.py` — парсинг Excel

#### `test_xlsb_dates_parsed_correctly`
**Что:** `.xlsb`-файл формата A с числовыми датами (Excel serial) парсится с корректными `ts_recorded`.  
**Фикстура:** `.xlsb` с колонками формата A, дата `Дата и время записи = 45000.5` (≈ 2023-03-17).  
**Assert:** `sensors['ts_recorded'].iloc[0] > 0`, значение соответствует ожидаемому timestamp.

#### `test_detect_format_a`
**Что:** файл с колонкой `T пр` → формат A.  
**Фикстура:** DataFrame с заголовками формата A.  
**Assert:** `detect_format(df) == "A"`

#### `test_detect_format_b`
**Что:** файл с колонкой `t_forward` → формат B.  
**Assert:** `detect_format(df) == "B"`

#### `test_detect_format_unknown`
**Что:** файл с незнакомыми заголовками → `"UNKNOWN"`.  
**Assert:** `detect_format(df) == "UNKNOWN"`

#### `test_normalize_format_a_columns`
**Что:** после нормализации формата A DataFrame содержит все нужные колонки в правильных типах.  
**Assert:** колонки `record_id`, `object_id`, `ts_measurement`, `t_supply`, `t_return`, `p_supply`, `p_return`, `ts_recorded` присутствуют; `ts_measurement` и `ts_recorded` — int64.

#### `test_normalize_format_a_alt_name`
**Что:** вариант с `Наименование объекта` вместо `Наименование котельной` нормализуется корректно.  
**Assert:** колонка `facility_name` заполнена.

#### `test_normalize_format_b_ts_measurement_equals_ts_recorded`
**Что:** в формате B нет отдельной колонки времени измерения → `ts_measurement == ts_recorded`.  
**Assert:** `sensors['ts_measurement'].equals(sensors['ts_recorded'])`

#### `test_normalize_format_b_missing_meta_columns`
**Что:** `object_type` и `facility_type` отсутствуют в формате B → заполняются NaN.  
**Assert:** `meta['object_type'].isna().all()`

---

### `test_cleaner.py` — очистка данных

#### `test_physical_bounds_out_of_range_to_nan`
**Что:** значение `t_supply=200.0` (выше 150) → становится NaN, строка не удаляется если есть другие датчики.  
**Assert:** `sensors.loc[0, 't_supply'] is NaN`, строка осталась.

#### `test_drop_row_all_sensors_nan`
**Что:** строка где все 4 датчика NaN — удаляется.  
**Assert:** `len(result) == len(input) - 1`

#### `test_keep_row_partial_nan`
**Что:** строка где только `p_return` NaN, остальные в норме — остаётся.  
**Assert:** строка присутствует в результате.

#### `test_drop_missing_required_fields`
**Что:** строки с NaN в `record_id`, `object_id`, `ts_recorded` — удаляются.  
**Assert:** `len(result) == 0` для датафрейма где все строки с NaN в обязательных полях.

#### `test_dedup_by_record_id`
**Что:** две строки с одинаковым `record_id` → остаётся одна.  
**Assert:** `len(result) == 1`

---

## E2E-тесты

Перед каждым тестом: `tmp_data/` с пустыми `sensors.parquet` и `objects_meta.parquet`. После теста: директория удаляется.

---

### `test_ingest_zip.py`

#### `test_upload_zip_returns_job_id`
**Что:** POST `/ingest/upload` с валидным ZIP → возвращает `job_id` и `status=processing`.  
**Фикстура:** ZIP с одним xlsx формата A (10 строк, 2 объекта).  
**Assert:** ответ содержит `job_id: str`, `status == "processing"`.

#### `test_job_completes`
**Что:** после загрузки задача переходит в `done`.  
**Фикстура:** тот же ZIP.  
**Assert:** polling GET `/ingest/jobs/{id}` с timeout 30с → `status == "done"`, `stats` не None.

#### `test_sensors_saved_to_data_service`
**Что:** после успешной задачи данные доступны через data-service.  
**Assert:** GET `data-service:8000/sensors?object_id=<id из фикстуры>` → `total > 0`.

#### `test_objects_meta_saved`
**Что:** метаданные объектов сохранены.  
**Assert:** GET `data-service:8000/objects/<object_id>` → 200, поля заполнены.

---

### `test_ingest_rar.py`

#### `test_upload_rar_completes`
**Что:** RAR-архив с xlsx формата A → задача переходит в `done`.  
**Assert:** `status == "done"`.

#### `test_upload_rar_sensors_in_data_service`
**Что:** после успешной задачи данные доступны через data-service.  
**Assert:** `job["stats"]["sensors_inserted"] == 8`, данные видны через `GET /sensors`.

---

### `test_ingest_upload.py` — загрузка файлов (BUG-007)

#### `test_upload_file_size_matches_original`
**Что:** размер сохранённого архива совпадает с оригиналом.  
**Фикстура:** ZIP-архив известного размера.  
**Шаги:** POST `/ingest/upload`, считать байты сохранённого файла через логи или доп. эндпоинт.  
**Assert:** `saved_bytes == original_bytes`.

#### `test_upload_multiple_files_queued`
**Что:** загрузка нескольких файлов одним запросом — все получают статус `queued`.  
**Фикстура:** два ZIP-архива.  
**Assert:** ответ содержит 2 job_id, оба `status == "queued"`, обрабатываются последовательно.

---

### `test_ingest_zip.py` — корректность мёрджа

#### `test_merge_deduplication`
**Что:** загрузить один и тот же архив дважды → данные не дублируются.  
**Шаги:**
1. Загрузить архив, дождаться `done`, запомнить `sensors_count = stats.sensors_inserted`
2. Загрузить тот же архив повторно, дождаться `done`
3. GET `/health` data-service → `sensors_count` не изменился

**Assert:** `second_job.stats.sensors_inserted == 0`, `second_job.stats.sensors_duplicates == sensors_count`

#### `test_merge_new_records_added`
**Что:** загрузить архив A (объекты 1,2), потом архив B (объекты 2,3) → итого 3 уникальных объекта, данные объекта 2 не задвоились.  
**Шаги:**
1. Загрузить архив A (record_id: 1..10, objects: 1,2)
2. Загрузить архив B (record_id: 11..20, objects: 2,3)
3. GET `/sensors?object_id=2` → считаем строки

**Assert:** кол-во строк объекта 2 = кол-во его строк из A + кол-во его строк из B (без дублей).

#### `test_merge_partial_overlap`
**Что:** архив B содержит 5 строк из архива A (одинаковые `record_id`) и 5 новых → вставляется ровно 5.  
**Assert:** `second_job.stats.sensors_inserted == 5`, `sensors_duplicates == 5`
