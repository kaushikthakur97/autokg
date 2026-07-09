# autokg

**The backend that turns ordinary tables into an AI-queryable knowledge graph.**

`autokg` is a self-contained, platform-agnostic, LLM-agnostic graph compiler and query backend. Define your **tables**, **primary keys**, and **manual relationships** once. `autokg` builds a governed RDF knowledge graph and serves it through SPARQL, REST APIs, and MCP tools for LLMs and agents.

```bash
pip install autokg

autokg init customer360
cd autokg_project
python make_demo_data.py

autokg validate -c autokg.yml
autokg build -c autokg.yml
autokg ask gold "show customers"
autokg api gold --port 8080
autokg mcp --store gold/store --stdio
```

No warehouse lock-in. No LLM lock-in. No cloud requirement. No hidden schema guessing in production.

---

## What autokg gives you

```text
Input
  CSV / Parquet / DataFrames / optional database connectors
  + manually declared relationships
  + optional column and PII policies

Output
  governed knowledge graph package
  + SPARQL query backend
  + REST API
  + MCP tools for LLMs and agents
  + optional NL → SPARQL generation
  + multi-turn graph conversation
```

A build creates:

```text
gold/
  graph.ttl
  graph.jsonld
  graph.nt
  graph.rdf
  ontology.ttl
  shapes.ttl
  manifest.json
  lineage.json
  audit.jsonl
  validation_report.json
  build_report.html
  store/
```

---

## Why teams need this

LLMs and agents do not naturally understand enterprise data models. They need a safe backend that knows:

- which tables exist
- which columns identify entities
- which relationships are valid
- which fields are PII
- how entities connect across tables
- how to query the graph without inventing joins or predicates

`autokg` converts that knowledge into infrastructure.

| Without autokg | With autokg |
|---|---|
| Agents need huge schema prompts | Agents call MCP tools backed by a graph schema |
| SQL joins are rewritten everywhere | Relationships are declared once and reused |
| RAG retrieves text but misses entity relationships | SPARQL traverses explicit relationships |
| Governance is bolted on later | PII, lineage, audit, and validation ship with the graph |
| LLM vendor choice leaks into architecture | LLM providers are adapters, not core dependencies |

---

## Core product model

`autokg` has two layers.

### 1. Deterministic graph compiler

```text
tables + primary keys + manual relationships → RDF knowledge graph
```

This layer is fully deterministic and requires **no LLM**.

### 2. Query backend for apps and agents

```text
knowledge graph → SPARQL / REST / MCP / NL→SPARQL / multi-turn chat
```

This layer can optionally use any LLM provider through adapters.

Supported provider architecture:

```text
mock/rule-based
OpenAI
Anthropic
Gemini
Ollama
custom HTTP endpoint
```

---

## Five-minute demo

```bash
autokg init customer360 -o demo
cd demo
python make_demo_data.py

autokg validate -c autokg.yml
autokg build -c autokg.yml
autokg inspect gold
autokg report gold
```

Ask the graph:

```bash
autokg ask gold "show customers"
```

Generate SPARQL from natural language:

```bash
autokg generate-sparql gold "show customers"
```

Start the REST backend:

```bash
autokg api gold --port 8080
```

Start MCP for Claude Desktop, Cursor, or another MCP client:

```bash
autokg mcp --store gold/store --stdio
```

---

## Production `autokg.yml`

Users define tables and relationships manually. autokg validates them strictly.

```yaml
project:
  name: customer360-demo
  namespace: https://demo.autokg.ai/customer360
  output_dir: gold
  strict: true
  fail_on_invalid_fk: true
  fail_on_missing_pk: true
  fail_on_duplicate_pk: true

tables:
  - name: customers
    source: silver/customers.csv
    entity: Customer
    primary_key: customer_id
    columns:
      customer_id: {property: schema:identifier, required: true}
      name: {property: schema:name, pii: true, pii_type: person_name, mask: partial}
      email: {property: schema:email, pii: true, pii_type: email, mask: hash}
      segment: {property: ex:segment}

  - name: orders
    source: silver/orders.csv
    entity: Order
    primary_key: order_id
    columns:
      order_id: {property: schema:identifier, required: true}
      amount: {property: schema:price, type: decimal}

  - name: products
    source: silver/products.csv
    entity: Product
    primary_key: product_id

relationships:
  - name: order_placed_by_customer
    from: {table: orders, column: customer_id}
    to: {table: customers, column: customer_id}
    predicate: ex:placedBy
    inverse_predicate: ex:placedOrder
    cardinality: many_to_one
    required: true
    declared_by: data-platform@example.com
    ticket: DEMO-1
    description: An order is placed by a customer.

  - name: order_contains_product
    from: {table: orders, column: product_id}
    to: {table: products, column: product_id}
    predicate: ex:containsProduct
    cardinality: many_to_one
    required: true
    declared_by: data-platform@example.com
    ticket: DEMO-2
    description: An order contains a product.

outputs:
  rdf:
    enabled: true
    formats: [turtle, jsonld, ntriples, rdfxml]
  report: {enabled: true}

store:
  enabled: true
  type: local
  path: gold/store
```

---

## Query backend

The query backend makes the graph useful to applications and LLMs.

### Natural language to SPARQL

```bash
autokg generate-sparql gold "show VIP customers who bought high-risk products"
```

Provider examples:

```bash
# Local Ollama
autokg ask gold "show VIP customers" --llm-provider ollama --model llama3.1

# OpenAI
OPENAI_API_KEY=... autokg ask gold "show risky orders" --llm-provider openai --model gpt-4o

# Anthropic
ANTHROPIC_API_KEY=... autokg ask gold "show claims by customer" --llm-provider anthropic --model claude-3-5-sonnet-latest

# Custom HTTP endpoint
autokg ask gold "show connected entities" --llm-provider custom_http --endpoint http://localhost:8000/chat
```

