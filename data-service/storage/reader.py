from __future__ import annotations
import os
import math
import duckdb
import pandas as pd
from pathlib import Path


def _sanitize(records: list[dict]) -> list[dict]:
    """Заменяем float NaN/Inf → None чтобы JSON сериализация не падала."""
    result = []
    for row in records:
        clean = {}
        for k, v in row.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                clean[k] = None
            else:
                clean[k] = v
        result.append(clean)
    return result


def _con(data_dir: str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(database=":memory:")


def _sensors_path(data_dir: str) -> str:
    return str(Path(data_dir) / "sensors.parquet")


def _meta_path(data_dir: str) -> str:
    return str(Path(data_dir) / "objects_meta.parquet")


def _incidents_path(data_dir: str) -> str:
    return str(Path(data_dir) / "incidents.parquet")


def _quote(value: str) -> str:
    return value.replace("'", "''")


def _file_exists(path: str) -> bool:
    return os.path.exists(path)


def read_sensors(
    data_dir: str,
    object_id: str,
    from_ts: int | None = None,
    to_ts: int | None = None,
    offset: int = 0,
    limit: int = 1000,
) -> tuple[list[dict], int]:
    path = _sensors_path(data_dir)
    if not _file_exists(path):
        return [], 0

    con = _con(data_dir)
    where = f"WHERE object_id = '{object_id}'"
    if from_ts is not None:
        where += f" AND ts_recorded >= {from_ts}"
    if to_ts is not None:
        where += f" AND ts_recorded <= {to_ts}"

    total = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{path}') {where}"
    ).fetchone()[0]

    rows = con.execute(
        f"SELECT * FROM read_parquet('{path}') {where} "
        f"ORDER BY ts_recorded LIMIT {limit} OFFSET {offset}"
    ).df()

    con.close()
    return _sanitize(rows.to_dict(orient="records")), total


