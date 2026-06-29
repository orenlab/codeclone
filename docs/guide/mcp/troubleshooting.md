<!-- doc-scope: MCP troubleshooting. class: guide max-lines: 160 -->

# MCP troubleshooting

When MCP setup, tool calls, or change-control responses fail — start here.
Install and transport basics:
[Client setup](client-setup.md),
[Server & transport](server-and-transport.md).

Normative contracts:
[MCP interface](../../book/25-mcp-interface/index.md),
[Change controller](../../book/12-structural-change-controller/index.md).

## Install and launcher

| Symptom | Fix |
|---------|-----|
| `CodeClone MCP support requires the optional 'mcp' extra` | `uv tool install --prerelease allow "codeclone[mcp]"` or `pip install --pre 'codeclone[mcp]'` |
| Client cannot find `codeclone-mcp` | Install the extra above, or point `command` at the full launcher path in MCP config |
| Wrong / missing tools after upgrade | Restart the MCP process; confirm `codeclone --version` matches the client bundle |
| Plugin installed but MCP silent | Check client MCP logs; verify stdio command is `codeclone-mcp --transport stdio` |

## Transport and HTTP

| Symptom | Fix |
|---------|-----|
| HTTP server refuses to start | Set `CODECLONE_MCP_AUTH_TOKEN` to ≥32 characters before launch — no unauthenticated HTTP |
| Remote client cannot connect | Use `streamable-http`; pass Bearer token; for non-loopback hosts add `--allow-remote` |
| Client only accepts remote MCP | See [Server & transport](server-and-transport.md#transports) — stdio for local IDEs |

## Analysis parameters

| Symptom | Fix |
|---------|-----|
| `requires an absolute repository root` | Pass full path (`/Users/.../repo`), not `.` or a relative segment |
| `Repository root '…' does not exist` | Fix typo; ensure the path is the repo root on the machine running MCP |
| `path traversal not allowed` | Use repo-relative paths inside tools; do not pass `../` escapes |
| `changed_paths` rejected | Pass `list[str]` of repo-relative file paths, or use `git_diff_ref` |
| `analyze_changed_paths` fails | Provide **either** `changed_paths` **or** `git_diff_ref`, not neither |
| `cache_policy='refresh' is CLI-only` | MCP accepts `reuse` (default) or `off` only |
| `coverage_xml requires analysis_mode='full'` | Set `analysis_mode="full"` before joining Cobertura XML |
| Stale or wrong findings | Call `analyze_repository` again; runs are in-memory and bounded (`--history-limit`) |

## Session and workflow state

| Symptom | Fix |
|---------|-----|
| Agent reads results from an old run | Re-analyze, or pass the explicit `run_id` you intend |
| Review markers out of sync | `mark_finding_reviewed` + `list_findings(exclude_reviewed=true)`; markers are session-local |
| Need a clean MCP session | `clear_session_runs` — also clears workspace intents; see [Session markers](workflows/session-and-coverage.md#session-review-loop-in-memory-markers) |
| Process restarted — intents gone | Expected: intent registry is ephemeral; re-run `analyze_repository` → `start_controlled_change` |

## Change control responses

| `status` / message | What to do |
|--------------------|------------|
| `needs_analysis` | Call `analyze_repository(root=<abs>)` before `start_controlled_change` |
| `queued`, `edit_allowed: false` | Another intent is active — `manage_change_intent(action="promote")` or narrow scope |
| `blocked`, dirty scope overlap | Inspect git diff; commit/stash/revert, narrow scope, or `dirty_scope_policy="continue_own_wip"` for own WIP |
| `finish` → `unverified` | Follow `next_step` in the response (often a new after-run + same `intent_id`) |
| `finish` → `violated` | Fix scope or regressions; or `start` again with expanded `allowed_files` |
| Foreign intent overlap | Coordinate with the user — do not kill foreign PIDs without confirmation |

Full workflow:
[Change control](workflows/change-control.md).

## Engineering Memory

| Symptom | Fix |
|---------|-----|
| `get_relevant_memory` fails without `root` | Always pass the same absolute `root` as analysis — `intent_id` alone is invalid |
| Empty memory on first use | Normal — `bootstrap_if_missing` ingests on first scoped call after `analyze_repository` |
| Cannot approve drafts via MCP | By design — use VS Code **Memory** view; agents only `record_candidate` |

## Quick diagnostic checklist

1. `codeclone --version` and `codeclone-mcp --help` succeed on the host that runs MCP.
2. `root` is **absolute** and points at the repository the client has open.
3. `analyze_repository` → `get_run_summary` works before deeper tools.
4. `help(topic="engineering_memory")` or `help(topic="change_control")` for contract copy.
5. Enable server debug: `codeclone-mcp --log-level DEBUG` (stdio clients: check MCP stderr).

## Report a bug or false positive

If the steps above do not match what you see, open a GitHub issue:

**[github.com/orenlab/codeclone/issues](https://github.com/orenlab/codeclone/issues)**

Include:

- CodeClone version (`codeclone --version`)
- Client (Cursor, Codex, Claude Code, VS Code, Claude Desktop, other)
- Transport (`stdio` or `streamable-http`)
- Tool name and parameters (redact tokens and private paths)
- Full error text or MCP log excerpt

---
