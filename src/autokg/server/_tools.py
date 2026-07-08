from __future__ import annotations

import json
import logging
from typing import Any, Callable

import polars as pl

_logger = logging.getLogger(__name__)

TOOL_REGISTRY: dict[str, dict] = {}


def register_tool(name: str, description: str, input_schema: dict, handler: Callable):
    TOOL_REGISTRY[name] = {
        "name": name,
        "description": description,
        "input_schema": input_schema,
        "handler": handler,
    }


def _search_entities(kg, context, args: dict) -> dict:
    query = args.get("query", "")
    entity_type = args.get("entity_type")
    limit = args.get("limit", 10)
    triples = kg._mapper.get_triples()
    matches: list[dict] = []
    q_lower = query.lower()
    for t in triples:
        subj = str(t.get("subject", ""))
        obj = str(t.get("object", ""))
        pred = str(t.get("predicate", ""))
        if q_lower in subj.lower() or q_lower in obj.lower() or q_lower in pred.lower():
            matches.append({"subject": subj, "predicate": pred, "object": obj, "is_iri": t.get("is_iri") or t.get("object_iri")})
        if len(matches) >= limit * 3:
            break
    seen: set[str] = set()
    unique: list[dict] = []
    for m in matches:
        key = m["subject"]
        if entity_type and entity_type.lower() not in key.lower() and entity_type.lower() not in str(m).lower():
            continue
        if key not in seen:
            seen.add(key)
            unique.append(m)
            if len(unique) >= limit:
                break
    result_count = len(unique)
    context.record(f"search_entities: {query}", unique, focus=unique[0]["subject"] if unique else None)
    return {"query": query, "results": unique, "total": result_count}


def _get_entity(kg, context, args: dict) -> dict:
    iri = args.get("iri", "")
    triples = kg._mapper.get_triples()
    facts: dict[str, list[str]] = {}
    for t in triples:
        if t.get("subject", "") == iri:
            pred = t.get("predicate", "")
            obj = str(t.get("object", ""))
            if pred not in facts:
                facts[pred] = []
            facts[pred].append(obj)
    context.record(f"get_entity: {iri}", facts.get("iri", []), focus=iri)
    return {"iri": iri, "facts": facts, "property_count": len(facts)}


def _get_related(kg, context, args: dict) -> dict:
    iri = args.get("iri", "")
    relationship = args.get("relationship")
    depth = args.get("depth", 1)
    triples = kg._mapper.get_triples()
    related: list[dict] = []
    for t in triples:
        if t.get("subject") == iri and t.get("is_iri") or t.get("object_iri"):
            if relationship and relationship.lower() not in t.get("predicate", "").lower():
                continue
            related.append({"subject": t["subject"], "predicate": t["predicate"], "object": t["object"], "edge": "outgoing"})
        elif t.get("is_iri") or t.get("object_iri"):
            if str(t.get("object", "")) == iri:
                if relationship and relationship.lower() not in t.get("predicate", "").lower():
                    continue
                related.append({"subject": t["subject"], "predicate": t["predicate"], "object": t["object"], "edge": "incoming"})
    context.record(f"get_related: {iri}", related[:10], focus=iri)
    return {"iri": iri, "related_count": len(related), "depth": depth, "related": related[:20]}


def _query_graph(kg, context, args: dict) -> dict:
    sparql = args.get("sparql", "")
    try:
        result = kg.query(sparql)
        if result is not None and result.height > 0:
            rows = [dict(zip(result.columns, row)) for row in result.iter_rows()]
            context.record(f"query: {sparql[:100]}", rows[:20])
            return {"sparql": sparql, "result_count": len(rows), "rows": rows[:50]}
        return {"sparql": sparql, "result_count": 0, "rows": []}
    except Exception as e:
        return {"error": str(e), "sparql": sparql}


def _ask_question(kg, context, args: dict) -> dict:
    question = args.get("question", "")
    from autokg._agent import GraphAgent
    agent = GraphAgent(kg, provider="openai", model="gpt-4o")
    try:
        augmented = context.augment_question(question)
        result = agent.ask(augmented)
        rows = []
        if result is not None and result.height > 0:
            rows = [dict(zip(result.columns, row)) for row in result.iter_rows()]
        context.record(question, rows[:20])
        return {"question": question, "augmented": augmented != question, "result_count": len(rows), "rows": rows[:50]}
    except Exception as e:
        return {"error": str(e), "question": question}


