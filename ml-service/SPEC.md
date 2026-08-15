# ML Service — Спецификация

## Бизнес-ценность

Сервис исполнения предиктивного стека (§10 NARRATIVE). Загружает модельный бандл,
опубликованный `training-service`, и обслуживает четыре слоя системы предупреждения
аварий: хронический watch-list, острый ежедневный алерт с триггером, гейтинг и
объяснение для диспетчера, плюс KPI-отчётность. Не знает об устройстве хранилища и
не обучает модели.

**Ключевые задачи:**
- Загрузить бандл ([MODEL_BUNDLE.md](../MODEL_BUNDLE.md)), сверить parity, кэшировать скоры.
- Слой 1: пообъектный хронический риск (RSF) → watch-list для планового ТО.
- Слой 2: острый скор (Full XGBoost H=30) + триггер (EWMA/persist) → очередь нарядов.
- Слой 3: гейтинг (острый ∧ объект в top-K RSF) → снижение ложных.
- Слой 4: объяснение (AFT-срок + суточный профиль), калиброванная вероятность для показа.
- KPI: честная temporal-отчётность (detection≈0.48, lift +0.20, κ*).

> **Самодостаточность.** Семантика триггеров (persist/EWMA/gate, cooldown, эпизод→наряд)
> и object-level реконструкция **перенесены копией** из research-`harness/` внутрь
> сервиса. Признаки берутся только из `feature-service`, сырьё для профиля — из
> `data-service`. Ничего вне `production/` не импортируется и не читается.

---

## Роль в системе

```
        viewer ──REST──▶ ml-service ──GET /features──▶ feature-service
                             │      ──GET /sensors ───▶ data-service (суточный профиль)
                             │
                    читает [ /models volume (ro) ] ◀── публикует training-service
```

Единственная точка входа для UI по риску/алертам/объяснению. Данные о скорах —
предвычислены на старте и закэшированы (как в demo ml-service), пересчёт по `POST /reload`.

---

## Слои → модули

| Модуль | Слой §10 | Ответственность |
|---|---|---|
| `loader.py` | — | загрузка бандла + manifest, сверка parity, hot-reload |
| `scoring.py` | 1 + 2 | acute-скор (дневной/почасовой), RSF-watch-list, кэш, ранжирование |
| `decision.py` | 2 + 3 | триггер (EWMA/persist) + cooldown + эпизод→наряд + гейтинг Full∧RSF |
| `explain.py` | 4 | AFT-срок, калиброванная вероятность, суточный профиль из data-service |
| `reporting.py` | человек | KPI из `manifest.reporting` (temporal detection/lift/κ*) |
| `main.py` | — | FastAPI, роуты |

---

## Загрузка бандла и кэш (startup)

1. Прочитать `/models/manifest.json`; проверить **4 инварианта** ([MODEL_BUNDLE.md §2](../MODEL_BUNDLE.md)):
   `schema_version` совместим; `feature_schema.service_version` == feature-service `/schema`
   (**иначе train/serve skew → сервис не стартует на этом бандле**); все файлы моделей
   грузятся и checksums сходятся; `horizon_days == 30`.
2. Запросить дневную матрицу у feature-service строго в `feature_schema.columns` (порядок важен).
3. Посчитать и закэшировать:
   - `acute_daily[object, date]` — сырой P(отказ 30д) + калиброванная (isotonic).
   - `chronic[object]` — RSF-ранг (object-level baseline recon: медиана первых
     `baseline_days=14` дней, `merge_gap=7`).
   - `aft_days[object]` — медианный срок AFT.
   - производные: ранги по дням, пообъектные пороги p75/p90, очередь нарядов (decision).
4. Старый кэш держится до успешной загрузки нового бандла — битый бандл не роняет обслуживание.

---

## Функциональные требования по слоям

### Слой 1 — хронический watch-list (scoring)
- Пообъектный RSF-ранг для приоритизации планового ТО.
- Подаётся как «класс нелинейных» (не «чемпион RSF» — CI перекрываются, §5 NARRATIVE).

### Слой 2 — острый алерт + триггер (scoring + decision)
- Дневной/почасовой acute-скор, ранжирование объектов по дате.
- Порог — из `manifest.alert_threshold` (2%-квантиль, по рангу сырого скора).
- **Триггер** (из `trigger_config.json`, дефолт EWMA-10): дневной скор → решение «звать осмотр».
- **Cooldown 14 дн**: серия подряд идущих алертов объекта = **один наряд**, не алерт-день.

### Слой 3 — гейтинг (decision)
- Наряд подтверждается, если объект И над острым порогом, И в top-K% хроники RSF.
- Профиль gating (top-30/50) — из `trigger_config`, оправдан при дорогих авариях (κ≥25).

### Слой 4 — объяснение (explain)
- **AFT-срок**: медианное «время до аварии» в днях (интерпретируемое, §9 rec. 2).
- **Калиброванная вероятность** (isotonic) — **только для показа** средней вероятности.
- **Суточный профиль**: сырые почасовые P/T из `data-service /sensors` (регимное различие +
  ночной провал). Отдельной модели/артефакта не требуется. SHAP-драйверы в систему не входят.

### KPI (reporting)
- Возврат `manifest.reporting` как есть: temporal `detection 0.48`, `lift +0.20`, p, n, κ*.
- **Только temporal**; object-split 0.70 не отдаётся (внутри нулевого пола).

---

## API-контракт

Порт 8001. Swagger: `/api/ml/docs`. Группировка по слоям.

