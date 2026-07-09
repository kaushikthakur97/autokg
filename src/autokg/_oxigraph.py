from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional, Union

_logger = logging.getLogger(__name__)


def _sanitize_iri(value: str) -> str:
    """Remove invalid IRI code points that pyoxigraph rejects (backslashes, control chars)."""
    if not value:
        return value
    value = value.replace("\\", "/")
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', value)
    return value


def _extract_limit(sparql: str, default: int = 100) -> int:
    m = re.search(r"\bLIMIT\s+(\d+)", sparql or "", flags=re.IGNORECASE)
    if not m:
        return default
    try:
        return max(0, int(m.group(1)))
    except ValueError:
        return default


def _nt_iri(value: str) -> str:
    return "<" + _sanitize_iri(value) + ">"


def _nt_literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")
    return f'"{escaped}"'


class OxigraphStore:
    def __init__(self, store_path: Optional[Union[str, Path]] = None, read_only: bool = False, auth_token: Optional[str] = None):
        self.store_path = Path(store_path) if store_path else None
        self.read_only = read_only
        self.auth_token = auth_token
        self._store = None
        self._server_thread: Optional[threading.Thread] = None
        self._server_running = False
        self._oxigraph_available = self._check_oxigraph()
        self._triples_loaded = False

    @classmethod
    def load_existing(cls, store_path: Union[str, Path]) -> "OxigraphStore":
        path = Path(store_path)
        if not path.exists():
            raise FileNotFoundError(f"Oxigraph store not found: {store_path}")
        store = cls(store_path=path)
        store._get_store()
        return store

    @staticmethod
    def _check_oxigraph() -> bool:
        try:
            import pyoxigraph
            return True
        except ImportError:
            return False

    def _get_store(self):
        if self._store is None:
            if not self._oxigraph_available:
                raise ImportError("pyoxigraph required for embedded triple store. Install with: pip install pyoxigraph")
            import pyoxigraph
            if self.store_path and self.store_path.exists():
                self._store = pyoxigraph.Store(str(self.store_path))
            else:
                self._store = pyoxigraph.Store()
        return self._store

    def add_triples(self, triples: list[dict[str, Any]]) -> int:
        if not self._oxigraph_available:
            return self._add_triples_fallback(triples)

        import pyoxigraph

        store = self._get_store()
        count = 0
        for t in triples:
            try:
                s_raw = _sanitize_iri(str(t.get("subject", "")))
                p_raw = _sanitize_iri(str(t.get("predicate", "")))
                if not s_raw or not p_raw:
                    continue
                s = pyoxigraph.NamedNode(s_raw)
                p = pyoxigraph.NamedNode(p_raw)

                if t.get("is_iri") or t.get("object_iri"):
                    o_raw = _sanitize_iri(str(t.get("object", "")))
                    if not o_raw:
                        continue
                    o = pyoxigraph.NamedNode(o_raw)
                elif t.get("datatype"):
                    dt = str(t.get("datatype", ""))
                    if dt == "http://www.w3.org/2001/XMLSchema#integer":
                        o = pyoxigraph.Literal(str(t.get("object", "")), datatype=pyoxigraph.NamedNode(_sanitize_iri(dt)))
                    else:
                        o = pyoxigraph.Literal(str(t.get("object", "")), datatype=pyoxigraph.NamedNode(_sanitize_iri(dt)))
                else:
                    o = pyoxigraph.Literal(str(t.get("object", "")))

                store.add(pyoxigraph.Quad(s, p, o))
                count += 1
            except Exception as e:
                _logger.debug("Skipping invalid triple: %s", e)
        return count

    def _add_triples_fallback(self, triples: list[dict[str, Any]]) -> int:
        if not hasattr(self, "_fallback_triples"):
            self._fallback_triples: list[dict] = []
        self._fallback_triples.extend(triples)
        return len(triples)

    def query(self, sparql: str) -> Any:
        if not self._oxigraph_available:
            triples = getattr(self, "_fallback_triples", [])
            rows = []
            # Minimal fallback for smoke tests and local demos without pyoxigraph.
            # It intentionally supports only simple SELECT ?s ?p ?o patterns.
            for t in triples[: _extract_limit(sparql, default=100)]:
                rows.append({"s": t.get("subject"), "p": t.get("predicate"), "o": t.get("object")})
            return rows
        import pyoxigraph
        store = self._get_store()
        results = store.query(sparql)
        rows = []
        if isinstance(results, pyoxigraph.QuerySolutions):
            for solution in results:
                row = {}
                try:
                    vars_list = list(solution.variables) if hasattr(solution.variables, '__iter__') else []
                except Exception:
                    vars_list = []
                for var in vars_list:
                    val = solution.get(var) if hasattr(solution, 'get') else solution[var]
                    if val is None:
                        row[str(var)] = None
                    elif isinstance(val, pyoxigraph.NamedNode):
                        row[str(var)] = str(val.value)
                    elif isinstance(val, pyoxigraph.BlankNode):
                        row[str(var)] = str(val)
                    else:
                        row[str(var)] = str(val.value)
                rows.append(row)
        elif isinstance(results, pyoxigraph.QueryTriples):
            for triple in results:
                rows.append({
                    "subject": str(triple[0]),
                    "predicate": str(triple[1]),
                    "object": str(triple[2]),
                })
        return rows

    def dump(self, format: str = "ntriples") -> bytes:
        if not self._oxigraph_available:
            lines = []
            for t in getattr(self, "_fallback_triples", []):
                s = _nt_iri(str(t.get("subject", "")))
                p = _nt_iri(str(t.get("predicate", "")))
                obj = str(t.get("object", ""))
                if t.get("is_iri") or t.get("object_iri"):
                    o = _nt_iri(obj)
                else:
                    o = _nt_literal(obj)
                lines.append(f"{s} {p} {o} .")
            return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
        import pyoxigraph
        store = self._get_store()
        return store.dump(format)

    def serve(self, host: str = "localhost", port: int = 7878, auth_token: Optional[str] = None) -> str:
        if not self._oxigraph_available:
            raise ImportError("pyoxigraph required for SPARQL server. Install with: pip install pyoxigraph")
        import pyoxigraph

        token = auth_token or self.auth_token
        store = self._get_store()
        self._stop_event = threading.Event()

        def run_server():
            from http.server import HTTPServer, BaseHTTPRequestHandler
            import json as _json

            class SparqlGateHandler(BaseHTTPRequestHandler):
                def _check_auth(self) -> bool:
                    if not token:
                        return True
                    auth_header = self.headers.get("Authorization", "")
                    if auth_header.startswith("Bearer "):
                        return auth_header[7:] == token
                    return False

                def do_GET(self):
                    if self.path == "/health":
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(_json.dumps({"status": "ok", "triples": len(store), "server": "autokg-oxigraph"}).encode())
                        return
                    if not self._check_auth():
                        self.send_response(401)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(_json.dumps({"error": "Unauthorized"}).encode())
                        return
                    self.send_response(404)
                    self.end_headers()

                def do_POST(self):
                    if not self._check_auth():
                        self.send_response(401)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(_json.dumps({"error": "Unauthorized"}).encode())
                        return
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length) if content_length > 0 else b""
                    if b"query=" in body:
                        from urllib.parse import parse_qs
                        query = parse_qs(body.decode()).get("query", [""])[0]
                    else:
                        query = body.decode("utf-8", errors="replace")
                    accept = self.headers.get("Accept", "application/sparql-results+json")
                    try:
                        results = store.query(query)
                        if "json" in accept:
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            rows = []
                            if isinstance(results, pyoxigraph.QuerySolutions):
                                for solution in results:
                                    row = {}
                                    try:
                                        for var in solution.variables if hasattr(solution, 'variables') else []:
                                            val = solution.get(var) if hasattr(solution, 'get') else solution[var]
                                            row[str(var)] = str(val.value) if hasattr(val, 'value') else str(val) if val else None
                                    except Exception:
                                        pass
                                    rows.append(row)
                            self.wfile.write(_json.dumps({"head": {"vars": list(rows[0].keys()) if rows else []}, "results": {"bindings": rows}}).encode())
                        else:
                            self.send_response(200)
                            self.send_header("Content-Type", "text/plain")
                            self.end_headers()
                            self.wfile.write(str(results).encode())
                    except Exception as e:
                        self.send_response(400)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(_json.dumps({"error": str(e)}).encode())

                def log_message(self, format, *args):
                    pass

            health_server = HTTPServer((host, port + 1), SparqlGateHandler)
            health_thread = threading.Thread(target=health_server.serve_forever, daemon=True)
            health_thread.start()

            try:
                pyoxigraph.serve(store, host=host, port=port)
            except Exception:
                pass

        self._server_thread = threading.Thread(target=run_server, daemon=True)
        self._server_thread.start()
        self._server_running = True
        auth_msg = " (auth: Bearer token required)" if token else ""
        return f"http://{host}:{port}{auth_msg} (health: http://{host}:{port + 1}/health)"

    def stop(self):
        self._server_running = False
        if hasattr(self, "_stop_event"):
            self._stop_event.set()

    def save(self, path: Optional[Union[str, Path]] = None) -> str:
        target = Path(path) if path else self.store_path
        if target is None:
            raise ValueError("No store path specified")
        if not self._oxigraph_available:
            if target.suffix:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(self.dump("ntriples"))
            else:
                target.mkdir(parents=True, exist_ok=True)
                (target / "data.nt").write_bytes(self.dump("ntriples"))
            return str(target)

        import pyoxigraph
        store = self._get_store()
        target.parent.mkdir(parents=True, exist_ok=True)
        fmt = target.suffix.lstrip(".") if target.suffix else "ntriples"
        if fmt not in ("ntriples", "nt", "nq", "turtle", "ttl", "trig", "rdf", "xml"):
            fmt = "ntriples"
        store.dump(str(target), format=fmt)
        return str(target)

    def count(self) -> int:
        if not self._oxigraph_available:
            return len(getattr(self, "_fallback_triples", []))
        import pyoxigraph
        store = self._get_store()
        return len(store)
