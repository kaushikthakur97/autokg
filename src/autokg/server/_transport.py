from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

_logger = logging.getLogger(__name__)


def run_stdio(knowledge_graph, server_class=None):
    if server_class is None:
        from ._mcp import MCPServer
        server_class = MCPServer
    server = server_class(knowledge_graph)
    _logger.info("MCP server starting in stdio mode")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        response = server.handle_jsonrpc(line)
        if response:
            sys.stdout.write(response + "\n")
            sys.stdout.flush()


def run_http(knowledge_graph, host="0.0.0.0", port=9000, server_class=None,
             auth_token=None, tls_cert=None, tls_key=None,
             cors_origins="*", rate_limit_rpm=100):
    try:
        from aiohttp import web
    except ImportError:
        raise ImportError("aiohttp required for HTTP MCP mode. pip install aiohttp")

    if server_class is None:
        from ._mcp import MCPServer
        server_class = MCPServer

    server = server_class(knowledge_graph)
    _rate_limits: dict[str, list[float]] = {}

    def _check_rate_limit(session_id: str) -> tuple[bool, int]:
        now = time.monotonic()
        if session_id not in _rate_limits:
            _rate_limits[session_id] = []
        window = [t for t in _rate_limits[session_id] if now - t < 60]
        _rate_limits[session_id] = window
        if len(window) >= rate_limit_rpm:
            return False, 429
        window.append(now)
        return True, 200

    def _check_auth(request: web.Request) -> bool:
        if not auth_token:
            return True
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:] == auth_token
        return False

    async def handle_mcp(request: web.Request) -> web.Response:
        if not _check_auth(request):
            return web.json_response({"jsonrpc": "2.0", "error": {"code": -32000, "message": "Unauthorized"}, "id": None}, status=401)

        session_id = request.headers.get("X-Session-Id", "default")
        ok, status = _check_rate_limit(session_id)
        if not ok:
            return web.json_response({"jsonrpc": "2.0", "error": {"code": -32001, "message": "Rate limit exceeded"}, "id": None}, status=429)

        try:
            body = await request.json()
        except Exception:
            body = await request.text()
            if isinstance(body, str) and body.strip():
                try:
                    body = json.loads(body)
                except json.JSONDecodeError:
                    return web.json_response({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None})

        if isinstance(body, list):
            responses = [server.handle_jsonrpc(json.dumps(msg), session_id) for msg in body]
            return web.json_response([json.loads(r) if r else {} for r in responses])
        else:
            response = server.handle_jsonrpc(json.dumps(body) if not isinstance(body, str) else body, session_id)
            if response:
                return web.json_response(json.loads(response))
            return web.json_response({})

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "server": "autokg-mcp", "tools": len(server.get_or_create_session().kg._mapper.get_triples()) if hasattr(server, "get_or_create_session") else 0})

    app = web.Application()

    cors_kwargs = {}
    if cors_origins:
        try:
            import aiohttp_cors
            cors = aiohttp_cors.setup(app, defaults={cors_origins: aiohttp_cors.ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*")})
            cors_kwargs["cors"] = cors
        except ImportError:
            _logger.info("aiohttp-cors not installed. CORS disabled. pip install aiohttp-cors")

    app.router.add_post("/", handle_mcp)
    app.router.add_post("/mcp", handle_mcp)
    app.router.add_get("/health", health)

    ssl_context = None
    if tls_cert and tls_key:
        import ssl
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(tls_cert, tls_key)

    _logger.info("MCP server starting on %s:%d (auth=%s, tls=%s, cors=%s)", host, port, bool(auth_token), bool(ssl_context), cors_origins)
    web.run_app(app, host=host, port=port, ssl_context=ssl_context)
