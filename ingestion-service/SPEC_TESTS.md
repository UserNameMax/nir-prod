# ingestion-service — Спецификация тестов

## Стек

- `pytest` + `pytest-asyncio`
- `httpx.AsyncClient` для запросов к сервису в e2e
- `respx` для мокирования HTTP-вызовов к data-service в unit-тестах
- `openpyxl` для генерации тестовых xlsx-фикстур
- `pyxlsb` для генерации xlsb-фикстур (или создание через zipfile напрямую)
- `pytest-tmp-path` (встроен в pytest) для временных директорий

---

## Тестовая инфраструктура

E2E тесты поднимают **изолированный стек** — data-service и ingestion-service указывают на временные parquet-файлы, не на `../data/`.

```
tests/
├── fixtures/
│   ├── make_xlsx.py         генераторы тестовых xlsx (форматы A и B)
│   ├── make_xlsb.py         генератор xlsb-фикстур (формат A с float-датами)
│   ├── sample_format_a.xlsx маленький эталонный файл формата A (10 строк)
│   └── sample_format_b.xlsx маленький эталонный файл формата B (10 строк)
├── unit/
│   ├── test_extractor.py
│   ├── test_parser.py
│   ├── test_cleaner.py
│   └── test_meta_payload.py  тесты BUG-001
└── e2e/
    ├── conftest.py           session-фикстура services + autouse clean_data
    ├── helpers.py            wait_job_done(client, job_id, timeout)
    ├── test_ingest_zip.py
    ├── test_ingest_rar.py
    └── test_ingest_upload.py
```

> `conftest.py` намеренно лежит в `tests/e2e/` (не в `tests/`), чтобы `autouse`-фикстура `clean_data` не применялась к unit-тестам.

---

## Unit-тесты

### `test_extractor.py` — распаковка архивов

#### `test_fallback_to_unrar_on_unar_failure`
**Что:** unar возвращает `Failed!` в stdout → вызывается unrar как fallback.  
**Баг:** BUG-005 (unar на arm64/Linux не открывает RAR5).  
**Фикстура:** мок `_try_unar` → `(False, "Failed!")`, мок `_try_unrar` → `(True, "")`.  
**Assert:** `_try_unrar` вызван; xlsx-файлы найдены.

#### `test_unar_exit0_with_failed_in_stdout`
**Что:** unar возвращает код 0 но выводит `"Failed!"` → считается ошибкой.  
**Баг:** BUG-005 — unar может выйти с кодом 0 при реальном сбое.  
**Фикстура:** мок `subprocess.run` → `returncode=0`, `stdout="Failed! Archive.rar"`.  
**Assert:** `_try_unar` возвращает `(False, ...)`.

#### `test_no_duplicate_xlsx_after_fallback`
**Что:** после fallback unar→unrar в out_dir нет дублей xlsx.  
**Баг:** BUG-006 — unar частично распаковывает в `out_dir/archive_name/`, unrar в `out_dir/` → дубли.  
**Фикстура:** создаём xlsx в `out_dir/archive_name/` (имитируем unar), вызываем `_clear_dir`.  
**Assert:** после очистки только архив, xlsx удалены.

#### `test_clear_dir_keeps_archive`
**Что:** `_clear_dir(dir, keep={archive_path})` не удаляет сам архив.  
**Баг:** BUG-006 — первая версия фикса случайно удаляла архив до вызова unrar.  
**Assert:** архив на месте, все остальные файлы удалены.

#### `test_xlsb_found_by_extractor`
**Что:** `extract()` на архиве с `.xlsb` возвращает их в списке.  
**Баг:** BUG-008 — `rglob("*.xlsx")` не захватывал `.xlsb`.  
**Фикстура:** ZIP с `export.xlsb`.  
**Assert:** `len(result) == 1`, `result[0].suffix == ".xlsb"`.

#### `test_xls_found_by_extractor`
**Что:** `extract()` находит `.xls` файлы.  
**Assert:** `result[0].suffix == ".xls"`.

#### `test_unar_error_and_unrar_also_fails_raises`
**Что:** оба инструмента падают → `RuntimeError` с выводом обоих.  
**Assert:** `raises(RuntimeError)`, в сообщении есть `unar failed` и `unrar failed`.

---

### `test_parser.py` — парсинг Excel

#### Формат и детектирование

##### `test_detect_format_a`
**Что:** файл с колонкой `T пр` → формат A.  
**Assert:** `detect_format(df) == "A"`

##### `test_detect_format_a_by_id_object`
**Что:** файл с колонкой `ID объекта` (без `T пр`) → формат A.  
**Assert:** `detect_format(df) == "A"`

##### `test_detect_format_b`
**Что:** файл с колонкой `t_forward` → формат B.  
**Assert:** `detect_format(df) == "B"`

