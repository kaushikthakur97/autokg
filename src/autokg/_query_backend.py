from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._llm import LLMProvider, create_llm_provider
from ._security import QueryPolicy, redact_rows
from ._observability import MetricsRegistry, JsonlLogger
from ._query_planner import QueryPlanner
from ._rbac import PolicyEngine


class QueryBackendError(RuntimeError):
    pass


@dataclass
class SparqlValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    safe: bool = True
    sparql: str = ""


@dataclass
class QueryAnswer:
    question: str
    resolved_question: str
    sparql: str
    rows: list[dict[str, Any]]
    row_count: int
    answer: str
    evidence: dict[str, Any]
    validation: dict[str, Any]
    session_id: str | None = None


class SchemaIndex:
    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        if self.output_dir.name == "store":
            self.output_dir = self.output_dir.parent
        self.manifest = _read_json(self.output_dir / "manifest.json", default={})
        self.lineage = _read_json(self.output_dir / "lineage.json", default={})
        self.validation = _read_json(self.output_dir / "validation_report.json", default={})
        self.tables = self._load_tables()
        self.relationships = self.lineage.get("relationships", [])
        self.namespace = self.manifest.get("project", {}).get("namespace") or self.lineage.get("namespace") or "https://example.com/kg"

    def _load_tables(self) -> list[dict[str, Any]]:
        tables = []
        lineage_tables = {t.get("table"): t for t in self.lineage.get("tables", [])}
        for name, spec in (self.manifest.get("tables") or {}).items():
            lt = lineage_tables.get(name, {})
            tables.append({
                "name": name,
                "entity": spec.get("entity") or lt.get("entity") or name,
                "primary_key": spec.get("primary_key") or lt.get("primary_key"),
                "rows": spec.get("rows") or lt.get("rows"),
                "columns": lt.get("columns", []),
                "column_config": lt.get("column_config", {}),
                "source": lt.get("source"),
                "pii": lt.get("pii", []),
            })
        if not tables:
            for lt in self.lineage.get("tables", []):
                tables.append({"name": lt.get("table"), "entity": lt.get("entity"), "primary_key": lt.get("primary_key"), "rows": lt.get("rows"), "columns": lt.get("columns", []), "column_config": lt.get("column_config", {}), "source": lt.get("source"), "pii": lt.get("pii", [])})
        return tables

    def as_prompt_context(self, max_chars: int = 12000) -> str:
        data = {
            "namespace": self.namespace,
            "tables_entities": self.tables,
            "relationships": self.relationships,
            "rules": [
                "Use only classes, predicates, tables, and relationships shown here.",
                "Use PREFIX ex: <namespace#> for ontology properties/classes.",
                "Entity IRIs are generally namespace/entity/id.",
            ],
        }
        text = json.dumps(data, indent=2)
        return text[:max_chars]

    def get_schema(self) -> dict[str, Any]:
        return {"namespace": self.namespace, "tables": self.tables, "relationships": self.relationships, "manifest": self.manifest}

    def evidence_for_sparql(self, sparql: str) -> dict[str, Any]:
        text = sparql.lower()
        used_tables = []
        used_entities = []
        for t in self.tables:
            if str(t.get("entity", "")).lower() in text or str(t.get("name", "")).lower() in text:
                used_tables.append(t.get("name"))
                used_entities.append(t.get("entity"))
        used_rels = []
        for r in self.relationships:
            pred = str(r.get("predicate", ""))
            local = pred.split(":")[-1].lower()
            if local and local in text:
                used_rels.append(r)
        return {"entities": sorted(set(filter(None, used_entities))), "source_tables": sorted(set(filter(None, used_tables))), "relationships": used_rels}


