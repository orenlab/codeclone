### IDE-only tools (`--ide-governance-channel`)

Registered only when the MCP launcher passes `--ide-governance-channel` (VS Code
extension). Agent MCP clients without that flag do not see these tools in
`list_tools`.

| Tool                          | Key parameters | Purpose                                                                     |
|-------------------------------|----------------|-----------------------------------------------------------------------------|
| `get_workspace_session_stats` | `root`         | Workspace agents, intents, leases — same collector as CLI `--session-stats` |
| `get_controller_audit_trail`  | `root`         | Audit trail + payload footprint — same collector as CLI `--audit`           |

Requires `audit_enabled=true` for meaningful audit rows. Payload footprint
`top_workflows` entries expose workflow metrics as `calls` and `tokens` (see
`codeclone/controller_insights/audit_trail.py`).

---
