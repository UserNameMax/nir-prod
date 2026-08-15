# Система мониторинга тепловых сетей — Спецификация

## Бизнес-ценность

Система предназначена для сбора, хранения и визуализации телеметрии тепловых сетей Московской области с целью выявления аномалий и предиктивной аналитики аварийных событий.

**Проблема:** данные о показаниях датчиков (температура и давление теплоносителя) поступают в виде периодических выгрузок из ERP в разрозненных Excel-файлах с несовместимыми форматами. Аналитик не может видеть целостную картину по объектам и времени без значительной ручной обработки.

**Решение:** система автоматически принимает архивы, нормализует данные из разных форматов, дедуплицирует и хранит в едином виде. Аналитик получает веб-интерфейс для навигации по объектам и временным периодам, просмотра временных рядов датчиков и управления загрузкой данных.

**Пользователь:** аналитик данных и диспетчер/инженер-эксплуатационщик тепловых сетей МО.

**Scope:** система состоит из двух контуров.
- **Data-контур** (v1) — приём данных, хранение, визуализация телеметрии.
- **Предиктивный контур** (v2, §10 NARRATIVE) — инженерия признаков, обучение моделей,
  ежедневные алерты об авариях, watch-list для планового ТО. См. раздел ниже и
  [MODEL_BUNDLE.md](MODEL_BUNDLE.md).

---

## Компоненты системы

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│  ┌──────────────┐   загрузка архивов   ┌───────────────────────┐ │
│  │              │ ───────────────────▶ │  Ingestion Service    │ │
│  │    Viewer    │                      │  ETL пайплайн         │ │
│  │   (веб-UI)   │   чтение данных      └──────────┬────────────┘ │
│  │              │ ──────────────────────────────┐ │ запись       │
│  └──────────────┘                               │ ▼             │
│                                        ┌────────▼──────────────┐ │
│                                        │    Data Service       │ │
│                                        │    хранилище + API    │ │
│                                        └───────────────────────┘ │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Viewer
Веб-интерфейс для аналитика. Обеспечивает навигацию по объектам и датам, визуализацию временных рядов, управление загрузкой архивов. Не работает с данными напрямую — только через API.

### Ingestion Service
ETL-сервис. Принимает архивы (RAR/ZIP) с Excel-выгрузками, распаковывает, парсит, нормализует форматы, очищает данные и передаёт в Data Service. Обрабатывает очередь задач последовательно, поддерживает прогресс-трекинг.

### Data Service
Единственный владелец хранилища данных. Предоставляет REST API для чтения и записи показаний датчиков и метаданных объектов. Гарантирует дедупликацию, атомарность записи, изоляцию от деталей хранения. Для предиктивного контура дополнительно отдаёт верифицированные аварии (`/incidents`, метки для обучения).

---

## Предиктивный контур (§10 NARRATIVE)

Система преждевременного предупреждения аварий на ЦТП. Реализует стек из
`model_benchmark/NARRATIVE.md` (§10): хронический watch-list + острый ежедневный алерт
с триггером устойчивости + гейтинг + объяснение. Отчётность — честная (temporal-форкаст,
lift над случайным полом), не абсолютный detection.

```
Excel тех.нарушений ─▶ labeling-service ──/incidents/bulk──┐
                        (LLM + fuzzy, метки)                ▼
open-meteo ─▶ weather-service ─┐                     data-service
              (T_out)          ▼                      ▲   │
data-service ──/sensors──▶ feature-service ──/features──┬─▶ training-service ─▶ [/models] ─┐
     ▲        /incidents     (Слой 0,          /schema  │      (обучение,      бандл        │
ingestion-service           дневные признаки)           │       публикация)                 │
     (есть)                                              └─▶ ml-service ◀────────читает──────┘
                                                              (Слои 1-4)
                                                                  ▲
                                                            viewer (REST)
```