class SparqlValidator:
    BLOCKED = re.compile(r"\b(INSERT|DELETE|LOAD|CLEAR|CREATE|DROP|MOVE|COPY|ADD|SERVICE)\b", re.I)
    ALLOWED_START = re.compile(r"^\s*(PREFIX\s+\w+:\s*<[^>]+>\s*)*(SELECT|ASK|CONSTRUCT|DESCRIBE)\b", re.I | re.S)

    def __init__(self, *, max_query_chars: int = 20000, require_limit: bool = True, default_limit: int = 100, policy: QueryPolicy | None = None):
        self.policy = policy or QueryPolicy(max_query_chars=max_query_chars, require_limit=require_limit, max_rows=default_limit)
        self.max_query_chars = self.policy.max_query_chars
        self.require_limit = self.policy.require_limit
        self.default_limit = default_limit

    def validate(self, sparql: str) -> SparqlValidationResult:
        errors = []
        warnings = []
        q = _strip_markdown(sparql).strip()
        if not q:
            errors.append("SPARQL is empty")
        if len(q) > self.max_query_chars:
            errors.append(f"SPARQL exceeds max length {self.max_query_chars}")
        if self.BLOCKED.search(q):
            errors.append("SPARQL contains blocked update/federated operation")
        errors.extend(self.policy.check_sparql(q))
        if not self.ALLOWED_START.search(q):
            errors.append("Only SELECT, ASK, CONSTRUCT, and DESCRIBE queries are allowed")
        try:
            from rdflib.plugins.sparql import prepareQuery
            prepareQuery(q)
        except Exception as exc:
            errors.append(f"SPARQL parse error: {exc}")
        if self.require_limit and re.search(r"\bSELECT\b", q, re.I) and not re.search(r"\bLIMIT\s+\d+", q, re.I):
            warnings.append(f"SELECT query has no LIMIT; LIMIT {self.default_limit} will be appended")
            q = q.rstrip().rstrip(";") + f"\nLIMIT {self.default_limit}"
        return SparqlValidationResult(valid=not errors, errors=errors, warnings=warnings, safe=not errors, sparql=q)


class SparqlExecutor:
    def __init__(self, output_dir: str | Path, *, max_rows: int = 500):
        self.output_dir = Path(output_dir)
        if self.output_dir.name == "store":
            self.output_dir = self.output_dir.parent
        self.max_rows = max_rows
        self._graph = None

    def _load_graph(self):
        if self._graph is not None:
            return self._graph
        try:
            from rdflib import Graph
        except ImportError as exc:
            raise QueryBackendError("rdflib is required for query backend. Install autokg[query] or pip install rdflib") from exc
        g = Graph()
        candidates = [
            (self.output_dir / "graph.ttl", "turtle"),
            (self.output_dir / "graph.nt", "nt"),
            (self.output_dir / "graph.rdf", "xml"),
            (self.output_dir / "store" / "data.nt", "nt"),
        ]
        loaded = False
        for path, fmt in candidates:
            if path.exists():
                g.parse(str(path), format=fmt)
                loaded = True
                break
        if not loaded:
            raise QueryBackendError(f"No graph file found in {self.output_dir}")
        self._graph = g
        return g

    def execute(self, sparql: str) -> list[dict[str, Any]]:
        g = self._load_graph()
        result = g.query(sparql)
        rows: list[dict[str, Any]] = []
        for row in result:
            if hasattr(row, "asdict"):
                rows.append({str(k): _rdflib_value(v) for k, v in row.asdict().items()})
            else:
                rows.append({f"col_{i}": _rdflib_value(v) for i, v in enumerate(row)})
            if len(rows) >= self.max_rows:
                break
        return rows


