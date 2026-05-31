# viewer — Спецификация

**Порт:** 3000  
**Стек:** React 18 + TypeScript, Recharts, Tailwind CSS, Vite

## Назначение

SPA для просмотра данных датчиков: поиск объектов, календарь дней с данными, графики параметров за выбранный день.

---

## Переменные окружения

```
VITE_DATA_API_URL    URL data-service    (default: http://localhost:8000)
VITE_INGEST_API_URL  URL ingestion-service (default: http://localhost:8001)
```

---

## Страницы и роутинг

| Путь | Компонент | Назначение |
|------|-----------|-----------|
| `/` | `ObjectList` | Поиск и список объектов |
| `/object/:object_id` | `ObjectCalendar` | Метаданные + календарь |
| `/object/:object_id/day/:date` | `DayView` | Графики за день |
| `/ingest` | `IngestPage` | Загрузка архива |

---

## Страница `/` — Список объектов

- Поисковая строка по `facility_name` (debounce 300ms → `GET /objects?q=...`)
- Фильтры: `municipality`, `facility_type` (select, значения из `GET /objects` уникальные)
- Таблица: `facility_name`, `municipality`, `facility_type`, `object_type`
- Пагинация: 100 объектов/страница
- Клик по строке → `/object/:object_id`

---

## Страница `/object/:object_id` — Объект

### Шапка
Карточка с метаданными объекта: `facility_name`, `municipality`, `rso`, `object_type`, `facility_type`.

### Календарь

Источник данных: `GET /sensors/calendar?object_id=<id>` → список дат.

Отображение:
- Сетка по месяцам, навигация `← →` (переключение месяца)
- **День с данными** — синий, кликабельный → `/object/:id/day/:date`
- **День без данных** — серый, не кликабельный
- Текущий день — обведён рамкой

---

## Страница `/object/:object_id/day/:date` — День

Источник данных: `GET /sensors?object_id=<id>&from_ts=<начало дня>&to_ts=<конец дня>&limit=10000`

### Графики

4 графика `LineChart` (Recharts) в сетке 2×2:

| Позиция | Параметр | Ось Y |
|---------|----------|-------|
| Верх-лево | `t_supply` | °C |
| Верх-право | `t_return` | °C |
| Низ-лево | `p_supply` | бар |
| Низ-право | `p_return` | бар |

Параметры графиков:
- Ось X — `ts_measurement`, формат `HH:mm`
- NaN-разрывы → разрыв линии (`connectNulls={false}`)
- Tooltip: точное значение + время (`HH:mm:ss`)
- ResponsiveContainer (адаптируется по ширине)

### Навигация
- `← Предыдущий день` / `Следующий день →` — переходит только на дни с данными (берёт из списка дат календаря)
- `← К календарю` — возврат на `/object/:object_id`

---

## Страница `/ingest` — Загрузка выгрузки

- Drag & drop зона + кнопка выбора файла (`.rar`, `.zip`)
- После выбора — кнопка Upload → `POST /ingest/upload`
- Polling `GET /ingest/jobs/{job_id}` каждые 2с пока `status === "processing"`
- Во время обработки: прогресс-бар `files_processed / files_total`, подпись `current_file`, счётчик `rows_processed`
- После завершения: карточка со статистикой из `IngestStats`
- Таблица истории (`GET /ingest/jobs`): filename, статус, дата, период данных, кол-во строк

---

## Структура src/

```
src/
├── api/
│   ├── dataService.ts     GET /sensors, /objects, /sensors/calendar
│   └── ingestService.ts   POST /ingest/upload, GET /ingest/jobs
├── pages/
│   ├── ObjectList.tsx
│   ├── ObjectCalendar.tsx
│   ├── DayView.tsx
│   └── IngestPage.tsx
├── components/
│   ├── Calendar.tsx       сетка с синими/серыми днями
│   └── SensorChart.tsx    один LineChart для одного параметра
└── types/
    └── api.ts             типы Page<T>, SensorRecord, ObjectMeta, IngestJob
```
