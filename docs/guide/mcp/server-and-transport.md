<!-- doc-scope: MCP server transports. class: guide max-lines: 160 -->

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

```bash title="HTTP (loopback)"
export CODECLONE_MCP_AUTH_TOKEN="$(openssl rand -hex 32)"
codeclone-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

!!! warning "HTTP auth is mandatory"
    `streamable-http` **always** requires `CODECLONE_MCP_AUTH_TOKEN` with at
    least 32 characters. The server refuses to start without it — there is no
    unauthenticated HTTP mode. Non-loopback hosts additionally require
    `--allow-remote`. See
    [Environment variable overrides](../../book/10-config-and-defaults.md#mcp-http-authentication)
    and [Security Model](../../book/21-security-model.md#remote-mcp-transport).

### Server flags

| Flag                       | Default | Applies when      | Effect                                                 |
|----------------------------|---------|-------------------|--------------------------------------------------------|
| `--history-limit`          | `4`     | all transports    | In-memory run retention (`1`–`10`)                     |
| `--json-response`          | on      | `streamable-http` | JSON responses for Streamable HTTP                     |
| `--stateless-http`         | on      | `streamable-http` | Stateless Streamable HTTP mode                         |
| `--debug`                  | off     | all transports    | FastMCP debug mode                                     |
| `--log-level`              | `INFO`  | all transports    | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`     |
| `--allow-remote`           | off     | `streamable-http` | Bind non-loopback hosts (auth still required)          |
| `--ide-governance-channel` | off     | all transports    | VS Code only — registers session-stats and audit tools |

`--host` (default `127.0.0.1`) and `--port` (default `8000`) apply to
`streamable-http` only. Agent launchers must not pass `--ide-governance-channel`.

### Run retention

Run history is bounded: default `4`, max `10` (`--history-limit`).
Runs are in-memory only and do not survive process restart.

### Absolute roots

All analysis tools require an **absolute** repository root. Relative roots
like `.` are rejected because the server working directory may differ from
the client workspace.

---