def _get_schema(kg, context, args: dict) -> dict:
    entities: list[dict] = []
    if hasattr(kg, "_tables"):
        for name, info in kg._tables.items():
            df = info.get("df")
            if df is not None:
                entities.append({
                    "table": name,
                    "entity_type": info.get("entity_type", name),
                    "columns": list(df.columns),
                    "row_count": df.height,
                    "pk": info.get("pk_column"),
                })
    return {"entities": entities, "total_entities": len(entities)}


def _get_lineage(kg, context, args: dict) -> dict:
    iri = args.get("iri")
    triples = kg._mapper.get_triples()
    lineage: list[dict] = []
    for t in triples:
        pred = t.get("predicate", "")
        if "prov" in pred.lower() or "derivedFrom" in pred.lower() or "source" in pred.lower():
            if iri is None or t.get("subject") == iri or str(t.get("object", "")) == iri:
                lineage.append(t)
    return {"iri": iri, "lineage_triples": lineage, "count": len(lineage)}


def _get_metrics(kg, context, args: dict) -> dict:
    entity_type = args.get("entity_type")
    triples = kg._mapper.get_triples()
    metric_props: set[str] = set()
    for t in triples:
        pred = t.get("predicate", "")
        obj = t.get("object", "")
        if not t.get("is_iri") and not t.get("object_iri"):
            try:
                float(str(obj))
                if entity_type is None or entity_type.lower() in t.get("subject", "").lower():
                    metric_props.add(pred)
            except (ValueError, TypeError):
                pass
    return {"entity_type": entity_type, "metrics": sorted(metric_props)[:50], "count": len(metric_props)}


def _semantic_search(kg, context, args: dict) -> dict:
    query = args.get("query", "")
    top_k = args.get("top_k", 10)
    triples = kg._mapper.get_triples()
    matches: list[dict] = []
    q_lower = query.lower()
    q_words = q_lower.split()
    for t in triples:
        subj = str(t.get("subject", "")).lower()
        obj = str(t.get("object", "")).lower()
        score = 0
        for word in q_words:
            if word in subj:
                score += 1
            if word in obj:
                score += 1
        if score > 0:
            matches.append({"subject": t.get("subject"), "object": t.get("object"), "predicate": t.get("predicate"), "score": score})
    matches.sort(key=lambda x: -x["score"])
    unique_subjects: list[dict] = []
    seen: set[str] = set()
    for m in matches:
        if m["subject"] not in seen:
            seen.add(m["subject"])
            unique_subjects.append(m)
            if len(unique_subjects) >= top_k:
                break
    context.record(f"semantic_search: {query}", unique_subjects)
    return {"query": query, "results": unique_subjects, "total": len(unique_subjects)}


# --- Register all tools ---
register_tool(
    "search_entities", "Find entities by name or keyword in the knowledge graph",
    {"type": "object", "properties": {"query": {"type": "string"}, "entity_type": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]},
    _search_entities,
)
register_tool(
    "get_entity", "Get all facts and properties about a specific entity by its IRI",
    {"type": "object", "properties": {"iri": {"type": "string"}}, "required": ["iri"]},
    _get_entity,
)
register_tool(
    "get_related", "Traverse relationships from an entity to find connected entities",
    {"type": "object", "properties": {"iri": {"type": "string"}, "relationship": {"type": "string"}, "depth": {"type": "integer"}}, "required": ["iri"]},
    _get_related,
)
register_tool(
    "query_graph", "Execute a raw SPARQL query against the knowledge graph",
    {"type": "object", "properties": {"sparql": {"type": "string"}}, "required": ["sparql"]},
    _query_graph,
)
register_tool(
    "ask_question", "Ask a question in natural language and get results from the knowledge graph",
    {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
    _ask_question,
)
register_tool(
    "get_schema", "Get the ontology/schema summary of the knowledge graph — all entity types, columns, and row counts",
    {"type": "object", "properties": {}, "required": []},
    _get_schema,
)
register_tool(
    "get_lineage", "Get data lineage and provenance information for entities in the graph",
    {"type": "object", "properties": {"iri": {"type": "string"}}},
    _get_lineage,
)
register_tool(
    "get_metrics", "Get available numeric metrics and properties that can be aggregated or analyzed",
    {"type": "object", "properties": {"entity_type": {"type": "string"}}},
    _get_metrics,
)
register_tool(
    "semantic_search", "Find entities semantically related to a text query — broader than keyword search",
    {"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}}, "required": ["query"]},
    _semantic_search,
)
