# data-service — Спецификация

**Порт:** 8000  
**Стек:** FastAPI + Uvicorn, DuckDB, Pydantic v2

## Назначение

Единственный сервис, который читает и пишет parquet-файлы. Все остальные сервисы работают с данными только через него.

---

## Хранилище

| Файл | Ключ дедупликации | Колонки |
|------|------------------|---------|
| `sensors.parquet` | `record_id` | `record_id`, `object_id`, `ts_measurement` (unix), `t_supply`, `t_return`, `p_supply`, `p_return`, `ts_recorded` |
| `objects_meta.parquet` | `object_id` | `object_id`, `object_type`, `facility_type`, `facility_name`, `municipality`, `rso` |

Путь к папке с файлами передаётся через env `DATA_DIR` (default: `/app/data`).

---

## Асинхронная запись sensors через shared volume

`POST /sensors/bulk` возвращает ответ **немедленно**. Данные передаются не через JSON body (медленно — 8+ МБ на батч), а через **shared Docker volume**:

```
ingestion-service:
  1. Все батчи → staging parquet файлы в /app/data/incoming/
     (50k строк ≈ 1-2 МБ каждый, запись за секунды)
  2. POST /sensors/bulk {"parquet_paths": ["/app/data/incoming/job_0.parquet", ...]}
     ← 56 байт JSON вместо 160 МБ
  3. Ждёт GET /sensors/pending == 0

data-service воркер:
  1. Получает список путей (один элемент очереди)
  2. pd.concat(все файлы) → единый DataFrame
  3. Один _duckdb_append — ОДИН проход по sensors.parquet
  4. Удаляет staging файлы
```

**Почему shared volume а не JSON:** JSON-сериализация 200k записей = 33 МБ. Передача через Docker overlay network на macOS (VirtioFS) ≈ 0.5 МБ/с → таймаут. Parquet файл = 1-2 МБ, передача пути = 56 байт, response мгновенный.

**Shared volume:** Docker named volume `incoming` монтируется в оба контейнера как `/app/data/incoming`. Staging файлы создаёт ingestion, читает и удаляет data-service.

**Мониторинг:** `GET /sensors/pending` → `{"pending": N}`. ingestion ждёт `pending == 0`.

**Подсчёт inserted:** `sensors_after - sensors_before` через `GET /health → sensors_total`.

## Потокобезопасность записи

Два независимых `threading.Lock` — `sensors_lock` и `meta_lock`. Воркер вызывает `bulk_insert_sensors` через `run_in_executor` — гарантирует что DuckDB COPY не запускается параллельно.

### Алгоритм `bulk_insert_sensors` (под lock)

1. Прочитать только колонку `record_id` через pyarrow (`pq.read_table(columns=["record_id"])`) — 1 колонка вместо 8, быстро
2. Отфильтровать новые строки (не дубликаты)
3. Если есть что записывать — DuckDB streaming merge:
   ```sql
   COPY (
       SELECT * FROM read_parquet('sensors.parquet')  -- стримит батчами
       UNION ALL
       SELECT * FROM new_records                       -- новые строки из памяти
   ) TO 'sensors.parquet.tmp' (FORMAT PARQUET)
   ```
4. `os.replace(tmp, target)` — атомарный rename

**Почему DuckDB а не pandas:** `pd.read_parquet` загружает весь файл (36М строк) в RAM → OOM при больших архивах. DuckDB стримит существующий файл батчами — пиковая память ~300-500 МБ независимо от размера файла.

### Алгоритм `bulk_upsert_objects` (под lock)

Аналогично, но файл объектов маленький (~4к строк) — используется pandas concat (без DuckDB).

---

## Пагинация

Все list-эндпоинты используют offset-пагинацию:

```
?offset=0&limit=1000    (default limit=1000, max=10000)
```

Ответ — конверт `Page[T]`:

```json
{
  "items": [...],
  "total": 36000000,
  "offset": 0,
  "limit": 1000
}
```

---

## Endpoints

### Sensors

```
GET /sensors
    ?object_id=<str>     обязательный
    &from_ts=<unix>
    &to_ts=<unix>
    &offset=0&limit=1000
    → Page[SensorRecord]

GET /sensors/calendar
    ?object_id=<str>     обязательный
    → {"dates": ["2025-10-01", ...]}
    Дни, в которые есть хотя бы одна запись для объекта

GET /sensors/calendar/summary
    ?from_date=<YYYY-MM-DD>
    &to_date=<YYYY-MM-DD>
    → [{"day": "2025-10-01", "objects_count": 4200}, ...]
    Для каждого дня — количество уникальных объектов с данными

GET /sensors/calendar/objects
    ?date=<YYYY-MM-DD>   обязательный
    &offset=0&limit=100
    → Page[ObjectMeta]
    Объекты у которых есть данные за указанный день (JOIN sensors + objects_meta)

POST /sensors/bulk
     body: {"parquet_paths": ["/app/data/incoming/file.parquet", ...]}
           или {"parquet_path": "..."}   ← одиночный файл (совместимость)
           или SensorRecord[]            ← fallback JSON режим
     → {}                               ← возвращает сразу, запись асинхронная

GET /sensors/pending
    → {"pending": N}       ← кол-во задач ожидающих записи в parquet

GET /health
    → {"status": "ok", "sensors_count": N, "sensors_total": N,
       "period_from": "2025-10-01", "period_to": "2026-05-27"}
```

### Objects

```
GET /objects
    ?municipality=<str>
    &facility_type=<str>
    &q=<str>             поиск по facility_name (ILIKE)
    &offset=0&limit=100
    → Page[ObjectMeta]

GET /objects/{object_id}
    → ObjectMeta

PUT /objects/{object_id}
    body: ObjectMetaUpdate
    → ObjectMeta

POST /objects/bulk
     body: ObjectMeta[]  upsert: старые записи приоритетнее
     → BulkResult
```

---

## Схемы (Pydantic)

```python
class SensorRecord(BaseModel):
    record_id: str
    object_id: str
    ts_measurement: int        # unix seconds
    t_supply: float | None
    t_return: float | None
    p_supply: float | None
    p_return: float | None
    ts_recorded: int           # unix seconds

class ObjectMeta(BaseModel):
    object_id: str
    object_type: str | None
    facility_type: str | None
    facility_name: str | None
    municipality: str | None
    rso: str | None

class ObjectMetaUpdate(BaseModel):
    object_type: str | None = None
    facility_type: str | None = None
    facility_name: str | None = None
    municipality: str | None = None
    rso: str | None = None

class BulkResult(BaseModel):
    inserted: int
    skipped_duplicates: int

class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int
```
