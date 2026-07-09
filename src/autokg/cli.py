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
    _schema_parser(subparsers)
    _ontology_parser(subparsers)
    _eval_parser(subparsers)
    _doctor_parser(subparsers)
    _benchmark_parser(subparsers)
    _distributed_build_parser(subparsers)
    _push_store_parser(subparsers)
    _init_parser(subparsers)
    _studio_parser(subparsers)
    _serve_parser(subparsers)
    _query_parser(subparsers)
    _validate_parser(subparsers)
    _inspect_parser(subparsers)
    _report_parser(subparsers)
    _generate_sparql_parser(subparsers)
    _api_parser(subparsers)
    _chat_parser(subparsers)
    _ask_parser(subparsers)
    _profile_parser(subparsers)
    _diff_parser(subparsers)
    _mcp_parser(subparsers)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    dispatch(args)


def _schema_parser(subparsers):
    p = subparsers.add_parser("schema", help="Config schema utilities")
    sp = p.add_subparsers(dest="schema_command")
    export = sp.add_parser("export", help="Export autokg JSON Schema")
    export.add_argument("--output", "-o", default="autokg.schema.json")

    def handler(args):
        if args.schema_command == "export":
            from ._schema_contract import export_config_schema
            export_config_schema(args.output)
            print(f"Wrote JSON Schema: {args.output}")
        else:
            p.print_help(); sys.exit(1)

    p.set_defaults(handler=handler)


def _ontology_parser(subparsers):
    p = subparsers.add_parser("ontology", help="Generate ontology and SHACL shapes from autokg.yml")
    p.add_argument("--config", "-c", default="autokg.yml")
    p.add_argument("--output-dir", "-o")

    def handler(args):
        from ._ontology_tools import write_ontology_bundle
        result = write_ontology_bundle(args.config, args.output_dir)
        for k, v in result.items():
            print(f"{k}: {v}")

    p.set_defaults(handler=handler)


def _eval_parser(subparsers):
    p = subparsers.add_parser("eval", help="Evaluate NL→SPARQL and graph answers against a YAML eval set")
    p.add_argument("graph", help="autokg output directory, e.g. gold/")
    p.add_argument("eval_file", help="YAML eval file")
    p.add_argument("--output", "-o", default="eval_report.json")
    p.add_argument("--llm-provider", default="mock", choices=["mock", "openai", "anthropic", "gemini", "ollama", "custom_http"])
    p.add_argument("--model", default="")
    p.add_argument("--endpoint")

    def handler(args):
        from ._eval import run_eval, write_eval_report
        result = run_eval(args.graph, args.eval_file, llm_config={"provider": args.llm_provider, "model": args.model, "endpoint": args.endpoint})
        write_eval_report(result, args.output)
        print(json.dumps({"total": result.total, "passed": result.passed, "failed": result.failed, "metrics": result.metrics, "report": args.output}, indent=2))
        if result.failed:
            sys.exit(1)

    p.set_defaults(handler=handler)


def _doctor_parser(subparsers):
    p = subparsers.add_parser("doctor", help="Check local autokg installation and optional backends")

    def handler(args):
        checks = []
        def check(name, mod):
            try:
                __import__(mod); checks.append({"name": name, "ok": True})
            except Exception as e:
                checks.append({"name": name, "ok": False, "error": str(e)})
        check("polars", "polars")
        check("pyyaml", "yaml")
        check("rdflib/query", "rdflib")
        check("pyarrow/parquet", "pyarrow")
        check("pyoxigraph", "pyoxigraph")
        check("aiohttp/mcp-http", "aiohttp")
        print(json.dumps({"checks": checks}, indent=2))
        if any(not c["ok"] for c in checks[:3]):
            sys.exit(1)

    p.set_defaults(handler=handler)