### system
```
GET  /health     → { status, bundle_version, feature_schema_version, horizon_days,
                     cached_objects, cached_dates, trigger_default }
POST /reload      → перечитать бандл (hot-reload); { reloaded: true, bundle_version }
```

### Слой 1 — watch-list
```
GET /risk/watchlist?top_n=50
    → { items: [{ rank, object_id, chronic_score }], total_objects }
```

### Слой 1+2 — scoring
```
GET /risk/dates                              → [ "YYYY-MM-DD", ... ]
GET /risk/thresholds                         → { p50, p75, p90, alert_threshold }
GET /risk/ranking?date=&top_n=               → { date, total_objects, items:[{rank,object_id,risk_score}] }
GET /risk/object/{id}?date_from=&date_to=    → { object_id, timeline:[{date,risk_score,rank,last_ts}] }
GET /risk/object/{id}/hourly?date_from=&date_to= → { object_id, points:[{ts,risk_score}] }
GET /risk/object/{id}/thresholds             → { p75, p90 }   # пообъектные, дневные max
```

### Слой 2+3 — decision (очередь нарядов)
```
GET /alerts/queue?date=&profile=&gate=       → { date, profile, cooldown_days,
                                                 orders:[{object_id, opened_ts, acute_score,
                                                          in_chronic_topK, chronic_rank}] }
GET /alerts/object/{id}?profile=             → { object_id, episodes:[{start,end,peak_score}] }
GET /alerts/config                           → trigger_config.json (профили, κ-envelope, κ*)
```
`profile` (опц.) переопределяет дефолтный триггер; `gate` (bool) включает гейтинг Full∧RSF.

### Слой 4 — explain
```
GET /explain/{id}?date=  → { object_id,
                             aft_median_days,             # срок до аварии
                             calibrated_prob,             # ТОЛЬКО для показа
                             raw_score, alert_threshold,
                             daily_profile:[{ts,t_supply,t_return,p_supply,p_return}] }  # из data-service
```

### KPI
```
GET /kpi  → manifest.reporting  # { split:"temporal", detection, detection_null,
                                    detection_lift, lift_p_value, n_events, roc_auc, lead_within_H }
```

---

## Decision-слой: детали (stateful)

Триггеры и cooldown реализованы поверх кэша дневных скоров (без переобучения, §11):

- **persist-N** — алерт, когда скор ≥ порога на N подряд идущих **наблюдениях** объекта
  (данные разрежены → «подряд» = по последовательности, не по календарю).
- **EWMA-span** — сглаживание скора, затем порог (дефолт span=10).
- **эпизод→наряд**: подряд идущие алерт-дни объекта в пределах `cooldown_days=14` = один
  наряд (`opened_ts` = начало эпизода). Открытая заявка не переоткрывается ежедневно.
- **гейтинг**: наряд валиден, если `object_id` в top-`chronic_top_frac` RSF-хроники.

Состояние (эпизоды/наряды) вычисляется из кэша при загрузке бандла и по смене `profile`;
персистентной БД нет (осознанное ограничение ВКР, как in-memory очередь ingestion).

---

## Parity и инварианты

| Инвариант | Проверка |
|---|---|
| Порядок признаков | запрос к feature-service строго в `feature_schema.columns` |
| Train/serve schema | `feature_schema.service_version` == feature-service `/schema` |
| Горизонт | `horizon_days == 30` (иначе бандл отвергается) |
| Порог | по рангу сырого скора; калибровка на порог не влияет |
| Отчётность | только temporal из manifest; object-split не отдаётся |

---

## Нефункциональные требования

| Параметр | Требование |
|----------|-----------|
| Время отклика (чтение) | < 2 сек для типовых запросов (всё из памяти) |
| Старт | скоры считаются на startup (~десятки сек), затем кэш |
| Отказоустойчивость | битый/несовместимый бандл не роняет обслуживание |
| Масштаб | горизонтальное масштабирование не требуется (v1) |

---

## Текущая реализация (reference)

**Стек:** FastAPI + Uvicorn, Python 3.12, pandas/numpy, xgboost, scikit-survival (RSF),
lifelines (AFT), scikit-learn (isotonic), httpx.

### Окружение

| Переменная | Описание | Default |
|-----------|---------|---------|
| `MODEL_BUNDLE_DIR` | shared volume бандла (ro) | `/models` |
| `FEATURE_SERVICE_URL` | URL feature-service | `http://feature-service:8002` |
| `DATA_SERVICE_URL` | URL data-service (суточный профиль) | `http://data-service:8000` |
| `ROOT_PATH` | префикс за nginx | `/api/ml` |

### Разрешение открытых пунктов бандла

- **Формат AFT-выхода**: сервис отдаёт `aft_median_days` (медиана распределения,
  `LogNormalAFTFitter.predict_median`). Живой explainer/предрасчёт не нужны — SHAP исключён.
- **Копия feature_cols**: отдельный файл в бандле НЕ нужен — полный упорядоченный список
  уже лежит в `manifest.feature_schema.columns` (это и есть самодостаточная копия).

### Ограничения текущей реализации

- Скоры и очередь нарядов статичны между `POST /reload` (предвычислены из бандла+кэша).
- Состояние decision-слоя — in-memory (нет персистентной очереди заявок).
- Live-переоценка lift/κ* не делается — эти числа валидационные, из бандла (нет живых меток).
- Суточный профиль тянется из data-service синхронно (кэш профилей — вне scope v1).

Подробнее: [MODEL_BUNDLE.md](../MODEL_BUNDLE.md), [TECH_DEBT.md](../TECH_DEBT.md)
