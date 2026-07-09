# Advanced query planning and semantic linking

The query backend now uses a deterministic planner before falling back to the configured LLM.

```text
question
  → SemanticLinker
  → QueryPlanner
  → SPARQL
  → policy validation
  → execution
```

## SemanticLinker

Links natural language to:

- entities/classes
- source tables
- columns/properties
- declared relationships
- value aliases such as VIP/high/open/closed
- numeric comparisons such as `above 1000`

Optional glossary format:

```yaml
aliases:
  customer: [client, account holder]
  product: [sku, item]
values:
  premium: VIP
```

## QueryPlanner

The planner supports:

- entity selection
- relationship path planning over declared relationships
- inverse predicates
- simple filters
- numeric comparisons
- count aggregation
- safe limits

If the deterministic planner cannot produce a good query, the LLM adapter can still generate SPARQL using the schema context.
