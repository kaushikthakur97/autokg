from __future__ import annotations

import uuid
from typing import Optional, Union

import polars as pl


class IRIMinter:
    NAMESPACE = "namespace"
    UUID4 = "uuid4"
    UUID5 = "uuid5"
    HASH = "hash"
    NUMERIC = "numeric"

    def __init__(
        self,
        namespace: str,
        strategy: str = "namespace",
        uuid5_namespace: Optional[uuid.UUID] = None,
    ):
        self.namespace = namespace.rstrip("/#")
        self.strategy = strategy
        self.uuid5_namespace = uuid5_namespace or uuid.NAMESPACE_DNS

    def mint(self, df: pl.DataFrame, id_column: str, entity_type: Optional[str] = None) -> pl.DataFrame:
        entity = entity_type or id_column.replace("_id", "").replace("_", " ").title().replace(" ", "")

        if self.strategy == self.NAMESPACE:
            prefix = f"{self.namespace}/{entity}/" if "/" not in self.namespace[-1:] else f"{self.namespace}{entity}/"
            df = df.with_columns(
                pl.concat_str(pl.lit(prefix), df[id_column].cast(pl.Utf8)).alias("_iris_kg_iri")
            )

        elif self.strategy == self.UUID4:
            df = df.with_columns(
                pl.lit(uuid.uuid4()).apply(lambda _: str(uuid.uuid4())).alias("_iris_kg_uuid")
            )
            prefix = self._prefix_for(entity)
            df = df.with_columns(
                pl.concat_str(pl.lit(prefix), pl.col("_iris_kg_uuid")).alias("_iris_kg_iri")
            ).drop("_iris_kg_uuid")

        elif self.strategy == self.UUID5:
            prefix = self._prefix_for(entity)
            df = df.with_columns(
                pl.concat_str(pl.lit(f"{self.namespace}/{entity}/"), df[id_column].cast(pl.Utf8))
                .apply(lambda s: str(uuid.uuid5(self.uuid5_namespace, s)))
                .alias("_iris_kg_uuid")
            )
            df = df.with_columns(
                pl.concat_str(pl.lit(prefix), pl.col("_iris_kg_uuid")).alias("_iris_kg_iri")
            ).drop("_iris_kg_uuid")

        elif self.strategy == self.HASH:
            import hashlib
            prefix = self._prefix_for(entity)
            df = df.with_columns(
                pl.concat_str(pl.lit(f"{self.namespace}/{entity}/"), df[id_column].cast(pl.Utf8))
                .apply(lambda s: hashlib.sha256(s.encode()).hexdigest()[:16])
                .alias("_iris_kg_hash")
            )
            df = df.with_columns(
                pl.concat_str(pl.lit(prefix), pl.col("_iris_kg_hash")).alias("_iris_kg_iri")
            ).drop("_iris_kg_hash")

        elif self.strategy == self.NUMERIC:
            prefix = self._prefix_for(entity)
            df = df.with_columns(
                pl.concat_str(pl.lit(prefix), df[id_column].cast(pl.Utf8)).alias("_iris_kg_iri")
            )

        return df

    def _prefix_for(self, entity_type: str) -> str:
        return f"{self.namespace}/{entity_type}/"

    def mint_batch(
        self,
        tables: dict[str, pl.DataFrame],
        id_columns: dict[str, str],
        entity_types: Optional[dict[str, str]] = None,
    ) -> dict[str, pl.DataFrame]:
        result: dict[str, pl.DataFrame] = {}
        for table_name, df in tables.items():
            id_col = id_columns.get(table_name, "id")
            etype = (entity_types or {}).get(table_name)
            result[table_name] = self.mint(df, id_col, etype)
        return result

    def mint_fk_iris(
        self,
        df: pl.DataFrame,
        fk_mapping: dict[str, str],
    ) -> pl.DataFrame:
        for fk_col, entity_type in fk_mapping.items():
            prefix = self._prefix_for(entity_type)
            df = df.with_columns(
                pl.when(pl.col(fk_col).is_not_null())
                .then(pl.concat_str(pl.lit(prefix), pl.col(fk_col).cast(pl.Utf8)))
                .otherwise(pl.lit(None))
                .alias(f"_iris_kg_fk_{fk_col}")
            )
        return df
