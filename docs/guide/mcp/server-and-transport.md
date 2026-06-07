<!-- doc-scope: MCP server transports. class: guide max-lines: 120 -->
# MCP server & transport

## Server

### Transports

| Transport         | Default | Use case                        |
|-------------------|---------|---------------------------------|
| `stdio`           | Yes     | Local agents, IDEs, CLI clients |
| `streamable-http` | No      | Remote clients, Responses API   |

```bash title="Local (default)"
codeclone-mcp --transport stdio
```

```bash title="HTTP (loopback only)"
codeclone-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

!!! warning "Remote exposure is opt-in"
    Non-loopback hosts require `--allow-remote`. For `streamable-http`, set
    `CODECLONE_MCP_AUTH_TOKEN` (≥32 chars) so clients must send
    `Authorization: Bearer …`. Without a token, HTTP MCP is unauthenticated —
    use only on trusted networks or behind a reverse proxy.

### Run retention

Run history is bounded: default `4`, max `10` (`--history-limit`).
Runs are in-memory only and do not survive process restart.

### Absolute roots

All analysis tools require an **absolute** repository root. Relative roots
like `.` are rejected because the server working directory may differ from
the client workspace.

---
