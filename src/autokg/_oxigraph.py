from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional, Union


class OxigraphStore:
    def __init__(self, store_path: Optional[Union[str, Path]] = None, read_only: bool = False):
        self.store_path = Path(store_path) if store_path else None
        self.read_only = read_only
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
            s = pyoxigraph.NamedNode(t.get("subject", ""))
            p = pyoxigraph.NamedNode(t.get("predicate", ""))

            if t.get("is_iri") or t.get("object_iri"):
                o = pyoxigraph.NamedNode(t.get("object", ""))
            elif t.get("datatype"):
                dt = t.get("datatype", "")
                if dt == "http://www.w3.org/2001/XMLSchema#integer":
                    o = pyoxigraph.Literal(t.get("object", ""), datatype=pyoxigraph.NamedNode(dt))
                else:
                    o = pyoxigraph.Literal(str(t.get("object", "")), datatype=pyoxigraph.NamedNode(dt))
            else:
                o = pyoxigraph.Literal(str(t.get("object", "")))

            store.add(pyoxigraph.Quad(s, p, o))
            count += 1
        return count

    def _add_triples_fallback(self, triples: list[dict[str, Any]]) -> int:
        if not hasattr(self, "_fallback_triples"):
            self._fallback_triples: list[dict] = []
        self._fallback_triples.extend(triples)
        return len(triples)

    def query(self, sparql: str) -> Any:
        if not self._oxigraph_available:
            return []
        import pyoxigraph
        store = self._get_store()
        results = store.query(sparql)
        rows = []
        if isinstance(results, pyoxigraph.QuerySolutions):
            for solution in results:
                row = {}
                for var in solution.variables:
                    val = solution[var]
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
            return b""
        import pyoxigraph
        store = self._get_store()
        return store.dump(format)

    def serve(self, host: str = "localhost", port: int = 7878) -> str:
        if not self._oxigraph_available:
            raise ImportError("pyoxigraph required for SPARQL server. Install with: pip install pyoxigraph")
        import pyoxigraph

        store = self._get_store()
        self._stop_event = threading.Event()

        def run_server():
            from http.server import HTTPServer, BaseHTTPRequestHandler
            import json as _json

            class HealthHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path == "/health":
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(_json.dumps({"status": "ok", "triples": len(store), "server": "autokg-oxigraph"}).encode())
                    else:
                        self.send_response(404)
                        self.end_headers()
                def log_message(self, format, *args):
                    pass

            health_server = HTTPServer((host, port + 1), HealthHandler)
            health_thread = threading.Thread(target=health_server.serve_forever, daemon=True)
            health_thread.start()

            try:
                pyoxigraph.serve(store, host=host, port=port)
            except Exception:
                pass

        self._server_thread = threading.Thread(target=run_server, daemon=True)
        self._server_thread.start()
        self._server_running = True
        return f"http://{host}:{port} (health: http://{host}:{port + 1})"

    def stop(self):
        self._server_running = False
        if hasattr(self, "_stop_event"):
            self._stop_event.set()

    def save(self, path: Optional[Union[str, Path]] = None) -> str:
        target = Path(path) if path else self.store_path
        if target is None:
            raise ValueError("No store path specified")
        if not self._oxigraph_available:
            return str(target)

        import pyoxigraph
        store = self._get_store()
        data = store.dump("ntriples")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return str(target)

    def count(self) -> int:
        if not self._oxigraph_available:
            return len(getattr(self, "_fallback_triples", []))
        import pyoxigraph
        store = self._get_store()
        return len(store)
