# labeling-service — Спецификация тестов

## Стек

- `pytest` (+ `pytest-asyncio`, `asyncio_mode=auto`)
- `respx` — мок HTTP-вызовов к data-service (GET /objects, POST /incidents/bulk)
- `monkeypatch` — подмена LLM (`resolve.ask_llm`), без Ollama
- `openpyxl` — генерация тестовых xlsx-фикстур (формат МО, header=8)

Все тесты **не требуют** ни Ollama, ни docker, ни реального data-service.

```
tests/
├── fixtures/make_xlsx.py     генератор Excel тех.нарушений (3 CTP + 1 GO, дубль id)
├── unit/
│   ├── test_fuzzy.py         детерминированное ядро разрешения
│   ├── test_ingest.py        нормализация, дедуп, split CTP/GO, чтение header=8
│   ├── test_resolve.py       оркестрация LLM+fuzzy, кэш/resume, ошибки LLM
│   └── test_publish.py       сборка Incident-записей
└── e2e/
    ├── conftest.py           autouse-сброс реестра задач
    └── test_pipeline.py      ingest→resolve→publish (respx + mock LLM)
```

---

## Матрица покрытия

### Ядро разрешения (`test_fuzzy.py`)
- нормализация number-only: `ЦТП № 1-3-4`→`1-3-4`, `цтп1105`→`1105`
- точный матч внутри района (`score=100`)
- **дизамбигуация одинакового номера** в разных районах через фильтр муниципалитета
- строгий `fuzz.ratio` отклоняет близкие номера (`63` ≠ `1`)
- номер вне справочника / «не найдено» / пустой / пустой справочник → `None`

### Ingest (`test_ingest.py`)
- парсинг типов: `t_ov` с запятой → float, даты, bool-флаги, `source_file`
- отсутствие обязательных колонок → `ValueError`
- дедуп по `id_cds_claim`, split `obj_ctp` vs GO, drop строк без текста/даты
- чтение реального xlsx с `header=8`

### Resolve (`test_resolve.py`)
- resolved / unresolved (номер вне справочника)
- **ошибка LLM** (timeout) → unresolved, `llm_error`, без падения
- **resume:** предзаполненный кэш → `ask_llm` НЕ вызывается (assert)
- запись кэша после разрешения

### Publish (`test_publish.py`)
- только resolved И с `d_create` попадают в payload
- `incident_ts`/`close_ts` = unix-время `d_create`/`d_close`, `close_ts=None` если не закрыта
- корректный `source`

### E2E (`test_pipeline.py`)
- полный `_pipeline`: 3 CTP-инцидента (дубль схлопнут → 2) + 1 GO;
  `resolved=1`, `unresolved=1`, `published=1`, `go_events=1`, `status=done`
- проверка payload, ушедшего в `POST /incidents/bulk` (object_id, incident_id, source)
- **ошибка Ollama** (ConnectError) → задача `done`, `resolved=0`, `published=0`

---

## Сравнение с черновым разметчиком (`compare_draft.py`)

Не pytest, а верификационный скрипт: прогоняет продакшен-ядро (ingest+fuzzy+publish) на
входах черновика, переиспользуя его кэш LLM (`labler/data/resolver_cache.json`) — LLM
изолирован, сравнение детерминированно. **Ожидание: 100% паритет** разрешения и совпадение
числа Incident-записей (1265). Фактический прогон: `both_agree=1265, disagree=0,
prod_only=0, draft_only=0, agreement=1.0000`.

```bash
python compare_draft.py        # ✅ ПАРИТЕТ
```

---

## Запуск

```bash
pip install -r requirements.txt
pytest tests/unit -q            # быстрые, без сети
pytest tests/e2e -q -m e2e      # интеграция (respx + mock LLM)
python compare_draft.py         # паритет с черновиком
```
