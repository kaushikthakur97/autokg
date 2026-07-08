from __future__ import annotations

import json
import logging
import sys
from typing import Any, Optional

from ._tools import TOOL_REGISTRY
from ._session import ConversationContext

_logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"


class MCPSession:
    def __init__(self, knowledge_graph):
        self.kg = knowledge_graph
        self.context = ConversationContext()
        self._initialized = False
        self._server_info = {
            "name": "autokg-mcp",
            "version": "0.2.0",
        }
        self._capabilities = {
            "tools": {"listChanged": False},
        }

    def handle_message(self, message: dict) -> Optional[dict]:
        method = message.get("method", "")
        msg_id = message.get("id")
        params = message.get("params", {})

        try:
            if method == "initialize":
                result = self._handle_initialize(params)
            elif method == "tools/list":
                result = self._handle_list_tools()
            elif method == "tools/call":
                result = self._handle_call_tool(params)
            elif method == "notifications/initialized":
                return None
            elif method == "ping":
                result = {}
            else:
                return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        except Exception as e:
            _logger.error("Error handling method %s: %s", method, e, exc_info=True)
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": str(e)}}

        if msg_id is not None:
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        return None

    def _handle_initialize(self, params: dict) -> dict:
        self._initialized = True
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "serverInfo": self._server_info,
            "capabilities": self._capabilities,
        }

    def _handle_list_tools(self) -> dict:
        tools = []
        for name, tool_info in sorted(TOOL_REGISTRY.items()):
            tools.append({
                "name": name,
                "description": tool_info["description"],
                "inputSchema": tool_info["input_schema"],
            })
        return {"tools": tools}

    def _handle_call_tool(self, params: dict) -> dict:
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        if tool_name not in TOOL_REGISTRY:
            return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}

        tool_info = TOOL_REGISTRY[tool_name]
        handler = tool_info["handler"]

        try:
            result = handler(self.kg, self.context, tool_args)
            if isinstance(result, dict) and "error" in result:
                return {"content": [{"type": "text", "text": result["error"]}], "isError": True}
            return {"content": [{"type": "text", "text": json.dumps(result, default=str, indent=2)}]}
        except Exception as e:
            _logger.error("Tool %s failed: %s", tool_name, e, exc_info=True)
            return {"content": [{"type": "text", "text": f"Tool error: {e}"}], "isError": True}


class MCPServer:
    def __init__(self, knowledge_graph):
        self.kg = knowledge_graph
        self._sessions: dict[str, MCPSession] = {}

    def get_or_create_session(self, session_id: str = "default") -> MCPSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = MCPSession(self.kg)
        return self._sessions[session_id]

    def handle_jsonrpc(self, line: str, session_id: str = "default") -> Optional[str]:
        if not line.strip():
            return None
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _logger.warning("Invalid JSON-RPC message: %s", line[:200])
            return json.dumps({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None})
        session = self.get_or_create_session(session_id)
        result = session.handle_message(message)
        if result is not None:
            return json.dumps(result)
        return None
