from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from ._connectors import read_table
from ._core import KnowledgeGraph


SUPPORTED_OUTPUT_FORMATS = {"turtle", "ttl", "jsonld", "ntriples", "nt", "rdfxml", "rdf"}


class V1ConfigError(ValueError):
    pass


@dataclass
class V1Column:
    name: str
    property: str | None = None
    required: bool = False
    type: str | None = None
    pii: bool = False
    pii_type: str | None = None
    mask: str | None = None


@dataclass
class V1Table:
    name: str
    source: str
    entity: str
    primary_key: str
    format: str | None = None
    columns: dict[str, V1Column] | None = None


@dataclass
class V1Relationship:
    name: str
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    predicate: str
    inverse_predicate: str | None = None
    cardinality: str = "many_to_one"
    required: bool = False
    declared_by: str = "unknown"
    ticket: str = ""
    description: str = ""


@dataclass
class V1Project:
    name: str
    namespace: str
    output_dir: str = "gold"
    strict: bool = True
    fail_on_invalid_fk: bool = True
    fail_on_missing_pk: bool = True
    fail_on_duplicate_pk: bool = True
    incremental: bool = False


@dataclass
class V1BuildResult:
    build_id: str
    output_dir: str
    triple_count: int
    table_count: int
    relationship_count: int
    output_files: list[str]
    duration_seconds: float
    validation_status: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_v1_config(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise V1ConfigError(f"Config file not found: {path}")
    text = _interpolate_env(path.read_text(encoding="utf-8"))
    if path.suffix.lower() == ".json":
        raw = json.loads(text)
    else:
        try:
            import yaml
        except ImportError as e:  # pragma: no cover
            raise V1ConfigError("PyYAML is required for YAML config. Install with: pip install pyyaml") from e
        raw = yaml.safe_load(text) or {}
    return normalize_config(raw, base_dir=path.parent)


def _interpolate_env(text: str) -> str:
    # ${VAR} interpolation; leaves unknown vars unchanged for debuggability.
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return os.environ.get(key, match.group(0))
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", repl, text)


def normalize_config(raw: dict[str, Any], base_dir: Path | None = None) -> dict[str, Any]:
    """Normalize both the v1 schema and legacy `sources` schema into one shape."""
    base_dir = base_dir or Path.cwd()
    raw = raw or {}

    if "project" in raw or "tables" in raw:
        project_raw = raw.get("project", {}) or {}
        project = {
            "name": project_raw.get("name") or raw.get("name") or "autokg-project",
            "namespace": project_raw.get("namespace") or raw.get("namespace") or "https://example.com/kg",
            "output_dir": str(project_raw.get("output_dir") or raw.get("output_dir") or "gold"),
            "strict": bool(project_raw.get("strict", raw.get("strict", True))),
            "fail_on_invalid_fk": bool(project_raw.get("fail_on_invalid_fk", raw.get("fail_on_invalid_fk", True))),
            "fail_on_missing_pk": bool(project_raw.get("fail_on_missing_pk", raw.get("fail_on_missing_pk", True))),
            "fail_on_duplicate_pk": bool(project_raw.get("fail_on_duplicate_pk", raw.get("fail_on_duplicate_pk", True))),
            "incremental": bool(project_raw.get("incremental", raw.get("incremental", False))),
        }
        tables_raw = raw.get("tables", []) or []
    else:
        project = {
            "name": raw.get("name") or "autokg-project",
            "namespace": raw.get("namespace") or "https://example.com/kg",
            "output_dir": raw.get("output_dir") or "gold",
            "strict": bool(raw.get("strict", True)),
            "fail_on_invalid_fk": True,
            "fail_on_missing_pk": True,
            "fail_on_duplicate_pk": True,
            "incremental": bool(raw.get("incremental", False)),
        }
        if raw.get("store"):
            project["store"] = raw.get("store")
        tables_raw = []
        for src in raw.get("sources", []) or []:
            tables_raw.append({
                "name": src.get("name") or Path(str(src.get("path") or src.get("source") or src.get("table", "table"))).stem,
                "source": src.get("path") or src.get("source") or src.get("table"),
                "format": src.get("format"),
                "entity": src.get("entity") or src.get("entity_type"),
                "primary_key": src.get("id_column") or src.get("primary_key"),
                "columns": _legacy_property_map_to_columns(src.get("property_map"), src.get("pii_policy")),
            })

    tables: list[dict[str, Any]] = []
    for table in tables_raw:
        src = table.get("source") or table.get("path") or table.get("table")
        if src and not _looks_remote(str(src)):
            src_path = Path(str(src))
            if not src_path.is_absolute():
                src = str((base_dir / src_path).resolve())
        columns = _normalize_columns(table.get("columns") or table.get("property_map") or {})
        tables.append({
            "name": table.get("name") or Path(str(src)).stem,
            "source": src,
            "format": table.get("format"),
            "entity": table.get("entity") or table.get("entity_type") or _pascal(table.get("name") or Path(str(src)).stem),
            "primary_key": table.get("primary_key") or table.get("id_column"),
            "columns": columns,
        })

    rels: list[dict[str, Any]] = []
    for rel in raw.get("relationships", []) or []:
        if "from" in rel and "to" in rel:
            from_ = rel.get("from") or {}
            to = rel.get("to") or {}
            rels.append({
                "name": rel.get("name") or f"{from_.get('table')}_{from_.get('column')}_to_{to.get('table')}",
                "from_table": from_.get("table"),
                "from_column": from_.get("column"),
                "to_table": to.get("table"),
                "to_column": to.get("column"),
                "predicate": rel.get("predicate") or f"ex:{rel.get('name') or 'relatedTo'}",
                "inverse_predicate": rel.get("inverse_predicate"),
                "cardinality": rel.get("cardinality", "many_to_one"),
                "required": bool(rel.get("required", False)),
                "declared_by": rel.get("declared_by") or rel.get("actor") or "unknown",
                "ticket": rel.get("ticket") or rel.get("ticket_ref") or "",
                "description": rel.get("description") or rel.get("justification") or "",
            })
        else:
            rels.append({
                "name": rel.get("name") or f"{rel.get('from_table') or rel.get('source_table')}_{rel.get('from_column') or rel.get('source_column')}_to_{rel.get('to_table') or rel.get('target_table')}",
                "from_table": rel.get("from_table") or rel.get("source_table"),
                "from_column": rel.get("from_column") or rel.get("source_column"),
                "to_table": rel.get("to_table") or rel.get("target_table") or rel.get("to_entity"),
                "to_column": rel.get("to_column") or rel.get("target_column") or "id",
                "predicate": rel.get("predicate") or f"ex:{rel.get('name') or 'relatedTo'}",
                "inverse_predicate": rel.get("inverse_predicate"),
                "cardinality": rel.get("cardinality", "many_to_one"),
                "required": bool(rel.get("required", False)),
                "declared_by": rel.get("declared_by") or raw.get("actor") or "unknown",
                "ticket": rel.get("ticket") or rel.get("ticket_ref") or "",
                "description": rel.get("description") or rel.get("justification") or "",
            })

    outputs = raw.get("outputs") or raw.get("output") or {}
    if isinstance(outputs, list):
        outputs = {"files": outputs}

    normalized = {
        "project": project,
        "runtime": raw.get("runtime", {}) or {},
        "tables": tables,
        "relationships": rels,
        "ontology": raw.get("ontology", {}) or {},
        "iri": raw.get("iri", {}) or {"strategy": "namespace", "pattern": "{namespace}/{entity}/{id}", "normalize": True},
        "governance": raw.get("governance", {}) or {},
        "outputs": outputs or {},
        "store": raw.get("store") if isinstance(raw.get("store"), dict) else {"enabled": bool(raw.get("store")), "path": raw.get("store")},
    }
    return normalized


def _legacy_property_map_to_columns(prop_map: dict[str, str] | None, pii_policy: dict | None) -> dict[str, Any]:
    cols: dict[str, Any] = {}
    for k, v in (prop_map or {}).items():
        cols[k] = {"property": v}
    return cols


def _normalize_columns(columns: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, spec in (columns or {}).items():
        if isinstance(spec, str):
            out[name] = {"property": spec}
        elif spec is None:
            out[name] = {}
        else:
            out[name] = dict(spec)
    return out


def _looks_remote(src: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", src))


def _pascal(value: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", str(value)) if part) or "Entity"


def validate_v1_config(config: dict[str, Any], load_data: bool = True) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    table_profiles: dict[str, Any] = {}
    tables = config.get("tables", [])
    rels = config.get("relationships", [])
    table_by_name = {t.get("name"): t for t in tables}

    if not tables:
        errors.append(_err("config.tables", "At least one table is required."))

    if len(table_by_name) != len(tables):
        errors.append(_err("config.tables", "Table names must be unique."))

    ns = config.get("project", {}).get("namespace")
    if not ns or not re.match(r"^https?://", str(ns)):
        errors.append(_err("project.namespace", "Namespace should be an absolute http(s) IRI."))

    loaded: dict[str, pl.DataFrame] = {}
    for t in tables:
        name = t.get("name")
        src = t.get("source")
        pk = t.get("primary_key")
        if not name:
            errors.append(_err("tables[].name", "Table name is required."))
        if not src:
            errors.append(_err(f"tables.{name}.source", "Source is required."))
        elif not _looks_remote(str(src)) and not Path(str(src)).exists():
            errors.append(_err(f"tables.{name}.source", f"Source does not exist: {src}"))
        if not t.get("entity"):
            errors.append(_err(f"tables.{name}.entity", "Entity is required."))
        if not pk:
            errors.append(_err(f"tables.{name}.primary_key", "Primary key is required."))
        if load_data and src and (Path(str(src)).exists() or _looks_remote(str(src))):
            try:
                kwargs = {"format": t.get("format")} if t.get("format") else {}
                df = read_table(src, **kwargs)
                loaded[name] = df
                table_profiles[name] = _profile_df(df, pk)
                if pk and pk not in df.columns:
                    errors.append(_err(f"tables.{name}.primary_key", f"Primary key column missing: {pk}"))
                elif pk:
                    dupes = df.height - df.select(pl.col(pk).n_unique()).item()
                    if dupes > 0:
                        errors.append(_err(f"tables.{name}.primary_key", f"Primary key has {dupes} duplicate values."))
                for col, spec in (t.get("columns") or {}).items():
                    if col not in df.columns:
                        warnings.append(_warn(f"tables.{name}.columns.{col}", f"Configured column not found in source: {col}"))
                    if spec.get("required") and col in df.columns and df[col].null_count() > 0:
                        errors.append(_err(f"tables.{name}.columns.{col}", f"Required column contains {df[col].null_count()} nulls."))
            except Exception as exc:
                errors.append(_err(f"tables.{name}.source", f"Could not read source: {exc}"))

    for rel in rels:
        rname = rel.get("name") or "relationship"
        ft, fc, tt, tc = rel.get("from_table"), rel.get("from_column"), rel.get("to_table"), rel.get("to_column")
        if ft not in table_by_name:
            errors.append(_err(f"relationships.{rname}.from.table", f"Source table does not exist: {ft}"))
            continue
        if tt not in table_by_name:
            errors.append(_err(f"relationships.{rname}.to.table", f"Target table does not exist: {tt}"))
            continue
        if load_data and ft in loaded and tt in loaded:
            df_from, df_to = loaded[ft], loaded[tt]
            if fc not in df_from.columns:
                errors.append(_err(f"relationships.{rname}.from.column", f"Source column does not exist: {ft}.{fc}"))
                continue
            if tc not in df_to.columns:
                errors.append(_err(f"relationships.{rname}.to.column", f"Target column does not exist: {tt}.{tc}"))
                continue
            target_dupes = df_to.height - df_to.select(pl.col(tc).n_unique()).item()
            if target_dupes > 0 and rel.get("cardinality", "many_to_one") in ("many_to_one", "one_to_one"):
                errors.append(_err(f"relationships.{rname}.cardinality", f"Target key {tt}.{tc} is not unique; {target_dupes} duplicate values."))
            if rel.get("required") and df_from[fc].null_count() > 0:
                errors.append(_err(f"relationships.{rname}.required", f"Required FK {ft}.{fc} contains {df_from[fc].null_count()} nulls."))
            src_vals = set(df_from.select(pl.col(fc).drop_nulls().cast(pl.Utf8)).to_series().to_list())
            tgt_vals = set(df_to.select(pl.col(tc).drop_nulls().cast(pl.Utf8)).to_series().to_list())
            orphans = src_vals - tgt_vals
            if orphans:
                sample = sorted(list(orphans))[:10]
                errors.append(_err(
                    f"relationships.{rname}.fk_integrity",
                    f"{len(orphans)} FK value(s) in {ft}.{fc} are missing from {tt}.{tc}. Sample: {sample}",
                    declared_by=rel.get("declared_by"), ticket=rel.get("ticket")
                ))

    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "table_profiles": table_profiles,
        "relationship_count": len(rels),
        "table_count": len(tables),
        "validated_at": utc_now(),
    }


def _err(path: str, message: str, **extra) -> dict[str, Any]:
    out = {"level": "error", "path": path, "message": message}
    out.update({k: v for k, v in extra.items() if v})
    return out


def _warn(path: str, message: str) -> dict[str, Any]:
    return {"level": "warning", "path": path, "message": message}


def _profile_df(df: pl.DataFrame, pk: str | None) -> dict[str, Any]:
    return {
        "rows": df.height,
        "columns": len(df.columns),
        "primary_key": pk,
        "column_profiles": {
            col: {
                "dtype": str(df[col].dtype),
                "nulls": int(df[col].null_count()),
                "null_rate": (float(df[col].null_count()) / df.height) if df.height else 0.0,
            }
            for col in df.columns
        },
    }


def build_v1(config_path: str | Path, *, output_dir: str | None = None, fail_on_validation_error: bool = True) -> V1BuildResult:
    start = time.time()
    config = load_v1_config(config_path)
    project = config["project"]
    out_dir = Path(output_dir or project.get("output_dir") or "gold")
    if not out_dir.is_absolute():
        out_dir = (Path(config_path).parent / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    build_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]

    audit_events: list[dict[str, Any]] = []
    _audit(audit_events, "config_loaded", {"config": str(config_path), "config_hash": _file_sha256(config_path)})

    validation = validate_v1_config(config, load_data=True)
    (out_dir / "validation_report.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    if validation["errors"] and fail_on_validation_error:
        _audit(audit_events, "build_failed", {"reason": "validation_failed", "errors": validation["errors"]})
        _write_jsonl(out_dir / "audit.jsonl", audit_events)
        raise V1ConfigError(_format_validation_errors(validation))

    namespace = project["namespace"]
    kg = KnowledgeGraph(
        namespace=namespace,
        use_maplib=False,
        strict=bool(project.get("strict", True)),
        actor=config.get("actor", "unknown"),
        audit_path=None,
        incremental=False,
        manifest_path=None,
    )

    table_by_name = {t["name"]: t for t in config["tables"]}
    rels_by_source: dict[str, dict[str, str]] = {}
    for rel in config["relationships"]:
        target_entity = table_by_name.get(rel["to_table"], {}).get("entity", rel["to_table"])
        rels_by_source.setdefault(rel["from_table"], {})[rel["from_column"]] = target_entity

    lineage_tables = []
    loaded_frames: dict[str, pl.DataFrame] = {}
    for t in config["tables"]:
        kwargs = {"format": t.get("format")} if t.get("format") else {}
        df = read_table(t["source"], **kwargs)
        df, pii_summary = _apply_column_policies(df, t, config)
        loaded_frames[t["name"]] = df
        property_map = {col: _expand_predicate(spec.get("property"), namespace) for col, spec in (t.get("columns") or {}).items() if spec.get("property")}
        kg.add_table(
            df,
            source_name=t["name"],
            entity_type=t["entity"],
            id_column=t["primary_key"],
            property_map=property_map,
            relationships=rels_by_source.get(t["name"], {}),
        )
        lineage_tables.append({
            "table": t["name"], "source": t["source"], "entity": t["entity"],
            "primary_key": t["primary_key"], "rows": df.height, "columns": df.columns,
            "fingerprint": _source_fingerprint(t["source"]), "pii": pii_summary, "column_config": t.get("columns", {}),
        })
        _audit(audit_events, "table_loaded", {"table": t["name"], "rows": df.height, "entity": t["entity"]})
        for pii_event in pii_summary:
            _audit(audit_events, "pii_masked", {"table": t["name"], **pii_event})

    for rel in config["relationships"]:
        kg.declare_relationship(
            rel["from_table"], rel["from_column"], rel["to_table"],
            target_column=rel["to_column"], declared_by=rel.get("declared_by"),
            ticket_ref=rel.get("ticket", ""), justification=rel.get("description", ""),
        )
        _audit(audit_events, "relationship_declared", rel)

    kg.build()

    # v1 production semantics: emit explicit rdf:type triples and custom relationship
    # predicates from autokg.yml. The legacy template generator emits column-based
    # relationship edges; these explicit triples make the declared ontology executable.
    rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    ns_hash = namespace.rstrip("/#") + "#"
    table_by_name = {t["name"]: t for t in config["tables"]}
    for t in config["tables"]:
        df = loaded_frames.get(t["name"])
        if df is None or t["primary_key"] not in df.columns:
            continue
        class_iri = ns_hash + _safe(t["entity"])
        for row in df.select(t["primary_key"]).iter_rows(named=True):
            subj = _entity_iri(namespace, t["entity"], row[t["primary_key"]])
            kg.add_triples(subj, rdf_type, class_iri, is_iri=True)
    for rel in config["relationships"]:
        src_t = table_by_name[rel["from_table"]]
        tgt_t = table_by_name[rel["to_table"]]
        df = loaded_frames.get(rel["from_table"])
        if df is None or rel["from_column"] not in df.columns or src_t["primary_key"] not in df.columns:
            continue
        pred = _expand_predicate(rel.get("predicate") or f"ex:{rel['name']}", namespace)
        inv_pred = _expand_predicate(rel["inverse_predicate"], namespace) if rel.get("inverse_predicate") else None
        for row in df.select([src_t["primary_key"], rel["from_column"]]).drop_nulls().iter_rows(named=True):
            subj = _entity_iri(namespace, src_t["entity"], row[src_t["primary_key"]])
            obj = _entity_iri(namespace, tgt_t["entity"], row[rel["from_column"]])
            kg.add_triples(subj, pred, obj, is_iri=True)
            if inv_pred:
                kg.add_triples(obj, inv_pred, subj, is_iri=True)

    _audit(audit_events, "graph_built", {"triple_count": kg.triple_count})

    output_files: list[str] = []
    format_map = _requested_formats(config)
    for fmt, filename in format_map.items():
        path = out_dir / filename
        kg.write(str(path), format=fmt)
        output_files.append(str(path))
        _audit(audit_events, "output_written", {"path": str(path), "format": fmt})

    ontology_ttl = generate_ontology_ttl(config)
    ontology_path = out_dir / "ontology.ttl"
    ontology_path.write_text(ontology_ttl, encoding="utf-8")
    output_files.append(str(ontology_path))
    try:
        from ._ontology_tools import generate_shacl_ttl
        shapes_path = out_dir / "shapes.ttl"
        shapes_path.write_text(generate_shacl_ttl(config), encoding="utf-8")
        output_files.append(str(shapes_path))
    except Exception as exc:
        _audit(audit_events, "shacl_generation_warning", {"error": str(exc)})

    lineage = {
        "build_id": build_id,
        "generated_at": utc_now(),
        "namespace": namespace,
        "tables": lineage_tables,
        "relationships": config["relationships"],
        "outputs": output_files,
    }
    lineage_path = out_dir / "lineage.json"
    lineage_path.write_text(json.dumps(lineage, indent=2), encoding="utf-8")
    output_files.append(str(lineage_path))

    manifest = {
        "build_id": build_id,
        "generated_at": utc_now(),
        "autokg_version": _version(),
        "project": project,
        "config_path": str(config_path),
        "config_hash": _file_sha256(config_path),
        "tables": {t["table"]: {"rows": t["rows"], "fingerprint": t["fingerprint"], "entity": t["entity"], "primary_key": t["primary_key"]} for t in lineage_tables},
        "relationships": len(config["relationships"]),
        "triples": kg.triple_count,
        "validation_status": validation["status"],
        "outputs": output_files,
        "duration_seconds": round(time.time() - start, 4),
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    output_files.append(str(manifest_path))

    _audit(audit_events, "build_completed", {"build_id": build_id, "triple_count": kg.triple_count, "duration_seconds": manifest["duration_seconds"]})
    audit_path = out_dir / "audit.jsonl"
    _write_jsonl(audit_path, audit_events)
    output_files.append(str(audit_path))

    report_path = out_dir / "build_report.html"
    report_path.write_text(render_build_report(config, validation, manifest, lineage), encoding="utf-8")
    output_files.append(str(report_path))

    store_cfg = config.get("store") or {}
    if store_cfg.get("enabled") or store_cfg.get("path"):
        store_path = Path(store_cfg.get("path") or (out_dir / "store"))
        if not store_path.is_absolute():
            store_path = (Path(config_path).parent / store_path).resolve()
        kg.save_store(str(store_path))
        output_files.append(str(store_path))

    manifest["outputs"] = output_files
    manifest["duration_seconds"] = round(time.time() - start, 4)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return V1BuildResult(
        build_id=build_id,
        output_dir=str(out_dir),
        triple_count=kg.triple_count,
        table_count=len(config["tables"]),
        relationship_count=len(config["relationships"]),
        output_files=output_files,
        duration_seconds=round(time.time() - start, 4),
        validation_status=validation["status"],
    )


def _format_validation_errors(validation: dict[str, Any]) -> str:
    lines = ["autokg validation failed:"]
    for err in validation.get("errors", []):
        extra = ""
        if err.get("declared_by") or err.get("ticket"):
            extra = f" (declared_by={err.get('declared_by','?')}, ticket={err.get('ticket','')})"
        lines.append(f"- {err['path']}: {err['message']}{extra}")
    return "\n".join(lines)


def _requested_formats(config: dict[str, Any]) -> dict[str, str]:
    out = config.get("outputs") or {}
    rdf = out.get("rdf") if isinstance(out, dict) else None
    formats = None
    if isinstance(rdf, dict) and rdf.get("enabled", True):
        formats = rdf.get("formats")
    if not formats and isinstance(out, dict) and out.get("files"):
        formats = [f.get("format") for f in out["files"] if f.get("format") in SUPPORTED_OUTPUT_FORMATS]
    formats = formats or ["turtle", "jsonld", "ntriples", "rdfxml"]
    result: dict[str, str] = {}
    for fmt in formats:
        fmt = {"ttl": "turtle", "nt": "ntriples", "rdf": "rdfxml"}.get(fmt, fmt)
        if fmt == "turtle":
            result[fmt] = "graph.ttl"
        elif fmt == "jsonld":
            result[fmt] = "graph.jsonld"
        elif fmt == "ntriples":
            result[fmt] = "graph.nt"
        elif fmt == "rdfxml":
            result[fmt] = "graph.rdf"
    return result


def _apply_column_policies(df: pl.DataFrame, table: dict[str, Any], config: dict[str, Any]) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
    summaries: list[dict[str, Any]] = []
    default_mask = (((config.get("governance") or {}).get("pii") or {}).get("default_mask") or "hash")
    salt_env = (((config.get("governance") or {}).get("pii") or {}).get("salt_env") or "AUTOKG_PII_SALT")
    salt = os.environ.get(salt_env, "autokg-default-salt")
    for col, spec in (table.get("columns") or {}).items():
        if col not in df.columns:
            continue
        if spec.get("pii") or spec.get("mask"):
            strategy = spec.get("mask") or default_mask
            if strategy == "drop":
                df = df.drop(col)
            elif strategy == "redact":
                df = df.with_columns(pl.lit("[REDACTED]").alias(col))
            elif strategy == "partial":
                df = df.with_columns(pl.col(col).cast(pl.Utf8).map_elements(lambda v: _partial(v), return_dtype=pl.Utf8).alias(col))
            elif strategy == "hash":
                df = df.with_columns(pl.col(col).cast(pl.Utf8).map_elements(lambda v: _hash_value(v, salt), return_dtype=pl.Utf8).alias(col))
            summaries.append({"column": col, "strategy": strategy, "pii_type": spec.get("pii_type"), "salt_env": salt_env if strategy == "hash" else None})
    return df, summaries


def _hash_value(value: Any, salt: str) -> str | None:
    if value is None:
        return None
    return "sha256:" + hashlib.sha256((salt + "::" + str(value)).encode("utf-8")).hexdigest()


def _partial(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value)
    if len(s) <= 4:
        return "*" * len(s)
    return s[:2] + "*" * max(1, len(s) - 4) + s[-2:]


def generate_ontology_ttl(config: dict[str, Any]) -> str:
    ns = config["project"]["namespace"].rstrip("/#") + "#"
    prefixes = ((config.get("ontology") or {}).get("prefixes") or {})
    lines = [
        "@prefix ex: <" + ns + "> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix schema: <https://schema.org/> .",
        "",
    ]
    for p, iri in prefixes.items():
        if p not in {"ex", "owl", "rdf", "rdfs", "schema"}:
            lines.insert(0, f"@prefix {p.rstrip(':')}: <{iri}> .")
    lines.append("ex:Ontology a owl:Ontology .\n")
    for t in config.get("tables", []):
        entity = _local(t["entity"])
        lines.append(f"ex:{entity} a owl:Class ;")
        lines.append(f"  rdfs:label \"{_escape(entity)}\" .\n")
        for col, spec in (t.get("columns") or {}).items():
            pred = spec.get("property") or f"ex:{_safe(col)}"
            lines.append(f"{_qname(pred)} a owl:DatatypeProperty ;")
            lines.append(f"  rdfs:domain ex:{entity} ;")
            lines.append(f"  rdfs:label \"{_escape(col)}\" .\n")
    for r in config.get("relationships", []):
        pred = _qname(r.get("predicate") or f"ex:{_safe(r['name'])}")
        domain = _local(next((t["entity"] for t in config["tables"] if t["name"] == r["from_table"]), r["from_table"]))
        range_ = _local(next((t["entity"] for t in config["tables"] if t["name"] == r["to_table"]), r["to_table"]))
        lines.append(f"{pred} a owl:ObjectProperty ;")
        lines.append(f"  rdfs:domain ex:{domain} ;")
        lines.append(f"  rdfs:range ex:{range_} ;")
        lines.append(f"  rdfs:label \"{_escape(r.get('name','relationship'))}\" .\n")
    return "\n".join(lines)


def _qname(value: str) -> str:
    if value.startswith("http://") or value.startswith("https://"):
        return f"<{value}>"
    if ":" in value:
        return value
    return "ex:" + _safe(value)


def _local(value: str) -> str:
    return _safe(str(value).split(":")[-1].split("/")[-1].split("#")[-1])


def _safe(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", str(value))
    if not s or s[0].isdigit():
        s = "_" + s
    return s


def _escape(value: str) -> str:
    return str(value).replace('"', '\\"')


def render_build_report(config: dict[str, Any], validation: dict[str, Any], manifest: dict[str, Any], lineage: dict[str, Any]) -> str:
    project = config["project"]
    table_rows = "".join(
        f"<tr><td>{html.escape(t['table'])}</td><td>{html.escape(t['entity'])}</td><td>{t['rows']}</td><td>{html.escape(t['primary_key'])}</td><td>{len(t.get('pii') or [])}</td></tr>"
        for t in lineage.get("tables", [])
    )
    rel_rows = "".join(
        f"<tr><td>{html.escape(r.get('name',''))}</td><td>{html.escape(r.get('from_table',''))}.{html.escape(r.get('from_column',''))}</td><td>{html.escape(r.get('to_table',''))}.{html.escape(r.get('to_column',''))}</td><td>{html.escape(r.get('declared_by',''))}</td><td>{html.escape(r.get('ticket',''))}</td></tr>"
        for r in config.get("relationships", [])
    )
    errors = "".join(f"<li>{html.escape(e['path'])}: {html.escape(e['message'])}</li>" for e in validation.get("errors", [])) or "<li>None</li>"
    outputs = "".join(f"<li>{html.escape(str(o))}</li>" for o in manifest.get("outputs", []))
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>autokg build report</title><style>body{{font-family:Inter,system-ui,sans-serif;background:#0b1020;color:#e8eefc;margin:0}}main{{max-width:1100px;margin:auto;padding:40px}}.card{{background:#121a33;border:1px solid #26345f;border-radius:16px;padding:22px;margin:18px 0}}h1{{font-size:42px}}h2{{color:#9ec5ff}}table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #26345f;padding:10px;text-align:left}}.ok{{color:#65e6a6}}.bad{{color:#ff8b8b}}code,pre{{background:#070b16;padding:10px;border-radius:10px;display:block;overflow:auto}}</style></head><body><main><h1>autokg build report</h1><div class='card'><h2>{html.escape(project['name'])}</h2><p>Namespace: <code>{html.escape(project['namespace'])}</code></p><p>Build ID: <code>{html.escape(manifest['build_id'])}</code></p><p>Status: <b class='{ 'ok' if validation['status']=='passed' else 'bad'}'>{validation['status']}</b></p><p>Triples: <b>{manifest['triples']}</b> · Duration: <b>{manifest['duration_seconds']}s</b></p></div><div class='card'><h2>Tables</h2><table><thead><tr><th>Table</th><th>Entity</th><th>Rows</th><th>Primary key</th><th>PII columns</th></tr></thead><tbody>{table_rows}</tbody></table></div><div class='card'><h2>Relationships</h2><table><thead><tr><th>Name</th><th>From</th><th>To</th><th>Declared by</th><th>Ticket</th></tr></thead><tbody>{rel_rows}</tbody></table></div><div class='card'><h2>Validation errors</h2><ul>{errors}</ul></div><div class='card'><h2>Outputs</h2><ul>{outputs}</ul></div></main></body></html>"""


def inspect_output(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if p.is_dir():
        manifest = p / "manifest.json"
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["output_dir"] = str(p)
            return data
        files = list(p.iterdir())
        return {"path": str(p), "files": [str(f) for f in files]}
    return {"path": str(p), "size_bytes": p.stat().st_size if p.exists() else None, "exists": p.exists()}


def _entity_iri(namespace: str, entity: str, value: Any) -> str:
    val = str(value).replace(" ", "_")
    return namespace.rstrip("/#") + f"/{_safe(entity)}/{val}"


def _expand_predicate(predicate: str, namespace: str) -> str:
    if predicate.startswith("http://") or predicate.startswith("https://"):
        return predicate
    if predicate.startswith("schema:"):
        return "https://schema.org/" + predicate.split(":", 1)[1]
    if predicate.startswith("rdf:"):
        return "http://www.w3.org/1999/02/22-rdf-syntax-ns#" + predicate.split(":", 1)[1]
    if predicate.startswith("rdfs:"):
        return "http://www.w3.org/2000/01/rdf-schema#" + predicate.split(":", 1)[1]
    if ":" in predicate:
        return namespace.rstrip("/#") + "#" + predicate.split(":", 1)[1]
    return namespace.rstrip("/#") + "#" + _safe(predicate)


def _audit(events: list[dict[str, Any]], event: str, details: dict[str, Any]) -> None:
    events.append({"timestamp": utc_now(), "event": event, "details": details})


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(e, default=str) + "\n" for e in events), encoding="utf-8")


def _file_sha256(path: str | Path) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _source_fingerprint(source: str) -> str:
    if _looks_remote(source):
        return hashlib.sha256(source.encode()).hexdigest()
    p = Path(source)
    h = hashlib.sha256()
    h.update(str(p.resolve()).encode())
    if p.exists():
        st = p.stat()
        h.update(str(st.st_size).encode())
        h.update(str(int(st.st_mtime)).encode())
    return h.hexdigest()


def _version() -> str:
    try:
        from . import __version__
        return __version__
    except Exception:
        return "unknown"
