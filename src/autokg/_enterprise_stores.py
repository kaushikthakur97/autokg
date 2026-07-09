from __future__ import annotations

import base64
import urllib.request
from pathlib import Path
from typing import Any

from ._stores import RemoteSPARQLStore


class GraphDBStore(RemoteSPARQLStore):
    def __init__(self, base_url: str, repository: str, *, username: str | None = None, password: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.repository = repository
        self.username = username
        self.password = password
        super().__init__(f"{self.base_url}/repositories/{repository}")

    def upload_file(self, path: str | Path, graph_uri: str | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/repositories/{self.repository}/statements"
        if graph_uri:
            url += f"?context=<{graph_uri}>"
        return _upload_rdf(url, path, self.username, self.password)


class StardogStore(RemoteSPARQLStore):
    def __init__(self, base_url: str, database: str, *, username: str | None = None, password: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.database = database
        self.username = username
        self.password = password
        super().__init__(f"{self.base_url}/{database}/query")

    def upload_file(self, path: str | Path, graph_uri: str | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/{self.database}/add"
        if graph_uri:
            url += f"?graph-uri={graph_uri}"
        return _upload_rdf(url, path, self.username, self.password)


class NeptuneStore(RemoteSPARQLStore):
    def __init__(self, endpoint: str, *, auth_token: str | None = None):
        endpoint = endpoint.rstrip("/")
        if not endpoint.endswith("/sparql"):
            endpoint = endpoint + "/sparql"
        super().__init__(endpoint, auth_token=auth_token)

    def upload_file(self, path: str | Path, graph_uri: str | None = None) -> dict[str, Any]:
        # Neptune bulk loader is S3/IAM based; this supports small graph-store protocol uploads.
        return _upload_rdf(self.endpoint, path, None, None, auth_token=self.auth_token)


def _upload_rdf(url: str, path: str | Path, username: str | None = None, password: str | None = None, auth_token: str | None = None) -> dict[str, Any]:
    p = Path(path)
    data = p.read_bytes()
    req = urllib.request.Request(url, data=data, method="POST")
    content_type = "text/turtle" if p.suffix in {".ttl", ".turtle"} else "application/n-triples" if p.suffix == ".nt" else "application/rdf+xml"
    req.add_header("Content-Type", content_type)
    if username is not None and password is not None:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    if auth_token:
        req.add_header("Authorization", f"Bearer {auth_token}")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return {"status": resp.status, "reason": resp.reason, "url": url, "bytes": len(data)}
