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
| `/calendar/:date` | `DayObjects` | Список объектов с данными за выбранный день |
| `/object/:object_id` | `ObjectCalendar` | Календарь дней с данными для конкретного объекта |
| `/object/:object_id/day/:date` | `DayView` | Графики датчиков за выбранный день |
| `/ingest` | `IngestPage` | Загрузка архивов и история задач |

**Навигация (Nav):** три вкладки — `Объекты`, `Календарь`, `Загрузка данных`.

nginx настроен с `try_files $uri /index.html` для корректной работы SPA-роутинга.

---

## Флоу навигации

```
ObjectList → ObjectCalendar → DayView
GlobalCalendar → DayObjects → DayView
```

---

## Страницы

### `ObjectList`

Таблица объектов с пагинацией (100 записей на страницу, offset-пагинация).

**Фильтры:** текстовый поиск по `facility_name` (debounce 300ms), выпадающие списки `municipality` и `facility_type`.

**Переход:** клик по строке → `/object/:object_id`.

### `GlobalCalendar`

Глобальный месячный календарь по всем объектам. Занимает полную высоту экрана (без скрола страницы), адаптируется по ширине.

**Источник данных:** `GET /sensors/calendar/summary?from_date=...&to_date=...`.

**Цвет дней:** синий — `objects_count > 0`, серый — нет данных. Тултип показывает количество объектов.

**Сетка:** всегда 6 строк × 7 столбцов (42 ячейки), строки равномерно заполняют доступную высоту.

**Переход:** клик по синему дню → `/calendar/:date`.

**Навигация по месяцам:** кнопки `←` / `→`, запрашиваем только видимый диапазон.

### `DayObjects`

Список объектов у которых есть данные за конкретный день.

**Источник данных:** `GET /sensors/calendar/objects?date=YYYY-MM-DD`.

**Переход:** клик по строке → `/object/:object_id/day/:date` (сразу на графики за этот день).

**Назад:** → `/calendar`.

### `ObjectCalendar`

Метаданные объекта + месячный календарь.

**Источник данных:** `GET /sensors/calendar?object_id=...` → список дней с данными.

**Цвет дней:** синий — есть данные, серый — нет данных.

**Переход:** клик по синему дню → `/object/:object_id/day/:date`.

### `DayView`

Сетка 2×2 из графиков датчиков за выбранный день.

| График | Поле | Единица | Цвет |
|--------|------|---------|------|
| Температура подачи | `t_supply` | °C | красный |
| Температура обратная | `t_return` | °C | оранжевый |
| Давление подачи | `p_supply` | МПа | синий |
| Давление обратное | `p_return` | МПа | фиолетовый |

**Навигация по дням:** `←` / `→` переключают между датами с данными (список дат берётся из `getCalendar`, кешируется в `sessionStorage` по `object_id`).

**Загрузка:** графики появляются сразу как пришли сенсорные данные, не дожидаясь ответа `getCalendar`. NaN-значения отображаются как разрывы (`connectNulls={false}`).

### `IngestPage`

Drag-and-drop загрузка одного или нескольких RAR/ZIP архивов одновременно.

**Очередь:** каждый файл создаёт отдельную задачу со статусом `queued`. Активные задачи (`queued` / `processing`) отображаются карточками над историей с прогресс-баром.

**Прогресс — фаза 1 (парсинг):** `files_processed / files_total`, текущий файл, счётчик строк.

**Прогресс — фаза 2 (мердж):** `merge_processed / merge_total` строк — отображается отдельно, чтобы индикатор не замирал на 100%.

**Персистентность:** при перезагрузке страницы `GET /ingest/jobs` возвращает активные задачи — поллинг возобновляется автоматически.

**История:** таблица завершённых задач (`done` / `error`) с датой, числом записей и периодом.

---

## Компоненты

### `Calendar`

Props: `objectId: string`, `dates: Set<string>`.

Помесячный грид. Клик по дню с данными → `navigate(/object/${objectId}/day/${date})`.

### `SensorChart`

Props: `data: SensorRecord[]`, `field`, `label`, `unit`, `color`.

Recharts `LineChart` с `connectNulls={false}`. Ось X — время (`ts_recorded`), ось Y — значение датчика.

---

## API-клиенты

| Файл | Сервис | Методы |
|------|--------|--------|
| `api/dataService.ts` | data-service | `getObjects`, `getObject`, `getCalendar`, `getCalendarSummary`, `getObjectsByDay`, `getSensors` |
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
