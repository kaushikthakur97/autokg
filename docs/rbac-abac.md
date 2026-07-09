# RBAC / ABAC

`autokg` includes a lightweight policy engine for backend filtering.

```yaml
security:
  policies:
    - role: default
      max_rows: 500

    - role: analyst
      deny_properties: [schema:email, schema:telephone]
      mask_properties: [email, phone]
      max_rows: 200

    - role: restricted
      allow_entities: [Customer, Order]
      deny_properties: [email, phone, ssn]
      max_rows: 50
```

Use with CLI:

```bash
autokg ask gold "show customers" --role analyst
```

Use with API:

```bash
curl -H 'X-Role: analyst' -X POST http://localhost:8080/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"show customers"}'
```

Policy support currently includes:

- allowed entities
- denied entities
- allowed properties
- denied properties
- masked properties
- per-role max rows

This is backend enforcement; a future hosted Studio can add login, users, and group management.
