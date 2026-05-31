# viewer — Спецификация

**Порт:** 3000  
**Стек:** React 18, Vite, TypeScript, Tailwind CSS v4, Recharts, React Router v6

## Назначение

React SPA для работы с данными тепловых сетей. Получает данные из **data-service** (`:8000`) и управляет загрузкой архивов через **ingestion-service** (`:8001`). Не работает с parquet-файлами напрямую.

---

## Маршрутизация

| Путь | Страница | Описание |
|------|----------|----------|
| `/` | `ObjectList` | Список объектов с поиском и фильтрами |
| `/calendar` | `GlobalCalendar` | Глобальный календарь — дни с данными по всем объектам |
| `/object/:object_id` | `ObjectCalendar` | Календарь дней с данными для конкретного объекта |
| `/object/:object_id/day/:date` | `DayView` | Графики датчиков за выбранный день |
| `/ingest` | `IngestPage` | Загрузка архивов и история задач |

**Навигация (Nav):** три вкладки — `Объекты`, `Календарь`, `Загрузка данных`.

nginx настроен с `try_files $uri /index.html` для корректной работы SPA-роутинга.

---

## Страницы

### `ObjectList`

Таблица объектов с пагинацией (100 записей на страницу, offset-пагинация).

**Фильтры:** текстовый поиск по `facility_name` (debounce 300ms), выпадающие списки `municipality` и `facility_type`.

**Переход:** клик по строке → `/object/:object_id`.

### `ObjectCalendar`

Метаданные объекта + месячный календарь.

**Цвет дней:** синий — есть данные, серый — нет данных. Логика получается через `GET /sensors/calendar?object_id=...`.

**Переход:** клик по синему дню → `/object/:object_id/:date`.

### `DayView`

Сетка 2×2 из графиков датчиков за выбранный день.

| График | Поле | Цвет |
|--------|------|------|
| Температура подачи | `t_supply` | красный |
| Температура обратная | `t_return` | оранжевый |
| Давление подачи | `p_supply` | синий |
| Давление обратное | `p_return` | фиолетовый |

Навигация по дням: `←` / `→` переключают между датами, в которых есть данные (берётся из календаря объекта). NaN-значения в графиках отображаются как разрывы (`connectNulls={false}`).

### `GlobalCalendar`

Глобальный месячный календарь по всем объектам.

**Источник данных:** `GET /sensors/calendar/summary?from_date=...&to_date=...` → `[{"day": "2025-10-01", "objects_count": 420}, ...]`.

**Цвет дней:** синий — `objects_count > 0`, серый — нет данных.

**Переход:** клик по синему дню — переходим на `/?date=YYYY-MM-DD` (фильтрует список объектов по дню — **TODO**, пока не реализовано) или просто отображает количество объектов за день в тултипе. Поведение уточнить при реализации.

**Навигация по месяцам:** кнопки `←` / `→`, запрашиваем только видимый диапазон дат.

### `IngestPage`

Drag-and-drop загрузка RAR/ZIP архива. После загрузки — прогресс-бар с обновлением каждые 2 секунды (polling `GET /ingest/jobs/{id}`).

**Прогресс:** `files_processed / files_total`, текущий файл `current_file`, счётчик строк `rows_processed`.

**История:** список последних задач с бейджами статуса (`processing` / `done` / `error`).

---

## Компоненты

### `Calendar`

Props: `objectId: string`, `dates: Set<string>`.

Рендерит помесячный грид. Клик по дню с данными вызывает `navigate(/object/${objectId}/${date})`.

### `SensorChart`

Props: `data: SensorRecord[]`, `field`, `label`, `unit`, `color`.

Recharts `LineChart` с `connectNulls={false}`. Ось X — время (`ts_recorded`), ось Y — значение датчика.

---

## API-клиенты

| Файл | Сервис | Методы |
|------|--------|--------|
| `api/dataService.ts` | data-service | `getObjects`, `getObject`, `getCalendar`, `getCalendarSummary`, `getSensors` |
| `api/ingestService.ts` | ingestion-service | `upload`, `getJob`, `listJobs` |

URL сервисов берётся из env-переменных Vite:
- `VITE_DATA_API_URL` (default: `http://localhost:8000`)
- `VITE_INGEST_API_URL` (default: `http://localhost:8001`)

---

## Сборка (Docker)

Multi-stage Dockerfile:
1. `node:20-alpine` — `npm ci && npm run build`
2. `nginx:alpine` — копирует `dist/`, подключает `nginx.conf`

`ARG VITE_DATA_API_URL` / `ARG VITE_INGEST_API_URL` передаются в `docker-compose.yml` через `build.args`.
