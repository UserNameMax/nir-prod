# Training Service — Спецификация

## Бизнес-ценность

Сервис обучения моделей системы предупреждения аварий (§10 NARRATIVE). Забирает
данные из внутренних сервисов production, обучает три модели предиктивного стека,
выбирает операционный триггер и **атомарно публикует модельный бандл**, который
затем обслуживает `ml-service`.

**Ключевые задачи:**
- Собрать обучающую выборку из `feature-service` (признаки) и `data-service` (метки).
- Обучить acute (Full XGBoost H=30), chronic (RSF watch-list), explain (Log-normal AFT).
- Откалибровать (isotonic для показа) и определить порог алертов (2% бюджет).
- Выбрать триггер по κ*-фронтиру → `trigger_config.json`.
- Провести temporal-валидацию (detection/lift над нулевым полом) → `manifest.json`.
- Опубликовать бандл по контракту [MODEL_BUNDLE.md](../MODEL_BUNDLE.md).

> **Самодостаточность.** Сервис не импортирует код и не читает файлы вне
> `production/`. Логика split / построения цели / реконструкции object-level /
> метрик / триггеров **перенесена копией** из research-`model_benchmark/harness/`
> внутрь сервиса. Данные — только из `feature-service` и `data-service`.

---

## Роль в системе

```
                    ┌── GET /features (дневная матрица) ──┐
training-service ───┤                                      ├──▶ feature-service
   (обучатель)      └── GET /incidents (метки аварий) ─────────▶ data-service
        │
        ▼ публикует бандл
  [ shared /models volume ] ──читает──▶ ml-service
        │
   POST /train, GET /jobs ◀── viewer / оператор / cron
```

Training — единственный **writer** бандла. Обучение запускается вручную (оператор/
viewer) или по расписанию (rolling-переобучение под дрейф, §10).

---

## Функциональные требования

### Сбор данных
- Признаки: `GET feature-service /features` — дневная каузальная матрица (Слой 0).
- Метки: `GET data-service /incidents` — верифицированные аварии `(object_id, incident_ts, close_ts)`.
- Построение цели `t_to_failure` (часы до ближайшей аварии) и `y = 1[t_to_failure ≤ H·24]`, H=30.
- Никаких обращений вне production; никаких локальных research-parquet.

### Split-политика (temporal, параметризуемая)
- **Чистая функция от даты, без файла-карты** (самодостаточность):
  ```
  test  = последний полный месяц данных
  val   = предыдущий месяц
  train = всё, что раньше
  ```
- Дефолт при демо-данных: `train < 2026-03-01`, `val = март 2026`, `test ≥ 2026-04-01`.
- Cutoffs — параметры запроса `POST /train` (для rolling-переобучения на новых окнах).
- Object-split (стратифицированный по объектам) **в проде не используется** — это был
  research-инструмент оценки generalization, завязанный на внешний `split_map.parquet`.

### Обучение моделей
| Модель | Алгоритм | Единица | Feature set | Выход |
|---|---|---|---|---|
| **acute** | XGBoost `binary:logistic` | C (объект-день) | `final_h30` (80) | сырой `P(отказ 30д)` |
| **chronic** | `sksurv.RandomSurvivalForest` | A (объект) | `r05`, object-level baseline | риск-ранг watch-list |
| **explain** | `lifelines.LogNormalAFTFitter` | A (объект) | object-level | медианный срок, дни |

Гиперпараметры (перенесены из research, см. §«Реализация»). Object-level датасет для
chronic/explain реконструируется из дневной матрицы: медиана признаков за первые
`baseline_days=14` дней строго ДО первого события; слияние близких событий `merge_gap=7`.

### Калибровка и порог
- **isotonic** (`sklearn.IsotonicRegression`) на val — **только для показа** средней
  вероятности (Слой 4). На порог не влияет.
- **Порог алертов** — квантиль val-скоров под бюджет `alert_rate=0.02` (сырой скор,
  монотонно эквивалентен калиброванному). Записывается в `manifest.alert_threshold`.

### Выбор триггера (κ*)
- Прогон persist-N / EWMA / gating по порогам → κ*-фронтир (§11).
- Дефолт **EWMA-10** (κ*≈5.3); полный κ-envelope и профили → `trigger_config.json`.
- Контроль-пол: те же триггеры на случайных скорах (для отчёта «×5…×9 над случаем»).

### Валидация (temporal)
- Метрики на test: `detection`, `detection_null` (permutation), `detection_lift`,
  p-value, `roc_auc`, `pr_auc`, `lead_within_H`, object-bootstrap CI (B=500).
- **Только temporal-числа** идут в `manifest.reporting` (для KPI-панели). Research-аналитику
  (object-split reference, calibration reframe, benchmark-сравнение, SHAP) НЕ сохраняем.

### Публикация бандла
- Атомарно по [MODEL_BUNDLE.md §1](../MODEL_BUNDLE.md): стейджинг в `/models/_tmp/<run_id>/`,
  самопроверка, атомарный перенос, `manifest.json` — последним.
- `manifest.feature_schema.service_version` = текущий хеш схемы feature-service (parity).
- (Опц.) уведомить ml-service `POST /reload`.

---

## API-контракт