| Сервис | Роль | Спека |
|---|---|---|
| **labeling-service** | ground-truth метки аварий: Excel тех.нарушений → LLM+fuzzy → `object_id` → `/incidents` (без трансформера) | [labeling-service/SPEC.md](labeling-service/SPEC.md) |
| **weather-service** | единственная внешняя точка: `T_out` (open-meteo), кэш | [weather-service/SPEC.md](weather-service/SPEC.md) |
| **feature-service** | Слой 0: дневные каузальные признаки (`final_h30`, 31 шт.), parity | [feature-service/SPEC.md](feature-service/SPEC.md) |
| **training-service** | обучение acute/chronic/explain, триггер, публикация бандла | [training-service/SPEC.md](training-service/SPEC.md) |
| **ml-service** | Слои 1-4: watch-list, острый алерт, гейтинг, объяснение, KPI | [ml-service/SPEC.md](ml-service/SPEC.md) |
| **viewer** (ML) | очередь нарядов, watch-list, drill-down, KPI-панель | [viewer/SPEC_ML.md](viewer/SPEC_ML.md) |
| Контракт бандла | стык training-service → ml-service | [MODEL_BUNDLE.md](MODEL_BUNDLE.md) |

**Порты:** data 8000 · ingestion 8001 · feature 8002 · weather 8003 · training 8004 ·
ml 8005 · labeling 8006 · viewer **3001** (3000 занят демо-стендом `demo/`).

**Порядок запуска с нуля:**

```bash
docker compose up -d
# метки аварий (нужны Ollama на host; загрузка Excel тех.нарушений):
curl -X POST localhost:8006/label/upload -F 'files=@svod_doc_2026.xlsx'
curl -X POST localhost:8003/weather/refresh -H 'Content-Type: application/json' \
     -d '{"date_from":"2025-10-01","date_to":"2026-05-27"}'
curl -X POST localhost:8002/features/rebuild -H 'Content-Type: application/json' \
     -d '{"date_from":"2025-10-01","date_to":"2026-05-27"}'
curl -X POST localhost:8004/train -H 'Content-Type: application/json' -d '{}'
curl -X POST localhost:8005/reload
```

Признаки считаются по ВСЕЙ истории: междневные окна и каузальный fit требуют
предыстории объекта. Метки аварий производит **labeling-service** (Excel тех.нарушений
→ `POST /incidents/bulk`) и должны быть загружены до обучения.

**Сквозные принципы контура:**
- **Самодостаточность** — никаких рантайм-зависимостей вне `production/`; логика
  research-харнесса и определение признаков перенесены копией внутрь.
- **Train/serve parity** — признаки строит единственный сервис (feature-service);
  `manifest.feature_schema.service_version` сверяется при загрузке бандла.
- **Честная отчётность** — только temporal (detection ≈0.48, lift +0.20), не
  object-split 0.70 (внутри нулевого пола); калибровка — для показа, не для порога.

---

## Взаимодействие сервисов

```
Viewer          Ingestion Service        Data Service        Хранилище
  │                    │                      │                  │
  │  POST /upload      │                      │                  │
  │──────────────────▶ │                      │                  │
  │  ← [job_id]        │                      │                  │
  │                    │  (фоновая обработка) │                  │
  │  GET /jobs (poll)  │                      │                  │
  │──────────────────▶ │                      │                  │
  │  ← {status, progress}                    │                  │
  │                    │  POST /sensors/bulk  │                  │
  │                    │────────────────────▶ │                  │
  │                    │  POST /objects/bulk  │  write + dedup   │
  │                    │────────────────────▶ │─────────────────▶│
  │                    │                      │                  │
  │  GET /sensors      │                      │                  │
  │─────────────────────────────────────────▶ │                  │
  │                    │                      │  read            │
  │  GET /objects      │                      │─────────────────▶│
  │─────────────────────────────────────────▶ │                  │
```

**Правила взаимодействия:**
- Viewer → Data Service: только чтение (GET)
- Viewer → Ingestion Service: управление задачами (загрузка + статус)
- Ingestion Service → Data Service: только запись (POST)
- Data Service — единственный writer хранилища
- Viewer никогда не обращается к Ingestion Service за данными датчиков

---

## Data Flow сценарии

### 1. Загрузка одного архива

```
Аналитик выбирает файл в Viewer
  └─▶ POST /ingest/upload
       └─▶ Ingestion: сохраняет архив на диск, создаёт задачу {status: queued}
            └─▶ Viewer: поллинг GET /ingest/jobs каждые 2 сек

Ingestion (фон, асинхронная очередь):
  ├─ extract:  распаковка RAR/ZIP → список Excel файлов
  ├─ parse:    определение формата (A/B), маппинг колонок, конвертация типов
  ├─ clean:    физические границы датчиков, удаление строк без обязательных полей
  └─ store:    передача нормализованных данных в Data Service

Data Service:
  ├─ дедупликация по record_id (новые строки vs существующие)
  └─ атомарная запись в хранилище

Viewer: задача → {status: done, stats: {inserted, duplicates, period}}
```

