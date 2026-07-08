from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union

import polars as pl


class RDFMapper:
    def __init__(self, use_maplib: bool = True):
        self.use_maplib = use_maplib
        self._model = None
        self._triples: list[dict[str, Any]] = []

    @property
    def model(self):
        if self._model is None:
            if self.use_maplib:
                try:
                    from maplib import Model
                    self._model = Model()
                except ImportError:
                    raise ImportError("maplib required. Install with: pip install maplib")
            else:
                self._model = {}
        return self._model

    def map_template(self, template, df: pl.DataFrame, pk_column: Optional[str] = None) -> "RDFMapper":
        if self.use_maplib and template is not None and hasattr(template, "template") and template.template:
            iri_col = "_iris_kg_iri"
            if iri_col in df.columns:
                iri_values = df[iri_col].to_list()

                mapped_df = df.clone()
                mapped_df = mapped_df.with_columns(pl.col(iri_col).alias("_iri"))

                param_cols = [p.variable.name for p in template.template.parameters]
                cols_to_use = []
                for pc in param_cols:
                    clean = pc.lstrip("_col_").lstrip("_fk_")
                    if pc.startswith("_col_"):
                        vn = pc
                        if clean in mapped_df.columns:
                            cols_to_use.append(clean)
                            mapped_df = mapped_df.with_columns(pl.col(clean).alias(vn))
                        else:
                            for dmc in mapped_df.columns:
                                if sanitize_for_compare(dmc) == sanitize_for_compare(clean):
                                    cols_to_use.append(dmc)
                                    mapped_df = mapped_df.with_columns(pl.col(dmc).alias(vn))
                                    break
                    elif pc.startswith("_fk_"):
                        fk_col = f"_iris_kg_fk_{clean}"
                        vn = pc
                        if fk_col in mapped_df.columns:
                            cols_to_use.append(fk_col)
                            mapped_df = mapped_df.with_columns(pl.col(fk_col).alias(vn))

                try:
                    self.model.map(template.template, mapped_df)
                except Exception:
                    manual = template.generate_triples_manual(df)
                    self._add_manual_triples(manual)
            else:
                if pk_column and pk_column in df.columns:
                    manual = template.generate_triples_manual(df, iri_col=pk_column)
                    self._add_manual_triples(manual)
                else:
                    manual = template.generate_triples_manual(df)
                    self._add_manual_triples(manual)
        else:
            if hasattr(template, "generate_triples_manual"):
                manual = template.generate_triples_manual(df)
                self._add_manual_triples(manual)

        return self

    def add_triples(self, triples: list[dict[str, Any]]) -> "RDFMapper":
        self._triples.extend(triples)
        return self

    def query(self, sparql: str) -> Optional[pl.DataFrame]:
        if self.use_maplib and self._model is not None and hasattr(self._model, "query"):
            try:
                return self.model.query(sparql)
            except Exception:
                pass
        return None

    def insert_construct(self, sparql: str) -> "RDFMapper":
        if self.use_maplib and self._model is not None and hasattr(self._model, "insert"):
            try:
                self.model.insert(sparql)
            except Exception:
                pass
        return self

    def _add_manual_triples(self, triples: list[dict[str, Any]]):
        self._triples.extend(triples)

    def get_triples(self) -> list[dict[str, Any]]:
        return list(self._triples)

    def count_triples(self) -> int:
        if self.use_maplib and self._model is not None and hasattr(self._model, "query"):
            try:
                result = self.model.query("SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o }")
                if result is not None and result.height > 0:
                    return result["c"][0]
            except Exception:
                pass
        return len(self._triples)

    def serialize(self, path: Union[str, Path], format: str = "turtle") -> str:
        path = Path(path)
        fmt = format.lower()

        if self.use_maplib and self._model is not None and hasattr(self._model, "write_triples"):
            self.model.write_triples(str(path), fmt)
            return str(path)

        return self._serialize_manual(path, fmt)

    def _serialize_manual(self, path: Path, fmt: str) -> str:
        from ._serializers import serialize_triples
        return serialize_triples(self._triples, path, fmt)

    def to_jsonld(self) -> dict:
        return {"@context": {"schema": "https://schema.org/", "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"}, "@graph": self._triples}


def sanitize_for_compare(s: str) -> str:
    return s.lower().replace("_", "").replace("-", "")