Every generated SPARQL query is validated before execution:

- read-only queries only by default
- blocks `INSERT`, `DELETE`, `LOAD`, `CLEAR`, `DROP`, and `SERVICE`
- parses SPARQL before execution
- adds safe limits
- returns evidence from schema and lineage

---

## Multi-turn conversation

`autokg` supports session-based graph conversation.

```bash
autokg chat gold --llm-provider ollama --model llama3.1
```

Example:

```text
User: Show customers who bought high-risk products.
User: Only VIP ones.
User: Show their orders above 1000.
```

The backend stores previous turns, generated SPARQL, row samples, and active evidence so follow-up questions can be resolved with context.

---

## REST API

Start the backend:

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
GET  /metrics
GET  /openapi.json
POST /sparql/generate
POST /sparql/validate
POST /sparql/execute
POST /ask
POST /sessions
POST /sessions/{session_id}/ask
```

Example:

```bash
curl -X POST http://localhost:8080/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"show customers"}'
```

---

## MCP for LLMs and agents

MCP lets Claude Desktop, Cursor, and other MCP-compatible agents use the graph backend as tools.

```bash
autokg mcp --store gold/store --stdio
```

Available MCP tool categories:

```text
Schema:
  get_schema
  list_sources
  list_relationships

SPARQL:
  generate_sparql
  validate_sparql
  execute_sparql
  query_graph

Natural language:
  ask_graph
  ask_question

Conversation:
  start_session

Governance:
  get_lineage
  get_manifest
  get_audit_log
```

The MCP layer is only an interface. The same query engine also powers CLI and REST.

---

## Installation

```bash
pip install autokg
pip install "autokg[mcp]"
pip install "autokg[all]"
```

Core dependencies are intentionally small. Cloud/database connectors are optional.

---

Advanced backend additions:

```text
Semantic entity linking:
  aliases, glossary hooks, value linking, schema term linking

Query planning:
  deterministic entity/relationship path planner before LLM fallback

RBAC/ABAC:
  role policies for entity/property filtering, masking, max rows

Distributed builds:
  local partition coordinator with Ray/Dask/Spark-ready backend interface

Enterprise graph stores:
  GraphDB, Stardog, and Neptune upload/query adapters

Studio:
  richer browser dashboard with tabs, validation, lineage, manifest, and API query playground
```

---

## Optional extras

```text
autokg[mcp]       MCP server transport
autokg[query]     query backend / SPARQL execution
autokg[api]       REST API backend
autokg[oxigraph]  embedded graph store
autokg[sql]       SQLAlchemy-based sources
autokg[snowflake] Snowflake input connector
autokg[delta]     Delta Lake input connector
autokg[semantic]  semantic/entity search extras
autokg[all]       everything
```

---

## What autokg is not

`autokg` is not trying to replace:

- your warehouse
- your lakehouse
- your data catalog
- your LLM
- your vector database
- your BI tool

It gives them a governed graph backend they can all use.

---

## Best-in-class backend features now included

`autokg` now includes the production hardening pieces required for a serious backend product:

```text
Schema contract:
  autokg schema export → JSON Schema for IDEs/CI

Semantic contract:
  ontology.ttl + shapes.ttl generated from autokg.yml

Query reliability:
  NL→SPARQL → safety validation → execution → evidence

Evaluation:
  autokg eval gold evals/customer360/questions.yml

Security guardrails:
  read-only SPARQL policy, blocked update operations, max rows, query audit

Observability:
  query_audit.jsonl, metrics registry, /metrics endpoint

Store abstraction:
  RDFLib local graph store and remote SPARQL store interface

Benchmarking:
  autokg benchmark --rows 100000

API contract:
  REST API exposes /openapi.json
```

Useful commands:

```bash
autokg schema export -o autokg.schema.json
autokg ontology -c autokg.yml
autokg eval gold evals/customer360/questions.yml
autokg benchmark --rows 10000
autokg doctor
autokg distributed-build -c autokg.yml --partitions 8
autokg push-store graphdb gold/graph.ttl --base-url http://localhost:7200 --repository repo
```

---

## Current status

`autokg` now includes:

- v1 deterministic graph compiler
- production `autokg.yml`
- strict relationship validation
- RDF/JSON-LD/N-Triples/RDF-XML output
- ontology and SHACL generation
- manifest, lineage, audit, validation report
- HTML build report
- REST query backend
- NL → SPARQL provider abstraction
- MCP tools for graph querying
- multi-turn session memory
- Docker and CI scaffolding
- JSON Schema export, eval runner, benchmark command, query observability

See:

- [`docs/v1-core.md`](docs/v1-core.md)
- [`docs/config-yaml.md`](docs/config-yaml.md)
- [`docs/query-backend.md`](docs/query-backend.md)
- [`docs/mcp.md`](docs/mcp.md)
- [`docs/production-hardening.md`](docs/production-hardening.md)
- [`docs/stores.md`](docs/stores.md)
- [`docs/best-in-class-roadmap.md`](docs/best-in-class-roadmap.md)
- [`docs/advanced-query-planning.md`](docs/advanced-query-planning.md)
- [`docs/rbac-abac.md`](docs/rbac-abac.md)
- [`docs/distributed-builds.md`](docs/distributed-builds.md)
- [`docs/enterprise-stores.md`](docs/enterprise-stores.md)

---

## License

Apache 2.0.
