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

## Потокобезопасность записи

Два независимых `threading.Lock` — `sensors_lock` и `meta_lock`.

Алгоритм записи под lock:
1. Загрузить текущий parquet в DuckDB
2. Вставить новые строки (upsert по ключу)
3. Сохранить в `<name>.tmp.parquet`
4. `os.replace(tmp, target)` — атомарный rename
5. Освободить lock

Два отдельных lock-а позволяют параллельно писать sensors и meta.

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
    → [{"date": "2025-10-01", "objects_count": 4200}, ...]
    Для каждого дня — количество уникальных объектов с данными

POST /sensors/bulk
     body: SensorRecord[]
     → BulkResult

GET /health
    → {"status": "ok", "sensors_count": 36000000,
       "period_from": "2025-10-01", "period_to": "2026-03-25"}
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