def _benchmark_parser(subparsers):
    p = subparsers.add_parser("benchmark", help="Run a local synthetic v1 build benchmark")
    p.add_argument("--rows", type=int, default=10000)
    p.add_argument("--output", default="benchmark_report.json")

    def handler(args):
        import tempfile, time
        import polars as pl
        tmp = Path(tempfile.mkdtemp(prefix="autokg_bench_"))
        silver = tmp / "silver"; silver.mkdir()
        customers = pl.DataFrame({"customer_id": [f"C{i}" for i in range(args.rows)], "segment": ["VIP" if i % 5 == 0 else "Standard" for i in range(args.rows)]})
        orders = pl.DataFrame({"order_id": [f"O{i}" for i in range(args.rows)], "customer_id": [f"C{i}" for i in range(args.rows)], "amount": [float(i % 1000) for i in range(args.rows)]})
        customers.write_csv(silver / "customers.csv"); orders.write_csv(silver / "orders.csv")
        cfg = tmp / "autokg.yml"
        cfg.write_text(f"""project:\n  name: bench\n  namespace: https://bench.example/kg\n  output_dir: gold\n  strict: true\ntables:\n  - name: customers\n    source: silver/customers.csv\n    entity: Customer\n    primary_key: customer_id\n    columns:\n      segment: {{property: ex:segment}}\n  - name: orders\n    source: silver/orders.csv\n    entity: Order\n    primary_key: order_id\n    columns:\n      amount: {{property: schema:price, type: decimal}}\nrelationships:\n  - name: order_customer\n    from: {{table: orders, column: customer_id}}\n    to: {{table: customers, column: customer_id}}\n    predicate: ex:placedBy\n    required: true\n    declared_by: benchmark\n    ticket: BENCH\noutputs:\n  rdf:\n    enabled: true\n    formats: [ntriples]\n""", encoding="utf-8")
        from ._v1 import build_v1
        start = time.time(); result = build_v1(cfg); dur = time.time() - start
        report = {"rows_per_table": args.rows, "tables": 2, "total_rows": args.rows * 2, "triples": result.triple_count, "duration_seconds": round(dur, 4), "triples_per_second": round(result.triple_count / dur, 2) if dur else 0, "workdir": str(tmp)}
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))

    p.set_defaults(handler=handler)



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


def _distributed_build_parser(subparsers):
    p = subparsers.add_parser("distributed-build", help="Prepare partitioned build artifacts and run deterministic final graph build")
    p.add_argument("--config", "-c", default="autokg.yml")
    p.add_argument("--partitions", type=int, default=4)
    p.add_argument("--backend", default="local", choices=["local", "ray", "dask", "spark"], help="Execution backend label; local is built in")

    def handler(args):
        from ._distributed import DistributedBuildCoordinator
        report = DistributedBuildCoordinator(args.config, partitions=args.partitions, backend=args.backend).run()
        print(json.dumps(report.__dict__, indent=2))

    p.set_defaults(handler=handler)


def _push_store_parser(subparsers):
    p = subparsers.add_parser("push-store", help="Upload RDF output to GraphDB, Stardog, or Neptune-compatible SPARQL store")
    p.add_argument("backend", choices=["graphdb", "stardog", "neptune"])
    p.add_argument("file", help="RDF file, e.g. gold/graph.ttl or gold/graph.nt")
    p.add_argument("--base-url", help="GraphDB/Stardog base URL")
    p.add_argument("--repository", help="GraphDB repository")
    p.add_argument("--database", help="Stardog database")
    p.add_argument("--endpoint", help="Neptune endpoint")
    p.add_argument("--username")
    p.add_argument("--password")
    p.add_argument("--auth-token")
    p.add_argument("--graph-uri")

    def handler(args):
        from ._enterprise_stores import GraphDBStore, StardogStore, NeptuneStore
        if args.backend == "graphdb":
            store = GraphDBStore(args.base_url, args.repository, username=args.username, password=args.password)
        elif args.backend == "stardog":
            store = StardogStore(args.base_url, args.database, username=args.username, password=args.password)
        else:
            store = NeptuneStore(args.endpoint, auth_token=args.auth_token)
        print(json.dumps(store.upload_file(args.file, graph_uri=args.graph_uri), indent=2))

    p.set_defaults(handler=handler)