```
POST /train
     Content-Type: application/json
     { "cutoffs": {"val_start": "2026-03-01", "test_start": "2026-04-01"} | null,
       "alert_rate": 0.02, "horizon_days": 30 }
     → { "job_id": "uuid", "status": "queued" }

GET /train/jobs            → TrainJob[]   последние N, sort by created_at desc
GET /train/jobs/{job_id}   → TrainJob
```

### Схема задачи

```python
class TrainJob:
    job_id: str
    status: "queued" | "processing" | "done" | "error"
    created_at: datetime
    finished_at: datetime | None
    error: str | None
    # прогресс по этапам пайплайна
    stage: "fetch" | "dataset" | "train_acute" | "train_chronic" |
           "train_explain" | "triggers" | "validate" | "publish" | None
    # итог
    stats: TrainStats | None

class TrainStats:
    run_id: str
    bundle_version: str
    n_objects: int
    n_pos_objects: int
    data_window: dict            # train/val/test границы
    detection: float             # temporal
    detection_lift: float
    trigger_default: str         # "ewma10"
    kappa_star: float
```

Очередь **последовательная** (одно обучение за раз — параллельная публикация бандла
недопустима). Статусы — in-memory, как в ingestion-service (осознанное ограничение ВКР).

---

## Пайплайн обучения

```
GET feature-service /features   GET data-service /incidents
              │                          │
              ▼ dataset (цель t_to_failure, y@H30, temporal split, object-level recon)
        ┌─────┴───────────────────────────────┐
        ▼               ▼                       ▼
   train_acute     train_chronic          train_explain
   (XGB+isotonic    (RSF object-A)         (LogNormal AFT)
    +порог 2%)          │                       │
        └───────┬───────┴───────────────────────┘
                ▼ triggers (κ*-фронтир → trigger_config.json)
                ▼ validate (temporal detection/lift/CI → manifest.reporting)
                ▼ publish (атомарно в /models, manifest.json последним)
```

---

## Внутренние модули

| Модуль | Ответственность | Источник кода (vendored) |
|---|---|---|
| `clients.py` | HTTP к feature-service / data-service | — |
| `dataset.py` | цель, temporal split, object-level recon | `harness/data.py` |
| `trainers/acute.py` | XGBoost H=30 + isotonic + порог | — |
| `trainers/chronic.py` | RSF object-level watch-list | `02_survival.ipynb` |
| `trainers/explain.py` | Log-normal AFT | `05_parametric_aft.ipynb` |
| `triggers.py` | persist/EWMA/gate, κ*-фронтир | `harness/triggers.py` |
| `metrics.py` | detection/lift, permutation-null, object-bootstrap | `harness/evaluate.py` |
| `publish.py` | атомарная запись бандла + manifest | контракт §1 |
| `jobs.py` | очередь, прогресс по стадиям | `ingestion-service/jobs.py` |
| `main.py` | FastAPI, эндпоинты `/train` | — |

---

## Нефункциональные требования

| Параметр | Требование |
|----------|-----------|
| Параллельность обучения | не допускается (последовательная очередь) |
| Атомарность публикации | гарантируется (staging + rename, manifest последним) |
| Train/serve parity | `feature_schema.service_version` сверяется с feature-service |
| Воспроизводимость | все seed=42; конфиг моделей — константы |
| Отчётность | только temporal-метрики в бандл |

---

## Текущая реализация (reference)

**Стек:** FastAPI + Uvicorn, Python 3.12, pandas/numpy, xgboost, scikit-learn,
scikit-survival (RSF), lifelines (AFT), httpx.

### Гиперпараметры (константы, перенесены из research)

```python
# acute — XGBoost H=30 (temporal, 12_temporal_holdout cell 5)
XGB = dict(n_estimators=1000, max_depth=4, learning_rate=0.05,
           subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
           reg_lambda=1.0, tree_method="hist", eval_metric="aucpr",
           early_stopping_rounds=50, random_state=42)
# scale_pos_weight = (y==0).sum() / max((y==1).sum(), 1)  — по train
ALERT_RATE = 0.02          # порог = квантиль val-скоров под бюджет

# chronic — RSF object-level (02_survival)
RSF = dict(n_estimators=200, min_samples_leaf=20, max_features="sqrt",
           n_jobs=-1, random_state=42)          # + SimpleImputer + StandardScaler
BASELINE_DAYS, MERGE_GAP = 14, 7

# explain — Log-normal AFT (05_parametric_aft), lifelines.LogNormalAFTFitter
HORIZON_DAYS = 30          # ТОЛЬКО H=30 операционно валиден
```

### Окружение

| Переменная | Описание | Default |
|-----------|---------|---------|
| `FEATURE_SERVICE_URL` | URL feature-service | `http://feature-service:8002` |
| `DATA_SERVICE_URL` | URL data-service | `http://data-service:8000` |
| `MODEL_BUNDLE_DIR` | shared volume бандла (rw) | `/models` |
| `ML_SERVICE_URL` | для опц. `POST /reload` | `http://ml-service:8001` |

### Ограничения текущей реализации

- Статусы задач теряются при рестарте контейнера (in-memory).
- Одно обучение за раз; нет распределённого обучения.
- Нет автоматического отката к предыдущему бандлу при провале самопроверки —
  публикация просто не происходит (старый бандл остаётся валидным).
- Rolling-расписание переобучения — вне scope v1 (запуск ручной или внешним cron).

Подробнее: [MODEL_BUNDLE.md](../MODEL_BUNDLE.md), [TECH_DEBT.md](../TECH_DEBT.md)
