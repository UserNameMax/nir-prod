# Data Service — Спецификация

## Бизнес-ценность

Единственный владелец хранилища данных в системе. Изолирует детали хранения от остальных компонентов — ни Viewer, ни Ingestion Service не знают как и где хранятся данные. Гарантирует дедупликацию, атомарность и целостность данных при любых операциях записи.

---

## Роль в системе

```
Ingestion Service ──POST /bulk──▶ Data Service ──read/write──▶ Хранилище
Viewer            ──GET  /...──▶ Data Service
```

Data Service — единственный writer хранилища. Это предотвращает гонки при параллельных запросах на запись.

---

## Функциональные требования

### Показания датчиков (sensors)
- Хранение временных рядов по объектам: 4 датчика (t_supply, t_return, p_supply, p_return)
- Дедупликация по уникальному идентификатору записи (`record_id`)
- Запрос показаний по объекту с фильтрацией по временному диапазону, пагинация
- Калькуляция дней с данными для объекта (для отображения в календаре)
- Калькуляция глобального покрытия: сколько объектов имеют данные за каждый день
- Запрос объектов имеющих данные за конкретный день

### Метаданные объектов
- Хранение справочника объектов: тип, тип котельной, название, муниципалитет, РСО
- Поиск и фильтрация объектов
- Upsert: при повторной загрузке старые записи имеют приоритет

### Верифицированные аварии (incidents)
- Хранение подтверждённых аварийных событий — **метки для обучения предиктивных
  моделей** (потребитель: training-service)
- Дедупликация по `incident_id` (идемпотентность повторной загрузки)
- Запрос с фильтрацией по объекту и окну времени открытия инцидента
- Незакрытая авария допустима: `close_ts` может отсутствовать
- Список объектов, у которых есть хотя бы одна авария

### Общие требования
- Атомарная запись (без частичных состояний)
- Запись строго последовательная (один активный writer)
- Мониторинг состояния хранилища (количество записей, период данных)

---

## API-контракт

### Sensors

```
GET /sensors
    ?object_id=<str>     обязательный
    &from_ts=<unix>
    &to_ts=<unix>
    &offset=0&limit=1000  (max 10000)
    → Page[SensorRecord]

GET /sensors/calendar
    ?object_id=<str>
    → {"dates": ["2025-10-01", ...]}
    Дни с хотя бы одной записью для объекта

GET /sensors/calendar/summary
    ?from_date=<YYYY-MM-DD>
    &to_date=<YYYY-MM-DD>
    → [{"day": "2025-10-01", "objects_count": 4200}, ...]

GET /sensors/calendar/objects
    ?date=<YYYY-MM-DD>
    &offset=0&limit=100
    → Page[ObjectMeta]
    Объекты с данными за указанный день

GET /sensors/pending
    → {"pending": N}
    Количество задач записи в очереди (0 = запись завершена)

POST /sensors/bulk
    body: {"parquet_paths": ["...", ...]}  ← основной режим
          или SensorRecord[]               ← fallback
    → {}   (возвращает немедленно, запись асинхронная)

GET /health
    → {"status": "ok", "sensors_total": N,
       "period_from": "YYYY-MM-DD", "period_to": "YYYY-MM-DD"}
```

### Objects

```
GET /objects
    ?municipality=<str>
    &facility_type=<str>
    &q=<str>              поиск по facility_name (ILIKE)
    &offset=0&limit=100
    → Page[ObjectMeta]

GET /objects/{object_id}
    → ObjectMeta

PUT /objects/{object_id}
    body: ObjectMetaUpdate
    → ObjectMeta

POST /objects/bulk
    body: ObjectMeta[]    upsert: старые записи приоритетнее
    → BulkResult
```

### Incidents

```
GET /incidents
    ?object_id=<str>
    &from_ts=<unix>       фильтр по времени ОТКРЫТИЯ инцидента
    &to_ts=<unix>
    &offset=0&limit=1000
    → Page[Incident]      сортировка по incident_ts

GET /incidents/objects
    → list[str]           object_id, у которых есть аварии

POST /incidents/bulk
    body: Incident[]      дедупликация по incident_id
    → BulkResult
```

### Схемы

