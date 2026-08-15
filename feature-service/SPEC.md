# Feature Service — Спецификация

## Бизнес-ценность

Сервис инженерии признаков — **Слой 0** системы (§10 NARRATIVE). Единственная
реализация построения дневной каузальной матрицы признаков из сырых показаний
датчиков. Обслуживает и `training-service` (обучение), и `ml-service` (инференс) —
**train/serve parity гарантируется по построению**: одна реализация за сервисной
границей, skew невозможен.

**Ключевые задачи:**
- Забрать сырые показания из `data-service`, привести к дневной сетке «объект-день».
- Построить признаки: внутрисуточные, междневные, физические (температурный график),
  циклические — строго **каузально** (без look-ahead).
- Реализовать **зафиксированный исследованием набор `final_h30` (31 признак)** как
  внутреннюю константу.
- Отдавать матрицу (`/features`) и хеш схемы (`/schema`) для сверки parity.

> **Самодостаточность.** Определение набора признаков и вся логика пайплайна —
> внутри `production/`, скопированы из research-`features/`. Сырьё датчиков — из
> `data-service`, наружная температура `T_out` — из `weather-service`. Внешний мир
> инкапсулирован в weather-service, feature-service о нём не знает.

---

## Роль в системе

```
data-service    ──GET /sensors──▶ feature-service ──GET /features──▶ training-service
weather-service ──GET /weather──▶       │          ──GET /features──▶ ml-service
                                        │          ──GET /schema ───▶ (сверка parity)
                                 [ кэш дневной матрицы ]
```

Feature-service — единственный владелец логики признаков. Ни training-service, ни
ml-service не строят признаки сами — только запрашивают.

---

## Функциональные требования

### Набор признаков `final_h30` (зафиксирован, 31 признак)
Реализуется как **упорядоченная константа** внутри сервиса (не читается из файлов вне
production). Категории:

| Категория | Признаки (примеры) |
|---|---|
| Внутрисуточные | `dp_night`, `dt_night`, `dp_night_ratio`, `p_drop_night`, `p_supply_drop_depth_intraday` |
| Дневные агрегаты | `t_supply_std`, `t_return_mean`, `p_return_max`, `dp_std`, `p_supply_skew`, `dp_skew` |
| Робастные z | `p_supply_robust_z`, `t_supply_robust_z` |
| Междневная динамика | `dp_slope_30d`, `dt_slope_30d`, `dt_accel`, `p_supply_accel`, `dp_vol_ratio`, `ewma_cross_dp` |
| Физика (темп. график, G4) | `dt_vs_expected`, `t_supply_vs_curve_slope_7d`, `t_supply_vs_curve_slope_30d` |
| Аномалийная память | `days_since_last_anomaly`, `dp_exceed_freq_14d` |
| Циклические | `sin_month`, `cos_month`, `sin_weekday`, `cos_weekday` |
| Покрытие | `n_samples`, `low_coverage` |

### Каузальность (критично)
- Все окна — трейлинг; ewm — каузальный; ffill — только прошлого.
- **G4-fix (аудит утечек, §8 NARRATIVE):** температурный график `f(T_out)` на объект
  фитится **expanding-fit** — на день `t` только строки `≤ t` (кумулятивные суммы, O(n)).
  `residual = факт − ожидание`. НЕ `polyfit` по всей истории (это был look-ahead).
- Гарантия: признаки причинны, target-производных нет (проверено аудитом research).

### Дневная агрегация
- Сырьё (~15-мин показания) → одна строка на `(object_id, date)`.
- `low_coverage` / `n_samples` фиксируют неполноту дня; пропуски НЕ заполняются нулями
  (XGBoost ест NaN нативно — 68% пропусков, §10 Слой 0).

### API
- `GET /features` — дневная матрица в наборе `final_h30` (+ `object_id`, `date`).
- `GET /schema` — версия/хеш схемы для parity-сверки ml-service и training-service.
- Warmup: для корректных rolling/ewm признаков дни считаются с прогревом истории
  (первые дни объекта могут иметь NaN в slope/accel — это норма).

---

## API-контракт

Порт 8002. Swagger: `/api/features/docs`.

```
GET /schema
    → { "name": "final_h30", "version": "<хеш>", "pipeline_version": "1",
        "n_features": 31, "columns": [ ...упорядоченный список 31... ],
        "keys": ["object_id","date"], "horizon_days": 30 }

GET /features?date_from=&date_to=&object_ids=
    → parquet-поток (application/vnd.apache.parquet)
      колонки: object_id, date + 31 признак в порядке schema.FEATURES
      заголовки: X-Rows, X-Schema-Version
      Отдаёт посчитанное; до первого rebuild — пустая матрица с полным контрактом колонок.

POST /features/rebuild
     { "date_from": "2025-10-01", "date_to": "2026-05-27" }
     → { object_days, objects, sensor_rows, weather_days, schema_version }
     Соседний сервис недоступен → 502 (кэш остаётся валидным).
     Нет показаний за период → 404.

GET /health
    → { status, schema_version, cached_object_days, cached_objects, date_from, date_to }
```