class NL2SparqlGenerator:
    def __init__(self, schema: SchemaIndex, llm: LLMProvider | None = None):
        self.schema = schema
        self.llm = llm or create_llm_provider(None)

    def generate(self, question: str, *, conversation_context: str = "") -> str:
        rule_based = self._try_rule_based(question)
        if rule_based:
            return rule_based
        messages = self._messages(question, conversation_context)
        text = self.llm.generate(messages, temperature=0.0, max_tokens=2200)
        return _strip_markdown(text)

    def repair(self, question: str, bad_sparql: str, errors: list[str], *, conversation_context: str = "") -> str:
        messages = self._messages(question, conversation_context)
        messages.append({"role": "user", "content": "The SPARQL you generated was invalid.\nErrors:\n" + json.dumps(errors, indent=2) + "\nBad SPARQL:\n" + bad_sparql + "\nReturn corrected SPARQL only."})
        return _strip_markdown(self.llm.generate(messages, temperature=0.0, max_tokens=2200))

    def _messages(self, question: str, conversation_context: str) -> list[dict[str, str]]:
        system = """You are autokg's NL-to-SPARQL compiler.
Return only SPARQL. No markdown. No commentary.
Rules:
- Use only the provided schema context.
- Do not invent classes or predicates.
- Generate read-only SPARQL only.
- Prefer SELECT queries.
- Include PREFIX declarations.
- Add a LIMIT unless the question explicitly asks for all results.
- Use graph relationships for joins; do not mention SQL.
"""
        ctx = self.schema.as_prompt_context()
        user = f"Schema context:\n{ctx}\n\nConversation context:\n{conversation_context or 'None'}\n\nQuestion:\n{question}\n\nSPARQL:"
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _try_rule_based(self, question: str) -> str | None:
        q = question.lower().strip()
        ns = self.schema.namespace.rstrip("/#")
        prefixes = f"PREFIX ex: <{ns}#>\nPREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\nPREFIX schema: <https://schema.org/>\n"
        if q in ("show triples", "list triples", "everything", "show graph"):
            return prefixes + "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 100"
        for t in self.schema.tables:
            ent = str(t.get("entity", ""))
            name = str(t.get("name", ""))
            if ent.lower() in q or name.lower() in q:
                return prefixes + f"SELECT ?entity ?p ?o WHERE {{\n  ?entity rdf:type ex:{_safe_local(ent)} .\n  ?entity ?p ?o .\n}} LIMIT 100"
        return None


class ConversationManager:
    def __init__(self):
        self._lock = threading.Lock()
        self.sessions: dict[str, list[dict[str, Any]]] = {}

    def start(self) -> str:
        sid = uuid.uuid4().hex
        with self._lock:
            self.sessions[sid] = []
        return sid

    def context(self, session_id: str | None) -> str:
        if not session_id:
            return ""
        turns = self.sessions.get(session_id, [])[-5:]
        slim = [{"question": t.get("question"), "sparql": t.get("sparql"), "row_count": t.get("row_count"), "sample_rows": t.get("rows", [])[:3]} for t in turns]
        return json.dumps(slim, default=str, indent=2)

    def record(self, session_id: str | None, turn: dict[str, Any]) -> str:
        if not session_id:
            session_id = self.start()
        turn = dict(turn)
        turn["timestamp"] = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.sessions.setdefault(session_id, []).append(turn)
        return session_id

    def get(self, session_id: str) -> list[dict[str, Any]]:
        return self.sessions.get(session_id, [])

    def clear(self, session_id: str) -> None:
        with self._lock:
            self.sessions.pop(session_id, None)


