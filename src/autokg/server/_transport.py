from __future__ import annotations

import asyncio
import json
import logging
import sys
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


def run_http(knowledge_graph, host: str = "0.0.0.0", port: int = 9000, server_class=None):
    try:
        from aiohttp import web
    except ImportError:
        raise ImportError("aiohttp required for HTTP MCP mode. Install with: pip install aiohttp")

    if server_class is None:
        from ._mcp import MCPServer
        server_class = MCPServer

    server = server_class(knowledge_graph)

    async def handle_mcp(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            body = await request.text()
            if isinstance(body, str) and body.strip():
                try:
                    body = json.loads(body)
                except json.JSONDecodeError:
                    return web.json_response({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None})

        session_id = request.headers.get("X-Session-Id", "default")
        if isinstance(body, list):
            responses = [server.handle_jsonrpc(json.dumps(msg), session_id) for msg in body]
            return web.json_response([json.loads(r) if r else {} for r in responses])
        else:
            response = server.handle_jsonrpc(json.dumps(body) if not isinstance(body, str) else body, session_id)
            if response:
                return web.json_response(json.loads(response))
            return web.json_response({})

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "server": "autokg-mcp"})

    app = web.Application()
    app.router.add_post("/", handle_mcp)
    app.router.add_post("/mcp", handle_mcp)
    app.router.add_get("/health", health)

    _logger.info("MCP server starting in HTTP mode on %s:%d", host, port)
    web.run_app(app, host=host, port=port)
