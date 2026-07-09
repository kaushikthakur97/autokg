from __future__ import annotations

import json
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class GraphStore(ABC):
    @abstractmethod
    def query(self, sparql: str) -> list[dict[str, Any]]: ...
    @abstractmethod
    def count(self) -> int: ...
    @abstractmethod
    def health(self) -> dict[str, Any]: ...


class RDFLibGraphStore(GraphStore):
    def __init__(self, output_dir: str | Path):
        from ._query_backend import SparqlExecutor
        self.executor = SparqlExecutor(output_dir)
        self.output_dir = Path(output_dir)

    def query(self, sparql: str) -> list[dict[str, Any]]:
        return self.executor.execute(sparql)

    def count(self) -> int:
        return len(self.executor._load_graph())

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "backend": "rdflib", "triples": self.count(), "output_dir": str(self.output_dir)}


class RemoteSPARQLStore(GraphStore):
    def __init__(self, endpoint: str, auth_token: str | None = None):
        self.endpoint = endpoint
        self.auth_token = auth_token

    def query(self, sparql: str) -> list[dict[str, Any]]:
        data = urllib.parse.urlencode({"query": sparql}).encode()
        req = urllib.request.Request(self.endpoint, data=data, method="POST")
        req.add_header("Accept", "application/sparql-results+json")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        if self.auth_token:
            req.add_header("Authorization", f"Bearer {self.auth_token}")
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        vars_ = payload.get("head", {}).get("vars", [])
        rows = []
        for b in payload.get("results", {}).get("bindings", []):
            rows.append({v: b.get(v, {}).get("value") for v in vars_})
        return rows

    def count(self) -> int:
        rows = self.query("SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }")
        try:
            return int(rows[0].get("count", 0))
        except Exception:
            return 0

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "backend": "remote_sparql", "endpoint": self.endpoint, "triples": self.count()}