class QueryEngine:
    def __init__(self, output_dir: str | Path, *, llm_config: dict[str, Any] | None = None, max_rows: int = 500, security_config: dict[str, Any] | None = None, metrics_path: str | Path | None = None):
        self.output_dir = Path(output_dir)
        if self.output_dir.name == "store":
            self.output_dir = self.output_dir.parent
        self.schema = SchemaIndex(self.output_dir)
        self.security_config = security_config or {}
        self.policy = QueryPolicy.from_config(self.security_config)
        self.access = PolicyEngine.from_config(self.security_config)
        self.policy.max_rows = max_rows if max_rows is not None else self.policy.max_rows
        self.metrics = MetricsRegistry()
        self.logger = JsonlLogger(metrics_path or (self.output_dir / "query_audit.jsonl"))
        self.llm = create_llm_provider(llm_config)
        self.planner = QueryPlanner(self.schema)
        self.generator = NL2SparqlGenerator(self.schema, self.llm)
        self.validator = SparqlValidator(policy=self.policy, default_limit=self.policy.max_rows)
        self.executor = SparqlExecutor(self.output_dir, max_rows=self.policy.max_rows)
        self.conversations = ConversationManager()

    def get_schema(self, *, role: str | None = None) -> dict[str, Any]:
        return self.access.filter_schema(self.schema.get_schema(), role)

    def start_session(self) -> str:
        return self.conversations.start()

    def generate_sparql(self, question: str, *, session_id: str | None = None, repair_attempts: int = 1) -> dict[str, Any]:
        context = self.conversations.context(session_id)
        plan = self.planner.plan(question)
        sparql = self.planner.to_sparql(plan) or self.generator.generate(question, conversation_context=context)
        validation = self.validator.validate(sparql)
        attempts = 0
        while not validation.valid and attempts < repair_attempts:
            sparql = self.generator.repair(question, validation.sparql or sparql, validation.errors, conversation_context=context)
            validation = self.validator.validate(sparql)
            attempts += 1
        return {"question": question, "sparql": validation.sparql or sparql, "validation": validation.__dict__, "evidence": self.schema.evidence_for_sparql(validation.sparql or sparql), "plan": plan.__dict__}

    def validate_sparql(self, sparql: str) -> dict[str, Any]:
        return self.validator.validate(sparql).__dict__

    def execute_sparql(self, sparql: str, *, role: str | None = None) -> dict[str, Any]:
        import time
        start = time.time()
        validation = self.validator.validate(sparql)
        if not validation.valid:
            self.metrics.inc("sparql_validation_failed")
            self.logger.event("sparql_rejected", errors=validation.errors, sparql=sparql[:1000])
            return {"rows": [], "row_count": 0, "validation": validation.__dict__, "error": "; ".join(validation.errors)}
        rows = self.executor.execute(validation.sparql)
        rows = redact_rows(rows, self.policy.denied_predicates + self.policy.denied_entities)
        rows = self.access.filter_rows(rows, role)
        self.metrics.inc("sparql_executed")
        self.metrics.observe("sparql_latency_seconds", time.time() - start)
        self.logger.event("sparql_executed", row_count=len(rows), latency_seconds=round(time.time()-start, 4), sparql=validation.sparql[:2000])
        return {"rows": rows, "row_count": len(rows), "validation": validation.__dict__, "evidence": self.schema.evidence_for_sparql(validation.sparql)}

    def ask(self, question: str, *, session_id: str | None = None, role: str | None = None) -> QueryAnswer:
        draft = self.generate_sparql(question, session_id=session_id)
        validation = draft["validation"]
        rows: list[dict[str, Any]] = []
        if validation.get("valid"):
            exec_result = self.execute_sparql(draft["sparql"], role=role)
            rows = exec_result.get("rows", [])
        answer = self._format_answer(question, rows, draft["evidence"], validation)
        sid = self.conversations.record(session_id, {"question": question, "sparql": draft["sparql"], "rows": rows[:20], "row_count": len(rows), "evidence": draft["evidence"], "validation": validation})
        return QueryAnswer(question=question, resolved_question=question, sparql=draft["sparql"], rows=rows, row_count=len(rows), answer=answer, evidence=draft["evidence"], validation=validation, session_id=sid)

    def _format_answer(self, question: str, rows: list[dict[str, Any]], evidence: dict[str, Any], validation: dict[str, Any]) -> str:
        if not validation.get("valid"):
            return "I could not generate a valid safe SPARQL query: " + "; ".join(validation.get("errors", []))
        if not rows:
            return "No matching rows were found."
        return f"Found {len(rows)} row(s). Evidence used entities={evidence.get('entities', [])}, source_tables={evidence.get('source_tables', [])}."


