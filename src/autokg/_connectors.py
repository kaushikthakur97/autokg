from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, Union

import polars as pl

_logger = logging.getLogger(__name__)


def from_parquet(path, **kwargs) -> pl.DataFrame:
    return pl.read_parquet(str(path), **kwargs)


def from_csv(path, **kwargs) -> pl.DataFrame:
    return pl.read_csv(str(path), **kwargs)


def from_json(path, **kwargs) -> pl.DataFrame:
    return pl.read_json(str(path), **kwargs)


def from_delta(path, version=None, **kwargs) -> pl.DataFrame:
    try:
        import deltalake
    except ImportError:
        raise ImportError("deltalake required for Delta Lake support. pip install deltalake")
    table = deltalake.DeltaTable(str(path), version=version)
    return pl.from_arrow(table.to_pyarrow_table(**kwargs))


def from_databricks_table(full_table_name: str, version: Optional[int] = None, **kwargs) -> pl.DataFrame:
    try:
        import deltalake
    except ImportError:
        raise ImportError("deltalake required for Databricks. pip install deltalake")
    table = deltalake.DeltaTable(full_table_name, version=version)
    return pl.from_arrow(table.to_pyarrow_table(**kwargs))


def from_snowflake(account: str, warehouse: str, database: str, schema: str, table: Optional[str] = None, query: Optional[str] = None, auth: Optional[dict] = None, **kwargs) -> pl.DataFrame:
    try:
        import snowflake.connector
    except ImportError:
        raise ImportError("snowflake-connector-python required. pip install snowflake-connector-python")
    conn_params = {"account": account, "warehouse": warehouse, "database": database, "schema": schema}
    if auth:
        conn_params.update(auth)
    conn = snowflake.connector.connect(**conn_params)
    try:
        cursor = conn.cursor()
        sql = query or f"SELECT * FROM {database}.{schema}.{table}"
        cursor.execute(sql)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return pl.DataFrame(rows, schema=columns)
    finally:
        conn.close()


def from_pandas(df: "Any") -> pl.DataFrame:
    return pl.from_pandas(df)


def from_polars(df: pl.DataFrame) -> pl.DataFrame:
    return df


def scan_parquet_chunked(path: Union[str, Path], chunk_size: int = 250_000):
    lf = pl.scan_parquet(str(path))
    total_rows = lf.select(pl.len()).collect().item()
    n_chunks = max(1, total_rows // chunk_size + (1 if total_rows % chunk_size else 0))
    for i in range(n_chunks):
        offset = i * chunk_size
        chunk = lf.slice(offset, chunk_size).collect()
        yield i + 1, n_chunks, chunk


def read_table(source, format=None, **kwargs) -> pl.DataFrame:
    if isinstance(source, pl.DataFrame):
        return source
    if hasattr(source, "to_pandas"):
        return pl.from_pandas(source)
    if isinstance(source, (str, Path)):
        src_str = str(source).lower()
        if format is None:
            if src_str.endswith(".parquet"):
                return from_parquet(source, **kwargs)
            elif src_str.endswith(".csv") or src_str.endswith(".tsv"):
                return from_csv(source, **kwargs)
            elif src_str.endswith(".json") or src_str.endswith(".jsonl"):
                return from_json(source, **kwargs)
            elif ".delta" in src_str or src_str.startswith("s3://") and "delta" in src_str:
                return from_delta(source, **kwargs)
            else:
                raise ValueError(f"Could not determine format of '{source}'. Use the 'format' parameter.")
        if format == "parquet":
            return from_parquet(source, **kwargs)
        elif format == "csv":
            return from_csv(source, **kwargs)
        elif format == "json":
            return from_json(source, **kwargs)
        elif format == "delta":
            return from_delta(source, **kwargs)
        else:
            raise ValueError(f"Unknown format: {format}")
    raise TypeError(f"Unsupported source type: {type(source)}")


CONNECTOR_REGISTRY: dict[str, Any] = {"parquet": from_parquet, "csv": from_csv, "json": from_json, "delta": from_delta}


def register_connector(name: str, reader):
    CONNECTOR_REGISTRY[name] = reader


def get_connector(name: str):
    if name not in CONNECTOR_REGISTRY:
        raise KeyError(f"No connector registered for '{name}'. Available: {list(CONNECTOR_REGISTRY)}")
    return CONNECTOR_REGISTRY[name]
