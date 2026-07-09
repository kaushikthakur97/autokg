# autokg

**Turn warehouse/lakehouse tables into a governed knowledge graph for AI agents.**

`autokg` builds an explicit entity-relationship graph from Parquet, Delta, CSV, SQL, dbt-style config, or DataFrames, then exposes it through **MCP**, SPARQL, JSON-LD, and Python APIs. Agents can answer multi-table business questions without hard-coded SQL joins or giant schema prompts — with lineage, PII masking, and audit trails built in.

```bash
pip install autokg

autokg init customer360
cd autokg_project
python make_demo_data.py
autokg build -c autokg.yml
autokg mcp --store gold/store --stdio
```

Ask Claude Desktop, Cursor, or any MCP client:

> “Show me Customer C001 and every related order/product. Explain the graph path and source tables.”

---

## Why this exists

Enterprises are connecting AI agents to data warehouses, but agents do not understand schemas, joins, governance, or lineage. Teams compensate with brittle SQL tools, giant prompt context, and one-off RAG pipelines.

`autokg` makes relationships reusable infrastructure:

| Before | After autokg |
|---|---|
| Agents need massive table-schema prompts | Agents discover entities and relationships through MCP |
| Joins are duplicated in dashboards, notebooks, and agent tools | Relationships are declared once and reused everywhere |
| Catalogs describe data but do not make entity relationships executable | autokg creates a runtime knowledge graph |
| PII review and audit evidence are manual | PII policy, lineage, and audit trail ship with the graph |

---

## The product wedge

**Agent-ready semantic layer for structured enterprise data.**

`autokg` is not a warehouse, catalog, vector database, or graph database replacement. It is the compiler between your curated tables and every downstream consumer that needs entity knowledge.

```text
Parquet / Delta / CSV / SQL / dbt
        ↓
      autokg
        ↓
Governed RDF knowledge graph
        ↓
MCP agents · SPARQL · JSON-LD · Python · dashboards
```

---

## Five-minute demo

```bash
pip install autokg

autokg init insurance -o insurance_demo
cd insurance_demo
python make_demo_data.py

autokg build -c autokg.yml
autokg studio -c autokg.yml -o studio.html
autokg mcp --store gold/store --stdio
```

The generated `autokg.yml` is declarative and auditable:

```yaml
namespace: https://demo.autokg.ai/insurance
actor: data-platform@example.com
strict: true
store: gold/store
incremental: true

sources:
  - name: customers
    path: silver/customers.csv
    entity: Customer
    id_column: customer_id
    pii_policy: {strategy: hash}

  - name: policies
    path: silver/policies.csv
    entity: Policy
    id_column: policy_id

relationships:
  - from_table: policies
    from_column: customer_id
    to_table: customers
    to_column: customer_id
    declared_by: data-platform@example.com
    ticket_ref: DEMO-1
    justification: A policy belongs to a customer.
```

---

## Core capabilities

- **Table-to-graph generation** from Parquet, Delta, CSV, SQL, Polars, Pandas, and config files.
- **Accountable relationships** with `declared_by`, `ticket_ref`, and justification.
- **MCP server** for Claude Desktop, Cursor, Continue, and custom agents.
- **Embedded SPARQL** via Oxigraph plus file exports: Turtle, JSON-LD, N-Triples, RDF/XML.
- **PII detection and masking** before graph storage.
- **Audit and lineage** for builds, source additions, relationship declarations, and policies.
- **Incremental builds** using manifest-based change detection.
- **Conversation and natural-language query layer** for agent workflows.
- **Static Studio dashboard** for demos and project review.

---

## CLI

```bash
# Create a starter project
autokg init customer360 -o demo

# Build from auditable YAML
autokg build -c autokg.yml

# Build directly from files
autokg build silver/*.parquet -o gold/graph.ttl --format turtle

# Start MCP server for agents
autokg mcp --store gold/store --stdio
autokg mcp --store gold/store --port 9000 --auth-token "$AUTOKG_MCP_TOKEN"

# Start SPARQL endpoint
autokg serve gold/store --port 7878 --auth-token "$AUTOKG_TOKEN"

# Static dashboard
autokg studio -c autokg.yml -o studio.html
```

---

## Python API

```python
from autokg import KnowledgeGraph

kg = KnowledgeGraph(namespace="https://myco.example/kg", actor="alice@myco.example")
kg.add_table("silver/customers.parquet", source_name="customers", entity_type="Customer", id_column="customer_id")
kg.add_table("silver/orders.parquet", source_name="orders", entity_type="Order", id_column="order_id")

kg.declare_relationship(
    "orders", "customer_id", "customers",
    target_column="customer_id",
    declared_by="alice@myco.example",
    ticket_ref="DATA-4421",
    justification="A customer places orders."
)

kg.build()
kg.write("gold/graph.ttl")
kg.save_store("gold/store")
```

---

## MCP agent setup

Claude Desktop config example:

```json
{
  "mcpServers": {
    "autokg": {
      "command": "autokg",
      "args": ["mcp", "--store", "/absolute/path/to/gold/store", "--stdio"]
    }
  }
}
```

HTTP mode for remote/dev deployments:

```bash
autokg mcp --store gold/store --port 9000 --auth-token "$AUTOKG_MCP_TOKEN"
```

---

## Installation

```bash
pip install autokg                    # core
pip install "autokg[oxigraph,mcp]"    # production MCP/SPARQL
pip install "autokg[all]"             # all optional integrations
```

Python 3.10+. Linux, macOS, Windows.

---

## Examples and docs

- `examples/customer360` — customer/order/product graph
- `examples/insurance` — customer/policy/claim graph
- `docs/config-yaml.md` — declarative build config
- `docs/mcp.md` — MCP server deployment
- `docs/go-to-market.md` — pilot and GTM package
- `site/index.html` — landing page

---

## Roadmap

See [`ROADMAP.md`](ROADMAP.md). Near-term priorities: dbt connector, Databricks quickstart, enterprise MCP gateway, RBAC/OIDC, Helm chart, and large-scale benchmarks.

---

## License

Apache 2.0.
