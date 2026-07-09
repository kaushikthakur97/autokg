from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import polars as pl


def main():
    parser = argparse.ArgumentParser(
        prog="autokg",
        description="Auto-generate governed knowledge graphs from cleaned tables and expose them to AI agents",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    _build_parser(subparsers)
    _init_parser(subparsers)
    _studio_parser(subparsers)
    _serve_parser(subparsers)
    _query_parser(subparsers)
    _validate_parser(subparsers)
    _ask_parser(subparsers)
    _profile_parser(subparsers)
    _diff_parser(subparsers)
    _mcp_parser(subparsers)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    dispatch(args)


def _build_parser(subparsers):
    p = subparsers.add_parser("build", help="Build knowledge graph from tables")
    p.add_argument("sources", nargs="*", help="Source files (Parquet, CSV, JSON). Optional when --config is used.")
    p.add_argument("--namespace", "-n", default="http://example.org/", help="IRI namespace")
    p.add_argument("--output", "-o", default="knowledge_graph.ttl", help="Output file")
    p.add_argument("--format", "-f", default="turtle", choices=["turtle", "ttl", "jsonld", "ntriples", "rdfxml"], help="Output format")
    p.add_argument("--config", "-c", help="YAML pipeline config")
    p.add_argument("--entity", "-e", action="append", help="Entity type per source (repeatable)")
    p.add_argument("--store", "-s", help="Oxigraph persistent store path")
    p.add_argument("--serve", action="store_true", help="Start SPARQL server after build")
    p.add_argument("--port", type=int, default=7878, help="SPARQL server port")

    def handler(args):
        from ._core import KnowledgeGraph

        if args.config:
            _build_from_config(args)
            return

        if not args.sources:
            print("Error: provide source files or use --config autokg.yml", file=sys.stderr)
            sys.exit(1)

        kg = KnowledgeGraph(namespace=args.namespace, store_path=args.store, strict=False)

        entities = args.entity or []
        for i, source in enumerate(args.sources):
            entity = entities[i] if i < len(entities) else None
            kg.add_table(source, entity_type=entity)

        kg.infer_relationships()
        kg.build()

        path = kg.write(args.output, format=args.format)
        print(f"Knowledge graph written to: {path}")
        print(f"Triples: {kg.triple_count}")

        if args.store:
            store_path = kg.save_store(args.store)
            print(f"Store saved to: {store_path}")

        if args.serve:
            url = kg.serve(port=args.port)
            print(f"SPARQL endpoint at: {url}/sparql")
            print("Press Ctrl+C to stop")
            try:
                import time
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

    p.set_defaults(handler=handler)


def _init_parser(subparsers):
    p = subparsers.add_parser("init", help="Create a sellable starter project: config, demo data script, MCP client example")
    p.add_argument("template", nargs="?", default="customer360", choices=["customer360", "insurance", "ecommerce"], help="Starter template")
    p.add_argument("--output", "-o", default="autokg_project", help="Directory to create")
    p.add_argument("--force", action="store_true", help="Overwrite existing files")

    def handler(args):
        out = Path(args.output)
        if out.exists() and any(out.iterdir()) and not args.force:
            print(f"{out} already exists and is not empty. Use --force to overwrite.", file=sys.stderr)
            sys.exit(1)
        out.mkdir(parents=True, exist_ok=True)
        (out / "silver").mkdir(exist_ok=True)
        (out / "gold").mkdir(exist_ok=True)
        (out / ".cursor").mkdir(exist_ok=True)

        (out / "autokg.yml").write_text(_starter_config(args.template), encoding="utf-8")
        (out / "README.md").write_text(_starter_readme(args.template), encoding="utf-8")
        (out / "make_demo_data.py").write_text(_starter_data_script(args.template), encoding="utf-8")
        (out / "claude_desktop_config.json").write_text(_claude_config(out), encoding="utf-8")
        print(f"Created {args.template} starter in {out}")
        print("Next:")
        print(f"  cd {out}")
        print("  python make_demo_data.py")
        print("  autokg build -c autokg.yml")
        print("  autokg studio -c autokg.yml -o studio.html")
        print("  autokg mcp --store gold/store --stdio")

    p.set_defaults(handler=handler)


def _studio_parser(subparsers):
    p = subparsers.add_parser("studio", help="Generate a static HTML project dashboard from autokg.yml")
    p.add_argument("--config", "-c", default="autokg.yml", help="autokg.yml path")
    p.add_argument("--output", "-o", default="autokg_studio.html", help="HTML output path")

    def handler(args):
        try:
            import yaml
        except ImportError:
            print("PyYAML is required for studio. Install with: pip install pyyaml", file=sys.stderr)
            sys.exit(1)
        cfg_path = Path(args.config)
        config = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        html = _render_studio_html(config or {}, cfg_path)
        Path(args.output).write_text(html, encoding="utf-8")
        print(f"Studio dashboard written to: {args.output}")

    p.set_defaults(handler=handler)


def _serve_parser(subparsers):
    p = subparsers.add_parser("serve", help="Start SPARQL endpoint from store")
    p.add_argument("store_path", help="Path to Oxigraph store directory")
    p.add_argument("--host", default="localhost", help="Host to bind to")
    p.add_argument("--port", type=int, default=7878, help="Port to bind to")
    p.add_argument("--auth-token", help="Bearer token required for /health and SPARQL POST")

    def handler(args):
        from ._oxigraph import OxigraphStore

        store = OxigraphStore(store_path=args.store_path)
        url = store.serve(host=args.host, port=args.port, auth_token=args.auth_token)
        print(f"SPARQL endpoint at: {url}/sparql")
        print("Press Ctrl+C to stop")
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down.")

    p.set_defaults(handler=handler)


def _query_parser(subparsers):
    p = subparsers.add_parser("query", help="Execute SPARQL query")
    p.add_argument("query", help="SPARQL query string or path to .sparql file")
    p.add_argument("--endpoint", "-e", help="SPARQL endpoint URL")
    p.add_argument("--store", "-s", help="Path to Oxigraph store directory")
    p.add_argument("--output", "-o", default="json", choices=["json", "csv", "table"], help="Output format")

    def handler(args):
        query = args.query
        if Path(query).exists():
            query = Path(query).read_text(encoding="utf-8")

        if args.endpoint:
            import httpx
            headers = {"Accept": "application/sparql-results+json"}
            response = httpx.post(args.endpoint, data={"query": query}, headers=headers, timeout=30)
            data = response.json()
            if args.output == "json":
                print(json.dumps(data, indent=2))
            else:
                _print_sparql_results(data, args.output)
        elif args.store:
            from ._oxigraph import OxigraphStore
            store = OxigraphStore.load_existing(args.store)
            results = store.query(query)
            print(json.dumps(results, indent=2, default=str))
        else:
            print("Error: Provide --store <path> or --endpoint <url>", file=sys.stderr)
            sys.exit(1)

    p.set_defaults(handler=handler)


def _validate_parser(subparsers):
    p = subparsers.add_parser("validate", help="Validate data against SHACL shapes or schema rules")
    p.add_argument("sources", nargs="+", help="Source files to validate")
    p.add_argument("--namespace", "-n", default="http://example.org/", help="IRI namespace")
    p.add_argument("--shapes", help="SHACL shapes file (optional)")

    def handler(args):
        from ._core import KnowledgeGraph

        kg = KnowledgeGraph(namespace=args.namespace, strict=False)
        for src in args.sources:
            kg.add_table(src)
        kg.generate_templates()

        result = kg.validate(shapes_path=args.shapes)

        conforms = "PASSED" if result["conforms"] else "FAILED"
        print(f"Validation: {conforms}")
        for table, issues in result.get("by_table", {}).items():
            print(f"\n[{table}]")
            for issue in issues.get("violations", []):
                print(f"  VIOLATION: {issue['message']}")
            for issue in issues.get("warnings", []):
                print(f"  WARNING: {issue['message']}")
            for issue in issues.get("info", []):
                print(f"  INFO: {issue['message']}")

    p.set_defaults(handler=handler)


def _ask_parser(subparsers):
    p = subparsers.add_parser("ask", help="Natural language query against knowledge graph")
    p.add_argument("question", nargs="+", help="Natural language question")
    p.add_argument("--store", "-s", required=True, help="Path to knowledge graph store")
    p.add_argument("--provider", default="openai", choices=["openai", "ollama", "custom"], help="LLM provider")
    p.add_argument("--model", default="gpt-4o", help="LLM model name")

    def handler(args):
        from ._core import KnowledgeGraph
        from ._agent import GraphAgent

        kg = KnowledgeGraph.from_store(args.store)
        agent = GraphAgent(kg, provider=args.provider, model=args.model, verbose=True)

        question = " ".join(args.question)
        result = agent.ask(question)
        print(result)

    p.set_defaults(handler=handler)


def _profile_parser(subparsers):
    p = subparsers.add_parser("profile", help="Profile and analyze knowledge graph")
    p.add_argument("sources", nargs="+", help="Source files to profile")
    p.add_argument("--namespace", "-n", default="http://example.org/", help="IRI namespace")

    def handler(args):
        from ._core import KnowledgeGraph

        kg = KnowledgeGraph(namespace=args.namespace, strict=False)
        for src in args.sources:
            kg.add_table(src)
        kg.infer_relationships()
        kg.build()

        print("=== GRAPH PROFILE ===")
        print(kg.profile())

        print("\n=== CLASS DISTRIBUTION ===")
        print(kg.class_distribution())

        print("\n=== DIAGNOSTICS ===")
        diag = kg.diagnose()
        for issue in diag.get("issues", []):
            print(f"  ISSUE: {issue['message']}")
        for warn in diag.get("warnings", []):
            print(f"  WARNING: {warn['message']}")
        for info in diag.get("info", []):
            print(f"  INFO: {info['message']}")

    p.set_defaults(handler=handler)


def _diff_parser(subparsers):
    p = subparsers.add_parser("diff", help="Diff two knowledge graph snapshots")
    p.add_argument("tag_a", help="First snapshot tag")
    p.add_argument("tag_b", help="Second snapshot tag")
    p.add_argument("--store", "-s", required=True, help="Path to version store")

    def handler(args):
        from ._versioning import VersionManager

        vm = VersionManager(args.store)
        result = vm.diff(args.tag_a, args.tag_b)
        print(json.dumps(result, indent=2, default=str))

    p.set_defaults(handler=handler)


def dispatch(args):
    if hasattr(args, "handler"):
        args.handler(args)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)


