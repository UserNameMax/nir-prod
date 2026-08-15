from __future__ import annotations
import os
import threading
import duckdb
import pandas as pd
import pyarrow.parquet as pq
from pathlib import Path


_sensors_lock = threading.Lock()
_meta_lock = threading.Lock()
_incidents_lock = threading.Lock()

SENSORS_SCHEMA = {
    "record_id": "VARCHAR",
    "object_id": "VARCHAR",
    "ts_measurement": "BIGINT",
    "t_supply": "DOUBLE",
    "t_return": "DOUBLE",
    "p_supply": "DOUBLE",
    "p_return": "DOUBLE",
    "ts_recorded": "BIGINT",
}

META_SCHEMA = {
    "object_id": "VARCHAR",
    "object_type": "VARCHAR",
    "facility_type": "VARCHAR",
    "facility_name": "VARCHAR",
    "municipality": "VARCHAR",
    "rso": "VARCHAR",
}

INCIDENTS_SCHEMA = {
    "incident_id": "VARCHAR",
    "object_id": "VARCHAR",
    "incident_ts": "BIGINT",
    "close_ts": "BIGINT",
    "source": "VARCHAR",
}


def _read_ids(path: str, id_col: str) -> set:
    """Читаем только одну колонку id — не грузим весь файл."""
    table = pq.read_table(path, columns=[id_col])
    return set(table[id_col].to_pylist())


def _duckdb_append(existing_path: str, new_df: pd.DataFrame) -> None:
    """
    Дописываем new_df к existing_path через DuckDB COPY.
    DuckDB стримит существующий файл батчами — не грузит всё в pandas.
    Атомарная замена через tmp-файл.
    """
    tmp = existing_path + ".tmp"
    con = duckdb.connect()
    con.register("new_records", new_df)
    con.execute(f"""
        COPY (
            SELECT * FROM read_parquet('{existing_path}')
            UNION ALL
            SELECT * FROM new_records
        ) TO '{tmp}' (FORMAT PARQUET)
    """)
    con.close()
    os.replace(tmp, existing_path)


def bulk_insert_sensors_from_files(data_dir: str, staging_paths: list[str]) -> tuple[int, int]:
    """Вставить данные из нескольких staging parquet-файлов за ОДИН DuckDB COPY.

    Читает все файлы вместе, дедуплицирует по record_id,
    мёрджит одним проходом — избегает N последовательных merge операций.
    """
    path = str(Path(data_dir) / "sensors.parquet")
    # Читаем все staging файлы сразу
    new_df = pd.concat([pd.read_parquet(p) for p in staging_paths], ignore_index=True)
    new_df = new_df.drop_duplicates(subset=["record_id"])

    try:
        with _sensors_lock:
            if not os.path.exists(path):
                new_df.to_parquet(path, index=False)
                return len(new_df), 0

            existing_ids = _read_ids(path, "record_id")
            to_insert = new_df[~new_df["record_id"].isin(existing_ids)]
            skipped = len(new_df) - len(to_insert)

            if not to_insert.empty:
                _duckdb_append(path, to_insert)

            print(f"[writer] inserted={len(to_insert)}, skipped={skipped}", flush=True)
            return len(to_insert), skipped
    finally:
        for p in staging_paths:
            try:
                os.remove(p)
            except Exception:
                pass


def bulk_insert_sensors_from_file(data_dir: str, staging_path: str) -> tuple[int, int]:
    """Вставить данные из staging parquet-файла (shared volume).

    Читает staging_path напрямую через pandas (без dict round-trip),
    дедуплицирует по record_id, мёрджит в sensors.parquet через DuckDB.
    После мёрджа удаляет staging_path.
    """
    path = str(Path(data_dir) / "sensors.parquet")
    new_df = pd.read_parquet(staging_path)

    try:
        with _sensors_lock:
            if not os.path.exists(path):
                new_df.to_parquet(path, index=False)
                return len(new_df), 0

            existing_ids = _read_ids(path, "record_id")
            to_insert = new_df[~new_df["record_id"].isin(existing_ids)]
            skipped = len(new_df) - len(to_insert)

            if not to_insert.empty:
                _duckdb_append(path, to_insert)

            return len(to_insert), skipped
    finally:
        try:
            os.remove(staging_path)
        except Exception:
            pass


