# autokg customer360 starter

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