**Пересчитывать по всей истории.** Междневные окна (30D) и каузальный fit
температурного графика (нужно ≥15 наблюдений) требуют предыстории объекта: на
коротком окне `dt_vs_expected` и `*_slope_30d` в значительной части NaN. Запрос за
период режет уже посчитанную матрицу, а не считает окна заново — иначе значения
разошлись бы с обучением.

`version`/`<хеш>` — детерминированный хеш от (упорядоченный список признаков + версия
кода пайплайна). Меняется только при изменении набора/логики → сигнал «нужен новый бандл».

---

## Пайплайн признаков

```
data-service /sensors (15-мин P/T)    weather-service /weather (T_out)
        │                                        │
        ▼ intraday   (03_1: суточные агрегаты, ночное окно, drop_depth, robust_z)
        ▼ build_daily(03_2: сборка матрицы «объект-день»)
        ▼ interday   (03_3: slopes/accel/ewma_cross/days_since + G4 каузальный residual)
        ▼ cyclical   (sin/cos month, weekday)
        ▼ select     (набор final_h30 — 31 колонка, фиксированный порядок)
        ▼
   кэш дневной матрицы → /features
```

Стадии перенесены из research-`features/03_1..03_3` и `finalize_feature_sets.py`.

---

## Внутренние модули

| Модуль | Ответственность | Источник (vendored) |
|---|---|---|
| `client.py` | HTTP к data-service (`/sensors/export`) и weather-service (`/weather`) | — |
| `pipeline/intraday.py` | суточные агрегаты из 15-мин, ночное/дневное окна | `features/03_1_intraday.ipynb` |
| `pipeline/daily.py` | стыковка с погодой, календарь, `low_coverage` | `features/03_2_build_daily.ipynb` |
| `pipeline/interday.py` | G4 каузальный fit, робастные z, тренды, история событий | `features/03_3_interday.ipynb` |
| `pipeline/__init__.py` | оркестрация + `select()` (контракт колонок) | — |
| `schema.py` | константа `final_h30` (31 колонка) + хеш версии | `feature_cols_final_h30.json` |
| `cache.py` | предвычисленная дневная матрица (parquet) | — |
| `main.py` | FastAPI, `/features`, `/features/rebuild`, `/schema` | — |

Тесты (`tests/unit/`): `test_pipeline.py` — контракт колонок и **каузальность**
(параметризованный `test_feature_is_causal`: изменение будущего не меняет прошлые
признаки) плюс независимость от состава батча; `test_client.py` — граница с
соседними сервисами; `test_api.py` — эндпоинты с замоканными соседями.

### Отличия от research (осознанные)

1. **Цель не строится.** research в `03_2` подмешивал `t_to_failure`; здесь метки
   живут в data-service, а разметку под горизонт делает training-service.
2. **Пол масштаба робастных z заморожен константой** (`interday.SCALE_FLOOR`).
   В research пол считался как `0.05 · np.nanstd` по всему кадру — это (а) look-ahead
   (глобальная статистика включает будущее) и (б) поломка train/serve parity: один и
   тот же объект-день получал разный `robust_z` в зависимости от состава батча.
   Константы взяты с эталонной панели (747127 объект-дней), значения воспроизводятся.
3. **G4 действительно каузальный.** research-артефакт `daily_features.parquet` был
   сгенерирован ДО фикса и содержит протекающие значения (совпадение с leaky-вариантом
   до 1e-13). Поэтому при сверке с ним 28 из 31 признака совпадают бит-в-бит, а
   `dt_vs_expected` / `t_supply_vs_curve_slope_{7,30}d` отличаются — **это ожидаемо**
   (см. `model_benchmark/results/g4_causal_robustness.json`: ΔROC ≤0.01, н.з.).

---

## Нефункциональные требования

| Параметр | Требование |
|----------|-----------|
| Единственность реализации | признаки строит ТОЛЬКО этот сервис (parity) |
| Каузальность | все признаки трейлинг; G4 — expanding-fit (нет look-ahead) |
| Детерминизм схемы | `/schema` хеш стабилен при неизменном наборе/коде |
| Время отклика | матрица предвычислена и кэширована |
| Пропуски | сохраняются как NaN (не заполняются нулями) |

---

## Текущая реализация (reference)

**Стек:** FastAPI + Uvicorn, Python 3.12, polars/pandas, numpy, httpx.

### Окружение

| Переменная | Описание | Default |
|-----------|---------|---------|
| `DATA_SERVICE_URL` | URL data-service | `http://data-service:8000` |
| `WEATHER_SERVICE_URL` | URL weather-service (`T_out`) | `http://weather-service:8003` |
| `ROOT_PATH` | префикс за nginx | `/api/features` |

### Открытые пункты (закрыть при реализации)

- **Полный список 31 признака** зафиксировать в `schema.py` дословно из
  `feature_cols_final_h30.json` (перенос копией, не импорт).
- `T_out` берётся из `weather-service /weather`; физические признаки
  (`dt_vs_expected`, `t_supply_vs_curve_*`) требуют его наличия за нужные даты.

Подробнее: [MODEL_BUNDLE.md](../MODEL_BUNDLE.md), [SPEC.md](../SPEC.md)
