# ingestion-service — Спецификация

**Порт:** 8001  
**Стек:** FastAPI + Uvicorn, pandas + openpyxl + xlrd + pyxlsb, httpx, unar + unrar (системные утилиты)

## Назначение

Принять один или несколько архивов с выгрузкой датчиков (RAR или ZIP), распарсить Excel-файлы, сохранить данные через data-service. Архивы обрабатываются последовательно через внутреннюю asyncio-очередь. Разметка событий — вне скопа.

---

## Endpoints

```
POST /ingest/upload
     Content-Type: multipart/form-data
     files: <.rar | .zip>[]    один или несколько архивов
     → [{"job_id": "uuid", "status": "queued"}, ...]

GET  /ingest/jobs/{job_id}
     → IngestJob

GET  /ingest/jobs
     → IngestJob[]    последние 50, сортировка по created_at desc
```

---

## Очередь обработки

Каждый загруженный архив создаёт задачу со статусом `queued`. Воркер (asyncio task, запускается при старте сервиса) берёт задачи по одной и обрабатывает последовательно. Параллельная обработка не поддерживается — предотвращает гонки при записи parquet.

Загрузка файла: чанками по 1 МБ (`while chunk := await file.read(1MB)`) — предотвращает обрезание при файлах >400 МБ (BUG-007).

---

## Схемы (Pydantic)

```python
class IngestJob(BaseModel):
    job_id: str
    filename: str
    status: Literal["queued", "processing", "done", "error"]
    created_at: datetime
    finished_at: datetime | None
    stats: IngestStats | None
    error: str | None
    # прогресс парсинга (фаза 1)
    files_total: int | None
    files_processed: int | None
    current_file: str | None      # имя текущего обрабатываемого файла
    rows_processed: int | None
    # прогресс мерджа (фаза 2 — сохранение в data-service)
    merge_total: int | None       # общее кол-во строк для вставки
    merge_processed: int | None   # вставлено строк на данный момент

class IngestStats(BaseModel):
    xlsx_files_found: int         # кол-во найденных Excel-файлов (.xlsx/.xls/.xlsb)
    sensors_inserted: int
    sensors_duplicates: int       # строки пропущенные при дедупликации по record_id
    objects_upserted: int
    period_from: datetime | None  # min(ts_recorded) среди вставленных строк
    period_to: datetime | None    # max(ts_recorded) среди вставленных строк
    objects_count: int
```

---

## Хранилище статусов задач

`dict[job_id, IngestJob]` в памяти процесса. При рестарте контейнера история пропадает. Хранятся последние 50 задач (при превышении — удаляется самая старая).

---

## Пайплайн обработки (фоновая задача)

Запускается через внутреннюю `asyncio.Queue` — воркер запускается при старте сервиса и обрабатывает задачи последовательно.

### Шаг 1 — Распаковка

```bash
unar -o <tmpdir> <archive>          # попытка 1
unrar x -y <archive> <tmpdir>/      # попытка 2 (fallback)
```

Сначала пробуется `unar` (умеет ZIP и RAR). Если unar вернул ненулевой код или вывел `Failed!` в stdout — частично распакованные файлы очищаются (`_clear_dir`, keep={archive}) и запускается `unrar` как fallback. Такое поведение необходимо из-за бага unar 1.10.x на arm64/Linux (BUG-005, BUG-006).

После распаковки — рекурсивный поиск всех Excel-файлов (`.xlsx`, `.xls`, `.xlsb`).

### Шаг 2 — Парсинг Excel

Все файлы читаются с `dtype=object` — предотвращает `OutOfBoundsDatetime` при `pd.read_excel` на строках с очень старыми/некорректными датами (BUG-008).

Движок по расширению:
| Расширение | Движок |
|-----------|--------|
| `.xlsx` | openpyxl (default) |
| `.xls` | xlrd |
| `.xlsb` | pyxlsb |

Определение формата по заголовкам:

| Формат | Признак | Колонка объекта |
|--------|---------|----------------|
| **A** | `T пр` или `ID объекта` | `Наименование котельной` или `Наименование объекта` |
| **B** | `t_forward` | `name_koteln` |

Маппинг колонок в единую схему:

**Формат A:**
```python
{
    'ID':                       'record_id',
    'Дата и время показателей': 'ts_measurement_dt',
    'T пр':                     't_supply',
    'T обр':                    't_return',
    'P пр':                     'p_supply',
    'P обр':                    'p_return',
    'Дата и время записи':      'ts_recorded_dt',
    'ID объекта':               'object_id',
    'Тип объекта':              'object_type',
    'Котельная/ЦТП':            'facility_type',
    'Наименование котельной':   'facility_name',
    'Муниципалитет':            'municipality',
    'РСО':                      'rso',
}
```

**Формат B:**
```python
{
    'id':          'record_id',
    'data':        'ts_recorded_dt',   # ts_measurement = ts_recorded (одна колонка)
    't_forward':   't_supply',
    't_revers':    't_return',
    'p_forward':   'p_supply',
    'p_revers':    'p_return',
    'name_koteln': 'facility_name',
    'name_mr':     'municipality',
}
# object_type и facility_type отсутствуют → NaN
```

**Конвертация дат — `_to_datetime(series)`:**

С `dtype=object` даты приходят как Python datetime-объекты (xlsx/xls) или float (xlsb).
- Если первый непустой элемент — `float`: xlsb serial date → `pd.to_numeric(series)` → `pd.to_datetime(unit="D", origin="1899-12-30")`
  - Предварительный `pd.to_numeric` обязателен: pandas 2.x требует numeric dtype, а не object с float-значениями (BUG-008)
- Иначе: `pd.to_datetime(series, errors="coerce")`

**`_to_unix(series) → float64`:**
- Вызывает `_to_datetime`, затем `.astype("int64") // 10**9`
- NaT → `NaN` через `.where(dt.notna())` — не 0! (BUG-009)
- Строки с NaN в `ts_recorded` удаляются cleaner-ом

**`_clean_str(series) → StringDtype`:**
- `astype(str).str.strip()` — убирает пробелы
- `"nan"`, `"None"`, `""` → `pd.NA` — не попадают в базу как мусорные строки

После cleaner явный каст: `ts_recorded/ts_measurement → int64`, `t_supply/... → float64`.

**Числовые колонки** (`t_supply`, `t_return`, `p_supply`, `p_return`) — `pd.to_numeric(errors="coerce")` т.к. при `dtype=object` приходят как строки/объекты.

### Шаг 3 — Очистка

Физические границы (значения вне границ → `NaN`):
```python
BOUNDS = {
    't_supply': (0.0, 150.0),
    't_return': (0.0, 150.0),
    'p_supply': (0.0, 25.0),
    'p_return': (0.0, 25.0),
}
```

Удаление строк:
- `NaN` в `record_id`, `object_id`, `ts_recorded` (включая строки с пустым `object_id` из итоговых строк Excel)
- Все 4 датчика одновременно NaN

Дедупликация по `record_id` внутри текущей выгрузки.

### Шаг 4 — Сохранение через data-service (shared volume)

Данные передаются через shared Docker volume `/app/data/incoming`, не через HTTP body.

```
1. Все батчи по 50 000 строк → staging parquet файлы:
   /app/data/incoming/{job_id}_0.parquet
   /app/data/incoming/{job_id}_50000.parquet
   ...

2. Один POST /sensors/bulk с {"parquet_paths": [...все пути...]}
   ← 56 байт JSON, возвращает {} мгновенно

3. Polling GET /sensors/pending каждые 5 сек → ждём pending == 0 (max 10 мин)

4. inserted = GET /health sensors_total after - before
```

**Почему не JSON:** 50k строк = 8 МБ JSON. Через Docker overlay на macOS (VirtioFS) ≈ 12+ сек на запрос → таймауты. Parquet файл 1-2 МБ на диске, в HTTP только путь (56 байт).

**Retry:** 3 попытки при сбое POST с паузой 2 сек между попытками.

Objects отправляются синхронно (маленький файл, быстро):
```
POST data-service:8000/objects/bulk  → BulkResult
```

Перед отправкой objects: `meta.dropna(subset=["object_id"])` — строки с пустым object_id не отправляются (Pydantic требует `str`, не `None` — BUG-011).

`period_from/to` вычисляется как `min/max(ts_recorded)` среди строк с `ts_recorded > 0`.

URL data-service берётся из env `DATA_SERVICE_URL` (default: `http://data-service:8000`).

### Шаг 5 — Очистка

Удалить tmp-директорию с распакованными файлами и загруженным архивом (`shutil.rmtree`).