##### `test_detect_format_unknown`
**Что:** незнакомые заголовки → `"UNKNOWN"`.  
**Assert:** `detect_format(df) == "UNKNOWN"`

#### Нормализация формата A

##### `test_normalize_format_a_columns`
**Что:** все нужные колонки в правильных типах.  
**Assert:** присутствуют `record_id`, `object_id`, `ts_measurement`, `t_supply`, `t_return`, `p_supply`, `p_return`, `ts_recorded`; `ts_measurement` и `ts_recorded` — int64.

##### `test_normalize_format_a_alt_name`
**Что:** `Наименование объекта` вместо `Наименование котельной` нормализуется корректно.  
**Assert:** колонка `facility_name` заполнена.

##### `test_object_type_column_populated`
**Что:** колонка `Тип объекта` правильно маппится в `object_type`.  
**Баг:** BUG (сравнение с OLD) — битый символ `"Тип ��бъекта"` в rename dict → все object_type были NULL.  
**Assert:** `meta['object_type'].notna().any()`.

##### `test_object_id_strip_whitespace`
**Что:** лишние пробелы в object_id убираются.  
**Баг:** сравнение парк — `' д.18"'` vs `'д.18"'` в реальных данных.  
**Фикстура:** DataFrame с `object_id = " 12345 "`.  
**Assert:** `sensors['object_id'].iloc[0] == "12345"`.

##### `test_object_id_nan_becomes_pd_na`
**Что:** пустой object_id (из итоговых строк Excel) → `pd.NA`, не строка `"nan"`.  
**Баг:** до `_clean_str` — `astype(str)` давал `"nan"`, который проходил в базу как мусорный объект; после → 422 на `/objects/bulk`.  
**Фикстура:** DataFrame с `object_id = None`.  
**Assert:** `pd.isna(sensors['object_id'].iloc[0])`.

##### `test_record_id_float_string`
**Что:** `record_id` = `1.0` (float из xlsx с dtype=object) → `"1.0"`, не `"1"`.  
**Контекст:** проблема совместимости с record_id из старых данных где ID целые числа.  
**Assert:** `sensors['record_id'].iloc[0] == "1.0"` (документируем текущее поведение).

#### Конвертация дат

##### `test_xlsx_datetime_parsed_correctly`
**Что:** `.xlsx` с Python datetime → корректный unix timestamp.  
**Assert:** `ts_recorded` ≠ 0, соответствует ожидаемой дате.

##### `test_out_of_bounds_date_becomes_nan`
**Что:** дата 1000-01-01 (out of bounds для pandas ns) → NaT → NaN, не исключение.  
**Баг:** BUG-008 — `pd.read_excel` без `dtype=object` кидал `OutOfBoundsDatetime`.  
**Фикстура:** xlsx с датой `datetime(1000, 1, 1)` в `Дата и время записи`.  
**Assert:** `sensors['ts_recorded'].isna().any()` — строка содержит NaN.

##### `test_invalid_date_string_becomes_nan`
**Что:** строка `"not a date"` → NaN, не исключение и не 0.  
**Баг:** BUG-009 — старая версия `_to_unix` делала `fillna(Timestamp(0))` → 0 в базе.  
**Assert:** `sensors['ts_recorded'].isna().any()`.

##### `test_xlsb_serial_float_dates_parsed_correctly`
**Что:** `.xlsb` с float serial dates → корректный unix timestamp.  
**Баг:** BUG-008 — `pd.to_datetime(float_series_as_object, unit="D")` кидал ошибку в pandas 2.x;  
нужен предварительный `pd.to_numeric()`.  
**Фикстура:** object-dtype Series с float значением `45000.5` (≈ 2023-03-17).  
**Assert:** `ts_recorded ≈ 1679011200` (±86400).

##### `test_xlsb_engine_selected_for_xlsb_extension`
**Что:** файл `.xlsb` читается с движком `pyxlsb`.  
**Фикстура:** мок `pd.read_excel`, проверяем переданный `engine`.  
**Assert:** `pd.read_excel` вызван с `engine="pyxlsb"`.

#### Формат B

##### `test_normalize_format_b_ts_measurement_equals_ts_recorded`
**Assert:** `sensors['ts_measurement'].equals(sensors['ts_recorded'])`.

##### `test_normalize_format_b_missing_meta_columns`
**Assert:** `meta['object_type'].isna().all()`.

---

### `test_cleaner.py` — очистка данных

#### `test_physical_bounds_out_of_range_to_nan`
**Что:** `t_supply=200.0` (> 150) → NaN, строка не удаляется если есть другие датчики.  
**Assert:** `sensors.loc[0, 't_supply'] is NaN`, строка осталась.

#### `test_drop_row_all_sensors_nan`
**Что:** строка с 4 NaN датчиками удаляется.  
**Assert:** `len(result) == len(input) - 1`.

#### `test_keep_row_partial_nan`
**Что:** строка с одним NaN датчиком остаётся.  
**Assert:** строка присутствует.

