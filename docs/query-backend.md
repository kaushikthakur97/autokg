# Query backend

The query backend turns a built `gold/` graph package into a backend for humans, APIs, and LLM agents.

## Capabilities

- schema index from `manifest.json` and `lineage.json`
- SPARQL validation and safety checks
- SPARQL execution through RDFLib
- NL → SPARQL generation
- LLM provider abstraction
- REST API
- MCP tools
- multi-turn sessions

## CLI

```bash
autokg generate-sparql gold "show customers"
autokg ask gold "show customers"
autokg chat gold
autokg api gold --port 8080
```

## LLM providers

```bash
autokg ask gold "show risky orders" --llm-provider mock
autokg ask gold "show risky orders" --llm-provider ollama --model llama3.1
autokg ask gold "show risky orders" --llm-provider openai --model gpt-4o
autokg ask gold "show risky orders" --llm-provider anthropic --model claude-3-5-sonnet-latest
autokg ask gold "show risky orders" --llm-provider gemini --model gemini-1.5-pro
autokg ask gold "show risky orders" --llm-provider custom_http --endpoint http://localhost:8000/chat
```

## REST API

```bash
autokg api gold --port 8080 --auth-token "$AUTOKG_API_TOKEN"
```

Endpoints:

```text
GET  /health
GET  /schema
GET  /relationships
GET  /manifest
GET  /lineage
POST /sparql/generate
POST /sparql/validate
POST /sparql/execute
POST /ask
POST /sessions
POST /sessions/{session_id}/ask
```

## Safety

The validator blocks update/federated operations by default:

```text
INSERT DELETE LOAD CLEAR CREATE DROP MOVE COPY ADD SERVICE
```

It also parses generated SPARQL and adds safe `LIMIT` clauses to SELECT queries.
