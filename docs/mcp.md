# MCP server

The MCP server exposes the built autokg graph package to Claude Desktop, Cursor, and any MCP-compatible agent.

```bash
autokg build -c autokg.yml
autokg mcp --store gold/store --stdio
```

HTTP mode:

```bash
autokg mcp --store gold/store --port 9000 --auth-token "$AUTOKG_MCP_TOKEN"
```

## Tool groups

### Schema and discovery

```text
get_schema
list_sources
search_entities
get_entity
get_related
get_manifest
get_lineage
get_audit_log
```

### SPARQL and natural language

```text
generate_sparql
validate_sparql
execute_sparql
query_graph
ask_graph
```

### Conversation

```text
start_session
```

`ask_graph` uses the same query backend as the CLI and REST API:

```text
question → schema context → NL→SPARQL → validation → execution → evidence
```

By default, the query backend uses a deterministic mock/rule provider. To use an LLM through MCP, pass an `llm` object in the tool arguments:

```json
{
  "question": "Show VIP customers who bought high-risk products",
  "session_id": "demo",
  "llm": {
    "provider": "ollama",
    "model": "llama3.1",
    "endpoint": "http://localhost:11434/api/chat"
  }
}
```

Supported providers:

```text
mock
openai
anthropic
gemini
ollama
custom_http
```

## Production controls

- Use `--auth-token` for HTTP mode.
- Put HTTP MCP behind TLS or an identity-aware proxy.
- Keep graph operations read-only by default.
- Validate generated SPARQL before execution.
- Audit MCP tool calls.