### 2. Параллельная загрузка нескольких архивов

```
Аналитик выбирает N файлов → один POST /upload с N файлами
  └─▶ N задач: первая {status: processing}, остальные {status: queued}
       └─▶ Ingestion: строго последовательная обработка
            (параллельная запись не допускается — гонки при обновлении хранилища)
  └─▶ Viewer: все задачи видны как карточки, активная — с прогресс-баром
```

### 3. Повторная загрузка того же архива

```
Ingestion парсит архив → N строк
  └─▶ Data Service: все record_id уже в хранилище
       └─▶ inserted=0, duplicates=N → задача {status: done}
            (данные не дублируются, операция идемпотентна)
```

### 4. Просмотр данных объекта (путь через ObjectList)

```
Аналитик открывает Viewer
  └─▶ GET /objects → список объектов (поиск, фильтры)
       └─▶ выбирает объект → GET /sensors/calendar?object_id=X
            └─▶ календарь дней с данными
                 └─▶ выбирает день → GET /sensors?object_id=X&from_ts=...&to_ts=...
                      └─▶ 4 графика: t_supply, t_return, p_supply, p_return
```

### 5. Просмотр данных через глобальный календарь

```
Аналитик открывает Календарь
  └─▶ GET /sensors/calendar/summary → все дни, кол-во объектов за каждый
       └─▶ выбирает день → GET /sensors/calendar/objects?date=X
            └─▶ список объектов с данными за этот день
                 └─▶ выбирает объект → GET /sensors?... → 4 графика
```

### 6. Навигация между соседними днями

```
Аналитик смотрит графики за день D
  └─▶ нажимает ←/→ (следующий/предыдущий день с данными)
       └─▶ список доступных дней берётся из GET /sensors/calendar (кешируется)
            └─▶ GET /sensors?object_id=X&from_ts=...&to_ts=... для нового дня
```

---

## Функциональные требования

### Загрузка данных
- Форматы архивов: RAR (включая RAR5), ZIP
- Форматы Excel: `.xlsx`, `.xls`, `.xlsb`
- Автоопределение формата данных (формат A и формат B)
- Очистка: физические границы показаний, удаление строк без обязательных полей
- Прогресс в реальном времени: фаза парсинга и фаза записи раздельно
- Одновременная постановка N архивов в очередь
- Идемпотентность: повторная загрузка архива не создаёт дублей

### Хранение данных
- Дедупликация по уникальному идентификатору записи
- 4 типа показаний: температура подачи/обратки (°C), давление подачи/обратки (МПа)
- Метаданные объекта: тип, тип котельной, название, муниципалитет, РСО
- Атомарность записи: нет частичных состояний хранилища

### Визуализация
- Поиск объектов по названию, фильтрация по муниципалитету и типу
- Глобальный календарь: дни с данными, количество объектов за день
- Объектный календарь: дни с данными для конкретного объекта
- Временные ряды по 4 датчикам за выбранный день
- Навигация между соседними днями с данными

---

## Нефункциональные требования

| Параметр | Требование |
|----------|-----------|
| Масштаб данных | 50M+ записей датчиков |
| Размер архивов | до 500 МБ |
| Время отклика (чтение) | < 2 сек для типовых запросов |
| Дедупликация | гарантируется при повторных загрузках |
| Атомарность записи | гарантируется |
| Параллельные записи | не допускаются |
| Масштабирование | горизонтальное не требуется (v1) |

---

## Текущая реализация (reference)

Развёрнута локально через Docker Compose. Каждый компонент — отдельный контейнер.

