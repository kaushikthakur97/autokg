from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

import polars as pl


def from_parquet(path: Union[str, Path], **kwargs) -> pl.DataFrame:
    return pl.read_parquet(str(path), **kwargs)


def from_csv(path: Union[str, Path], **kwargs) -> pl.DataFrame:
    return pl.read_csv(str(path), **kwargs)


def from_json(path: Union[str, Path], **kwargs) -> pl.DataFrame:
    return pl.read_json(str(path), **kwargs)


def from_delta(path: Union[str, Path], version: Optional[int] = None, **kwargs) -> pl.DataFrame:
    try:
        import deltalake
    except ImportError:
        raise ImportError(
            "deltalake package required for Delta Lake support. Install with: pip install deltalake"
        )
    table = deltalake.DeltaTable(str(path), version=version)
    return pl.from_arrow(table.to_pyarrow_table(**kwargs))


def from_pandas(df: "Any") -> pl.DataFrame:
    return pl.from_pandas(df)


def from_polars(df: pl.DataFrame) -> pl.DataFrame:
    return df


def from_sql(connection_string: str, query: str, **kwargs) -> pl.DataFrame:
    try:
        import connectorx as cx
        return cx.read_sql(connection_string, query, **kwargs)
    except ImportError:
        pass
    try:
        from sqlalchemy import create_engine
        import pandas as pd
        engine = create_engine(connection_string)
        pdf = pd.read_sql(query, engine, **kwargs)
        return pl.from_pandas(pdf)
    except ImportError:
        raise ImportError(
            "sqlalchemy+pandas or connectorx required for SQL support. "
            "Install with: pip install sqlalchemy pandas connectorx"
        )


def read_table(
    source: Union[str, Path, pl.DataFrame, "Any"],
    format: Optional[str] = None,
    **kwargs,
) -> pl.DataFrame:
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
            elif src_str.endswith(".json") or src_str.endswith(".jsonl") or src_str.endswith(".ndjson"):
                return from_json(source, **kwargs)
            elif src_str.endswith(".delta") or "delta" in src_str:
                return from_delta(source, **kwargs)
            else:
                raise ValueError(
                    f"Could not determine format of '{source}'. "
                    "Use the 'format' parameter or specify a recognized file extension."
                )
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


CONNECTOR_REGISTRY: dict[str, Any] = {
    "parquet": from_parquet,
    "csv": from_csv,
    "json": from_json,
    "delta": from_delta,
}


def register_connector(name: str, reader):
    CONNECTOR_REGISTRY[name] = reader


def get_connector(name: str):
    if name not in CONNECTOR_REGISTRY:
        raise KeyError(f"No connector registered for '{name}'. Available: {list(CONNECTOR_REGISTRY)}")
    return CONNECTOR_REGISTRY[name]
