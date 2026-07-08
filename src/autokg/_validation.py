from __future__ import annotations

from typing import Any, Optional

import polars as pl

from ._types import detect_column_role, infer_xsd_type, sanitize_name, COLUMN_ROLE_PRIMARY_KEY


class ShaclValidator:
    def __init__(self, namespace: str):
        self.namespace = namespace.rstrip("/#")
        self._reports: list[dict] = []

    def generate_shapes(
        self,
        table_info: dict[str, dict],
        output: Optional[str] = None,
    ) -> str:
        lines = [
            "@prefix sh: <http://www.w3.org/ns/shacl#> .",
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
            "@prefix ex: <http://example.org/> .",
            "",
        ]

        for name, info in table_info.items():
            entity_type = info.get("entity_type", name)
            df = info.get("df")
            pk = info.get("pk_column") or (detect_primary_key(df) if df is not None else None)
            cols = info.get("columns", {})
            shape_iri = f"{self.namespace}/shape/{sanitize_name(entity_type)}"
            target_class = f"{self.namespace}/{entity_type}"

            lines.append(f"# Shape for {entity_type}")
            lines.append(f"<{shape_iri}> a sh:NodeShape ;")
            lines.append(f"    sh:targetClass <{target_class}> ;")

            if pk:
                pk_col_info = cols.get(pk, {})
                pk_prop = f"{self.namespace}/{sanitize_name(pk)}"
                lines.append(f"    sh:property [")
                lines.append(f"        sh:path <{pk_prop}> ;")
                lines.append(f"        sh:minCount 1 ;")
                lines.append(f"        sh:maxCount 1 ;")
                if pk_col_info.get("xsd_type"):
                    lines.append(f"        sh:datatype <{pk_col_info['xsd_type']}> ;")
                lines.append(f"    ] ;")

            if df is not None:
                for col in df.columns:
                    if col == pk or col.startswith("_iris_kg_"):
                        continue
                    role = detect_column_role(df, col, pk)
                    col_info = cols.get(col, {})
                    prop = f"{self.namespace}/{sanitize_name(col)}"
                    nullable = col_info.get("is_nullable", df[col].null_count() > 0)

                    lines.append(f"    sh:property [")
                    lines.append(f"        sh:path <{prop}> ;")
                    if not nullable:
                        lines.append(f"        sh:minCount 1 ;")
                    if col_info.get("xsd_type"):
                        lines.append(f"        sh:datatype <{col_info['xsd_type']}> ;")
                    lines.append(f"        sh:name \"{col}\" ;")
                    lines.append(f"    ] ;")

            lines[-1] = lines[-1].rstrip(" ;")
            if lines[-1].endswith("]"):
                lines[-1] = lines[-1] + " ."
            else:
                lines.append(".")
            lines.append("")

        content = "\n".join(lines)
        if output:
            from pathlib import Path
            Path(output).write_text(content, encoding="utf-8")
        return content

    def validate(
        self,
        triples: list[dict],
        shapes_path: Optional[str] = None,
    ) -> dict:
        issues: dict[str, list[dict]] = {
            "conforms": True,
            "violations": [],
            "warnings": [],
            "info": [],
        }

        return issues

    def validate_dataframe(
        self,
        df: pl.DataFrame,
        pk_column: Optional[str] = None,
        entity_type: str = "Entity",
    ) -> dict:
        issues = {
            "conforms": True,
            "violations": [],
            "warnings": [],
            "info": [],
            "stats": {"total_rows": df.height, "total_columns": len(df.columns)},
        }

        pk = pk_column or detect_primary_key(df)
        if pk:
            null_pk = df[pk].null_count()
            if null_pk > 0:
                issues["conforms"] = False
                issues["violations"].append({
                    "severity": "violation",
                    "column": pk,
                    "message": f"{null_pk} rows have null primary key values",
                    "count": null_pk,
                })
            dup = df.height - df[pk].n_unique()
            if dup > 0:
                issues["violations"].append({
                    "severity": "violation",
                    "column": pk,
                    "message": f"{dup} duplicate primary key values",
                    "count": dup,
                })
            else:
                issues["info"].append({
                    "severity": "info",
                    "column": pk,
                    "message": "All primary keys are unique and non-null",
                })

        for col in df.columns:
            if col == pk or col.startswith("_iris_kg_"):
                continue
            null_count = df[col].null_count()
            null_pct = (null_count / df.height * 100) if df.height > 0 else 0

            if null_pct == 100:
                issues["conforms"] = False
                issues["violations"].append({
                    "severity": "violation",
                    "column": col,
                    "message": f"Column '{col}' is entirely null",
                    "count": null_count,
                })
            elif null_pct > 50:
                issues["warnings"].append({
                    "severity": "warning",
                    "column": col,
                    "message": f"Column '{col}' has {null_pct:.1f}% null values",
                    "count": null_count,
                })

        return issues

    @property
    def reports(self) -> list[dict]:
        return self._reports
