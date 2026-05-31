import os
import threading
import pandas as pd
import pyarrow.parquet as pq
from pathlib import Path


_sensors_lock = threading.Lock()
_meta_lock = threading.Lock()

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


def _atomic_write(df: pd.DataFrame, target: str) -> None:
    tmp = target + ".tmp"
    df.to_parquet(tmp, index=False)
    os.replace(tmp, target)


def _read_ids(path: str, id_col: str) -> set:
    """Читаем только одну колонку id — в разы быстрее чем весь файл."""
    table = pq.read_table(path, columns=[id_col])
    return set(table[id_col].to_pylist())


def _ensure_parquet(path: str, schema: dict) -> pd.DataFrame:
    if os.path.exists(path):
        return pd.read_parquet(path)
    cols = list(schema.keys())
    return pd.DataFrame(columns=cols)


def bulk_insert_sensors(
    data_dir: str, records: list[dict]
) -> tuple[int, int]:
    """Upsert по record_id. Возвращает (inserted, skipped_duplicates)."""
    if not records:
        return 0, 0

    path = str(Path(data_dir) / "sensors.parquet")
    new_df = pd.DataFrame(records)

    with _sensors_lock:
        if not os.path.exists(path):
            _atomic_write(new_df, path)
            return len(new_df), 0

        # Читаем только record_id — не грузим все 8 колонок в память
        existing_ids = _read_ids(path, "record_id")
        new_df["record_id"] = new_df["record_id"].astype(str)

        to_insert = new_df[~new_df["record_id"].isin(existing_ids)]
        skipped = len(new_df) - len(to_insert)

        if not to_insert.empty:
            # Полный файл читаем только когда есть что дописывать
            existing = pd.read_parquet(path)
            merged = pd.concat([existing, to_insert], ignore_index=True)
            _atomic_write(merged, path)

        return len(to_insert), skipped


def bulk_upsert_objects(
    data_dir: str, records: list[dict]
) -> tuple[int, int]:
    """Upsert по object_id. Старые записи приоритетнее (object_type заполнен)."""
    if not records:
        return 0, 0

    path = str(Path(data_dir) / "objects_meta.parquet")
    new_df = pd.DataFrame(records)
    new_df["object_id"] = new_df["object_id"].astype(str)

    with _meta_lock:
        if not os.path.exists(path):
            deduped = new_df.sort_values("object_type", na_position="last") \
                            .drop_duplicates(subset=["object_id"], keep="first")
            _atomic_write(deduped, path)
            return len(deduped), 0

        # Читаем только object_id
        existing_ids = _read_ids(path, "object_id")
        new_df["object_id"] = new_df["object_id"].astype(str)

        new_objects = new_df[~new_df["object_id"].isin(existing_ids)]
        new_objects = new_objects.sort_values("object_type", na_position="last") \
                                 .drop_duplicates(subset=["object_id"], keep="first")
        skipped = len(new_df) - len(new_objects)

        if not new_objects.empty:
            existing = pd.read_parquet(path)
            merged = pd.concat([existing, new_objects], ignore_index=True)
            _atomic_write(merged, path)

        return len(new_objects), skipped


def update_object(data_dir: str, object_id: str, updates: dict) -> dict | None:
    path = str(Path(data_dir) / "objects_meta.parquet")

    with _meta_lock:
        existing = _ensure_parquet(path, META_SCHEMA)
        if existing.empty:
            return None

        existing["object_id"] = existing["object_id"].astype(str)
        mask = existing["object_id"] == str(object_id)
        if not mask.any():
            return None

        for key, val in updates.items():
            if key in existing.columns and val is not None:
                existing.loc[mask, key] = val

        _atomic_write(existing, path)
        return existing[mask].iloc[0].to_dict()
