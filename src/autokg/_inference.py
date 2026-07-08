from __future__ import annotations

from collections import defaultdict
from typing import Optional

import polars as pl

from ._types import detect_primary_key


class RelationshipInference:
    def __init__(self, tables: dict[str, pl.DataFrame]):
        self.tables = tables
        self._primary_keys: dict[str, Optional[str]] = {}
        self._foreign_keys: list[dict] = []
        self._join_paths: list[dict] = []

    def detect(self) -> "RelationshipInference":
        self._detect_primary_keys()
        self._detect_foreign_keys()
        self._build_join_paths()
        return self

    def _detect_primary_keys(self):
        for name, df in self.tables.items():
            self._primary_keys[name] = detect_primary_key(df)

    def _detect_foreign_keys(self):
        for name, df in self.tables.items():
            pk = self._primary_keys.get(name)
            for col in df.columns:
                if col == pk:
                    continue
                target = self._match_fk_column(col)
                if target:
                    self._foreign_keys.append({
                        "source_table": name,
                        "source_column": col,
                        "target_table": target,
                        "target_column": self._primary_keys.get(target, "id"),
                    })

    def _match_fk_column(self, col: str) -> Optional[str]:
        col_lower = col.lower()
        candidates: list[tuple[int, str]] = []

        for table_name in self.tables:
            tn_lower = table_name.lower()
            singular = tn_lower.rstrip("s") if tn_lower.endswith("s") else tn_lower

            if col_lower == f"{singular}_id":
                candidates.append((5, table_name))
            elif col_lower == f"{tn_lower}_id":
                candidates.append((5, table_name))
            elif col_lower.endswith("_id"):
                stem = col_lower[:-3]
                if stem == singular or stem == tn_lower:
                    candidates.append((4, table_name))
                elif stem in tn_lower or tn_lower in stem:
                    candidates.append((2, table_name))

        if candidates:
            candidates.sort(key=lambda x: -x[0])
            return candidates[0][1]
        return None

    def _build_join_paths(self):
        for fk in self._foreign_keys:
            self._join_paths.append({
                "from_table": fk["source_table"],
                "from_column": fk["source_column"],
                "to_table": fk["target_table"],
                "to_column": fk["target_column"],
            })

    @property
    def primary_keys(self) -> dict[str, Optional[str]]:
        return dict(self._primary_keys)

    @property
    def foreign_keys(self) -> list[dict]:
        return list(self._foreign_keys)

    @property
    def join_paths(self) -> list[dict]:
        return list(self._join_paths)

    @property
    def relationship_map(self) -> dict[str, list[dict]]:
        return self.to_relationship_map()

    def to_relationship_map(self) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = defaultdict(list)
        for fk in self._foreign_keys:
            result[fk["source_table"]].append({
                "column": fk["source_column"],
                "target_table": fk["target_table"],
                "target_column": fk["target_column"],
            })
        return dict(result)

    def summary(self) -> dict:
        return {
            "tables": len(self.tables),
            "primary_keys_found": sum(1 for pk in self._primary_keys.values() if pk),
            "foreign_keys_found": len(self._foreign_keys),
            "join_paths_found": len(self._join_paths),
            "primary_keys": self._primary_keys,
            "foreign_keys": self._foreign_keys,
            "join_paths": self._join_paths,
        }
