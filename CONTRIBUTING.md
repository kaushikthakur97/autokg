# Contributing

Thanks for helping make autokg the agent-ready knowledge layer for structured enterprise data.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[oxigraph,mcp]' pyarrow pytest
pytest -q
```

## Good first contributions

- new starter templates
- connector docs
- benchmark datasets
- MCP client guides
- config examples
