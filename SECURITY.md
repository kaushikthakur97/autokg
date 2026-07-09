# Security Policy

Report security issues privately to the maintainer before opening a public issue.

## Safe deployment defaults

- Run MCP and SPARQL services in read-only mode unless a workflow explicitly requires writes.
- Use `--auth-token` for HTTP MCP/SPARQL deployments.
- Place remote deployments behind TLS and an identity-aware proxy.
- Set query timeouts and result-row limits at the gateway layer.
- Do not put raw secrets in `autokg.yml`; use environment variables or a secret manager.

## Enterprise roadmap

- OIDC/SAML SSO
- role-based graph access
- policy-based sensitive predicate filtering
- per-agent audit logs
- OpenTelemetry traces
- signed build manifests