def bulk_insert_sensors(
    data_dir: str, records: list[dict]
) -> tuple[int, int]:
    """Upsert по record_id. Возвращает (inserted, skipped_duplicates)."""
    if not records:
        return 0, 0

    path = str(Path(data_dir) / "sensors.parquet")
    new_df = pd.DataFrame(records)
    new_df["record_id"] = new_df["record_id"].astype(str)
    new_df["object_id"] = new_df["object_id"].astype(str)

    with _sensors_lock:
        if not os.path.exists(path):
            new_df.to_parquet(path, index=False)
            return len(new_df), 0

        # Читаем только record_id (1 колонка из 8) — быстро
        existing_ids = _read_ids(path, "record_id")
        to_insert = new_df[~new_df["record_id"].isin(existing_ids)]
        skipped = len(new_df) - len(to_insert)

        if not to_insert.empty:
            # DuckDB стримит существующий файл — не грузим 36М строк в pandas
            _duckdb_append(path, to_insert)

        return len(to_insert), skipped


def bulk_upsert_objects(
    data_dir: str, records: list[dict]
) -> tuple[int, int]:
    """Upsert по object_id. Старые записи приоритетнее."""
    if not records:
        return 0, 0

    path = str(Path(data_dir) / "objects_meta.parquet")
    new_df = pd.DataFrame(records)
    new_df["object_id"] = new_df["object_id"].astype(str)

    with _meta_lock:
        if not os.path.exists(path):
            deduped = new_df.sort_values("object_type", na_position="last") \
                            .drop_duplicates(subset=["object_id"], keep="first")
            deduped.to_parquet(path, index=False)
            return len(deduped), 0

        # Читаем только object_id (1 колонка из 6) — быстро
        existing_ids = _read_ids(path, "object_id")
        new_objects = new_df[~new_df["object_id"].isin(existing_ids)]
        new_objects = new_objects.sort_values("object_type", na_position="last") \
                                 .drop_duplicates(subset=["object_id"], keep="first")
        skipped = len(new_df) - len(new_objects)

        if not new_objects.empty:
            # objects маленькие (~4к строк) — pandas здесь ок
            existing = pd.read_parquet(path)
            merged = pd.concat([existing, new_objects], ignore_index=True)
            merged.to_parquet(path + ".tmp", index=False)
            os.replace(path + ".tmp", path)

        return len(new_objects), skipped


def bulk_insert_incidents(
    data_dir: str, records: list[dict]
) -> tuple[int, int]:
    """Upsert аварий по incident_id. Возвращает (inserted, skipped_duplicates)."""
    if not records:
        return 0, 0

    path = str(Path(data_dir) / "incidents.parquet")
    new_df = pd.DataFrame(records)
    new_df["incident_id"] = new_df["incident_id"].astype(str)
    new_df["object_id"] = new_df["object_id"].astype(str)
    # Nullable Int64: у незакрытой аварии close_ts пуст. Без явного типа партия
    # со сплошным None делает колонку float64 — схема parquet «плыла» бы между
    # загрузками.
    new_df["incident_ts"] = new_df["incident_ts"].astype("Int64")
    new_df["close_ts"] = new_df["close_ts"].astype("Int64")
    new_df = new_df.drop_duplicates(subset=["incident_id"])

    with _incidents_lock:
        if not os.path.exists(path):
            new_df.to_parquet(path, index=False)
            return len(new_df), 0

        existing_ids = _read_ids(path, "incident_id")
        to_insert = new_df[~new_df["incident_id"].isin(existing_ids)]
        skipped = len(new_df) - len(to_insert)

        if not to_insert.empty:
            # аварий немного (сотни) — pandas здесь ок
            existing = pd.read_parquet(path)
            merged = pd.concat([existing, to_insert], ignore_index=True)
            merged.to_parquet(path + ".tmp", index=False)
            os.replace(path + ".tmp", path)

        return len(to_insert), skipped


def update_object(data_dir: str, object_id: str, updates: dict) -> dict | None:
    path = str(Path(data_dir) / "objects_meta.parquet")

    with _meta_lock:
        if not os.path.exists(path):
            return None

        existing = pd.read_parquet(path)
        existing["object_id"] = existing["object_id"].astype(str)
        mask = existing["object_id"] == str(object_id)
        if not mask.any():
            return None

        for key, val in updates.items():
            if key in existing.columns and val is not None:
                existing.loc[mask, key] = val

        existing.to_parquet(path + ".tmp", index=False)
        os.replace(path + ".tmp", path)
        return existing[mask].iloc[0].to_dict()
