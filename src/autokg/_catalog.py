from __future__ import annotations

import datetime
from typing import Optional

import polars as pl

from ._types import DCAT, DCTERMS, PROV, SCHEMA, FOAF


class CatalogGenerator:
    def __init__(
        self,
        namespace: str,
        title: str = "Knowledge Graph Catalog",
        description: str = "Auto-generated DCAT catalog from autokg pipeline",
        publisher: Optional[str] = None,
        publisher_url: Optional[str] = None,
        theme: Optional[str] = None,
    ):
        self.namespace = namespace.rstrip("/#")
        self.title = title
        self.description = description
        self.publisher = publisher
        self.publisher_url = publisher_url
        self.theme = theme
        self._datasets: list[dict] = []
        self._catalog_iri = f"{self.namespace}/catalog"
        self._generated_at = datetime.datetime.utcnow().isoformat() + "Z"

    def add_dataset(
        self,
        name: str,
        description: str = "",
        source_path: str = "",
        distribution_format: str = "parquet",
        entity_type: Optional[str] = None,
        row_count: int = 0,
    ) -> "CatalogGenerator":
        ds_iri = f"{self.namespace}/dataset/{name.lower().replace(' ', '_')}"
        self._datasets.append({
            "iri": ds_iri,
            "name": name,
            "description": description,
            "source_path": source_path,
            "distribution_format": distribution_format,
            "entity_type": entity_type,
            "row_count": row_count,
        })
        return self

    def generate_triples(self) -> list[dict]:
        triples: list[dict] = []

        cat = self._catalog_iri
        triples.append({"subject": cat, "predicate": f"{RDF}t", "object_iri": True, "object": f"{DCAT}Catalog"})
        triples.append({"subject": cat, "predicate": f"{DCTERMS}title", "object": self.title, "datatype": "http://www.w3.org/2001/XMLSchema#string"})
        triples.append({"subject": cat, "predicate": f"{DCTERMS}description", "object": self.description, "datatype": "http://www.w3.org/2001/XMLSchema#string"})
        triples.append({"subject": cat, "predicate": f"{DCTERMS}issued", "object": self._generated_at, "datatype": "http://www.w3.org/2001/XMLSchema#dateTime"})

        if self.publisher:
            pub_iri = f"{self.namespace}/publisher"
            triples.append({"subject": pub_iri, "predicate": f"{RDF}t", "object_iri": True, "object": f"{FOAF}Organization"})
            triples.append({"subject": pub_iri, "predicate": f"{FOAF}name", "object": self.publisher, "datatype": "http://www.w3.org/2001/XMLSchema#string"})
            if self.publisher_url:
                triples.append({"subject": pub_iri, "predicate": f"{FOAF}homepage", "object_iri": True, "object": self.publisher_url})
            triples.append({"subject": cat, "predicate": f"{DCTERMS}publisher", "object_iri": True, "object": pub_iri})

        if self.theme:
            triples.append({"subject": cat, "predicate": f"{DCAT}theme", "object": self.theme, "datatype": "http://www.w3.org/2001/XMLSchema#string"})

        for ds in self._datasets:
            ds_iri = ds["iri"]
            triples.append({"subject": ds_iri, "predicate": f"{RDF}t", "object_iri": True, "object": f"{DCAT}Dataset"})
            triples.append({"subject": cat, "predicate": f"{DCAT}dataset", "object_iri": True, "object": ds_iri})
            triples.append({"subject": ds_iri, "predicate": f"{DCTERMS}title", "object": ds["name"], "datatype": "http://www.w3.org/2001/XMLSchema#string"})
            if ds["description"]:
                triples.append({"subject": ds_iri, "predicate": f"{DCTERMS}description", "object": ds["description"], "datatype": "http://www.w3.org/2001/XMLSchema#string"})

            dist_iri = f"{ds_iri}/distribution"
            triples.append({"subject": dist_iri, "predicate": f"{RDF}t", "object_iri": True, "object": f"{DCAT}Distribution"})
            triples.append({"subject": ds_iri, "predicate": f"{DCAT}distribution", "object_iri": True, "object": dist_iri})
            triples.append({"subject": dist_iri, "predicate": f"{DCAT}mediaType", "object": f"application/{ds['distribution_format']}", "datatype": "http://www.w3.org/2001/XMLSchema#string"})

            if ds.get("source_path"):
                triples.append({"subject": dist_iri, "predicate": f"{DCAT}accessURL", "object_iri": True, "object": ds["source_path"]})

            if ds.get("entity_type"):
                triples.append({"subject": ds_iri, "predicate": f"{DCTERMS}type", "object": ds["entity_type"], "datatype": "http://www.w3.org/2001/XMLSchema#string"})

        return triples

    def to_ttl(self) -> str:
        triples = self.generate_triples()
        lines = [
            "@prefix dcat: <http://www.w3.org/ns/dcat#> .",
            "@prefix dcterms: <http://purl.org/dc/terms/> .",
            "@prefix dct: <http://purl.org/dc/terms/> .",
            "@prefix foaf: <http://xmlns.com/foaf/0.1/> .",
            "@prefix prov: <http://www.w3.org/ns/prov#> .",
            "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
            "",
        ]
        for t in triples:
            subj = f"<{t['subject']}>"
            pred = f"<{t['predicate']}>"
            if t.get("object_iri"):
                obj = f"<{t['object']}>"
            else:
                escaped = str(t.get("object", "")).replace("\\", "\\\\").replace('"', '\\"')
                dt = t.get("datatype", "http://www.w3.org/2001/XMLSchema#string")
                obj = f'"{escaped}"^^<{dt}>'
            lines.append(f"{subj} {pred} {obj} .")
        return "\n".join(lines)


RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
