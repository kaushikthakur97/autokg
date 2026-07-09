from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ._semantic_linker import SemanticLinker


@dataclass
class QueryPlan:
    question: str
    entities: list[str] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    filters: list[dict[str, Any]] = field(default_factory=list)
    aggregations: list[str] = field(default_factory=list)
    order_by: str | None = None
    limit: int = 100
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)


class QueryPlanner:
    def __init__(self, schema_index, glossary_path: str | None = None):
        self.schema = schema_index
        self.linker = SemanticLinker(schema_index, glossary_path=glossary_path)

    def plan(self, question: str) -> QueryPlan:
        links = self.linker.link(question)
        entities = []
        for e in links["entities"]:
            target = e.get("target")
            if target and target not in entities:
                entities.append(target)
        if not entities:
            # fallback: first entity if question is broad
            if self.schema.tables:
                entities.append(self.schema.tables[0].get("entity"))
        rels = self._relationship_paths(entities)
        aggs = self._aggregations(question)
        limit = self._limit(question)
        conf = min(0.95, 0.35 + 0.15 * len(entities) + 0.1 * len(rels) + 0.05 * len(links["filters"]))
        return QueryPlan(question=question, entities=entities, relationships=rels, filters=links["filters"], aggregations=aggs, limit=limit, confidence=conf, notes=[f"linked {len(links['candidates'])} schema term(s)"])

    def to_sparql(self, plan: QueryPlan) -> str | None:
        if not plan.entities:
            return None
        ns = self.schema.namespace.rstrip("/#")
        prefixes = f"PREFIX ex: <{ns}#>\nPREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\nPREFIX schema: <https://schema.org/>\n"
        if plan.aggregations and "count" in plan.aggregations:
            select = "SELECT (COUNT(DISTINCT ?entity) AS ?count)"
        else:
            select = "SELECT DISTINCT ?entity ?p ?o"
        lines = [prefixes + select + " WHERE {"]
        primary = _safe(plan.entities[0])
        lines.append(f"  ?entity rdf:type ex:{primary} .")
        # Add traversals when query mentions multiple entities and a declared path exists.
        var_for = {plan.entities[0]: "?entity"}
        for i, rel in enumerate(plan.relationships):
            src_ent = rel.get("source_entity")
            tgt_ent = rel.get("target_entity")
            s_var = var_for.get(src_ent) or f"?e{i}s"
            o_var = var_for.get(tgt_ent) or f"?e{i}o"
            var_for[src_ent] = s_var
            var_for[tgt_ent] = o_var
            pred = _predicate_qname(rel.get("predicate"))
            lines.append(f"  {s_var} {pred} {o_var} .")
            lines.append(f"  {o_var} rdf:type ex:{_safe(tgt_ent)} .")
        # Basic filters mapped to common configured predicates.
        filter_lines = self._filter_lines(plan, var_for)
        lines.extend(filter_lines)
        if not plan.aggregations:
            lines.append("  ?entity ?p ?o .")
        lines.append("}")
        lines.append(f"LIMIT {plan.limit}")
        return "\n".join(lines)

    def _filter_lines(self, plan: QueryPlan, var_for: dict[str, str]) -> list[str]:
        lines: list[str] = []
        q = plan.question.lower()
        all_cols = []
        for t in self.schema.tables:
            for col, spec in (t.get("column_config") or {}).items():
                prop = spec.get("property") if isinstance(spec, dict) else None
                all_cols.append((t.get("entity"), col.lower(), prop or f"ex:{col}"))
        def find_prop(names):
            for ent, col, prop in all_cols:
                if any(n in col or n in prop.lower() for n in names):
                    return ent, _predicate_qname(prop)
            return None, None
        if "vip" in q or "premium" in q:
            ent, prop = find_prop(["segment", "tier", "type"])
            if prop:
                var = var_for.get(ent, "?entity")
                lines.append(f"  {var} {prop} ?segmentValue .")
                lines.append('  FILTER(LCASE(STR(?segmentValue)) = "vip")')
        if "high-risk" in q or "high risk" in q or "risky" in q:
            ent, prop = find_prop(["risk"])
            if prop:
                var = var_for.get(ent, "?entity")
                lines.append(f"  {var} {prop} ?riskValue .")
                lines.append('  FILTER(CONTAINS(LCASE(STR(?riskValue)), "high"))')
        # Numeric comparisons attach to amount/price if present.
        for f in plan.filters:
            if f.get("type") == "numeric_comparison":
                ent, prop = find_prop(["amount", "price", "premium", "paid", "claim"])
                if prop:
                    var = var_for.get(ent, "?entity")
                    lines.append(f"  {var} {prop} ?numericValue .")
                    lines.append(f"  FILTER(xsd:decimal(?numericValue) {f['operator']} {f['value']})")
        return lines

    def _relationship_paths(self, entities: list[str]) -> list[dict[str, Any]]:
        if len(entities) < 2:
            return []
        table_entity = {t.get("name"): t.get("entity") for t in self.schema.tables}
        edges = []
        for r in self.schema.relationships:
            se = table_entity.get(r.get("from_table"), r.get("from_table"))
            te = table_entity.get(r.get("to_table"), r.get("to_table"))
            rr = dict(r)
            rr["source_entity"] = se
            rr["target_entity"] = te
            edges.append(rr)
            if r.get("inverse_predicate"):
                inv = dict(r)
                inv["predicate"] = r.get("inverse_predicate")
                inv["source_entity"] = te
                inv["target_entity"] = se
                edges.append(inv)
        chosen = []
        current = entities[0]
        for target in entities[1:]:
            path = self._bfs(current, target, edges)
            if path:
                chosen.extend(path)
                current = target
        return chosen

    def _bfs(self, start: str, target: str, edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
        q = deque([(start, [])])
        seen = {start}
        while q:
            node, path = q.popleft()
            if node == target:
                return path
            for e in edges:
                if e.get("source_entity") == node and e.get("target_entity") not in seen:
                    seen.add(e.get("target_entity"))
                    q.append((e.get("target_entity"), path + [e]))
        return []

    def _aggregations(self, question: str) -> list[str]:
        q = question.lower()
        out = []
        if any(w in q for w in ["count", "how many", "number of"]):
            out.append("count")
        return out

    def _limit(self, question: str) -> int:
        m = re.search(r"\blimit\s+(\d+)\b", question.lower())
        return min(1000, int(m.group(1))) if m else 100


def _safe(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", str(value))
    return "_" + s if s and s[0].isdigit() else s


def _predicate_qname(pred: str | None) -> str:
    if not pred:
        return "ex:relatedTo"
    if pred.startswith("http://") or pred.startswith("https://"):
        return f"<{pred}>"
    if ":" in pred:
        return pred
    return "ex:" + _safe(pred)
