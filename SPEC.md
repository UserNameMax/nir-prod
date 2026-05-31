# Production — Обзорная спецификация

## Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker network                           │
│                                                                 │
│  ┌──────────────┐    REST API    ┌────────────────────────┐     │
│  │  ingestion-  │ ─────────────▶ │    data-service        │     │
│  │  service     │                │  (FastAPI + DuckDB)    │     │
│  │  :8001       │                │  :8000                 │     │
│  └──────────────┘                └──────────┬─────────────┘     │
│                                        ▲    │ читает/пишет      │
│  ┌──────────────┐    REST API          │    ▼                   │
│  │  viewer      │ ─────────────────────┘  data/                 │
│  │  (React SPA) │                         ├── sensors.parquet   │
│  │  :3000       │                         └── objects_meta...   │
│  └──────────────┘                                               │
└─────────────────────────────────────────────────────────────────┘
```

**Scope v1:** только `sensors.parquet` и `objects_meta.parquet`. Events и разметка — вне скопа.

---

## Сервисы

| Сервис | Спека | Назначение |
|--------|-------|-----------|
| data-service | [data-service/SPEC.md](data-service/SPEC.md) | CRUD API для показаний датчиков и метаданных объектов |
| ingestion-service | [ingestion-service/SPEC.md](ingestion-service/SPEC.md) | Приём RAR/ZIP архивов, парсинг Excel, сохранение через data-service |
| viewer | [viewer/SPEC.md](viewer/SPEC.md) | React SPA — поиск объектов, календарь, графики по дням |

---

## Структура директорий

```
production/
├── SPEC.md                    ← этот файл
├── TECH_DEBT.md               ← известные ограничения и будущие улучшения
├── docker-compose.yml
│
├── data-service/
│   ├── SPEC.md
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── routers/
│   │   ├── sensors.py
│   │   └── objects.py
│   ├── storage/
│   │   ├── reader.py
│   │   └── writer.py
│   └── schemas.py
│
├── ingestion-service/
│   ├── SPEC.md
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── pipeline/
│   │   ├── extractor.py
│   │   ├── parser.py
│   │   └── cleaner.py
│   └── jobs.py
│
└── viewer/
    ├── SPEC.md
    ├── Dockerfile
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── api/
        ├── pages/
        ├── components/
        └── types/
```

---

## docker-compose.yml (скелет)

```yaml
services:
  data-service:
    build: ./data-service
    ports: ["8000:8000"]
    volumes:
      - ../data:/app/data:rw

  ingestion-service:
    build: ./ingestion-service
    ports: ["8001:8001"]
    environment:
      DATA_SERVICE_URL: http://data-service:8000
    depends_on: [data-service]

  viewer:
    build: ./viewer
    ports: ["3000:3000"]
    environment:
      VITE_DATA_API_URL: http://localhost:8000
      VITE_INGEST_API_URL: http://localhost:8001
```
