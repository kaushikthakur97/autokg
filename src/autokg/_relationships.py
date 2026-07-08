from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from datetime import timezone
from typing import Optional

import polars as pl


@dataclass
class RelationshipDeclaration:
    source_table: str
    source_column: str
    target_table: str
    target_column: str = "id"
    declared_by: str = "unknown"
    declared_at: str = field(default_factory=lambda: datetime.datetime.now(tz=timezone.utc).isoformat())
    justification: str = ""
    ticket_ref: str = ""


class RelationshipRegistry:
    def __init__(self):
        self._declarations: dict[str, list[RelationshipDeclaration]] = {}
        self._history: list[RelationshipDeclaration] = []

    def declare(
        self,
        source_table: str,
        source_column: str,
        target_table: str,
        *,
        target_column: str = "id",
        declared_by: str = "unknown",
        ticket_ref: str = "",
        justification: str = "",
    ) -> RelationshipDeclaration:
        decl = RelationshipDeclaration(
            source_table=source_table,
            source_column=source_column,
            target_table=target_table,
            target_column=target_column,
            declared_by=declared_by,
            ticket_ref=ticket_ref,
            justification=justification,
        )
        if source_table not in self._declarations:
            self._declarations[source_table] = []
        self._declarations[source_table].append(decl)
        self._history.append(decl)
        return decl

    def get_for_table(self, table_name: str) -> list[RelationshipDeclaration]:
        return list(self._declarations.get(table_name, []))

    def get_all(self) -> dict[str, list[RelationshipDeclaration]]:
        return {k: list(v) for k, v in self._declarations.items()}

    def list_all(self) -> list[RelationshipDeclaration]:
        return list(self._history)

    def count(self) -> int:
        return len(self._history)

    def validate(self, tables: dict[str, pl.DataFrame]) -> dict:
        result: dict[str, list[dict]] = {
            "valid": [],
            "warnings": [],
            "errors": [],
        }
        for table_name, declarations in self._declarations.items():
            df = tables.get(table_name)
            if df is None:
                result["errors"].append({
                    "table": table_name,
                    "message": f"Declared relationships for '{table_name}' but table not loaded",
                })
                continue
            for decl in declarations:
                if decl.source_column not in df.columns:
                    result["errors"].append({
                        "table": table_name,
                        "column": decl.source_column,
                        "message": f"Declared FK column '{decl.source_column}' not found in '{table_name}'",
                        "declared_by": decl.declared_by,
                        "ticket_ref": decl.ticket_ref,
                    })
                elif decl.target_table not in tables:
                    result["warnings"].append({
                        "table": table_name,
                        "target": decl.target_table,
                        "message": f"Target table '{decl.target_table}' for FK '{decl.source_column}' not loaded",
                        "declared_by": decl.declared_by,
                        "ticket_ref": decl.ticket_ref,
                    })
                else:
                    result["valid"].append({
                        "table": table_name,
                        "column": decl.source_column,
                        "target": decl.target_table,
                    })
        return result

    def to_dict(self) -> list[dict]:
        return [
            {
                "source_table": d.source_table,
                "source_column": d.source_column,
                "target_table": d.target_table,
                "target_column": d.target_column,
                "declared_by": d.declared_by,
                "declared_at": d.declared_at,
                "justification": d.justification,
                "ticket_ref": d.ticket_ref,
            }
            for d in self._history
        ]

    @classmethod
    def from_dict(cls, data: list[dict]) -> "RelationshipRegistry":
        reg = cls()
        for d in data:
            reg.declare(
                source_table=d["source_table"],
                source_column=d["source_column"],
                target_table=d["target_table"],
                target_column=d.get("target_column", "id"),
                declared_by=d.get("declared_by", "unknown"),
                ticket_ref=d.get("ticket_ref", ""),
                justification=d.get("justification", ""),
            )
        return reg
