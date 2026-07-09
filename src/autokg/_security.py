from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class QueryPolicy:
    read_only: bool = True
    max_rows: int = 500
    max_query_chars: int = 20000
    require_limit: bool = True
    allow_service: bool = False
    denied_predicates: list[str] = field(default_factory=list)
    denied_entities: list[str] = field(default_factory=list)
    role: str = "default"

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "QueryPolicy":
        sec = (config or {}).get("security") or {}
        q = sec.get("query") or sec
        return cls(
            read_only=bool(q.get("read_only", True)),
            max_rows=int(q.get("max_rows", 500)),
            max_query_chars=int(q.get("max_query_chars", 20000)),
            require_limit=bool(q.get("require_limit", True)),
            allow_service=bool(q.get("allow_service", False)),
            denied_predicates=list(q.get("denied_predicates", [])),
            denied_entities=list(q.get("denied_entities", [])),
            role=str(q.get("role", "default")),
        )

    def check_sparql(self, sparql: str) -> list[str]:
        errors: list[str] = []
        if len(sparql) > self.max_query_chars:
            errors.append(f"query exceeds max_query_chars={self.max_query_chars}")
        if self.read_only and re.search(r"\b(INSERT|DELETE|LOAD|CLEAR|CREATE|DROP|MOVE|COPY|ADD)\b", sparql, re.I):
            errors.append("query policy is read-only")
        if not self.allow_service and re.search(r"\bSERVICE\b", sparql, re.I):
            errors.append("SERVICE is disabled by query policy")
        for pred in self.denied_predicates:
            if pred and pred in sparql:
                errors.append(f"predicate is denied by policy: {pred}")
        for ent in self.denied_entities:
            if ent and ent in sparql:
                errors.append(f"entity is denied by policy: {ent}")
        return errors


def redact_rows(rows: list[dict[str, Any]], denied_keys: list[str] | None = None) -> list[dict[str, Any]]:
    denied = [d.lower() for d in (denied_keys or [])]
    out = []
    for row in rows:
        r = {}
        for k, v in row.items():
            if any(d in k.lower() or d in str(v).lower() for d in denied):
                r[k] = "[REDACTED]"
            else:
                r[k] = v
        out.append(r)
    return out
