# Enterprise graph stores

`autokg` includes production adapter classes for common RDF stores.

## GraphDB

```bash
autokg push-store graphdb gold/graph.ttl \
  --base-url http://localhost:7200 \
  --repository myrepo \
  --username admin \
  --password password
```

## Stardog

```bash
autokg push-store stardog gold/graph.ttl \
  --base-url http://localhost:5820 \
  --database mydb \
  --username admin \
  --password password
```

## Neptune

```bash
autokg push-store neptune gold/graph.nt \
  --endpoint https://your-neptune-endpoint:8182/sparql
```

These adapters build on the `RemoteSPARQLStore` abstraction.
