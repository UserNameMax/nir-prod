# Weather Service — Спецификация

## Бизнес-ценность

Сервис погоды — источник наружной температуры `T_out` для физических признаков
(температурный график, §Слой 0 NARRATIVE). Изолирует единственную внешнюю данность
системы: `feature-service` получает `T_out` через стабильный внутренний API и не знает
про внешний источник погоды.

**Зачем отдельный сервис:** погода — это bounded-концерн со своей внешней
зависимостью (open-meteo) и своим жизненным циклом (доступность API, кэш). Держать её
в `data-service` (телеметрия датчиков) или в `feature-service` (логика признаков)
смешало бы ответственности. Отдельный сервис = чистая граница «всё внешнее — здесь».

**Ключевые задачи:**
- Забрать дневную `T_out` по региону (Москва) из внешнего источника.
- **Кэшировать локально** (свой том) — система работает и при недоступности источника.
- Отдавать `T_out` по датам через `/weather`.

---

## Роль в системе

```
open-meteo (внешн.) ──ingest──▶ weather-service ──GET /weather (T_out)──▶ feature-service
                                       │
                                [ кэш weather_daily ]
```

Единственный сервис production, обращающийся во внешний мир. По образцу
`ingestion-service` (внешний ввод → локальное хранилище), но крошечный: один источник,
один ряд, одна метрика.

---

## Функциональные требования

### Приём погоды
- Источник: open-meteo archive (`archive-api.open-meteo.com/v1/archive`), координаты
  региона — Москва (`LAT=55.7558, LON=37.6173`), таймзона `Europe/Moscow` — совпадает
  с research (`02_weather.ipynb`).
- Гранулярность: **дневная**. Метрики (приходят одним запросом):
  `t_out_mean` (её использует G4-fit температурного графика), `t_out_min`, `t_out_max`,
  и производная `heating_degree = max(0, 18 − t_out_mean)`.
- Диапазон дат — под период данных датчиков (research: с `2025-10-01`).
- **Идемпотентность**: повторный ingest того же диапазона не создаёт дублей (upsert по дате).
- **Экономия обращений**: `refresh` тянет наружу только отсутствующие дни; `force=true`
  перезапрашивает период целиком (архив уточняется задним числом).

### Кэш и отказоустойчивость
- Данные хранятся в собственном томе (parquet). После первого ingest сервис отдаёт
  `T_out` **без обращения к внешнему источнику**.
- Недоступность open-meteo не роняет обслуживание уже загруженных дат — только
  блокирует догрузку новых.

### Отдача
- `GET /weather?date_from=&date_to=` → ряд дневной `T_out`.
- `POST /weather/refresh` → догрузить диапазон из внешнего источника (ручной/по cron).

---

## API-контракт

Порт 8003. Swagger: `/api/weather/docs`.

```
GET /weather?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD
    → { "region": "moscow",
        "rows": [ { "date": "2026-05-01", "t_out_mean": 5.2, "t_out_min": 1.3,
                    "t_out_max": 9.0, "heating_degree": 12.8 }, ... ] }
    Наружу НЕ ходит — отдаёт только загруженное.

POST /weather/refresh
     { "date_from": "2026-04-01", "date_to": "2026-05-31", "force": false }
     → { "fetched": 61, "added": 61, "updated": 0, "source": "open-meteo" }
     Период уже в кэше → { "fetched": 0, ..., "source": "cache" } (без внешнего вызова).
     Источник недоступен → 502, кэш остаётся валидным.
     date_from > date_to → 400.

GET /health
    → { status, region, cached_days, date_from, date_to }
```

---

## Внутренние модули

| Модуль | Ответственность |
|---|---|
| `source.py` | клиент open-meteo (единственная внешняя точка), `WeatherSourceError` |
| `store.py` | локальный кэш `weather_daily.parquet`: upsert по дате, чтение периода, `missing_days` |
| `schemas.py` | `WeatherDay`, `WeatherSeries`, `RefreshRequest`, `RefreshResult` |
| `dependencies.py` | `get_weather_dir` / `override_weather_dir` (подмена в тестах) |
| `main.py` | FastAPI, `/weather`, `/weather/refresh`, `/health` |

Тесты: `tests/unit/test_store.py` (кэш), `tests/unit/test_api.py` (API с замоканным
источником — тесты наружу не ходят).

---

## Нефункциональные требования

| Параметр | Требование |
|----------|-----------|
| Внешние обращения | только этот сервис; только к погодному источнику |
| Отказоустойчивость | загруженные даты отдаются при недоступности источника |
| Идемпотентность | повторный ingest = 0 дублей (upsert по дате) |
| Регион | одна точка (Москва); мультирегион — вне scope v1 |

---

## Текущая реализация (reference)

**Стек:** FastAPI + Uvicorn, Python 3.12, httpx (open-meteo), pandas/pyarrow.

### Окружение

| Переменная | Описание | Default |
|-----------|---------|---------|
| `WEATHER_API_URL` | базовый URL источника | `https://archive-api.open-meteo.com/v1/archive` |
| `WEATHER_LAT` / `WEATHER_LON` | координаты региона | `55.7558` / `37.6173` |
| `WEATHER_TZ` | таймзона агрегации | `Europe/Moscow` |
| `WEATHER_TIMEOUT` | таймаут запроса, сек | `30` |
| `WEATHER_REGION` | метка региона в ответе | `moscow` |
| `WEATHER_DIR` | том кэша | `/app/data` |
| `ROOT_PATH` | префикс за nginx | `/api/weather` |

Порт `8003`, том `weather` в [docker-compose.yml](../docker-compose.yml).

### Ограничения текущей реализации

- Один регион (Москва). Пообъектная геопривязка — вне scope v1 (research тоже брал
  одну точку на всю сеть МО).
- Автоматический refresh по расписанию — вне scope (ручной `POST /weather/refresh`
  или внешний cron), как rolling-переобучение training-service.
- `T_out_mean` дневной — единственная отдаваемая метрика (то, что нужно G4-fit).

Подробнее: [MODEL_BUNDLE.md](../MODEL_BUNDLE.md), [feature-service/SPEC.md](../feature-service/SPEC.md)
