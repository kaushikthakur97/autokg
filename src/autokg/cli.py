from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import polars as pl


def main():
    parser = argparse.ArgumentParser(
        prog="autokg",
        description="Auto-generate RDF knowledge graphs from cleaned tables",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    _build_parser(subparsers)
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
    p.add_argument("sources", nargs="+", help="Source files (Parquet, CSV, JSON)")
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
        from ._connectors import read_table

        if args.config:
            _build_from_config(args)
            return

        kg = KnowledgeGraph(namespace=args.namespace, store_path=args.store)

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


def _serve_parser(subparsers):
    p = subparsers.add_parser("serve", help="Start SPARQL endpoint from store")
    p.add_argument("store_path", help="Path to Oxigraph store directory")
    p.add_argument("--host", default="localhost", help="Host to bind to")
    p.add_argument("--port", type=int, default=7878, help="Port to bind to")

    def handler(args):
        from ._oxigraph import OxigraphStore

        store = OxigraphStore(store_path=args.store_path)
        url = store.serve(host=args.host, port=args.port)
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

        kg = KnowledgeGraph(namespace=args.namespace)
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

        kg = KnowledgeGraph(namespace=args.namespace)
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
    import yaml

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    from ._core import KnowledgeGraph

    namespace = config.get("namespace", args.namespace)
    store_path = config.get("store", args.store)
    kg = KnowledgeGraph(namespace=namespace, store_path=store_path)

    sources = config.get("sources", [])
    for src_cfg in sources:
        table = src_cfg.get("table", "")
        entity = src_cfg.get("entity")
        id_col = src_cfg.get("id_column")
        prop_map = src_cfg.get("property_map")
        rels = src_cfg.get("relationships")

        kg.add_table(
            table,
            entity_type=entity,
            id_column=id_col,
            property_map=prop_map,
            relationships=rels,
        )

    kg.infer_relationships()
    kg.build()

    outputs = config.get("output", [])
    for output_cfg in outputs:
        fmt = output_cfg.get("format", "turtle")
        path = output_cfg.get("path", "knowledge_graph.ttl")

        if fmt == "sparql_endpoint":
            url = output_cfg.get("url")
            if url:
                auth = None
                auth_key = output_cfg.get("auth")
                if auth_key:
                    import os
                    auth = (os.environ.get(auth_key, ""), "")
                kg.push_to_sparql(url)
                print(f"Pushed to: {url}")
        else:
            kg.write(path, format=fmt)
            print(f"Written: {path}")

    if store_path:
        kg.save_store(store_path)
        print(f"Store saved: {store_path}")

    print(f"Total triples: {kg.triple_count}")


def _mcp_parser(subparsers):
    p = subparsers.add_parser("mcp", help="Start MCP server (Model Context Protocol) for AI agents")
    p.add_argument("--store", "-s", required=True, help="Path to knowledge graph store")
    p.add_argument("--stdio", action="store_true", default=True, help="Stdio mode (for Claude Desktop)")
    p.add_argument("--port", "-p", type=int, default=9000, help="HTTP port (0 = stdio only)")
    p.add_argument("--host", default="0.0.0.0", help="HTTP host")

    def handler(args):
        from ._core import KnowledgeGraph
        kg = KnowledgeGraph.from_store(args.store)
        if args.port > 0 and not args.stdio:
            from .server._transport import run_http
            print(f"MCP server starting on http://{args.host}:{args.port}")
            run_http(kg, host=args.host, port=args.port)
        else:
            from .server._transport import run_stdio
            print("MCP server starting in stdio mode (connect from Claude Desktop, Cursor, etc.)", file=sys.stderr)
            run_stdio(kg)

    p.set_defaults(handler=handler)


def _print_sparql_results(data: dict, format: str):
    bindings = data.get("results", {}).get("bindings", [])
    variables = data.get("head", {}).get("vars", [])

    if format == "csv":
        print(",".join(variables))
        for row in bindings:
            print(",".join(row.get(v, {}).get("value", "") for v in variables))
    elif format == "table":
        import polars as pl
        rows = []
        for row in bindings:
            rows.append({v: row.get(v, {}).get("value", "") for v in variables})
        print(pl.DataFrame(rows))


if __name__ == "__main__":
    main()
