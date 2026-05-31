# ingestion-service — Спецификация

**Порт:** 8001  
**Стек:** FastAPI + Uvicorn, pandas + openpyxl, httpx, unar (системная утилита)

## Назначение

Принять архив с выгрузкой датчиков (RAR или ZIP), распарсить Excel-файлы, сохранить данные через data-service. Разметка событий — вне скопа.

---

## Endpoints

```
POST /ingest/upload
     Content-Type: multipart/form-data
     file: <.rar | .zip>
     → {"job_id": "uuid", "status": "processing"}

GET  /ingest/jobs/{job_id}
     → IngestJob

GET  /ingest/jobs
     → IngestJob[]    последние 50, сортировка по created_at desc
```

---

## Схемы (Pydantic)

```python
class IngestJob(BaseModel):
    job_id: str
    filename: str
    status: Literal["processing", "done", "error"]
    created_at: datetime
    finished_at: datetime | None
    stats: IngestStats | None
    error: str | None
    # прогресс (заполняется во время processing)
    files_total: int | None
    files_processed: int | None
    current_file: str | None      # имя текущего обрабатываемого файла
    rows_processed: int | None

class IngestStats(BaseModel):
    xlsx_files_found: int
    sensors_inserted: int
    sensors_duplicates: int
    objects_upserted: int
    period_from: datetime
    period_to: datetime
    objects_count: int
```

---

## Хранилище статусов задач

`dict[job_id, IngestJob]` в памяти процесса. При рестарте контейнера история пропадает. Хранятся последние 50 задач (при превышении — удаляется самая старая).

---

## Пайплайн обработки (фоновая задача)

Запускается через `BackgroundTasks` FastAPI после успешного upload.

### Шаг 1 — Распаковка

```bash
unar -o <tmpdir> <archive>
```

`unar` умеет оба формата (RAR и ZIP) без дополнительных флагов. После распаковки — рекурсивный поиск всех `.xlsx` файлов.

### Шаг 2 — Парсинг Excel

Определение формата по заголовкам первой строки:

| Формат | Признак | Колонка объекта |
|--------|---------|----------------|
| **A** | `T пр` или `ID объекта` | `Наименование котельной` или `Наименование объекта` (оба варианта) |
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

Временны́е колонки (`*_dt`) конвертируются в unix seconds (`int64`). В формате B `ts_measurement = ts_recorded`.

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
- NaN в `record_id`, `object_id`, `ts_recorded`
- Все 4 датчика одновременно NaN

Дедупликация по `record_id` внутри текущей выгрузки (один архив мог содержать перекрывающиеся файлы).

### Шаг 4 — Сохранение через data-service

Батчами по **50 000 строк**:
```
POST http://data-service:8000/sensors/bulk  → body: SensorRecord[50000]
POST http://data-service:8000/objects/bulk  → body: ObjectMeta[]
```

URL data-service берётся из env `DATA_SERVICE_URL` (default: `http://data-service:8000`).

### Шаг 5 — Очистка

Удалить tmp-директорию с распакованными файлами и загруженным архивом.
