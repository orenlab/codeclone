## Security model

| Property          | Guarantee                                                                                                                                                        |
|-------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Default transport | Local `stdio`                                                                                                                                                    |
| Remote exposure   | Explicit `--allow-remote` required for non-loopback                                                                                                              |
| Lazy loading      | Base installs and CI do not require MCP packages                                                                                                                 |
| Read-only         | Never mutates source, baseline, cache, or canonical report artifacts; may write the ephemeral workspace intent registry under `.codeclone/`, optional audit/observability DBs, Engineering Memory **draft** rows, and projection job metadata when enabled |

---



## Determinism

- Run identity is derived from canonical report integrity digest.
- Summary, hotspots, findings, and remediation payloads are deterministic
  projections over stored run state.
- MCP must not create MCP-only analysis semantics or MCP-only gate
  semantics.

---



## Locked by tests

- `tests/test_mcp_service.py`
- `tests/test_mcp_server.py`
- `tests/test_mcp_tool_schema_snapshot.py`

---



## See also

- [14-claim-guard.md](../14-claim-guard.md) — citation-based review validation
- [12-structural-change-controller/index.md](../12-structural-change-controller/index.md) — change control workflow
- [11-cli.md](../11-cli.md) — CLI reference
- [05-report.md](../05-report.md) — canonical report schema
- [MCP deep dive](../../guide/mcp/README.md) — architecture, client setup, workflows, and prompt patterns
