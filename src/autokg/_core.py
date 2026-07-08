from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional, Union

import polars as pl

from ._connectors import read_table
from ._iri import IRIMinter
from ._types import detect_primary_key, detect_column_role, sanitize_name, COLUMN_ROLE_FOREIGN_KEY
from ._templates import TemplateGenerator
from ._mapper import RDFMapper
from ._relationships import RelationshipRegistry
from ._catalog import CatalogGenerator
from ._serializers import serialize_triples, push_to_sparql_endpoint
from ._oxigraph import OxigraphStore
from ._agent import GraphAgent
from ._validation import ShaclValidator
from ._provenance import ProvenanceTracker
from ._entity_resolver import EntityResolver
from ._profiler import GraphProfiler
from ._versioning import VersionManager
from ._audit import AuditTrail
from ._masking import PIIPolicy

_logger = logging.getLogger(__name__)


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
        audit_path: Optional[str] = None,
        openlineage_endpoint: Optional[str] = None,
        strict: bool = False,
        actor: str = "unknown",
    ):
        self.namespace = namespace.rstrip("/#")
        self.use_maplib = use_maplib
        self.auto_iri = auto_iri
        self.auto_template = auto_template
        self.iri_strategy = iri_strategy
        self.store_path = store_path
        self.strict = strict
        self.actor = actor

        self._iri_minter = IRIMinter(self.namespace, strategy=iri_strategy)
        self._mapper = RDFMapper(use_maplib=use_maplib)
        self._validator = ShaclValidator(self.namespace)
        self._provenance = ProvenanceTracker(self.namespace)
        self._profiler = GraphProfiler(self)
        self._relationships = RelationshipRegistry()
        self._audit = AuditTrail(log_path=audit_path or (f"{store_path}/audit_events.jsonl" if store_path else None), openlineage_endpoint=openlineage_endpoint)
        self._oxigraph: Optional[OxigraphStore] = None

        self._tables: dict[str, dict] = {}
        self._templates: dict[str, Any] = {}
        self._pii_policies: dict[str, PIIPolicy] = {}
        self._built = False
        self._version_manager: Optional[VersionManager] = None

    @classmethod
    def from_table(cls, source, *, namespace="http://example.org/", entity_type=None, id_column=None, property_map=None, relationships=None, **kwargs) -> "KnowledgeGraph":
        kg = cls(namespace=namespace, **kwargs)
        kg.add_table(source, entity_type=entity_type, id_column=id_column, property_map=property_map, relationships=relationships)
        return kg

    @classmethod
    def from_store(cls, store_path, namespace="http://example.org/", **kwargs) -> "KnowledgeGraph":
        kg = cls(namespace=namespace, store_path=str(store_path), **kwargs)
        kg._oxigraph = OxigraphStore(store_path=str(store_path), read_only=True)
        if store_path and Path(store_path).exists():
            kg._oxigraph._get_store()
        kg._built = True
        return kg

    def add_table(self, source, *, entity_type=None, id_column=None, property_map=None, relationships=None, source_name=None, pii_policy=None, chunk_size=None, **kwargs) -> "KnowledgeGraph":
        df = read_table(source, **kwargs)
        name = source_name or (Path(source).stem if isinstance(source, (str, Path)) else f"table_{len(self._tables)}")
        etype = entity_type or name.replace("_", " ").title().replace(" ", "")
        pk = id_column or detect_primary_key(df)

        if pii_policy:
            policy = PIIPolicy(**pii_policy) if isinstance(pii_policy, dict) else pii_policy
            policy.detect(df)
            df = policy.apply(df)
            self._pii_policies[name] = policy
            self._audit.record("pii_masked", actor=self.actor, details={"table": name, "masked_columns": policy.masked_columns, "strategy": policy.strategy})

        self._tables[name] = {
            "df": df, "entity_type": etype, "pk_column": pk,
            "property_map": property_map or {},
            "relationships": relationships or {},
            "source": str(source) if isinstance(source, (str, Path)) else f"in_memory_{name}",
            "chunk_size": chunk_size,
        }
        self._provenance.record_source(source_path=str(source) if isinstance(source, (str, Path)) else f"memory:{name}", entity_type=etype, row_count=df.height)
        self._audit.record("add_table", actor=self.actor, details={"table": name, "entity_type": etype, "rows": df.height, "columns": len(df.columns)})
        return self

    def add_delta_table(self, source, *, entity_type=None, id_column=None, property_map=None, relationships=None, version=None, **kwargs) -> "KnowledgeGraph":
        return self.add_table(source, entity_type=entity_type, id_column=id_column, property_map=property_map, relationships=relationships, format="delta", version=version, **kwargs)

    def declare_relationship(self, source_table: str, source_column: str, target_table: str, *, target_column: str = "id", declared_by: str = None, ticket_ref: str = "", justification: str = "") -> "KnowledgeGraph":
        decl = self._relationships.declare(source_table, source_column, target_table, target_column=target_column, declared_by=declared_by or self.actor, ticket_ref=ticket_ref, justification=justification)
        self._audit.record("declare_relationship", actor=declared_by or self.actor, details={"source_table": source_table, "source_column": source_column, "target_table": target_table, "target_column": target_column, "justification": justification}, ticket_ref=ticket_ref)
        return self

    def remove_table(self, name: str) -> "KnowledgeGraph":
        if name in self._tables:
            del self._tables[name]
        if name in self._templates:
            del self._templates[name]
        self._audit.record("remove_table", actor=self.actor, details={"table": name})
        return self

    def mint_iris(self, id_columns=None) -> "KnowledgeGraph":
        for name, info in self._tables.items():
            id_col = (id_columns or {}).get(name) or info.get("pk_column") or "id"
            if id_col and id_col in info["df"].columns:
                info["df"] = self._iri_minter.mint(info["df"], id_col, info["entity_type"])
        for name, info in self._tables.items():
            rels = info.get("relationships", {})
            fk_map = {col: rels.get(col, col.replace("_id", "").title().replace(" ", "")) for col in rels}
            if fk_map:
                info["df"] = self._iri_minter.mint_fk_iris(info["df"], fk_map)
        return self

    def generate_templates(self, override=None) -> "KnowledgeGraph":
        for name, info in self._tables.items():
            gen = TemplateGenerator(namespace=self.namespace, entity_type=info["entity_type"], iri_column=info.get("pk_column"), property_map=info.get("property_map", {}), fk_mapping=info.get("relationships", {}), use_maplib=self.use_maplib)
            self._templates[name] = gen.generate(info["df"])
        return self

    def build(self, on_chunk: Optional[Callable[[int, int, int], None]] = None) -> "KnowledgeGraph":
        if self.strict and self._relationships.count() == 0 and len(self._tables) > 1:
            _logger.warning("Strict mode: No relationships declared for %d tables. Use declare_relationship() or set strict=False.", len(self._tables))

        rel_validation = self._relationships.validate({name: info["df"] for name, info in self._tables.items()})
        if rel_validation["errors"]:
            for err in rel_validation["errors"]:
                _logger.error("Relationship error: %s (declared by %s, ticket %s)", err["message"], err.get("declared_by", "?"), err.get("ticket_ref", "?"))
            if self.strict:
                raise ValueError(f"{len(rel_validation['errors'])} relationship validation errors.")
        if rel_validation["warnings"]:
            for warn in rel_validation["warnings"]:
                _logger.warning("Relationship warning: %s", warn["message"])

        if self.auto_iri:
            self.mint_iris()
        if self.auto_template:
            self.generate_templates()

        for name, info in self._tables.items():
            template = self._templates.get(name)
            if template:
                df = info["df"]
                iri_col = "_iris_kg_iri"
                if iri_col not in df.columns and info.get("pk_column"):
                    df = df.with_columns(pl.concat_str(pl.lit(f"{self.namespace}/{info['entity_type']}/"), df[info["pk_column"]].cast(pl.Utf8)).alias(iri_col))
                    info["df"] = df
                self._mapper.map_template(template, df, pk_column=info.get("pk_column"))

        catalog = CatalogGenerator(self.namespace, title="Knowledge Graph Catalog")
        for name, info in self._tables.items():
            catalog.add_dataset(name=name, description=f"Dataset for {info['entity_type']}", source_path=info.get("source", ""), entity_type=info["entity_type"], row_count=info["df"].height)
        self._mapper.add_triples(catalog.generate_triples())
        self._mapper.add_triples(self._provenance.generate_triples())

        self._built = True
        self._audit.record("build", actor=self.actor, details={"triple_count": self.triple_count, "table_count": len(self._tables), "relationship_count": self._relationships.count()})

        return self

    @property
    def is_built(self) -> bool:
        return self._built

    @property
    def triple_count(self) -> int:
        return self._mapper.count_triples()

    @property
    def table_names(self) -> list[str]:
        return list(self._tables.keys())

    @property
    def provenance_summary(self) -> dict:
        return self._provenance.finish()

    @property
    def relationships(self) -> RelationshipRegistry:
        return self._relationships

    def query(self, sparql: str) -> Optional[pl.DataFrame]:
        return self._mapper.query(sparql)

    def validate(self, shapes_path=None) -> dict:
        all_issues = {"conforms": True, "by_table": {}}
        for name, info in self._tables.items():
            result = self._validator.validate_dataframe(info["df"], pk_column=info.get("pk_column"), entity_type=info["entity_type"])
            all_issues["by_table"][name] = result
            if not result["conforms"]:
                all_issues["conforms"] = False
        rel_val = self._relationships.validate({name: info["df"] for name, info in self._tables.items()})
        all_issues["relationship_validation"] = rel_val
        return all_issues

    def write(self, path, format="turtle") -> str:
        return serialize_triples(self._mapper.get_triples(), path, format)

    def serve(self, host="localhost", port=7878) -> str:
        if self._oxigraph is None:
            self._oxigraph = OxigraphStore(store_path=self.store_path)
        if not getattr(self._oxigraph, "_triples_loaded", False):
            self._oxigraph.add_triples(self._mapper.get_triples())
            self._oxigraph._triples_loaded = True
        return self._oxigraph.serve(host=host, port=port)

    def save_store(self, path=None) -> str:
        if self._oxigraph is None:
            self._oxigraph = OxigraphStore(store_path=path or self.store_path)
        self._oxigraph.add_triples(self._mapper.get_triples())
        return self._oxigraph.save(path)

    def push_to_sparql(self, endpoint_url, graph_uri=None, auth=None) -> bool:
        return push_to_sparql_endpoint(self._mapper.get_triples(), endpoint_url, graph_uri, auth)

    def generate_catalog(self, title="Knowledge Graph Catalog", publisher=None) -> CatalogGenerator:
        catalog = CatalogGenerator(self.namespace, title=title, publisher=publisher)
        for name, info in self._tables.items():
            catalog.add_dataset(name=name, description=f"Dataset for {info['entity_type']}", source_path=info.get("source", ""), entity_type=info["entity_type"], row_count=info["df"].height)
        return catalog

    def generate_shacl_shapes(self, output=None) -> str:
        table_info = {}
        for name, info in self._tables.items():
            df = info["df"]
            cols = {}
            for col in df.columns:
                role = detect_column_role(df, col, info.get("pk_column"))
                cols[col] = {"role": role, "is_nullable": df[col].null_count() > 0, "xsd_type": "http://www.w3.org/2001/XMLSchema#string"}
            table_info[name] = {"entity_type": info["entity_type"], "df": df, "pk_column": info.get("pk_column"), "columns": cols}
        return self._validator.generate_shapes(table_info, output)

    def profile(self) -> pl.DataFrame:
        return self._profiler.profile()

    def class_distribution(self) -> pl.DataFrame:
        return self._profiler.class_distribution()

    def diagnose(self) -> dict:
        return self._profiler.diagnose()

    def create_agent(self, provider="openai", model="gpt-4o", api_key=None, **kwargs) -> GraphAgent:
        return GraphAgent(self, provider=provider, model=model, api_key=api_key, **kwargs)

    def resolve_entities(self, source_a, source_b, on, strategy="exact") -> EntityResolver:
        resolver = EntityResolver(self)
        resolver.match(source_a, source_b, on=on, strategy=strategy)
        resolver.link()
        return resolver

    def snapshot(self, tag, description="") -> str:
        if self._version_manager is None:
            self._version_manager = VersionManager(str(Path(tempfile.gettempdir()) / "autokg_versions"))
        result = self._version_manager.snapshot(self._mapper.get_triples(), tag, description)
        self._audit.record("snapshot", actor=self.actor, details={"tag": tag, "description": description})
        return result

    def diff(self, tag_a, tag_b) -> dict:
        if self._version_manager is None:
            raise RuntimeError("No snapshots available. Call .snapshot() first.")
        return self._version_manager.diff(tag_a, tag_b)

    def audit_log(self) -> pl.DataFrame:
        return self._audit.log()

    def who_changed(self, entity_iri: str) -> list:
        return self._audit.who_changed(entity_iri)

    def get_pii_policy(self) -> dict:
        return {name: p.summary() for name, p in self._pii_policies.items()}

    def add_triples(self, subject, predicate, obj, *, is_iri=False, datatype=None):
        t = {"subject": subject, "predicate": predicate, "object": obj}
        if is_iri:
            t["is_iri"] = True
        if datatype:
            t["datatype"] = datatype
        self._mapper.add_triples([t])
