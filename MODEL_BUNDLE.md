# Контракт модельного бандла — training-service → ml-service

Этот документ фиксирует **стык** между двумя сервисами:

- **Writer** — `training-service`: обучает модели, атомарно публикует бандл.
- **Reader** — `ml-service`: загружает бандл, обслуживает слои 1–4 (§10 NARRATIVE).

Пока контракт не зафиксирован, спеки обоих сервисов писать нельзя — все их
входы/выходы завязаны на структуру бандла и `manifest.json`.

Числа и постановка — из `model_benchmark/NARRATIVE.md` (§5, §7, §9–§11).

> **Принцип самодостаточности.** `production/` не имеет рантайм-зависимостей на код
> или файлы вне себя. Логика research-харнесса (`model_benchmark/harness/`:
> split/target/eval/triggers) и определение набора признаков **переносятся копией
> внутрь production** — харнесс лишь ИСТОЧНИК при копировании, не импортируемая
> библиотека. Данные training-service берёт только из `data-service` (внутри
> production). Числа NARRATIVE — референс постановки, не рантайм-связь.

---

## 1. Физическое размещение и жизненный цикл

Бандл — каталог на **shared volume**, смонтированный в оба сервиса:

```
training-service:  /models        (rw)   — пишет
ml-service:        /models        (ro)   — читает
docker-compose:    volume model-bundle:/models
```

Структура:

```
/models/
├── manifest.json              ← корень контракта (версия, пороги, метрики, ссылки на файлы)
├── trigger_config.json        ← Слой 2/3: выбранный триггер, κ*, gating
├── acute/
│   ├── xgb_h30.ubj            ← Слой 2: Full XGBoost, дискретный hazard H=30
│   └── isotonic_h30.pkl       ← калибровка ТОЛЬКО для показа средней вероятности
├── chronic/
│   └── rsf.pkl                ← Слой 1: RSF, object-level watch-list
├── explain/
│   └── aft_lognormal.pkl      ← Слой 4: «срок» до аварии (интерпретируемое время)
└── _tmp/                       ← стейджинг незавершённой публикации (см. §5)
```

> Слой 4 «объяснение» в системе = **только AFT-срок**. SHAP и прочие
> research-артефакты (важности, графики) в бандл НЕ входят — использовались лишь
> в исследовании. Суточный профиль объекта UI строит из сырых почасовых данных
> data-service, отдельная модель не нужна.

### Атомарность публикации

`training-service` не пишет в `/models/*` напрямую. Протокол:

1. пишет всё в `/models/_tmp/<run_id>/`;
2. проверяет самопроверкой (`manifest.json` валиден, все файлы на месте, модели грузятся);
3. атомарно перемещает каждый артефакт на место, **`manifest.json` — последним**
   (`os.replace`, атомарно в пределах тома).

`manifest.json`, появившийся последним, — сигнал «бандл целостен».

### Hot-reload

`ml-service` при старте и по `POST /reload` (или при изменении `manifest.json.version`)
перечитывает бандл. Старый бандл держится в памяти до успешной загрузки нового —
частичный/битый бандл не роняет обслуживание.

---

## 2. `manifest.json` — корень контракта

```jsonc
{
  "schema_version": "1.0",              // версия ЭТОГО контракта
  "version": "2026-07-15T18:22:00Z",    // версия бандла; смена → hot-reload в ml-service
  "run_id": "train_20260715_182200",
  "created_by": "training-service@<git_sha>",

  "horizon_days": 30,                   // ТОЛЬКО H=30 операционно валиден (§7: H14 форкаст ниже пола)

  // --- КОНТРАКТ ПРИЗНАКОВ (гарантия train/serve parity) ---
  // Набор ЗАФИКСИРОВАН исследованием (final_h30, 80 колонок) и РЕАЛИЗОВАН как
  // внутренняя константа feature-service — НЕ читается из файлов вне production.
  "feature_schema": {
    "name": "final_h30",
    "service_version": "<хеш схемы feature-service>",   // ml-service СВЕРЯЕТ с feature-service /schema
    "n_features": 31,                                    // отобранный набор (из 80-колоночной полной матрицы)
    "columns": ["t_supply_std", "t_return_mean", "p_return_max", "dp_night",
                "t_supply_vs_curve_slope_30d", "days_since_last_anomaly", "..."]  // ПОЛНЫЙ упорядоченный список
  },

  // --- ПОРОГ АЛЕРТОВ (Слой 2) ---
  "alert_threshold": {
    "policy": "budget_quantile",        // порог = квантиль val-скоров под бюджет
    "alert_rate": 0.02,                 // ставка 2% объект-дней (НЕ абсолют — §9)
    "raw_score_threshold": 0.174,       // соответствующий сырой скор acute-модели
    "note": "порог по РАНГУ сырого скора; калибровка на порог НЕ влияет"
  },

  // --- ОТЧЁТНОСТЬ ДЛЯ KPI-ПАНЕЛИ: ТОЛЬКО temporal (§7) ---
  // Минимальный операционный блок для UI. Research-аналитику (object-split reference,
  // calibration reframe, benchmark-сравнение) в систему НЕ сохраняем.
  "reporting": {
    "split": "temporal",                // train окт–фев / val март / test апр–май
    "detection": 0.48,
    "detection_null": 0.28,             // нулевой пол случайного алертирования
    "detection_lift": 0.20,
    "lift_p_value": 0.001,
    "n_events": 92,
    "roc_auc": 0.775,
    "lead_within_H": 0.68
  },

  // --- МЕТА ПО КАЖДОЙ МОДЕЛИ ---
  "models": {
    "acute":   { "file": "acute/xgb_h30.ubj", "family": "xgb-binary", "unit": "C",
                 "objective": "binary:logistic", "output": "P(отказ за 30д) raw",
                 "calibrator": "acute/isotonic_h30.pkl" },
    "chronic": { "file": "chronic/rsf.pkl", "family": "survival-A", "unit": "A",
                 "c_index": 0.819, "trained_on": "события строго ДО тестового окна",
                 "note": "класс нелинейных, НЕ «чемпион RSF»" },
    "explain_aft": { "file": "explain/aft_lognormal.pkl", "family": "aft-A", "unit": "A",
                 "output": "медианный срок до аварии, дни" }
  },

  // --- РЕКОНСТРУКЦИЯ object-level (для chronic/AFT; логика перенесена в production) ---
  "object_survival_recon": { "baseline_days": 14, "merge_gap": 7 },

  "data_window": { "train": "2025-10..2026-02", "val": "2026-03", "test": "2026-04..2026-05" },
  "checksums": { "acute/xgb_h30.ubj": "sha256:...", "...": "..." }
}
```

