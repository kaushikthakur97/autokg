from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Optional, Union
from urllib.parse import urlparse

import polars as pl

TURTLE = "turtle"
TTL = "ttl"
JSONLD = "jsonld"
JSON_LD = "json-ld"
NTRIPLES = "ntriples"
NT = "nt"
RDFXML = "rdfxml"
XML = "xml"

PREFIX_MAP: dict[str, str] = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "schema": "https://schema.org/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "dcterms": "http://purl.org/dc/terms/",
    "prov": "http://www.w3.org/ns/prov#",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "ex": "http://example.org/",
}


def serialize_triples(
    triples: list[dict[str, Any]],
    path: Union[str, Path],
    format: str = "turtle",
) -> str:
    path = Path(path)
    fmt = format.lower()
    lines: list[str] = []

    if fmt in (TURTLE, TTL):
        for prefix, uri in PREFIX_MAP.items():
            lines.append(f"@prefix {prefix}: <{uri}> .")
        lines.append("")
        for t in triples:
            subj = _format_term(t.get("subject", ""))
            pred = _format_term(t.get("predicate", ""))
            obj = _format_object(t)
            lines.append(f"{subj} {pred} {obj} .")
            lines.append("")

    elif fmt in (JSONLD, JSON_LD):
        graph = {"@context": PREFIX_MAP, "@graph": triples}
        path.write_text(json.dumps(graph, indent=2, default=str), encoding="utf-8")
        return str(path)

    elif fmt in (NTRIPLES, NT):
        for t in triples:
            subj = f"<{t.get('subject', '')}>"
            pred = f"<{t.get('predicate', '')}>"
            if t.get("is_iri") or t.get("object_iri"):
                obj = f"<{t.get('object', '')}>"
            else:
                escaped = _escape(str(t.get("object", "")))
                dt = t.get("datatype", "")
                if dt:
                    obj = f'"{escaped}"^^<{dt}>'
                else:
                    obj = f'"{escaped}"'
            lines.append(f"{subj} {pred} {obj} .")

    elif fmt in (RDFXML, XML):
        path.write_text(_to_rdfxml(triples, PREFIX_MAP), encoding="utf-8")
        return str(path)

    content = "\n".join(lines)
    path.write_text(content, encoding="utf-8")
    return str(path)


def register_prefix(prefix: str, uri: str):
    PREFIX_MAP[prefix] = uri


def _format_term(value: str) -> str:
    if not value:
        return "<>"
    if value.startswith("http"):
        for prefix, uri in PREFIX_MAP.items():
            if value.startswith(uri):
                local = value[len(uri):]
                if local:
                    return f"{prefix}:{local}"
                return prefix
        return f"<{value}>"
    if ":" in value:
        return value
    return f"<{value}>"


def _format_object(triple: dict) -> str:
    if triple.get("is_iri") or triple.get("object_iri"):
        return _format_term(str(triple.get("object", "")))
    value = str(triple.get("object", ""))
    escaped = _escape(value)
    dt = triple.get("datatype", "")
    lang = triple.get("language", "")
    suffix = ""
    if lang:
        suffix = f"@{lang}"
    elif dt and dt != "http://www.w3.org/2001/XMLSchema#string":
        suffix = f"^^<{dt}>"
    return f'"{escaped}"{suffix}'


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def _to_rdfxml(triples: list[dict], prefixes: dict) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<rdf:RDF')
    for prefix, uri in sorted(prefixes.items()):
        lines.append(f'  xmlns:{prefix}="{uri}"')
    lines.append('>')
    lines.append("")
    for t in triples:
        subj = str(t.get("subject", ""))
        pred = str(t.get("predicate", ""))
        pred_tag = _xml_tag(pred, prefixes)
        lines.append(f'  <rdf:Description rdf:about="{_xml_escape(subj)}">')
        obj = str(t.get("object", ""))
        if t.get("is_iri") or t.get("object_iri"):
            lines.append(f'    <{pred_tag} rdf:resource="{_xml_escape(obj)}"/>')
        else:
            lines.append(f"    <{pred_tag}>{_xml_escape(obj)}</{pred_tag}>")
        lines.append("  </rdf:Description>")
    lines.append("</rdf:RDF>")
    return "\n".join(lines)


def _xml_tag(value: str, prefixes: dict) -> str:
    if value.startswith("http"):
        for prefix, uri in prefixes.items():
            if value.startswith(uri):
                local = value[len(uri):]
                return f"{prefix}:{local}" if local else prefix
        parsed = urlparse(value)
        path = (parsed.path or parsed.fragment or "").strip("/#")
        parts = [p for p in path.split("/") if p]
        local = parts[-1] if parts else value.rsplit("/", 1)[-1].split("#", 1)[-1]
        return f"ns_{local}"
    if ":" in value:
        return value
    return f"ex:{value}"


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def serialize_maplib_model(model: Any, path: Union[str, Path], format: str = "turtle") -> str:
    path = Path(path)
    fmt = format.lower()
    if hasattr(model, "write_triples"):
        model.write_triples(str(path), fmt)
        return str(path)
    raise RuntimeError("Cannot serialize: model does not support serialization")


def push_to_sparql_endpoint(
    triples: list[dict[str, Any]],
    endpoint_url: str,
    graph_uri: Optional[str] = None,
    auth: Optional[tuple[str, str]] = None,
    method: str = "POST",
) -> bool:
    try:
        import httpx
    except ImportError:
        raise ImportError("httpx required for SPARQL endpoint push. Install with: pip install httpx")

    tmp = Path(tempfile.gettempdir()) / "autokg_push.nt"
    serialize_triples(triples, tmp, format="ntriples")
    data = tmp.read_text(encoding="utf-8")

    headers = {"Content-Type": "application/sparql-update"}
    graph_clause = f"GRAPH <{graph_uri}> {{" if graph_uri else ""
    graph_close = "}" if graph_uri else ""
    update_query = f"INSERT DATA {{ {graph_clause} {data} {graph_close} }}"

    kwargs = {}
    if auth:
        kwargs["auth"] = auth

    client = httpx.Client(timeout=60)
    try:
        if method.upper() == "POST":
            response = client.post(endpoint_url, content=update_query, headers=headers, **kwargs)
        else:
            response = client.put(endpoint_url, content=data, headers={"Content-Type": "application/n-triples"}, **kwargs)
        tmp.unlink(missing_ok=True)
        return 200 <= response.status_code < 300
    finally:
        client.close()


def write_triples(
    triples: list[dict[str, Any]],
    path: Union[str, Path],
    format: str = "turtle",
) -> str:
    return serialize_triples(triples, path, format)


def write_catalog(triples: list[dict[str, Any]], path: Union[str, Path], format: str = "turtle") -> str:
    return serialize_triples(triples, path, format)
