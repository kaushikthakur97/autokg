from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AccessPolicy:
    role: str
    allow_entities: list[str] = field(default_factory=list)
    deny_entities: list[str] = field(default_factory=list)
    allow_properties: list[str] = field(default_factory=list)
    deny_properties: list[str] = field(default_factory=list)
    mask_properties: list[str] = field(default_factory=list)
    max_rows: int | None = None


class PolicyEngine:
    def __init__(self, policies: list[AccessPolicy] | None = None):
        self.policies = {p.role: p for p in (policies or [])}

    @classmethod
    def from_file(cls, path: str | Path | None) -> "PolicyEngine":
        if not path or not Path(path).exists():
            return cls([])
        p = Path(path)
        if p.suffix.lower() == ".json":
            raw = json.loads(p.read_text(encoding="utf-8"))
        else:
            import yaml
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls.from_config(raw)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "PolicyEngine":
        raw_policies = ((config or {}).get("security") or {}).get("policies") or (config or {}).get("policies") or []
        policies = [AccessPolicy(**p) for p in raw_policies]
        return cls(policies)

    def policy_for(self, role: str | None) -> AccessPolicy:
        return self.policies.get(role or "default") or self.policies.get("default") or AccessPolicy(role=role or "default")

    def filter_schema(self, schema: dict[str, Any], role: str | None) -> dict[str, Any]:
        policy = self.policy_for(role)
        tables = []
        for t in schema.get("tables", []):
            ent = t.get("entity")
            if policy.allow_entities and ent not in policy.allow_entities:
                continue
            if ent in policy.deny_entities:
                continue
            tt = dict(t)
            if policy.deny_properties:
                tt["columns"] = [c for c in (tt.get("columns") or []) if c not in policy.deny_properties]
            tables.append(tt)
        out = dict(schema)
        out["tables"] = tables
        out["access_role"] = policy.role
        return out

    def filter_rows(self, rows: list[dict[str, Any]], role: str | None) -> list[dict[str, Any]]:
        policy = self.policy_for(role)
        out = []
        for row in rows[: policy.max_rows or len(rows)]:
            rr = {}
            for k, v in row.items():
                sv = str(v)
                if any(p in k or p in sv for p in policy.deny_properties):
                    continue
                if any(p in k or p in sv for p in policy.mask_properties):
                    rr[k] = "[MASKED]"
                else:
                    rr[k] = v
            out.append(rr)
        return out


def sample_policy_yaml() -> str:
    return """security:
  policies:
    - role: default
      deny_properties: []
      mask_properties: []
      max_rows: 500
    - role: analyst
      deny_properties: [schema:email, schema:telephone]
      mask_properties: [email, phone]
      max_rows: 200
    - role: restricted
      allow_entities: [Customer, Order]
      deny_properties: [email, phone, ssn]
      max_rows: 50
"""