**Инварианты, которые ml-service обязан проверить при загрузке (иначе бандл отвергается):**

1. `schema_version` совместим (major совпадает).
2. `feature_schema.service_version` == текущая схема из feature-service `/schema`
   → **иначе train/serve skew, обслуживание не стартует на этом бандле**.
3. все файлы из `models.*` присутствуют и грузятся; `checksums` сходятся.
4. `horizon_days == 30`.

---

## 3. `trigger_config.json` — решающий слой (Слой 2/3)

Определяет, как дневной скор acute-модели превращается в **наряд на осмотр**
(§11). Выбирается training-service по κ*-фронтиру, но ml-service может переключать
профиль без переобучения.

```jsonc
{
  "default": "ewma10",                  // §11.3: min стоимость, κ*=5.3
  "cooldown_days": 14,                  // серия алертов объекта = один наряд
  "profiles": {
    "ewma10":     { "type": "ewma", "span": 10, "kappa_star": 5.3, "optimal_kappa": "4..24" },
    "persist5":   { "type": "persist", "n": 5, "kappa_star": 8.1, "note": "раннесть lead 0.79" },
    "persist7":   { "type": "persist", "n": 7, "kappa_star": 7.6, "optimal_kappa": "1..3" },
    "gate_top30": { "type": "gate", "chronic_top_frac": 0.30, "kappa_star": 9.3,
                    "optimal_kappa": "25..35", "note": "острый ∧ объект в top-30% RSF" },
    "gate_top50": { "type": "gate", "chronic_top_frac": 0.50, "kappa_star": 8.2,
                    "optimal_kappa": ">=36" }
  },
  "kappa_envelope": [                   // §11.4: оптимум зависит от цены аварии
    { "kappa": "1..3",   "optimum": "persist7" },
    { "kappa": "4..24",  "optimum": "ewma10" },
    { "kappa": "25..35", "optimum": "gate_top30" },
    { "kappa": ">=36",   "optimum": "gate_top50" }
  ],
  "null_floor": { "kappa_star_random": [68, 86], "model_advantage": "×5..×9" }
}
```

Семантика триггеров (persist/EWMA/gate, эпизод→наряд, cooldown) **перенесена копией
в production** (из research-`harness/triggers.py`) и живёт внутри `ml-service` —
никакого импорта извне.

---

## 4. Контракты моделей (вход/выход)

| Модель | Вход | Выход | Кто потребляет |
|---|---|---|---|
| `acute/xgb_h30.ubj` | дневной вектор `feature_schema.columns` (порядок важен; NaN нативно) | сырой `P(отказ за 30д)`, больше = рискованнее | scoring → decision |
| `acute/isotonic_h30.pkl` | сырой скод acute | калиброванная вероятность (для показа) | explain/UI |
| `chronic/rsf.pkl` | object-level baseline-признаки (реконструкция §object_survival_recon) | пообъектный риск-ранг (watch-list) | scoring, gating |
| `explain/aft_lognormal.pkl` | те же object-level признаки | медианный срок до аварии, дни | explain |

**Правило порядка признаков:** ml-service запрашивает у feature-service вектор
строго в `feature_schema.columns`. Любое расхождение имён/порядка — ошибка загрузки.

---

## 5. Версионирование и совместимость

- **`schema_version`** (этот контракт) — SemVer. Смена major = ломающее изменение
  структуры бандла; ml-service отвергает несовместимый major.
- **`version`** (данные бандла) — метка публикации; её смена триггерит hot-reload.
- **`feature_schema.service_version`** — хеш схемы feature-service. Бандл, обученный
  на схеме A, **не загружается** против feature-service схемы B. Обновление признаков
  = переобучение + новый бандл (никогда не частичная замена).

---

## 6. Самодостаточность и открытые пункты

**Что перенесено внутрь `production/` (копией из research, без рантайм-импорта):**

- логика split / построения цели / реконструкции object-level → в `training-service`;
- метрики и bootstrap (detection/lift/roc, object-bootstrap) → в `training-service`;
- семантика триггеров (persist/EWMA/gate, cooldown, эпизод→наряд) → в `ml-service`;
- определение набора признаков `final_h30` (80 колонок) → как константа в `feature-service`.

**Открытые пункты (решить при спеке сервисов):**

- **Split-политика в production.** research брал `split_map.parquet` (внешний файл) —
  в production его нет. training-service должен определять split САМ по
  детерминированной политике: temporal по дате (train окт–фев / val март /
  test апр–май) + object-split по хешу `object_id`. Зафиксировать в спеке training-service.
- **Загрузка меток (incidents) в data-service.** Сырые сенсоры уже грузит
  ingestion-service; для обучения нужны верифицированные аварии — определить их путь
  в data-service (эндпоинт `/incidents`), т.к. извне production читать нельзя.
