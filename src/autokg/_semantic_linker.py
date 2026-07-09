from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LinkCandidate:
    kind: str
    label: str
    target: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class SemanticLinker:
    """Schema/value linker for NL→SPARQL planning.

    Deterministic first: exact names, aliases, column configs, relationships, and
    optional glossary. This intentionally does not require embeddings/LLMs.
    """

    DEFAULT_ALIASES = {
        "vip": ["VIP", "premium", "high value"],
        "standard": ["standard", "regular"],
        "high": ["high", "high-risk", "risky", "risk high"],
        "open": ["open", "active", "unresolved"],
        "closed": ["closed", "resolved"],
        "customer": ["customer", "customers", "client", "clients", "policyholder", "policyholders"],
        "order": ["order", "orders", "purchase", "purchases", "bought", "buy"],
        "product": ["product", "products", "item", "items"],
        "claim": ["claim", "claims"],
        "policy": ["policy", "policies"],
    }

    def __init__(self, schema_index, glossary_path: str | Path | None = None):
        self.schema = schema_index
        self.glossary = self._load_glossary(glossary_path)
        self.aliases = {**self.DEFAULT_ALIASES, **self.glossary.get("aliases", {})}
        self.value_aliases = self.glossary.get("values", {})

    def link(self, question: str) -> dict[str, list[dict[str, Any]]]:
        q = question.lower()
        candidates: list[LinkCandidate] = []
        for table in self.schema.tables:
            entity = str(table.get("entity", ""))
            table_name = str(table.get("name", ""))
            labels = {entity, table_name, entity.lower(), table_name.lower()}
            labels.update(self.aliases.get(entity.lower(), []))
            labels.update(self.aliases.get(table_name.lower(), []))
            for label in labels:
                if label and self._contains(q, label):
                    candidates.append(LinkCandidate("entity", label, entity, self._score(label), {"table": table_name, "primary_key": table.get("primary_key")}))
            for col in table.get("columns", []) or []:
                if self._contains(q, str(col)):
                    candidates.append(LinkCandidate("column", str(col), str(col), self._score(str(col)), {"table": table_name, "entity": entity}))
            for col, spec in (table.get("column_config") or {}).items():
                prop = spec.get("property") if isinstance(spec, dict) else None
                labels = {col, str(prop or "").split(":")[-1]}
                labels.update(self.aliases.get(col.lower(), []))
                for label in labels:
                    if label and self._contains(q, label):
                        candidates.append(LinkCandidate("property", label, prop or col, self._score(label), {"table": table_name, "entity": entity, "column": col}))
        for rel in self.schema.relationships:
            labels = {rel.get("name", ""), rel.get("predicate", "").split(":")[-1], rel.get("description", "")}
            for label in labels:
                if label and self._contains(q, label):
                    candidates.append(LinkCandidate("relationship", label, rel.get("predicate", rel.get("name")), self._score(label), rel))
        filters = self._link_values(question)
        return {
            "candidates": [c.__dict__ for c in sorted(candidates, key=lambda x: -x.score)],
            "entities": [c.__dict__ for c in candidates if c.kind == "entity"],
            "properties": [c.__dict__ for c in candidates if c.kind in {"property", "column"}],
            "relationships": [c.__dict__ for c in candidates if c.kind == "relationship"],
            "filters": filters,
        }

    def _link_values(self, question: str) -> list[dict[str, Any]]:
        q = question.lower()
        filters: list[dict[str, Any]] = []
        # Generic value aliases: VIP/high/open/closed etc.
        for canonical, labels in self.aliases.items():
            for label in labels:
                if self._contains(q, label):
                    filters.append({"label": label, "canonical": canonical, "value": self._canonical_value(canonical, label), "score": self._score(label)})
                    break
        # Numeric comparisons: above 1000, greater than 1000, under 50
        for op_label, op in [("above", ">"), ("over", ">"), ("greater than", ">"), ("more than", ">"), ("under", "<"), ("below", "<"), ("less than", "<")]:
            m = re.search(rf"\b{re.escape(op_label)}\s+([0-9]+(?:\.[0-9]+)?)", q)
            if m:
                filters.append({"label": op_label, "operator": op, "value": m.group(1), "type": "numeric_comparison"})
        return filters

    def _canonical_value(self, canonical: str, label: str) -> str:
        if canonical == "vip":
            return "VIP"
        if canonical == "high":
            return "High"
        if canonical == "open":
            return "Open"
        if canonical == "closed":
            return "Closed"
        return canonical if canonical else label

    def _contains(self, question_lower: str, label: str) -> bool:
        label = str(label).lower().strip()
        if not label:
            return False
        if len(label) <= 3:
            return re.search(rf"\b{re.escape(label)}\b", question_lower) is not None
        return label in question_lower

    def _score(self, label: str) -> float:
        return min(1.0, max(0.2, len(str(label)) / 20.0))

    def _load_glossary(self, path: str | Path | None) -> dict[str, Any]:
        if not path:
            return {}
        p = Path(path)
        if not p.exists():
            return {}
        if p.suffix.lower() == ".json":
            return json.loads(p.read_text(encoding="utf-8"))
        try:
            import yaml
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