def _build_from_config(args):
    try:
        import yaml
    except ImportError:  # pragma: no cover
        print("PyYAML is required for --config. Install with: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    from ._core import KnowledgeGraph

    namespace = config.get("namespace", args.namespace)
    store_path = config.get("store", args.store)
    actor = config.get("actor", "unknown")
    kg = KnowledgeGraph(
        namespace=namespace,
        store_path=store_path,
        audit_path=config.get("audit_path"),
        openlineage_endpoint=config.get("openlineage_endpoint"),
        strict=bool(config.get("strict", True)),
        actor=actor,
        incremental=bool(config.get("incremental", False)),
        manifest_path=config.get("manifest_path"),
    )

    sources = config.get("sources", [])
    if not sources:
        print(f"No sources configured in {args.config}", file=sys.stderr)
        sys.exit(1)

    for src_cfg in sources:
        table_path = src_cfg.get("path") or src_cfg.get("table") or src_cfg.get("source")
        if not table_path:
            print(f"Source entry missing path/table/source: {src_cfg}", file=sys.stderr)
            sys.exit(1)
        add_kwargs = {}
        if src_cfg.get("format"):
            add_kwargs["format"] = src_cfg["format"]
        kg.add_table(
            table_path,
            source_name=src_cfg.get("name"),
            entity_type=src_cfg.get("entity") or src_cfg.get("entity_type"),
            id_column=src_cfg.get("id_column"),
            property_map=src_cfg.get("property_map"),
            relationships=src_cfg.get("relationships"),
            pii_policy=src_cfg.get("pii_policy"),
            **add_kwargs,
        )

    for rel_cfg in config.get("relationships", []):
        kg.declare_relationship(
            rel_cfg.get("from_table") or rel_cfg.get("source_table"),
            rel_cfg.get("from_column") or rel_cfg.get("source_column"),
            rel_cfg.get("to_table") or rel_cfg.get("target_table") or rel_cfg.get("to_entity"),
            target_column=rel_cfg.get("to_column") or rel_cfg.get("target_column") or "id",
            declared_by=rel_cfg.get("declared_by") or actor,
            ticket_ref=rel_cfg.get("ticket_ref", ""),
            justification=rel_cfg.get("justification", ""),
        )

    if config.get("infer_relationships", False):
        kg.infer_relationships()

    kg.build()

    outputs = config.get("output") or config.get("outputs") or []
    if isinstance(outputs, dict):
        outputs = [outputs]
    if not outputs:
        outputs = [{"path": args.output, "format": args.format}]

    for output_cfg in outputs:
        fmt = output_cfg.get("format", "turtle")
        path = output_cfg.get("path", "knowledge_graph.ttl")
        if fmt == "sparql_endpoint":
            url = output_cfg.get("url")
            if url:
                auth = None
                auth_key = output_cfg.get("auth_env") or output_cfg.get("auth")
                if auth_key:
                    import os
                    auth = (os.environ.get(auth_key, ""), "")
                kg.push_to_sparql(url, auth=auth)
                print(f"Pushed to: {url}")
        else:
            kg.write(path, format=fmt)
            print(f"Written: {path}")

    if store_path:
        kg.save_store(store_path)
        print(f"Store saved: {store_path}")

    print(f"Tables: {len(kg.table_names)}")
    print(f"Relationships: {kg.relationships.count()}")
    print(f"Total triples: {kg.triple_count}")

    if getattr(args, "serve", False):
        url = kg.serve(port=args.port)
        print(f"SPARQL endpoint at: {url}/sparql")
        print("Press Ctrl+C to stop")
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


def _mcp_parser(subparsers):
    p = subparsers.add_parser("mcp", help="Start MCP server (Model Context Protocol) for AI agents")
    p.add_argument("--store", "-s", required=True, help="Path to knowledge graph store")
    p.add_argument("--stdio", action="store_true", default=True, help="Stdio mode (for Claude Desktop)")
    p.add_argument("--port", "-p", type=int, default=0, help="HTTP port (0 = stdio only)")
    p.add_argument("--host", default="0.0.0.0", help="HTTP host")
    p.add_argument("--auth-token", help="Bearer token required for HTTP access")
    p.add_argument("--tls-cert", help="TLS certificate path")
    p.add_argument("--tls-key", help="TLS private key path")
    p.add_argument("--cors-origins", default="*", help="CORS allowed origins")
    p.add_argument("--rate-limit", type=int, default=100, help="Max requests per minute per session")

    def handler(args):
        from ._core import KnowledgeGraph
        kg = KnowledgeGraph.from_store(args.store)
        if args.port > 0:
            from .server._transport import run_http
            print(f"MCP server starting on https://{args.host}:{args.port}" if args.tls_cert else f"MCP server starting on http://{args.host}:{args.port}")
            run_http(kg, host=args.host, port=args.port, auth_token=args.auth_token, tls_cert=args.tls_cert, tls_key=args.tls_key, cors_origins=args.cors_origins, rate_limit_rpm=args.rate_limit)
        else:
            from .server._transport import run_stdio
            print("MCP server starting in stdio mode (connect from Claude Desktop, Cursor, etc.)", file=sys.stderr)
            run_stdio(kg)

    p.set_defaults(handler=handler)


def _starter_config(template: str) -> str:
    if template == "insurance":
        return """namespace: https://demo.autokg.ai/insurance
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
  - name: claims
    path: silver/claims.csv
    entity: Claim
    id_column: claim_id
relationships:
  - from_table: policies
    from_column: customer_id
    to_table: customers
    to_column: customer_id
    declared_by: data-platform@example.com
    ticket_ref: DEMO-1
    justification: A policy belongs to a customer.
  - from_table: claims
    from_column: policy_id
    to_table: policies
    to_column: policy_id
    declared_by: data-platform@example.com
    ticket_ref: DEMO-2
    justification: A claim is filed against a policy.
output:
  - path: gold/graph.ttl
    format: turtle
  - path: gold/graph.jsonld
    format: jsonld
"""
    return """namespace: https://demo.autokg.ai/customer360
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
  - name: orders
    path: silver/orders.csv
    entity: Order
    id_column: order_id
  - name: products
    path: silver/products.csv
    entity: Product
    id_column: product_id
relationships:
  - from_table: orders
    from_column: customer_id
    to_table: customers
    to_column: customer_id
    declared_by: data-platform@example.com
    ticket_ref: DEMO-1
    justification: A customer places orders.
  - from_table: orders
    from_column: product_id
    to_table: products
    to_column: product_id
    declared_by: data-platform@example.com
    ticket_ref: DEMO-2
    justification: An order contains a product.
output:
  - path: gold/graph.ttl
    format: turtle
  - path: gold/graph.jsonld
    format: jsonld
"""


def _starter_readme(template: str) -> str:
    return f"""# autokg {template} starter

This starter shows the sellable workflow:

1. clean tables in `silver/`
2. accountable relationships in `autokg.yml`
3. governed knowledge graph in `gold/`
4. MCP server for Claude Desktop, Cursor, and other agents

```bash
python make_demo_data.py
autokg build -c autokg.yml
autokg studio -c autokg.yml -o studio.html
autokg mcp --store gold/store --stdio
```

Try asking an agent:

- "Show me Customer C001 and every related record."
- "Which relationships were declared and by whom?"
- "Trace the graph path between a customer and an order/claim."
"""


def _starter_data_script(template: str) -> str:
    if template == "insurance":
        return """import polars as pl
from pathlib import Path
Path('silver').mkdir(exist_ok=True)
pl.DataFrame({'customer_id':['C001','C002'],'name':['Ada Lovelace','Grace Hopper'],'email':['ada@example.com','grace@example.com'],'segment':['VIP','Standard']}).write_csv('silver/customers.csv')
pl.DataFrame({'policy_id':['P100','P200'],'customer_id':['C001','C002'],'policy_type':['Auto','Home'],'status':['Active','Active']}).write_csv('silver/policies.csv')
pl.DataFrame({'claim_id':['CL900','CL901'],'policy_id':['P100','P200'],'claim_amount':[12500,3200],'status':['Open','Closed']}).write_csv('silver/claims.csv')
print('Demo insurance CSVs written to silver/')
"""
    return """import polars as pl
from pathlib import Path
Path('silver').mkdir(exist_ok=True)
pl.DataFrame({'customer_id':['C001','C002'],'name':['Ada Lovelace','Grace Hopper'],'email':['ada@example.com','grace@example.com'],'segment':['VIP','Standard']}).write_csv('silver/customers.csv')
pl.DataFrame({'product_id':['PR1','PR2'],'name':['Risk Scanner','Analytics Seat'],'risk_level':['High','Low']}).write_csv('silver/products.csv')
pl.DataFrame({'order_id':['O100','O101'],'customer_id':['C001','C002'],'product_id':['PR1','PR2'],'amount':[4999,299]}).write_csv('silver/orders.csv')
print('Demo customer360 CSVs written to silver/')
"""


def _claude_config(out: Path) -> str:
    return json.dumps({
        "mcpServers": {
            "autokg-demo": {
                "command": "autokg",
                "args": ["mcp", "--store", str((out / "gold" / "store").resolve()), "--stdio"]
            }
        }
    }, indent=2)


def _render_studio_html(config: dict, cfg_path: Path) -> str:
    import html
    sources = config.get("sources", []) if config else []
    rels = config.get("relationships", []) if config else []
    source_rows = "".join(
        f"<tr><td>{html.escape(str(s.get('name','')))}</td><td>{html.escape(str(s.get('entity') or s.get('entity_type','')))}</td><td>{html.escape(str(s.get('path') or s.get('table','')))}</td><td>{html.escape(str(s.get('id_column','')))}</td></tr>"
        for s in sources
    )
    rel_rows = "".join(
        f"<tr><td>{html.escape(str(r.get('from_table','')))}.{html.escape(str(r.get('from_column','')))}</td><td>{html.escape(str(r.get('to_table') or r.get('target_table','')))}.{html.escape(str(r.get('to_column') or r.get('target_column','id')))}</td><td>{html.escape(str(r.get('declared_by','')))}</td><td>{html.escape(str(r.get('ticket_ref','')))}</td></tr>"
        for r in rels
    )
    raw = html.escape(json.dumps(config or {}, indent=2))
    namespace = html.escape(str((config or {}).get('namespace', 'not set')))
    strict = html.escape(str((config or {}).get('strict', True)))
    store = html.escape(str((config or {}).get('store', 'gold/store')))
    cfg = html.escape(str(cfg_path))
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>autokg Studio</title><style>body{{font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#0b1020;color:#e8eefc}}main{{max-width:1100px;margin:auto;padding:40px}}.card{{background:#121a33;border:1px solid #26345f;border-radius:16px;padding:24px;margin:18px 0;box-shadow:0 10px 30px #0004}}h1{{font-size:42px;margin:0}}h2{{color:#9ec5ff}}table{{width:100%;border-collapse:collapse}}td,th{{padding:10px;border-bottom:1px solid #26345f;text-align:left}}code,pre{{background:#070b16;border-radius:10px;padding:14px;overflow:auto}}.pill{{display:inline-block;background:#234a8f;padding:6px 10px;border-radius:999px;margin:6px 8px 0 0}}</style></head><body><main><h1>autokg Studio</h1><p>Static project dashboard for <code>{cfg}</code></p><div class='card'><h2>Project</h2><span class='pill'>Namespace: {namespace}</span><span class='pill'>Strict: {strict}</span><span class='pill'>Store: {store}</span></div><div class='card'><h2>Sources</h2><table><thead><tr><th>Name</th><th>Entity</th><th>Path</th><th>ID column</th></tr></thead><tbody>{source_rows}</tbody></table></div><div class='card'><h2>Accountable relationships</h2><table><thead><tr><th>From</th><th>To</th><th>Declared by</th><th>Ticket</th></tr></thead><tbody>{rel_rows}</tbody></table></div><div class='card'><h2>Agent setup</h2><pre>autokg build -c {cfg}
autokg mcp --store {store} --stdio</pre></div><div class='card'><h2>Raw config</h2><pre>{raw}</pre></div></main></body></html>"""


def _print_sparql_results(data: dict, format: str):
    bindings = data.get("results", {}).get("bindings", [])
    variables = data.get("head", {}).get("vars", [])

    if format == "csv":
        print(",".join(variables))
        for row in bindings:
            print(",".join(row.get(v, {}).get("value", "") for v in variables))
    elif format == "table":
        rows = []
        for row in bindings:
            rows.append({v: row.get(v, {}).get("value", "") for v in variables})
        print(pl.DataFrame(rows))


if __name__ == "__main__":
    main()
