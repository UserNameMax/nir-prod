# Ingestion Service — Спецификация

## Бизнес-ценность

ETL-сервис для приёма исходных данных тепловых сетей. Источник данных — периодические архивные выгрузки из ERP в виде Excel-файлов (RAR/ZIP). Сервис автоматизирует преобразование разрозненных файлов разных форматов в единую нормализованную схему и передаёт данные в хранилище.

**Ключевые задачи:**
- Принять архив любого поддерживаемого формата
- Надёжно извлечь Excel-файлы (включая RAR5 на arm64, xlsb)
- Нормализовать данные разных форматов в единую схему
- Отфильтровать физически невозможные значения
- Гарантировать идемпотентность (повторная загрузка = 0 дублей)
- Дать аналитику видимость прогресса в реальном времени

---

## Роль в системе

```
Аналитик ──POST /upload──▶ Ingestion Service ──POST /bulk──▶ Data Service
Viewer   ──GET  /jobs ──▶ Ingestion Service
```

Ingestion — единственный producer данных. Viewer управляет задачами (upload, статус), но не читает данные через Ingestion.

---

## Функциональные требования

### Приём архивов
- Форматы: RAR (включая RAR5), ZIP
- Загрузка нескольких архивов одним запросом
- Последовательная обработка очереди (параллельная запись не допускается)
- Персистентность очереди: статус задач видны после перезагрузки страницы

### Парсинг Excel
- Форматы файлов: `.xlsx`, `.xls`, `.xlsb`
- Автоопределение формата данных (А или B) по заголовкам
- Корректная обработка edge cases (xlsb serial dates, out-of-bounds даты, МКД-паттерн)

### Очистка данных
- Физические границы показаний (t: 0–150°C, p: 0–25 МПа)
- Удаление строк с пустыми обязательными полями (record_id, object_id, ts_recorded)
- Дедупликация внутри одной выгрузки по record_id

### Прогресс и статус
- Два этапа прогресса: парсинг (файлы) и запись (строки)
- Статусы задачи: queued → processing → done / error
- История последних 50 задач

---

## API-контракт

```
POST /ingest/upload
     Content-Type: multipart/form-data
     files: <.rar | .zip>[]   один или несколько архивов
     → [{"job_id": "uuid", "status": "queued"}, ...]

GET /ingest/jobs
     → IngestJob[]   последние 50, сортировка по created_at desc

GET /ingest/jobs/{job_id}
     → IngestJob
```

### Схема задачи

```python
class IngestJob:
    job_id: str
    filename: str
    status: "queued" | "processing" | "done" | "error"
    created_at: datetime
    finished_at: datetime | None
    error: str | None
    # прогресс фазы 1 — парсинг
    files_total: int | None
    files_processed: int | None
    current_file: str | None
    rows_processed: int | None
    # прогресс фазы 2 — запись
    merge_total: int | None
    merge_processed: int | None
    # итог
    stats: IngestStats | None

class IngestStats:
    xlsx_files_found: int
    sensors_inserted: int
    sensors_duplicates: int
    objects_upserted: int
    period_from: datetime | None
    period_to: datetime | None
    objects_count: int
```

---

## Пайплайн обработки

```
Архив (RAR/ZIP)
    │
    ▼ extract
Excel файлы (.xlsx / .xls / .xlsb)
    │
    ▼ parse
DataFrame: record_id, object_id, ts_measurement, ts_recorded,
           t_supply, t_return, p_supply, p_return
    │
    ▼ clean
Отфильтрованный DataFrame (физические границы, обязательные поля)
    │
    ▼ store
Data Service API
```

---

## Особенности данных (edge cases)

### Формат A vs Формат B

Два варианта выгрузки с разными заголовками:

| | Формат A | Формат B |
|---|---|---|
| Детектор | `T пр` или `ID объекта` | `t_forward` |
| `ts_measurement` | отдельная колонка | = `ts_recorded` |
| `object_type` | заполнен | отсутствует (NaN) |

