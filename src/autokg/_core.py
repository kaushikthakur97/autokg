from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Optional, Union

import polars as pl

from ._connectors import read_table, register_connector as _reg_conn
from ._iri import IRIMinter
from ._types import (
    detect_primary_key,
    detect_foreign_keys,
    detect_column_role,
    resolve_auto_map,
    sanitize_name,
    COLUMN_ROLE_FOREIGN_KEY,
    COLUMN_ROLE_LIST,
    COLUMN_ROLE_PRIMARY_KEY,
)
from ._templates import TemplateGenerator
from ._mapper import RDFMapper
from ._inference import RelationshipInference
from ._catalog import CatalogGenerator
from ._serializers import serialize_triples, push_to_sparql_endpoint
from ._oxigraph import OxigraphStore
from ._agent import GraphAgent
from ._validation import ShaclValidator
from ._provenance import ProvenanceTracker
from ._entity_resolver import EntityResolver
from ._profiler import GraphProfiler
from ._versioning import VersionManager


class KnowledgeGraph:
    def __init__(
        self,
        namespace: str = "http://example.org/",
        *,
        use_maplib: bool = True,
        auto_iri: bool = True,
        auto_template: bool = True,
        iri_strategy: str = "namespace",
        store_path: Optional[str] = None,
    ):
        self.namespace = namespace.rstrip("/#")
        self.use_maplib = use_maplib
        self.auto_iri = auto_iri
        self.auto_template = auto_template
        self.iri_strategy = iri_strategy
        self.store_path = store_path

        self._iri_minter = IRIMinter(self.namespace, strategy=iri_strategy)
        self._mapper = RDFMapper(use_maplib=use_maplib)
        self._validator = ShaclValidator(self.namespace)
        self._provenance = ProvenanceTracker(self.namespace)
        self._profiler = GraphProfiler(self)
        self._oxigraph: Optional[OxigraphStore] = None

        self._tables: dict[str, dict] = {}
        self._templates: dict[str, Any] = {}
        self._built = False
        self._version_manager: Optional[VersionManager] = None

    @classmethod
    def from_table(
        cls,
        source: Union[str, Path, pl.DataFrame, Any],
        *,
        namespace: str = "http://example.org/",
        entity_type: Optional[str] = None,
        id_column: Optional[str] = None,
        property_map: Optional[dict[str, str]] = None,
        relationships: Optional[dict[str, str]] = None,
        **kwargs,
    ) -> "KnowledgeGraph":
        kg = cls(namespace=namespace, **kwargs)
        kg.add_table(source, entity_type=entity_type, id_column=id_column, property_map=property_map, relationships=relationships)
        return kg

    @classmethod
    def from_store(cls, store_path: Union[str, Path], namespace: str = "http://example.org/", **kwargs) -> "KnowledgeGraph":
        kg = cls(namespace=namespace, **kwargs)
        kg._oxigraph = OxigraphStore(store_path=str(store_path), read_only=True)
        if store_path and Path(store_path).exists():
            kg._oxigraph._get_store()
        kg._built = True
        return kg

    def add_table(
        self,
        source: Union[str, Path, pl.DataFrame, Any],
        *,
        entity_type: Optional[str] = None,
        id_column: Optional[str] = None,
        property_map: Optional[dict[str, str]] = None,
        relationships: Optional[dict[str, str]] = None,
        source_name: Optional[str] = None,
        **kwargs,
    ) -> "KnowledgeGraph":
        df = read_table(source, **kwargs)
        name = source_name or (Path(source).stem if isinstance(source, (str, Path)) else f"table_{len(self._tables)}")
        etype = entity_type or name.replace("_", " ").title().replace(" ", "")

        pk = id_column or detect_primary_key(df)

        self._tables[name] = {
            "df": df,
            "entity_type": etype,
            "pk_column": pk,
            "property_map": property_map or {},
            "relationships": relationships or {},
            "source": str(source) if isinstance(source, (str, Path)) else f"in_memory_{name}",
        }

        self._provenance.record_source(
            source_path=str(source) if isinstance(source, (str, Path)) else f"memory:{name}",
            entity_type=etype,
            row_count=df.height,
        )

        return self

    def remove_table(self, name: str) -> "KnowledgeGraph":
        if name in self._tables:
            del self._tables[name]
        if name in self._templates:
            del self._templates[name]
        return self

    def add_delta_table(
        self,
        source: Union[str, Path],
        *,
        entity_type: Optional[str] = None,
        id_column: Optional[str] = None,
        property_map: Optional[dict[str, str]] = None,
        relationships: Optional[dict[str, str]] = None,
        version: Optional[int] = None,
        **kwargs,
    ) -> "KnowledgeGraph":
        return self.add_table(source, entity_type=entity_type, id_column=id_column, property_map=property_map, relationships=relationships, format="delta", version=version, **kwargs)

    def mint_iris(self, id_columns: Optional[dict[str, str]] = None) -> "KnowledgeGraph":
        for name, info in self._tables.items():
            id_col = (id_columns or {}).get(name) or info.get("pk_column") or "id"
            if id_col and id_col in info["df"].columns:
                info["df"] = self._iri_minter.mint(info["df"], id_col, info["entity_type"])

        for name, info in self._tables.items():
            relationships = info.get("relationships", {})
            fk_cols = list(relationships.keys())
            if fk_cols:
                fk_map = {col: relationships.get(col, col.replace("_id", "").title().replace(" ", "")) for col in fk_cols}
                info["df"] = self._iri_minter.mint_fk_iris(info["df"], fk_map)

        return self

    def generate_templates(self, override: Optional[dict[str, Any]] = None) -> "KnowledgeGraph":
        for name, info in self._tables.items():
            df = info["df"]
            etype = info["entity_type"]
            prop_map = info.get("property_map", {})
            rels = info.get("relationships", {})

            generator = TemplateGenerator(
                namespace=self.namespace,
                entity_type=etype,
                iri_column=info.get("pk_column"),
                property_map=prop_map,
                fk_mapping=rels,
                use_maplib=self.use_maplib,
            )

            self._templates[name] = generator.generate(df)

        return self

    def infer_relationships(self) -> "KnowledgeGraph":
        dfs = {name: info["df"] for name, info in self._tables.items()}
        inference = RelationshipInference(dfs)
        inference.detect()

        for name, info in self._tables.items():
            fks = inference.to_relationship_map().get(name, [])
            for fk in fks:
                col = fk["column"]
                target = fk["target_table"]
                if col not in info.get("relationships", {}):
                    info.setdefault("relationships", {})[col] = target

        self._inference_result = inference
        return self

    def build(self) -> "KnowledgeGraph":
        if self.auto_iri:
            self.mint_iris()
        if self.auto_template:
            self.generate_templates()

        for name, info in self._tables.items():
            template = self._templates.get(name)
            if template:
                df = info["df"]
                pk = info.get("pk_column")

                iri_col = "_iris_kg_iri"
                if iri_col not in df.columns and pk:
                    df = df.with_columns(
                        pl.concat_str(
                            pl.lit(f"{self.namespace}/{info['entity_type']}/"),
                            df[pk].cast(pl.Utf8),
                        ).alias(iri_col)
                    )
                    info["df"] = df

                self._mapper.map_template(template, df, pk_column=pk)

        catalog = CatalogGenerator(self.namespace, title="Knowledge Graph Catalog")
        for name, info in self._tables.items():
            catalog.add_dataset(
                name=name,
                description=f"Dataset for {info['entity_type']}",
                source_path=info.get("source", ""),
                entity_type=info["entity_type"],
                row_count=info["df"].height,
            )
        catalog_triples = catalog.generate_triples()
        self._mapper.add_triples(catalog_triples)

        prov_triples = self._provenance.generate_triples()
        self._mapper.add_triples(prov_triples)

        self._built = True
        return self

    def query(self, sparql: str) -> Optional[pl.DataFrame]:
        return self._mapper.query(sparql)

    def add_triples(self, subject: str, predicate: str, obj: Any, *, is_iri: bool = False, datatype: Optional[str] = None):
        triple = {"subject": subject, "predicate": predicate, "object": obj}
        if is_iri:
            triple["is_iri"] = True
        if datatype:
            triple["datatype"] = datatype
        self._mapper.add_triples([triple])

    def insert_construct(self, sparql: str) -> "KnowledgeGraph":
        self._mapper.insert_construct(sparql)
        return self

    def write(self, path: Union[str, Path], format: str = "turtle") -> str:
        triples = self._mapper.get_triples()
        return serialize_triples(triples, path, format)

    def to_rdf(self, path: Union[str, Path], format: str = "turtle") -> str:
        return self.write(path, format)

    def push_to_sparql(self, endpoint_url: str, graph_uri: Optional[str] = None, auth: Optional[tuple] = None) -> bool:
        triples = self._mapper.get_triples()
        return push_to_sparql_endpoint(triples, endpoint_url, graph_uri, auth)

    def serve(self, host: str = "localhost", port: int = 7878) -> str:
        if self._oxigraph is None:
            self._oxigraph = OxigraphStore(store_path=self.store_path)
        if not getattr(self._oxigraph, '_triples_loaded', False):
            self._oxigraph.add_triples(self._mapper.get_triples())
            self._oxigraph._triples_loaded = True
        return self._oxigraph.serve(host=host, port=port)

    def save_store(self, path: Optional[str] = None) -> str:
        if self._oxigraph is None:
            self._oxigraph = OxigraphStore(store_path=path or self.store_path)
        self._oxigraph.add_triples(self._mapper.get_triples())
        return self._oxigraph.save(path)

    def generate_catalog(self, title: str = "Knowledge Graph Catalog", publisher: Optional[str] = None) -> CatalogGenerator:
        catalog = CatalogGenerator(self.namespace, title=title, publisher=publisher)
        for name, info in self._tables.items():
            catalog.add_dataset(
                name=name,
                description=f"Dataset for {info['entity_type']}",
                source_path=info.get("source", ""),
                entity_type=info["entity_type"],
                row_count=info["df"].height,
            )
        return catalog

    def validate(self, shapes_path: Optional[str] = None) -> dict:
        all_issues = {"conforms": True, "by_table": {}}
        for name, info in self._tables.items():
            result = self._validator.validate_dataframe(
                info["df"],
                pk_column=info.get("pk_column"),
                entity_type=info["entity_type"],
            )
            all_issues["by_table"][name] = result
            if not result["conforms"]:
                all_issues["conforms"] = False
        return all_issues

    def generate_shacl_shapes(self, output: Optional[str] = None) -> str:
        table_info = {}
        for name, info in self._tables.items():
            df = info["df"]
            cols = {}
            for col in df.columns:
                role = detect_column_role(df, col, info.get("pk_column"))
                cols[col] = {
                    "role": role,
                    "is_nullable": df[col].null_count() > 0,
                    "xsd_type": get_xsd_type(df[col].dtype),
                }
            table_info[name] = {
                "entity_type": info["entity_type"],
                "df": df,
                "pk_column": info.get("pk_column"),
                "columns": cols,
            }
        return self._validator.generate_shapes(table_info, output)

    def profile(self) -> pl.DataFrame:
        return self._profiler.profile()

    def class_distribution(self) -> pl.DataFrame:
        return self._profiler.class_distribution()

    def diagnose(self) -> dict:
        return self._profiler.diagnose()

    def create_agent(self, provider: str = "openai", model: str = "gpt-4o", api_key: Optional[str] = None, **kwargs) -> GraphAgent:
        return GraphAgent(self, provider=provider, model=model, api_key=api_key, **kwargs)

    def resolve_entities(self, source_a: str, source_b: str, on: list[str], strategy: str = "exact") -> EntityResolver:
        resolver = EntityResolver(self)
        resolver.match(source_a, source_b, on=on, strategy=strategy)
        resolver.link()
        return resolver

    def snapshot(self, tag: str, description: str = "") -> str:
        if self._version_manager is None:
            self._version_manager = VersionManager(
                str(Path(tempfile.gettempdir()) / "autokg_versions")
            )
        triples = self._mapper.get_triples()
        return self._version_manager.snapshot(triples, tag, description)

    def diff(self, tag_a: str, tag_b: str) -> dict:
        if self._version_manager is None:
            raise RuntimeError("No snapshots available. Call .snapshot() first.")
        return self._version_manager.diff(tag_a, tag_b)

    @property
    def provenance_summary(self) -> dict:
        return self._provenance.finish()

    @property
    def triple_count(self) -> int:
        return self._mapper.count_triples()

    @property
    def table_names(self) -> list[str]:
        return list(self._tables.keys())

    @property
    def is_built(self) -> bool:
        return self._built


def get_xsd_type(dtype: pl.DataType) -> str:
    from ._types import infer_xsd_type
    return infer_xsd_type(dtype)
