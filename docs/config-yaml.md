# Declarative `autokg.yml`

Use config-driven builds when you want repeatable, auditable knowledge graph generation.

```yaml
namespace: https://acme.example/kg
actor: alice@acme.example
strict: true
store: gold/store
incremental: true

sources:
  - name: customers
    path: silver/customers.parquet
    entity: Customer
    id_column: customer_id
    pii_policy:
      strategy: hash

  - name: orders
    path: silver/orders.parquet
    entity: Order
    id_column: order_id

relationships:
  - from_table: orders
    from_column: customer_id
    to_table: customers
    to_column: customer_id
    declared_by: alice@acme.example
    ticket_ref: DATA-4421
    justification: A customer places orders.

output:
  - path: gold/graph.ttl
    format: turtle
  - path: gold/graph.jsonld
    format: jsonld
```

Build:

```bash
autokg build -c autokg.yml
```