def _init_parser(subparsers):
    p = subparsers.add_parser("init", help="Create a sellable starter project: config, demo data script, MCP client example")
    p.add_argument("template", nargs="?", default="customer360", choices=["blank", "customer360", "insurance", "ecommerce"], help="Starter template")
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
        raw_config = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        from ._v1 import normalize_config
        config = normalize_config(raw_config or {}, base_dir=cfg_path.parent)
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
    p = subparsers.add_parser("validate", help="Validate autokg.yml or source files")
    p.add_argument("sources", nargs="*", help="Source files to validate when --config is not used")
    p.add_argument("--config", "-c", help="autokg.yml path")
    p.add_argument("--namespace", "-n", default="http://example.org/", help="IRI namespace")
    p.add_argument("--shapes", help="SHACL shapes file (optional)")
    p.add_argument("--json", action="store_true", help="Print validation report as JSON")

    def handler(args):
        if args.config:
            from ._v1 import load_v1_config, validate_v1_config
            config = load_v1_config(args.config)
            report = validate_v1_config(config, load_data=True)
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                status = "PASSED" if report["status"] == "passed" else "FAILED"
                print(f"Validation: {status}")
                print(f"Tables: {report['table_count']}")
                print(f"Relationships: {report['relationship_count']}")
                for err in report.get("errors", []):
                    print(f"  ERROR: {err['path']}: {err['message']}")
                for warn in report.get("warnings", []):
                    print(f"  WARNING: {warn['path']}: {warn['message']}")
            if report["status"] != "passed":
                sys.exit(1)
            return

        if not args.sources:
            print("Error: provide source files or use --config autokg.yml", file=sys.stderr)
            sys.exit(1)

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


def _inspect_parser(subparsers):
    p = subparsers.add_parser("inspect", help="Inspect a built autokg output directory or graph file")
    p.add_argument("path", help="Output directory or graph file")
    p.add_argument("--json", action="store_true", help="Print JSON")

    def handler(args):
        from ._v1 import inspect_output
        data = inspect_output(args.path)
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print("=== autokg inspect ===")
            for k, v in data.items():
                if k == "outputs" and isinstance(v, list):
                    print("outputs:")
                    for item in v:
                        print(f"  - {item}")
                else:
                    print(f"{k}: {v}")

    p.set_defaults(handler=handler)


def _report_parser(subparsers):
    p = subparsers.add_parser("report", help="Print or locate the HTML build report")
    p.add_argument("output_dir", nargs="?", default="gold", help="autokg output directory")

    def handler(args):
        report = Path(args.output_dir) / "build_report.html"
        if report.exists():
            print(str(report))
        else:
            print(f"Report not found: {report}", file=sys.stderr)
            sys.exit(1)

    p.set_defaults(handler=handler)



def _generate_sparql_parser(subparsers):
    p = subparsers.add_parser("generate-sparql", help="Generate safe SPARQL from natural language using the query backend")
    p.add_argument("graph", help="autokg output directory, e.g. gold/")
    p.add_argument("question", nargs="+", help="Natural language question")
    p.add_argument("--llm-provider", default="mock", choices=["mock", "openai", "anthropic", "gemini", "ollama", "custom_http"], help="LLM provider")
    p.add_argument("--model", default="", help="LLM model")
    p.add_argument("--endpoint", help="LLM endpoint for ollama/custom_http")
    p.add_argument("--session-id", help="Conversation session id")
    p.add_argument("--json", action="store_true", help="Print JSON")

    def handler(args):
        from ._query_backend import QueryEngine
        engine = QueryEngine(args.graph, llm_config={"provider": args.llm_provider, "model": args.model, "endpoint": args.endpoint})
        result = engine.generate_sparql(" ".join(args.question), session_id=args.session_id)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(result["sparql"])
            if not result["validation"].get("valid"):
                print("\nValidation errors:", file=sys.stderr)
                for e in result["validation"].get("errors", []):
                    print(f"  - {e}", file=sys.stderr)
                sys.exit(1)

    p.set_defaults(handler=handler)


