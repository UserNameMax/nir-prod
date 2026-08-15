# labeling-service — Спецификация

## Бизнес-ценность

Производит **ground-truth метки аварий** для предиктивного контура: превращает журналы
технических нарушений (Excel) в верифицированные аварии `(object_id, время)` и публикует
их в data-service (`POST /incidents/bulk`). Без этих меток training-service не на чем
обучать.

**Проблема:** аварии зафиксированы свободным текстом в Excel-сводках тех.нарушений; прямой
связи «событие → `object_id` объекта с телеметрией» нет.

**Решение — детерминированный разметчик:** LLM извлекает номер ЦТП из текста, fuzzy-матч
сопоставляет его со справочником объектов, время открытия аварии (`d_create`) становится
якорем метки. Прозрачно, воспроизводимо, проверяется на голден-сете.

> **Отказ от трансформера (решение по итогам аудита).** Черновой `labler/` содержал
> трансформер-классификатор + soft-метки; он показал val AUC 0.529 (уровень монеты),
> а тест локализации (`labler/08_localization_test.ipynb`) подтвердил, что метить объект
> по ошибке реконструкции нельзя (top-1 не бьёт случайный пол). В продакшен переносится
> **только детерминированная ветка** (ingest + resolve + publish). Трансформер, оконный
> билдер, инференс и soft-метки исключены.

**Пользователь:** аналитик/исследователь, загружающий сводки тех.нарушений.

---

## Место в системе

```
Excel тех.нарушений
      │  POST /label/upload
      ▼
┌──────────────────────┐   GET /objects (справочник ЦТП)   ┌──────────────┐
│  labeling-service    │ ◀──────────────────────────────── │ data-service │
│  ingest→resolve→pub  │   POST /incidents/bulk (метки)     │              │
└──────────┬───────────┘ ─────────────────────────────────▶└──────┬───────┘
           │ Ollama (LLM, единственная внешняя точка)              │ /incidents
           ▼                                                       ▼
       извлечение № ЦТП                                    training-service
```

data-service — единственный источник справочника объектов и единственный владелец
хранилища меток. labeling-service ничего не пишет в общий том напрямую (кроме своего
resolver-кэша).

---

## Пайплайн (фоновая задача)

```
1. ingest   — Excel(header=8) → нормализация → дедуп по id_cds_claim →
              split: obj_ctp=True (кандидаты) / GO (котельные, сети — не размечаются)
2. resolve  — для каждого инцидента:
                LLM(текст, район) → номер ЦТП   (Ollama, /no_think)
                fuzzy_match(номер, район, справочник) → object_id | None
              checkpoint-кэш по id_cds_claim (resume, идемпотентность)
3. publish  — resolved → Incident{incident_id, object_id, incident_ts, close_ts, source}
              → POST /incidents/bulk (дедуп по incident_id на стороне data-service)
```

**Воронка (на текущих данных, 2024–2026):** 2371 инцидент ЦТП → LLM извлёк номер 91.7%
→ **1265 resolved (53.4%)** → data-service. Потеря 38% — номера объектов **без телеметрии**
(их нет в справочнике; аварии на них вне скоупа). Это осознанная граница полноты.

---

## Контракт метки (data-service `Incident`)

| Поле | Тип | Источник |
|---|---|---|
| `incident_id` | str | `id_cds_claim` |
| `object_id` | str | результат fuzzy-матча |
| `incident_ts` | int (unix s) | `d_create` — **якорь = время регистрации** нарушения |
| `close_ts` | int \| None | `d_close` (None если не закрыта) |
| `source` | str | `тех.нарушения` |

Дедупликация по `incident_id` — повторная загрузка тех же сводок идемпотентна.

---

## API

```
POST /label/upload            multipart: files[] (.xlsx/.xls/.xlsb)
    → { job_id, status }

GET  /label/jobs              → LabelJob[]         (новые сверху)
GET  /label/jobs/{job_id}     → LabelJob           (прогресс: stage, incidents_processed)
GET  /health                  → { status }
```

