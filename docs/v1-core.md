# autokg v1 Core

`autokg` v1 core is a deterministic, self-contained, platform-agnostic, LLM-agnostic table-to-knowledge-graph compiler.

## Contract

Input:

- table definitions
- primary keys
- manual relationship declarations
- optional column/property/PII policies

Output:

- `graph.ttl`
- `graph.jsonld`
- `graph.nt`
- `graph.rdf`
- `ontology.ttl`
- `manifest.json`
- `lineage.json`
- `audit.jsonl`
- `validation_report.json`
- `build_report.html`
- optional local `store/`

No LLM API key is required. No cloud platform is required.

## Commands

```bash
autokg init customer360
cd autokg_project
python make_demo_data.py
autokg validate -c autokg.yml
autokg build -c autokg.yml
autokg inspect gold
autokg report gold
```

## Config shape

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
      email: {property: schema:email, pii: true, pii_type: email, mask: hash}

  - name: orders
    source: silver/orders.csv
    entity: Order
    primary_key: order_id

relationships:
  - name: order_placed_by_customer
    from: {table: orders, column: customer_id}
    to: {table: customers, column: customer_id}
    predicate: ex:placedBy
    cardinality: many_to_one
    required: true
    declared_by: data-platform@example.com
    ticket: DEMO-1
    description: An order is placed by a customer.

outputs:
  rdf:
    enabled: true
    formats: [turtle, jsonld, ntriples, rdfxml]

store:
  enabled: true
  type: local
  path: gold/store
```