def _api_parser(subparsers):
    p = subparsers.add_parser("api", help="Start REST query backend for schema, SPARQL, NL→SPARQL, ask, and sessions")
    p.add_argument("graph", help="autokg output directory, e.g. gold/")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--auth-token", help="Bearer token required for API calls")
    p.add_argument("--llm-provider", default="mock", choices=["mock", "openai", "anthropic", "gemini", "ollama", "custom_http"], help="LLM provider")
    p.add_argument("--model", default="", help="LLM model")
    p.add_argument("--endpoint", help="LLM endpoint for ollama/custom_http")

    def handler(args):
        from ._query_backend import run_api
        run_api(args.graph, host=args.host, port=args.port, auth_token=args.auth_token, llm_config={"provider": args.llm_provider, "model": args.model, "endpoint": args.endpoint})

    p.set_defaults(handler=handler)


def _chat_parser(subparsers):
    p = subparsers.add_parser("chat", help="Interactive multi-turn chat over an autokg graph")
    p.add_argument("graph", help="autokg output directory, e.g. gold/")
    p.add_argument("--llm-provider", default="mock", choices=["mock", "openai", "anthropic", "gemini", "ollama", "custom_http"], help="LLM provider")
    p.add_argument("--model", default="", help="LLM model")
    p.add_argument("--endpoint", help="LLM endpoint for ollama/custom_http")

    def handler(args):
        from ._query_backend import QueryEngine
        engine = QueryEngine(args.graph, llm_config={"provider": args.llm_provider, "model": args.model, "endpoint": args.endpoint})
        session_id = engine.start_session()
        print(f"autokg chat started. session_id={session_id}. Type 'exit' to quit.")
        while True:
            try:
                q = input("autokg> ").strip()
            except EOFError:
                break
            if q.lower() in {"exit", "quit", ":q"}:
                break
            if not q:
                continue
            ans = engine.ask(q, session_id=session_id)
            print(ans.answer)
            print("SPARQL:")
            print(ans.sparql)
            if ans.rows:
                print("Rows sample:")
                print(json.dumps(ans.rows[:5], indent=2))

    p.set_defaults(handler=handler)