`LabelJob.stats` (`LabelStats`): `incidents_ctp, go_events, llm_extracted, resolved,
unresolved, published, duplicates, period_from/to`.

---

## Конфигурация (env)

| Переменная | Дефолт | Смысл |
|---|---|---|
| `DATA_SERVICE_URL` | `http://data-service:8000` | справочник + публикация |
| `OLLAMA_URL` | `http://host.docker.internal:11434/api/chat` | LLM |
| `LLM_MODEL` | `qwen3.5` | модель извлечения |
| `LLM_TIMEOUT` | `60` | сек на запрос |
| `FUZZY_THRESHOLD` | `85` | порог `fuzz.ratio` (number-only) |
| `EXCEL_HEADER_ROW` | `8` | строка заголовка формата МО |
| `DATA_DIR` | `/app/data` | resolver-кэш |
| `LABEL_SOURCE` | `тех.нарушения` | `Incident.source` |

---

## Разрешение — детали ([fuzzy.py](fuzzy.py))

- **Нормализация:** имя → только числовая часть (`ЦТП-1105`→`1105`, `ЦТП № 1-3-4`→`1-3-4`).
- **Scorer:** `rapidfuzz.fuzz.ratio` (строгое посимвольное: `63` ≉ `3`).
- **Фильтр по муниципалитету** (`str.contains`, очистка `г.о./г.`); при пустом
  подмножестве — fallback на весь справочник (событие не теряется).
- **Порог:** `score ≥ FUZZY_THRESHOLD` → resolved; иначе → unresolved.

На текущих данных 98.3% матчей имеют `score=100`, неоднозначных номеров (район+№) — 36 из
1156 → риск ложного матча низкий.

---

## Edge cases

| Ситуация | Поведение |
|---|---|
| LLM вернул «не найдено» | unresolved (не публикуется) |
| LLM timeout / Ollama недоступен | `llm_error`, событие → unresolved; **задача не падает** |
| номер не в справочнике (нет телеметрии) | unresolved (осознанно вне скоупа) |
| муниципалитет не найден | fallback на весь справочник |
| дубль `id_cds_claim` | схлопывается (ingest) + дедуп по `incident_id` (data-service) |
| повторный запуск | resume из resolver-кэша, LLM не переспрашивается |

---

## Нефункциональные требования

| Параметр | Требование |
|---|---|
| Идемпотентность | resolver-кэш + дедуп `incident_id` |
| Resume | продолжение с точки прерывания без повторных LLM-запросов |
| Внешние зависимости | только Ollama (LLM); всё остальное — внутри `production/` |
| Порт | 8006 |
| LLM latency | 1–5 с/запрос (Ollama local) |

---

## Структура

```
labeling-service/
├── SPEC.md, SPEC_TESTS.md
├── Dockerfile, requirements.txt, pytest.ini
├── main.py          FastAPI + фоновый воркер (job-API)
├── jobs.py          in-memory реестр задач
├── schemas.py       LabelJob, LabelStats
├── config.py        env-конфиг
├── ingest.py        Excel → нормализованные инциденты (CTP/GO)
├── fuzzy.py         детерминированное ядро разрешения (unit-tested)
├── resolve.py       LLM (Ollama) + fuzzy + checkpoint-кэш
├── clients.py       data-service: справочник + публикация меток
├── publish.py       сборка Incident-записей
├── compare_draft.py сравнение с черновым labler/ (паритет)
└── tests/           unit/ + e2e/ + fixtures/
```

## Реализация (reference)

FastAPI + Uvicorn, pandas, rapidfuzz, httpx, openpyxl/pyxlsb, Python 3.12. Развёртывание —
контейнер в Docker Compose. Известное ограничение: состояние задач in-memory (теряется при
рестарте), как у ingestion-service.
