# Production hardening

This layer turns autokg from a graph compiler into a backend product.

## Config contract

```bash
autokg schema export -o autokg.schema.json
```

Use the exported schema in CI and IDEs to validate `autokg.yml`.

## Ontology and SHACL

```bash
autokg ontology -c autokg.yml
```

Builds:

```text
ontology.ttl
shapes.ttl
```

`shapes.ttl` is generated from required columns, primary keys, and declared relationships.

## Query security

The query backend uses `QueryPolicy` guardrails:

- read-only by default
- blocks SPARQL update operations
- blocks `SERVICE` by default
- max query length
- max rows
- optional denied predicates/entities
- query audit JSONL

## Observability

Runtime files/endpoints:

```text
gold/query_audit.jsonl
GET /metrics
```

## Evaluation

```bash
autokg eval gold evals/customer360/questions.yml
```

Metrics:

- pass rate
- valid SPARQL rate
- execution success rate
- hallucination failure count
- duration

## Benchmarks

```bash
autokg benchmark --rows 100000 --output benchmark_report.json
```

Tracks:

- rows
- triples
- duration
- triples/sec