```python
class Incident:
    incident_id: str        # уникальный идентификатор аварии
    object_id: str
    incident_ts: int        # unix seconds — открытие аварии
    close_ts: int | None    # закрытие; None — авария не закрыта
    source: str | None      # источник метки (заявки, тех. нарушения)

class SensorRecord:
    record_id: str          # уникальный идентификатор измерения
    object_id: str          # идентификатор объекта
    ts_measurement: int     # unix seconds — время снятия показания
    t_supply: float | None  # температура подачи, °C
    t_return: float | None  # температура обратки, °C
    p_supply: float | None  # давление подачи, МПа
    p_return: float | None  # давление обратки, МПа
    ts_recorded: int        # unix seconds — время записи в систему

class ObjectMeta:
    object_id: str
    object_type: str | None    # тип объекта (ТИ, МКД, ...)
    facility_type: str | None  # тип котельной (Котельная, ЦТП, ...)
    facility_name: str | None
    municipality: str | None
    rso: str | None            # ресурсоснабжающая организация

class BulkResult:
    inserted: int
    skipped_duplicates: int

class Page[T]:
    items: list[T]
    total: int
    offset: int
    limit: int
```

---

## Нефункциональные требования

| Параметр | Требование |
|----------|-----------|
| Дедупликация | гарантируется по record_id |
| Атомарность | запись либо полная, либо не происходит |
| Изоляция writer | только один активный writer в любой момент |
| Время отклика (чтение) | < 2 сек для типовых запросов |
| Масштаб | 50M+ записей |

---

## Текущая реализация (reference)

**Стек:** FastAPI + Uvicorn, DuckDB, Apache Parquet, Python 3.12

### Хранилище

Два parquet-файла на локальной файловой системе:

| Файл | Ключ дедупликации | Описание |
|------|------------------|---------|
| `sensors.parquet` | `record_id` (string) | Временные ряды датчиков, 55M+ строк, ~1 ГБ |
| `objects_meta.parquet` | `object_id` (string) | Справочник объектов, ~4.5k строк |
| `incidents.parquet` | `incident_id` (string) | Верифицированные аварии (метки обучения), сотни строк |

`incident_ts` / `close_ts` пишутся как nullable `Int64`: партия, где все аварии не
закрыты, иначе сделала бы колонку `float64` и схема parquet «плыла» бы между загрузками.

Путь задаётся через env `DATA_DIR` (default: `/app/data`).

### Запись: асинхронная очередь + shared volume

`POST /sensors/bulk` возвращает `{}` мгновенно. Данные передаются через shared Docker volume:

```
Ingestion пишет batches → staging parquet в /app/data/incoming/
POST /sensors/bulk {"parquet_paths": [...]}   ← 56 байт

Data Service воркер:
  pd.concat(все файлы) → дедупликация → один DuckDB COPY → удаление staging
```

**Почему не JSON:** 50k строк = 8 МБ JSON. Через Docker overlay на macOS (VirtioFS) — 12+ сек/батч → таймаут. Parquet файл = 1-2 МБ, HTTP = 56 байт.

### Алгоритм bulk_insert_sensors

```
1. pd.concat(staging files) → единый DataFrame, drop_duplicates(record_id)
2. pq.read_table(sensors.parquet, columns=["record_id"]) → existing_ids
   (читаем только 1 колонку из 8 — быстро)
3. filter: to_insert = new_df[~new_df.record_id.isin(existing_ids)]
4. DuckDB COPY:
   COPY (SELECT * FROM read_parquet('sensors.parquet')
         UNION ALL SELECT * FROM new_records)
   TO 'sensors.parquet.tmp' (FORMAT PARQUET)
5. os.replace(tmp, sensors.parquet)  ← атомарный rename
```

### Потокобезопасность

`threading.Lock` (`_sensors_lock`, `_meta_lock`) защищают от конкурентных записей внутри процесса. Uvicorn запускается с `--workers 1`.

### Docker volume

```yaml
volumes:
  - ../data:/app/data:rw        # основное хранилище (bind mount)
  - incoming:/app/data/incoming  # staging для передачи батчей (named volume)
```

### Ограничения текущей реализации

- Monolithic parquet: DuckDB COPY читает весь файл (~1 ГБ) при каждой записи. На macOS Docker (VirtioFS) — несколько минут на операцию
- Lock не работает при `--workers > 1`
- Состояние очереди теряется при рестарте контейнера
- Shared volume — не подходит для деплоя на несколько машин без сетевой ФС

Подробнее: [TECH_DEBT.md](../TECH_DEBT.md)