def read_sensors_calendar(data_dir: str, object_id: str) -> list[str]:
    path = _sensors_path(data_dir)
    if not _file_exists(path):
        return []

    con = _con(data_dir)
    rows = con.execute(
        f"""
        SELECT DISTINCT strftime(to_timestamp(ts_recorded), '%Y-%m-%d') AS day
        FROM read_parquet('{path}')
        WHERE object_id = '{object_id}'
        ORDER BY day
        """
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def read_sensors_calendar_summary(
    data_dir: str,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[dict]:
    path = _sensors_path(data_dir)
    if not _file_exists(path):
        return []

    con = _con(data_dir)
    where = ""
    if from_date:
        where += f" AND day >= '{from_date}'"
    if to_date:
        where += f" AND day <= '{to_date}'"

    rows = con.execute(
        f"""
        SELECT day, COUNT(DISTINCT object_id) AS objects_count
        FROM (
            SELECT object_id,
                   strftime(to_timestamp(ts_recorded), '%Y-%m-%d') AS day
            FROM read_parquet('{path}')
        )
        WHERE 1=1 {where}
        GROUP BY day
        ORDER BY day
        """
    ).df()
    con.close()
    return rows.to_dict(orient="records")


def read_sensors_health(data_dir: str) -> dict:
    path = _sensors_path(data_dir)
    if not _file_exists(path):
        return {"sensors_count": 0, "period_from": None, "period_to": None}

    con = _con(data_dir)
    row = con.execute(
        f"""
        SELECT COUNT(*) AS cnt,
               strftime(to_timestamp(MIN(ts_recorded)), '%Y-%m-%d') AS period_from,
               strftime(to_timestamp(MAX(ts_recorded)), '%Y-%m-%d') AS period_to
        FROM read_parquet('{path}')
        """
    ).fetchone()
    con.close()
    return {"sensors_count": row[0], "sensors_total": row[0], "period_from": row[1], "period_to": row[2]}


def export_sensors(
    data_dir: str,
    out_path: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> int:
    """Выгрузить показания за период в parquet-файл. Возвращает число строк.

    Массовое чтение (инженерия признаков) не помещается в постраничный JSON:
    DuckDB стримит выборку прямо в parquet, симметрично staging-пути на запись.
    """
    path = _sensors_path(data_dir)
    if not _file_exists(path):
        return 0

    con = _con(data_dir)
    conditions = ["1=1"]
    if date_from:
        conditions.append(
            f"ts_recorded >= epoch(CAST('{_quote(date_from)}' AS TIMESTAMP))"
        )
    if date_to:
        # включительно: до конца суток date_to
        conditions.append(
            f"ts_recorded < epoch(CAST('{_quote(date_to)}' AS TIMESTAMP) + INTERVAL 1 DAY)"
        )
    where = "WHERE " + " AND ".join(conditions)

    con.execute(
        f"""
        COPY (
            SELECT object_id, ts_measurement, ts_recorded,
                   t_supply, t_return, p_supply, p_return
            FROM read_parquet('{path}') {where}
            ORDER BY object_id, ts_recorded
        ) TO '{out_path}' (FORMAT PARQUET)
        """
    )
    rows = con.execute(f"SELECT COUNT(*) FROM read_parquet('{out_path}')").fetchone()[0]
    con.close()
    return rows


def read_incidents(
    data_dir: str,
    object_id: str | None = None,
    from_ts: int | None = None,
    to_ts: int | None = None,
    offset: int = 0,
    limit: int = 1000,
) -> tuple[list[dict], int]:
    """Верифицированные аварии. Фильтр по объекту и окну открытия инцидента."""
    path = _incidents_path(data_dir)
    if not _file_exists(path):
        return [], 0

    con = _con(data_dir)
    conditions = ["1=1"]
    if object_id:
        conditions.append(f"object_id = '{_quote(object_id)}'")
    if from_ts is not None:
        conditions.append(f"incident_ts >= {from_ts}")
    if to_ts is not None:
        conditions.append(f"incident_ts <= {to_ts}")
    where = "WHERE " + " AND ".join(conditions)

    total = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{path}') {where}"
    ).fetchone()[0]

    rows = con.execute(
        f"SELECT * FROM read_parquet('{path}') {where} "
        f"ORDER BY incident_ts LIMIT {limit} OFFSET {offset}"
    ).df()

    con.close()
    return _sanitize(rows.to_dict(orient="records")), total


def read_incident_object_ids(data_dir: str) -> list[str]:
    """Список object_id, у которых есть хотя бы одна авария."""
    path = _incidents_path(data_dir)
    if not _file_exists(path):
        return []

    con = _con(data_dir)
    rows = con.execute(
        f"SELECT DISTINCT object_id FROM read_parquet('{path}') ORDER BY object_id"
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def read_incidents_health(data_dir: str) -> dict:
    path = _incidents_path(data_dir)
    if not _file_exists(path):
        return {"incidents_count": 0, "incidents_objects": 0}

    con = _con(data_dir)
    row = con.execute(
        f"""
        SELECT COUNT(*) AS cnt, COUNT(DISTINCT object_id) AS objects
        FROM read_parquet('{path}')
        """
    ).fetchone()
    con.close()
    return {"incidents_count": row[0], "incidents_objects": row[1]}


def read_objects_by_day(
    data_dir: str,
    date: str,
    offset: int = 0,
    limit: int = 100,
) -> tuple[list[dict], int]:
    sensors_path = _sensors_path(data_dir)
    meta_path = _meta_path(data_dir)
    if not _file_exists(sensors_path):
        return [], 0

    con = _con(data_dir)

    base = f"""
        SELECT DISTINCT object_id
        FROM read_parquet('{sensors_path}')
        WHERE strftime(to_timestamp(ts_recorded), '%Y-%m-%d') = '{date}'
    """

    if _file_exists(meta_path):
        count_q = f"""
            SELECT COUNT(*) FROM ({base}) ids
            LEFT JOIN read_parquet('{meta_path}') m USING (object_id)
        """
        rows_q = f"""
            SELECT m.* FROM ({base}) ids
            LEFT JOIN read_parquet('{meta_path}') m USING (object_id)
            ORDER BY m.object_id
            LIMIT {limit} OFFSET {offset}
        """
    else:
        count_q = f"SELECT COUNT(*) FROM ({base})"
        rows_q = f"""
            SELECT object_id, NULL as object_type, NULL as facility_type,
                   NULL as facility_name, NULL as municipality, NULL as rso
            FROM ({base})
            ORDER BY object_id
            LIMIT {limit} OFFSET {offset}
        """

    total = con.execute(count_q).fetchone()[0]
    rows = con.execute(rows_q).df()
    con.close()
    return _sanitize(rows.to_dict(orient="records")), total


def read_objects(
    data_dir: str,
    municipality: str | None = None,
    facility_type: str | None = None,
    q: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> tuple[list[dict], int]:
    path = _meta_path(data_dir)
    if not _file_exists(path):
        return [], 0

    con = _con(data_dir)
    conditions = ["1=1"]
    if municipality:
        conditions.append(f"municipality = '{municipality}'")
    if facility_type:
        conditions.append(f"facility_type = '{facility_type}'")
    if q:
        safe_q = q.replace("'", "''")
        conditions.append(f"facility_name ILIKE '%{safe_q}%'")
    where = "WHERE " + " AND ".join(conditions)

    total = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{path}') {where}"
    ).fetchone()[0]

    rows = con.execute(
        f"SELECT * FROM read_parquet('{path}') {where} "
        f"ORDER BY object_id LIMIT {limit} OFFSET {offset}"
    ).df()
    con.close()
    return _sanitize(rows.to_dict(orient="records")), total


def read_object_by_id(data_dir: str, object_id: str) -> dict | None:
    path = _meta_path(data_dir)
    if not _file_exists(path):
        return None

    con = _con(data_dir)
    rows = con.execute(
        f"SELECT * FROM read_parquet('{path}') WHERE object_id = '{object_id}'"
    ).df()
    con.close()
    if rows.empty:
        return None
    return _sanitize([rows.iloc[0].to_dict()])[0]