#### `test_drop_missing_required_fields`
**Что:** NaN в `record_id`, `object_id`, `ts_recorded` → удаляются.  
**Assert:** `len(result) == 0`.

#### `test_drop_row_ts_recorded_nan_from_invalid_date`
**Что:** строка с `ts_recorded=NaN` (от невалидной даты) удаляется.  
**Баг:** BUG-009 — старый `fillna(0)` давал `ts_recorded=0`, cleaner не удалял.  
**Фикстура:** sensors_df с одной строкой, `ts_recorded=NaN` (float).  
**Assert:** `len(clean_sensors(df)) == 0`.

#### `test_object_id_na_drops_row`
**Что:** строка с `object_id=pd.NA` (от пустой ячейки в Excel) удаляется.  
**Баг:** до `_clean_str` — `"nan"` как строка проходил насквозь.  
**Assert:** `len(result) == 0`.

#### `test_dedup_by_record_id`
**Что:** две строки с одинаковым `record_id` → остаётся одна.  
**Assert:** `len(result) == 1`.

---

### `test_meta_payload.py` — сериализация объектов (BUG-001)

#### `test_nan_in_object_type_serializes_as_null`
**Что:** `object_type=NaN` → `null` в JSON, не `NaN`.  
**Assert:** `json.dumps(payload)` не кидает исключение; `payload[0]['object_type'] is None`.

#### `test_null_object_id_filtered_before_bulk`
**Что:** строки с `object_id=pd.NA` не попадают в payload для `/objects/bulk`.  
**Баг:** 422 Unprocessable Entity — Pydantic требует `str`, не `None`.  
**Фикстура:** meta DataFrame с двумя строками: одна валидная, одна с `object_id=pd.NA`.  
**Assert:** payload содержит ровно 1 запись.

---

## E2E-тесты

Перед каждым тестом: `tmp_data/` с пустыми `sensors.parquet` и `objects_meta.parquet`. После теста: директория удаляется.

---

### `test_ingest_upload.py` — загрузка файлов

#### `test_upload_file_size_matches_original`
**Что:** размер сохранённого архива совпадает с оригиналом.  
**Баг:** BUG-007 — `await file.read()` обрезал файлы >400 МБ.  
**Assert:** `saved_bytes == original_bytes`.

#### `test_upload_multiple_files_queued`
**Что:** несколько файлов одним запросом → все получают `status="queued"`.  
**Assert:** ответ содержит N job_id, все `status == "queued"`, обрабатываются последовательно.

---

### `test_ingest_zip.py`

#### `test_upload_zip_returns_job_id`
**Assert:** ответ содержит `job_id: str`, `status == "queued"`.

#### `test_job_completes`
**Assert:** polling GET `/ingest/jobs/{id}` с timeout 30с → `status == "done"`.

#### `test_sensors_saved_to_data_service`
**Assert:** GET `data-service:8000/sensors?object_id=<id>` → `total > 0`.

#### `test_objects_meta_saved`
**Assert:** GET `data-service:8000/objects/<object_id>` → 200, `object_type` не `"nan"`.

#### `test_merge_deduplication`
**Что:** загрузить один архив дважды → данные не дублируются.  
**Assert:** `second_job.stats.sensors_inserted == 0`, `sensors_duplicates == N`.

#### `test_merge_new_records_added`
**Что:** архив A (объекты 1,2) + архив B (объекты 2,3) → 3 уникальных объекта.  
**Assert:** кол-во строк объекта 2 = строки из A + строки из B (без дублей).

#### `test_merge_partial_overlap`
**Что:** архив B содержит 5 строк из A и 5 новых → вставляется ровно 5.  
**Assert:** `sensors_inserted == 5`, `sensors_duplicates == 5`.

#### `test_object_type_not_null_after_ingest`
**Что:** после загрузки format-A архива `object_type` в objects_meta не NULL.  
**Баг:** битый символ `"Тип ��бъекта"` в rename dict → все object_type были NULL.  
**Assert:** GET `/objects/<id>` → `object_type` not null.

---

### `test_ingest_rar.py`

#### `test_upload_rar_completes`
**Assert:** `status == "done"`.

#### `test_upload_rar5_fallback_to_unrar`
**Что:** RAR5-архив который unar не открывает → fallback на unrar, задача done.  
**Баг:** BUG-005.  
**Assert:** `status == "done"`, `sensors_inserted > 0`.

#### `test_upload_xlsb_in_rar_correct_dates`
**Что:** RAR с `.xlsb` файлами → даты в базе корректные (не 1970-01-01).  
**Баг:** BUG-008/009 — xlsb serial dates → epoch 0.  
**Assert:** `period_from > datetime(2020, 1, 1)`.

#### `test_upload_xlsb_sensors_in_data_service`
**Assert:** `sensors_inserted > 0`, данные видны через GET `/sensors`.
