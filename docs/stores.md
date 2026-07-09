# Graph stores

`autokg` writes files always and exposes a store abstraction for serving.

## Included interfaces

```text
GraphStore
RDFLibGraphStore
RemoteSPARQLStore
```

## RDFLib local store

Used by the query backend for local `gold/` packages.

```python
from autokg import RDFLibGraphStore
store = RDFLibGraphStore("gold")
rows = store.query("SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10")
```

## Remote SPARQL store

```python
from autokg import RemoteSPARQLStore
store = RemoteSPARQLStore("https://graph.example.com/sparql", auth_token="...")
```

Future production adapters can implement the same interface for GraphDB, Stardog, Neptune, Fuseki, and Oxigraph.
