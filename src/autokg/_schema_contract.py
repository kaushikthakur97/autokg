from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_SCHEMA_VERSION = "1.0.0"

CONFIG_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://autokg.ai/schemas/autokg.v1.schema.json",
    "title": "autokg v1 project configuration",
    "type": "object",
    "required": ["project", "tables"],
    "additionalProperties": True,
    "properties": {
        "project": {
            "type": "object",
            "required": ["name", "namespace"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "namespace": {"type": "string", "pattern": "^https?://"},
                "output_dir": {"type": "string", "default": "gold"},
                "strict": {"type": "boolean", "default": True},
                "fail_on_invalid_fk": {"type": "boolean", "default": True},
                "fail_on_missing_pk": {"type": "boolean", "default": True},
                "fail_on_duplicate_pk": {"type": "boolean", "default": True},
                "incremental": {"type": "boolean", "default": False},
            },
        },
        "tables": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["name", "source", "entity", "primary_key"],
                "properties": {
                    "name": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"},
                    "source": {"type": ["string", "object"]},
                    "format": {"type": "string"},
                    "entity": {"type": "string", "minLength": 1},
                    "primary_key": {"type": "string", "minLength": 1},
                    "columns": {
                        "type": "object",
                        "additionalProperties": {
                            "type": ["object", "string", "null"],
                            "properties": {
                                "property": {"type": "string"},
                                "required": {"type": "boolean"},
                                "type": {"type": "string"},
                                "pii": {"type": "boolean"},
                                "pii_type": {"type": "string"},
                                "mask": {"enum": ["none", "hash", "partial", "redact", "drop", "tokenize"]},
                            },
                        },
                    },
                },
            },
        },
        "relationships": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "from", "to", "predicate"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "from": {"type": "object", "required": ["table", "column"], "properties": {"table": {"type": "string"}, "column": {"type": "string"}}},
                    "to": {"type": "object", "required": ["table", "column"], "properties": {"table": {"type": "string"}, "column": {"type": "string"}}},
                    "predicate": {"type": "string"},
                    "inverse_predicate": {"type": "string"},
                    "cardinality": {"enum": ["one_to_one", "one_to_many", "many_to_one", "many_to_many"]},
                    "required": {"type": "boolean"},
                    "declared_by": {"type": "string"},
                    "ticket": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
        },
        "outputs": {"type": "object"},
        "store": {"type": "object"},
        "security": {"type": "object"},
        "llm": {"type": "object"},
    },
}


def export_config_schema(path: str | Path | None = None) -> dict[str, Any]:
    if path:
        Path(path).write_text(json.dumps(CONFIG_JSON_SCHEMA, indent=2), encoding="utf-8")
    return CONFIG_JSON_SCHEMA


def structural_config_lint(config: dict[str, Any]) -> list[dict[str, str]]:
    """Small zero-dependency JSON-schema-like lint for the most important errors.

    Full JSON Schema is exported for IDEs/CI. This function avoids adding jsonschema as
    a core runtime dependency.
    """
    issues: list[dict[str, str]] = []
    if "project" not in config:
        issues.append({"path": "project", "message": "project section is required"})
    if "tables" not in config or not config.get("tables"):
        issues.append({"path": "tables", "message": "at least one table is required"})
    names: set[str] = set()
    for i, t in enumerate(config.get("tables", []) or []):
        for key in ("name", "source", "entity", "primary_key"):
            if not t.get(key):
                issues.append({"path": f"tables[{i}].{key}", "message": f"{key} is required"})
        if t.get("name") in names:
            issues.append({"path": f"tables[{i}].name", "message": f"duplicate table name: {t.get('name')}"})
        names.add(t.get("name"))
    for i, r in enumerate(config.get("relationships", []) or []):
        for key in ("name", "predicate"):
            if not r.get(key):
                issues.append({"path": f"relationships[{i}].{key}", "message": f"{key} is required"})
        if not r.get("from") or not r.get("from", {}).get("table") or not r.get("from", {}).get("column"):
            issues.append({"path": f"relationships[{i}].from", "message": "from.table and from.column are required"})
        if not r.get("to") or not r.get("to", {}).get("table") or not r.get("to", {}).get("column"):
            issues.append({"path": f"relationships[{i}].to", "message": "to.table and to.column are required"})
    return issues