### МКД-паттерн

В источнике для МКД-объектов колонки сдвинуты: `Тип объекта` содержит муниципалитет, `Котельная/ЦТП` содержит `"МКД"`. Корректируется при парсинге.

### xlsb serial dates

`.xlsb` хранит даты как float (Excel serial: дней с 30.12.1899). Требует `pd.to_numeric()` → `pd.to_datetime(unit="D", origin="1899-12-30")`.

### Out-of-bounds даты

Некоторые ячейки содержат даты до 1677 года — за пределами pandas Timestamp. Чтение с `dtype=object` предотвращает падение `read_excel`.

### Невалидные даты → NaN, не 0

`_to_unix()` возвращает `NaN` для невалидных дат (не 0). Строки с `NaN` в `ts_recorded` удаляются cleaner-ом.

---

## Нефункциональные требования

| Параметр | Требование |
|----------|-----------|
| Размер архива | до 500 МБ |
| Идемпотентность | повторная загрузка = inserted=0, duplicates=N |
| Параллельность записи | не допускается (очередь последовательная) |
| Видимость прогресса | обновление каждые ~2 сек через polling |

---

## Текущая реализация (reference)

**Стек:** FastAPI + Uvicorn, Python 3.12, pandas, openpyxl, xlrd, pyxlsb, httpx, unar, unrar

### Очередь

`asyncio.Queue` + один воркер (asyncio task, стартует при запуске сервиса). Обрабатывает задачи строго последовательно. Статусы хранятся в памяти (теряются при рестарте).

### Загрузка файла

Чанковое чтение: `while chunk := await file.read(1 MB)` — предотвращает обрезание при файлах >400 МБ.

### Извлечение архива

```
1. unar -o <tmpdir> <archive>       ← попытка 1
2. Если unar вернул "Failed!" →
   _clear_dir(tmpdir, keep={archive}) ← удаляем частичный результат
   unrar x -y <archive> <tmpdir>/   ← попытка 2
3. rglob("*.xlsx") + rglob("*.xls") + rglob("*.xlsb")
```

unar падает на RAR5 с arm64/Linux (BUG-005). unrar из non-free Debian — fallback.

### Парсинг и очистка

```python
# Все форматы читаются с dtype=object (нет OutOfBoundsDatetime при read_excel)
raw = pd.read_excel(path, engine=engine, dtype=object)

# Конвертация дат
def _to_unix(series) -> float64:  # NaT → NaN, не 0
    ...

# После cleaner — явный каст
sensors["ts_recorded"] = sensors["ts_recorded"].astype("int64")
```

Физические границы:
```python
BOUNDS = {"t_supply": (0, 150), "t_return": (0, 150),
          "p_supply": (0, 25),  "p_return": (0, 25)}
```

### Передача данных в Data Service

```
Ingestion (в executor thread):
  1. Все батчи 50k строк → staging parquet в /app/data/incoming/
     (общий Docker named volume с data-service)
  2. POST /sensors/bulk {"parquet_paths": [...]}  ← 56 байт
  3. Polling GET /sensors/pending → ждём 0 (max 10 мин)
  4. inserted = GET /health sensors_total_after - sensors_total_before
```

### Окружение

| Переменная | Описание | Default |
|-----------|---------|---------|
| `DATA_SERVICE_URL` | URL data-service | `http://data-service:8000` |
| `DATA_DIR` | Путь к директории с данными | `/app/data` |

### Ограничения текущей реализации

- Статусы задач теряются при рестарте контейнера
- Shared volume не подходит для деплоя без shared filesystem
- Нет retry при сбое записи в data-service (повторная загрузка архива решает)
- Нет проверки целостности по Content-Length

Подробнее: [TECH_DEBT.md](../TECH_DEBT.md), [BUGS.md](../BUGS.md)
