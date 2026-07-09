from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ._v1 import load_v1_config, generate_ontology_ttl


def generate_shacl_ttl(config: dict[str, Any]) -> str:
    ns = config["project"]["namespace"].rstrip("/#") + "#"
    lines = [
        f"@prefix ex: <{ns}> .",
        "@prefix sh: <http://www.w3.org/ns/shacl#> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix schema: <https://schema.org/> .",
        "",
    ]
    table_by_name = {t["name"]: t for t in config.get("tables", [])}
    for table in config.get("tables", []):
        entity = _safe(table["entity"])
        lines += [f"ex:{entity}Shape a sh:NodeShape ;", f"  sh:targetClass ex:{entity} ;"]
        props: list[str] = []
        pk = table.get("primary_key")
        for col, spec in (table.get("columns") or {}).items():
            pred = _qname(spec.get("property") or f"ex:{_safe(col)}")
            min_count = 1 if spec.get("required") or col == pk else 0
            dtype = _xsd(spec.get("type"))
            props.append(f"  sh:property [ sh:path {pred} ; sh:minCount {min_count} ; sh:datatype {dtype} ]")
        # relationships sourced from this table
        for rel in config.get("relationships", []):
            if rel.get("from_table") == table["name"]:
                target = table_by_name.get(rel.get("to_table"), {}).get("entity", rel.get("to_table"))
                pred = _qname(rel.get("predicate") or f"ex:{_safe(rel['name'])}")
                min_count = 1 if rel.get("required") else 0
                props.append(f"  sh:property [ sh:path {pred} ; sh:minCount {min_count} ; sh:class ex:{_safe(target)} ]")
        if props:
            lines.append(" ;\n".join(props) + " .\n")
        else:
            lines[-1] = lines[-1].rstrip(" ;") + " .\n"
    return "\n".join(lines)


def write_ontology_bundle(config_path: str | Path, output_dir: str | Path | None = None) -> dict[str, str]:
    config = load_v1_config(config_path)
    out = Path(output_dir or config["project"].get("output_dir", "gold"))
    if not out.is_absolute():
        out = Path(config_path).parent / out
    out.mkdir(parents=True, exist_ok=True)
    ontology = out / "ontology.ttl"
    shapes = out / "shapes.ttl"
    ontology.write_text(generate_ontology_ttl(config), encoding="utf-8")
    shapes.write_text(generate_shacl_ttl(config), encoding="utf-8")
    return {"ontology": str(ontology), "shapes": str(shapes)}


def diff_ontology(left: str | Path, right: str | Path) -> dict[str, Any]:
    a = set(Path(left).read_text(encoding="utf-8").splitlines())
    b = set(Path(right).read_text(encoding="utf-8").splitlines())
    return {"added": sorted(b - a), "removed": sorted(a - b), "added_count": len(b - a), "removed_count": len(a - b)}


def _safe(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", str(value))
    return "_" + s if s and s[0].isdigit() else s


def _qname(value: str) -> str:
    if not value:
        return "ex:unknown"
    if value.startswith("http://") or value.startswith("https://"):
        return f"<{value}>"
    if ":" in value:
        return value
    return "ex:" + _safe(value)


def _xsd(dtype: str | None) -> str:
    if not dtype:
        return "xsd:string"
    d = dtype.lower()
    if d in ("int", "integer", "long"):
        return "xsd:integer"
    if d in ("float", "double", "decimal", "number"):
        return "xsd:decimal"
    if d in ("bool", "boolean"):
        return "xsd:boolean"
    if d in ("date",):
        return "xsd:date"
    if d in ("datetime", "timestamp"):
        return "xsd:dateTime"
    return "xsd:string"