def _ask_parser(subparsers):
    p = subparsers.add_parser("ask", help="Ask a natural language question against an autokg graph")
    p.add_argument("args", nargs="+", help="Either: <graph_dir> <question...> or <question...> with --store")
    p.add_argument("--store", "-s", help="Path to knowledge graph store/output directory")
    p.add_argument("--provider", default=None, choices=["openai", "ollama", "custom"], help="Legacy GraphAgent provider")
    p.add_argument("--llm-provider", default="mock", choices=["mock", "openai", "anthropic", "gemini", "ollama", "custom_http"], help="Query backend LLM provider")
    p.add_argument("--model", default="", help="LLM model name")
    p.add_argument("--endpoint", help="LLM endpoint for ollama/custom_http")
    p.add_argument("--session-id", help="Conversation session id")
    p.add_argument("--role", help="Access-control role for RBAC/ABAC filtering")
    p.add_argument("--json", action="store_true")

    def handler(args):
        from ._query_backend import QueryEngine
        if args.store:
            graph = args.store
            question = " ".join(args.args)
        else:
            if len(args.args) < 2:
                print("Usage: autokg ask <gold_dir> <question...> or autokg ask <question...> --store <gold_dir>", file=sys.stderr)
                sys.exit(1)
            graph = args.args[0]
            question = " ".join(args.args[1:])
        engine = QueryEngine(graph, llm_config={"provider": args.llm_provider, "model": args.model, "endpoint": args.endpoint})
        result = engine.ask(question, session_id=args.session_id, role=args.role)
        if args.json:
            print(json.dumps(result, default=lambda o: o.__dict__ if hasattr(o, "__dict__") else str(o), indent=2))
        else:
            print(result.answer)
            print("\nSPARQL:")
            print(result.sparql)
            print(f"\nRows: {result.row_count}")
            if result.rows:
                print(json.dumps(result.rows[:10], indent=2))
            print(f"\nSession: {result.session_id}")

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
    from ._v1 import build_v1, V1ConfigError

    try:
        result = build_v1(args.config, output_dir=None)
    except V1ConfigError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    print(f"Build ID: {result.build_id}")
    print(f"Output directory: {result.output_dir}")
    print(f"Tables: {result.table_count}")
    print(f"Relationships: {result.relationship_count}")
    print(f"Total triples: {result.triple_count}")
    print(f"Duration: {result.duration_seconds}s")
    print("Outputs:")
    for path in result.output_files:
        print(f"  - {path}")

    if getattr(args, "serve", False):
        from ._core import KnowledgeGraph
        store_path = str(Path(result.output_dir) / "store")
        kg = KnowledgeGraph.from_store(store_path)
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
    if template == "blank":
        return """project:
  name: my-knowledge-graph
  namespace: https://example.com/kg
  output_dir: gold
  strict: true
  fail_on_invalid_fk: true
  fail_on_missing_pk: true
  fail_on_duplicate_pk: true
  incremental: true

tables:
  - name: customers
    source: silver/customers.csv
    entity: Customer
    primary_key: customer_id
    columns:
      customer_id: {property: schema:identifier, required: true}
      email: {property: schema:email, pii: true, pii_type: email, mask: hash}

relationships:
  # - name: customer_places_order
  #   from: {table: orders, column: customer_id}
  #   to: {table: customers, column: customer_id}
  #   predicate: ex:placedBy
  #   cardinality: many_to_one
  #   required: true
  #   declared_by: data-platform@example.com
  #   ticket: DATA-1
  #   description: A customer places an order.

outputs:
  rdf:
    enabled: true
    formats: [turtle, jsonld, ntriples, rdfxml]
  ontology: {enabled: true}
  manifest: {enabled: true}
  lineage: {enabled: true}
  audit: {enabled: true}
  report: {enabled: true}

store:
  enabled: true
  type: local
  path: gold/store
"""
    if template == "insurance":
        return """project:
  name: insurance-demo
  namespace: https://demo.autokg.ai/insurance
  output_dir: gold
  strict: true
  fail_on_invalid_fk: true
  incremental: true

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

  - name: policies
    source: silver/policies.csv
    entity: Policy
    primary_key: policy_id
    columns:
      policy_id: {property: schema:identifier, required: true}
      policy_type: {property: schema:category}
      status: {property: schema:eventStatus}

  - name: claims
    source: silver/claims.csv
    entity: Claim
    primary_key: claim_id
    columns:
      claim_id: {property: schema:identifier, required: true}
      claim_amount: {property: ex:claimAmount, type: decimal}
      status: {property: schema:eventStatus}

relationships:
  - name: policy_belongs_to_customer
    from: {table: policies, column: customer_id}
    to: {table: customers, column: customer_id}
    predicate: ex:belongsToCustomer
    cardinality: many_to_one
    required: true
    declared_by: data-platform@example.com
    ticket: DEMO-1
    description: A policy belongs to a customer.

  - name: claim_against_policy
    from: {table: claims, column: policy_id}
    to: {table: policies, column: policy_id}
    predicate: ex:againstPolicy
    cardinality: many_to_one
    required: true
    declared_by: data-platform@example.com
    ticket: DEMO-2
    description: A claim is filed against a policy.

outputs:
  rdf:
    enabled: true
    formats: [turtle, jsonld, ntriples, rdfxml]
  report: {enabled: true}

store:
  enabled: true
  type: local
  path: gold/store
"""
    return """project:
  name: customer360-demo
  namespace: https://demo.autokg.ai/customer360
  output_dir: gold
  strict: true
  fail_on_invalid_fk: true
  incremental: true

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
    columns:
      product_id: {property: schema:identifier, required: true}
      name: {property: schema:name}
      risk_level: {property: ex:riskLevel}

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
    project = (config or {}).get("project") or {}
    sources = config.get("tables", []) if config else []
    rels = config.get("relationships", []) if config else []
    output_dir = Path(project.get("output_dir") or "gold")
    if not output_dir.is_absolute():
        output_dir = cfg_path.parent / output_dir
    manifest = {}
    lineage = {}
    validation = {}
    for name, target in [("manifest", output_dir / "manifest.json"), ("lineage", output_dir / "lineage.json"), ("validation", output_dir / "validation_report.json")]:
        try:
            if target.exists():
                data = json.loads(target.read_text(encoding="utf-8"))
                if name == "manifest": manifest = data
                elif name == "lineage": lineage = data
                else: validation = data
        except Exception:
            pass
    source_rows = "".join(
        f"<tr><td>{html.escape(str(t.get('name','')))}</td><td>{html.escape(str(t.get('entity','')))}</td><td>{html.escape(str(t.get('source','')))}</td><td>{html.escape(str(t.get('primary_key','')))}</td><td>{len((t.get('columns') or {}))}</td></tr>"
        for t in sources
    )
    rel_rows = "".join(
        f"<tr><td>{html.escape(str(r.get('name','')))}</td><td>{html.escape(str(r.get('from_table','')))}.{html.escape(str(r.get('from_column','')))}</td><td>{html.escape(str(r.get('to_table','')))}.{html.escape(str(r.get('to_column','id')))}</td><td>{html.escape(str(r.get('predicate','')))}</td><td>{html.escape(str(r.get('declared_by','')))}</td><td>{html.escape(str(r.get('ticket','')))}</td></tr>"
        for r in rels
    )
    val_errors = "".join(f"<li>{html.escape(e.get('path',''))}: {html.escape(e.get('message',''))}</li>" for e in validation.get('errors', [])) or "<li>None</li>"
    raw = html.escape(json.dumps(config or {}, indent=2))
    man = html.escape(json.dumps(manifest or {}, indent=2)[:12000])
    lin = html.escape(json.dumps(lineage or {}, indent=2)[:12000])
    namespace = html.escape(str(project.get('namespace', 'not set')))
    strict = html.escape(str(project.get('strict', True)))
    store = html.escape(str(((config or {}).get('store') or {}).get('path', 'gold/store')))
    cfg = html.escape(str(cfg_path))
    triples = manifest.get('triples', 'not built')
    build_id = manifest.get('build_id', 'not built')
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>autokg Studio</title><style>:root{{--bg:#07111f;--card:#101d33;--muted:#9fb0c8;--text:#edf5ff;--blue:#58a6ff;--green:#65e6a6;--red:#ff8b8b;--line:#263b5e}}*{{box-sizing:border-box}}body{{font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:radial-gradient(circle at 20% 0,#143b68,transparent 30%),var(--bg);color:var(--text)}}main{{max-width:1240px;margin:auto;padding:34px}}.top{{display:flex;justify-content:space-between;gap:20px;align-items:flex-start}}h1{{font-size:46px;margin:0}}h2{{color:#9ec5ff}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}.card{{background:linear-gradient(180deg,#12213a,#0d182b);border:1px solid var(--line);border-radius:16px;padding:20px;margin:16px 0;box-shadow:0 10px 30px #0004}}.metric{{font-size:28px;font-weight:800}}.muted{{color:var(--muted)}}table{{width:100%;border-collapse:collapse}}td,th{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}code,pre,textarea{{background:#050a13;color:#d9e8ff;border:1px solid var(--line);border-radius:10px;padding:12px;overflow:auto}}textarea{{width:100%;min-height:120px}}.pill{{display:inline-block;background:#173861;color:#cfe6ff;padding:6px 10px;border-radius:999px;margin:6px 8px 0 0}}.tabs button{{background:#10203a;color:#e8eefc;border:1px solid var(--line);padding:10px 14px;border-radius:10px;margin:4px;cursor:pointer}}.tab{{display:none}}.tab.active{{display:block}}@media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}</style></head><body><main><div class='top'><div><h1>autokg Studio</h1><p class='muted'>Project dashboard for <code>{cfg}</code></p></div><div><span class='pill'>Namespace: {namespace}</span><span class='pill'>Strict: {strict}</span><span class='pill'>Store: {store}</span></div></div><div class='grid'><div class='card'><div class='muted'>Tables</div><div class='metric'>{len(sources)}</div></div><div class='card'><div class='muted'>Relationships</div><div class='metric'>{len(rels)}</div></div><div class='card'><div class='muted'>Triples</div><div class='metric'>{triples}</div></div><div class='card'><div class='muted'>Build</div><div style='font-size:13px'>{html.escape(str(build_id))}</div></div></div><div class='card'><div class='tabs'><button onclick="showTab('sources')">Sources</button><button onclick="showTab('rels')">Relationships</button><button onclick="showTab('query')">Query Playground</button><button onclick="showTab('validation')">Validation</button><button onclick="showTab('lineage')">Lineage</button><button onclick="showTab('manifest')">Manifest</button><button onclick="showTab('config')">Config</button></div><section id='sources' class='tab active'><h2>Sources</h2><table><thead><tr><th>Name</th><th>Entity</th><th>Path</th><th>PK</th><th>Configured columns</th></tr></thead><tbody>{source_rows}</tbody></table></section><section id='rels' class='tab'><h2>Accountable relationships</h2><table><thead><tr><th>Name</th><th>From</th><th>To</th><th>Predicate</th><th>Declared by</th><th>Ticket</th></tr></thead><tbody>{rel_rows}</tbody></table></section><section id='query' class='tab'><h2>Query Playground</h2><p class='muted'>Start the API with <code>autokg api {html.escape(str(output_dir))} --port 8080</code>, then use this panel.</p><textarea id='question'>show customers</textarea><br/><button onclick='askGraph()'>Ask graph</button><pre id='answer'>Results appear here.</pre></section><section id='validation' class='tab'><h2>Validation</h2><ul>{val_errors}</ul></section><section id='lineage' class='tab'><h2>Lineage</h2><pre>{lin}</pre></section><section id='manifest' class='tab'><h2>Manifest</h2><pre>{man}</pre></section><section id='config' class='tab'><h2>Raw config</h2><pre>{raw}</pre></section></div><div class='card'><h2>Commands</h2><pre>autokg validate -c {cfg}\nautokg build -c {cfg}\nautokg ask {html.escape(str(output_dir))} "show customers"\nautokg api {html.escape(str(output_dir))} --port 8080\nautokg mcp --store {store} --stdio</pre></div></main><script>function showTab(id){{document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));document.getElementById(id).classList.add('active')}}async function askGraph(){{const q=document.getElementById('question').value;const out=document.getElementById('answer');out.textContent='Loading...';try{{const r=await fetch('http://localhost:8080/ask',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{question:q}})}});out.textContent=JSON.stringify(await r.json(),null,2)}}catch(e){{out.textContent='Could not reach API. Run: autokg api {html.escape(str(output_dir))} --port 8080\\n'+e}}}}</script></body></html>"""


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
