"""Пайплайн Слоя 0: сырьё датчиков → дневная каузальная матрица признаков."""
from __future__ import annotations

import numpy as np
import pandas as pd

import schema

from . import clean, daily, interday, intraday

# Сколько объектов агрегировать за раз. Внутрисуточный этап разворачивает 8
# дополнительных колонок на КАЖДЫЙ 15-минутный отсчёт, поэтому на полной сети
# (десятки млн строк) он и есть пик памяти. Этап пообъектный, поэтому режется на
# чанки без изменения результата; дальше работаем уже на уровне объект-день
# (сотни тысяч строк), где резать нечего.
CHUNK_OBJECTS = 250


def build_matrix(sensors: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    """Полный проход: очистка → агрегаты → погода/календарь → динамика → отбор.

    Возвращает кадр с ключами (object_id, date) и 31 признаком final_h30 в
    зафиксированном порядке. Пропуски остаются NaN — XGBoost принимает их нативно.
    """
    if sensors.empty:
        return pd.DataFrame(columns=[*schema.KEYS, *schema.FEATURES])

    frame = _aggregate_in_chunks(sensors)
    frame = daily.build(frame, weather)
    frame = interday.build(frame)
    return select(frame)


def _aggregate_in_chunks(sensors: pd.DataFrame) -> pd.DataFrame:
    """Очистка + внутрисуточная агрегация по группам объектов.

    Оба этапа не смотрят за пределы объекта (границы и битые метки — вовсе
    построчные, дедуп — внутри (object_id, ts)), поэтому результат совпадает с
    обработкой одним куском, а пик памяти остаётся ограниченным.
    """
    objects = sensors["object_id"].astype(str).unique()
    if len(objects) <= CHUNK_OBJECTS:
        return intraday.build(clean.run(sensors))

    ids = sensors["object_id"].astype(str)
    parts = []
    for chunk in np.array_split(objects, int(np.ceil(len(objects) / CHUNK_OBJECTS))):
        part = sensors[ids.isin(set(chunk))]
        if part.empty:
            continue
        part = clean.run(part)
        if not part.empty:
            parts.append(intraday.build(part))
    return pd.concat(parts, ignore_index=True)


def select(frame: pd.DataFrame) -> pd.DataFrame:
    """Оставить ключи и признаки набора в порядке schema.FEATURES.

    Признак, который пайплайн не смог посчитать (например, физика без погоды),
    добавляется как NaN — контракт колонок обязан соблюдаться всегда.

    inf → NaN: отношения (`dp_night_ratio`, `dt_night_ratio`, `dp_vol_ratio`)
    расходятся при нулевом знаменателе. Пропуск потребители переваривают нативно,
    а бесконечность роняет и XGBoost, и скейлеры — поэтому матрица обязана
    отдавать только конечные значения либо NaN.
    """
    out = frame.reindex(columns=[*schema.KEYS, *schema.FEATURES])
    numeric = out.select_dtypes(include=[np.number]).columns
    out[numeric] = out[numeric].replace([np.inf, -np.inf], np.nan)
    return out.sort_values(list(schema.KEYS)).reset_index(drop=True)
