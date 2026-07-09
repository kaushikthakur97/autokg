# MCP server

Start a local MCP server for Claude Desktop, Cursor, Continue, or any MCP-compatible client.

```bash
autokg build -c autokg.yml
autokg mcp --store gold/store --stdio
```

HTTP mode:

```bash
autokg mcp --store gold/store --port 9000 --auth-token "$AUTOKG_MCP_TOKEN"
```

Recommended production controls:

- use TLS or an identity-aware proxy
- require bearer tokens/OAuth
- run with read-only graph stores
- cap result rows and query timeouts
- log every agent query