| Компонент | Технологии | Спека |
|-----------|-----------|-------|
| Data Service | FastAPI + Uvicorn, DuckDB, Parquet, Python 3.12 | [data-service/SPEC.md](data-service/SPEC.md) |
| Ingestion Service | FastAPI, pandas, unar/unrar, pyxlsb, Python 3.12 | [ingestion-service/SPEC.md](ingestion-service/SPEC.md) |
| Labeling Service | FastAPI, pandas, rapidfuzz, httpx (Ollama), openpyxl, Python 3.12 | [labeling-service/SPEC.md](labeling-service/SPEC.md), [SPEC_TESTS.md](labeling-service/SPEC_TESTS.md) |
| Weather Service | FastAPI, httpx (open-meteo), Python 3.12 | [weather-service/SPEC.md](weather-service/SPEC.md) |
| Feature Service | FastAPI, polars/pandas, Python 3.12 | [feature-service/SPEC.md](feature-service/SPEC.md) |
| Training Service | FastAPI, xgboost, scikit-survival, lifelines, Python 3.12 | [training-service/SPEC.md](training-service/SPEC.md) |
| ML Service | FastAPI, xgboost, scikit-survival, lifelines, Python 3.12 | [ml-service/SPEC.md](ml-service/SPEC.md) |
| Viewer | React 18, TypeScript, Tailwind CSS, Recharts, nginx | [viewer/SPEC.md](viewer/SPEC.md), [viewer/SPEC_ML.md](viewer/SPEC_ML.md) |
| Контракт бандла | training-service → ml-service | [MODEL_BUNDLE.md](MODEL_BUNDLE.md) |
| Инфраструктура | Docker Compose, named volumes | [docker-compose.yml](docker-compose.yml) |
| Операционная документация | Баги, тех. долг | [BUGS.md](BUGS.md), [TECH_DEBT.md](TECH_DEBT.md) |

**Известные ограничения текущей реализации** (осознанные компромиссы для ВКР):
- Хранилище — один monolithic parquet-файл без партиционирования
- Состояние задач — in-memory, теряется при рестарте сервиса
- Горизонтальное масштабирование не поддерживается
- Запись через файловую систему (shared volume) — не подходит для облачного деплоя без адаптации

```
production/
├── SPEC.md                    ← этот файл (оба контура)
├── MODEL_BUNDLE.md            ← контракт бандла (training-service → ml-service)
├── BUGS.md                    ← история багов
├── TECH_DEBT.md               ← известные ограничения
├── docker-compose.yml
│
│   # --- Data-контур ---
├── data-service/              (+ /incidents для меток обучения)
│   ├── SPEC.md, Dockerfile, requirements.txt
│   ├── main.py, schemas.py
│   ├── routers/  (sensors.py, objects.py)
│   └── storage/  (reader.py, writer.py)
├── ingestion-service/
│   ├── SPEC.md, SPEC_TESTS.md, Dockerfile, requirements.txt
│   ├── main.py, jobs.py
│   └── pipeline/  (extractor.py, parser.py, cleaner.py)
│
│   # --- Предиктивный контур (§10) ---
├── labeling-service/          ← метки аварий: Excel тех.нарушений → LLM+fuzzy → /incidents
│   ├── SPEC.md, SPEC_TESTS.md, Dockerfile, requirements.txt, pytest.ini
│   ├── main.py, jobs.py, schemas.py, config.py
│   ├── ingest.py, fuzzy.py, resolve.py, clients.py, publish.py
│   ├── compare_draft.py       ← паритет с черновым labler/
│   └── tests/ (unit/, e2e/, fixtures/)
├── weather-service/           ← T_out (open-meteo), кэш
│   ├── SPEC.md, main.py, source.py, store.py
├── feature-service/           ← Слой 0: дневные признаки final_h30
│   ├── SPEC.md, main.py
│   ├── schema.py (const final_h30), cache.py, client.py
│   └── intraday.py, interday.py
├── training-service/          ← обучение + публикация бандла
│   ├── SPEC.md, main.py, jobs.py, clients.py
│   ├── dataset.py, triggers.py, metrics.py, publish.py
│   └── trainers/ (acute.py, chronic.py, explain.py)
├── ml-service/                ← Слои 1-4: инференс
│   ├── SPEC.md, main.py
│   ├── loader.py, scoring.py, decision.py, explain.py, reporting.py
│   └── models/                ← бандл (shared volume): manifest.json, acute/, chronic/, explain/, trigger_config.json
│
└── viewer/
    ├── SPEC.md, SPEC_ML.md, Dockerfile, package.json
    └── src/
        ├── api/       (dataService.ts, ingestService.ts, mlService.ts)
        ├── pages/     (data: ObjectList, GlobalCalendar, DayObjects, ObjectCalendar, DayView, IngestPage)
        │              (ML:   AlertQueue, WatchList, ObjectDrilldown, KpiPanel)
        └── components/ (Calendar, SensorChart, RiskChart, ObjectHeader, ProfilePanel)
```
