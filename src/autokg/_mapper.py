from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional, Union

import polars as pl

_logger = logging.getLogger(__name__)


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
                mapped_df = df.clone()
                mapped_df = mapped_df.with_columns(pl.col(iri_col).alias("_iri"))

                param_cols = [p.variable.name for p in template.template.parameters]
                for pc in param_cols:
                    clean = pc.lstrip("_col_").lstrip("_fk_")
                    if pc.startswith("_col_"):
                        if clean in mapped_df.columns:
                            mapped_df = mapped_df.with_columns(pl.col(clean).alias(pc))
                        else:
                            for col in mapped_df.columns:
                                if sanitize_for_compare(col) == sanitize_for_compare(clean):
                                    mapped_df = mapped_df.with_columns(pl.col(col).alias(pc))
                                    break
                    elif pc.startswith("_fk_"):
                        fk_col = f"_iris_kg_fk_{clean}"
                        if fk_col in mapped_df.columns:
                            mapped_df = mapped_df.with_columns(pl.col(fk_col).alias(pc))

                try:
                    self.model.map(template.template, mapped_df)
                except Exception as e:
                    _logger.warning("maplib map() failed (%s), falling back to manual triples", type(e).__name__)
                    manual = template.generate_triples_manual(df)
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
            except Exception as e:
                _logger.warning("maplib query failed: %s", e)
        return None

    def insert_construct(self, sparql: str) -> "RDFMapper":
        if self.use_maplib and self._model is not None and hasattr(self._model, "insert"):
            try:
                self.model.insert(sparql)
            except Exception as e:
                _logger.warning("maplib insert_construct failed: %s", e)
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
            except Exception as e:
                _logger.warning("maplib count_triples failed: %s", e)
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
        nodes = []
        for t in self._triples:
            subj = t.get("subject", "")
            pred = t.get("predicate", "")
            obj = t.get("object", "")
            if t.get("is_iri") or t.get("object_iri"):
                obj_node = {"@id": obj}
            else:
                obj_node = {"@value": obj}
                if t.get("datatype"):
                    obj_node["@type"] = t["datatype"]
            nodes.append({"@id": subj, pred: [obj_node]})
        return {"@context": {"schema": "https://schema.org/", "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"}, "@graph": nodes}


def sanitize_for_compare(s: str) -> str:
    return s.lower().replace("_", "").replace("-", "")