def run_api(output_dir: str | Path, *, host: str = "0.0.0.0", port: int = 8080, llm_config: dict[str, Any] | None = None, auth_token: str | None = None) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse

    engine = QueryEngine(output_dir, llm_config=llm_config)

    class Handler(BaseHTTPRequestHandler):
        def _auth(self) -> bool:
            if not auth_token:
                return True
            h = self.headers.get("Authorization", "")
            return h == f"Bearer {auth_token}"

        def _json(self, data: Any, status: int = 200):
            body = json.dumps(data, default=lambda o: o.__dict__ if hasattr(o, "__dict__") else str(o), indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict[str, Any]:
            n = int(self.headers.get("Content-Length", "0"))
            if n <= 0:
                return {}
            return json.loads(self.rfile.read(n).decode("utf-8"))

        def do_GET(self):
            if not self._auth():
                return self._json({"error": "Unauthorized"}, 401)
            path = urlparse(self.path).path
            if path == "/health":
                return self._json({"status": "ok", "server": "autokg-query", "output_dir": str(engine.output_dir)})
            if path == "/schema":
                return self._json(engine.get_schema(role=self.headers.get("X-Role")))
            if path == "/relationships":
                return self._json({"relationships": engine.schema.relationships})
            if path == "/manifest":
                return self._json(engine.schema.manifest)
            if path == "/lineage":
                return self._json(engine.schema.lineage)
            if path == "/metrics":
                return self._json(engine.metrics.summary())
            if path == "/openapi.json":
                return self._json(_openapi_schema())
            return self._json({"error": "Not found"}, 404)

        def do_POST(self):
            if not self._auth():
                return self._json({"error": "Unauthorized"}, 401)
            path = urlparse(self.path).path
            body = self._body()
            if path == "/sessions":
                return self._json({"session_id": engine.start_session()})
            if path == "/sparql/generate":
                return self._json(engine.generate_sparql(body.get("question", ""), session_id=body.get("session_id")))
            if path == "/sparql/validate":
                return self._json(engine.validate_sparql(body.get("sparql", "")))
            if path == "/sparql/execute":
                return self._json(engine.execute_sparql(body.get("sparql", ""), role=body.get("role") or self.headers.get("X-Role")))
            if path == "/ask":
                return self._json(engine.ask(body.get("question", ""), session_id=body.get("session_id"), role=body.get("role") or self.headers.get("X-Role")))
            m = re.match(r"^/sessions/([^/]+)/ask$", path)
            if m:
                return self._json(engine.ask(body.get("question", ""), session_id=m.group(1), role=body.get("role") or self.headers.get("X-Role")))
            return self._json({"error": "Not found"}, 404)

        def log_message(self, fmt, *args):
            return

    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"autokg query API listening on http://{host}:{port}")
    httpd.serve_forever()


def _openapi_schema() -> dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "autokg Query API", "version": "1.0.0"},
        "paths": {
            "/health": {"get": {"summary": "Health check"}},
            "/schema": {"get": {"summary": "Graph schema index"}},
            "/relationships": {"get": {"summary": "Declared relationships"}},
            "/manifest": {"get": {"summary": "Build manifest"}},
            "/lineage": {"get": {"summary": "Build lineage"}},
            "/metrics": {"get": {"summary": "Runtime metrics"}},
            "/sparql/generate": {"post": {"summary": "Generate SPARQL from natural language"}},
            "/sparql/validate": {"post": {"summary": "Validate SPARQL"}},
            "/sparql/execute": {"post": {"summary": "Execute SPARQL"}},
            "/ask": {"post": {"summary": "Ask graph in natural language"}},
            "/sessions": {"post": {"summary": "Start a session"}},
            "/sessions/{session_id}/ask": {"post": {"summary": "Ask follow-up question in a session"}},
        },
    }


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _strip_markdown(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _rdflib_value(v: Any) -> Any:
    if v is None:
        return None
    return str(v)


def _safe_local(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", str(value))
    return "_" + s if s and s[0].isdigit() else s
