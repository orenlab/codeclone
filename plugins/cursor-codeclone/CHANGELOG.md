# Change Log

## 0.1.0

- Initial Cursor plugin for CodeClone
- **Six skills:** `codeclone-production-triage`, `codeclone-hotspots`,
  `codeclone-blast-radius`, `codeclone-review`, `codeclone-change-control`,
  `codeclone-engineering-memory` (optional semantic search documented in skill +
  server config)
- **One agent:** `codeclone-structural-reviewer` (`agents/structural-reviewer.md`)
- **Three rules:** `codeclone-workflow.mdc`, `change-control-gate.mdc` (always),
  `codeclone-python.mdc` (glob `**/*.py`)
- **Three hooks** via `hooks/run_hook.py`: fail-closed `preToolUse` intent gate
  (`codeclone.workspace_intent`), `postToolUse` Python edit reminder
  (`additional_context`), `stop` unclosed-intent advisory (`followup_message`)
- **MCP:** `mcp.json` runs `python3 ./scripts/launch_mcp.py` (full 31-tool
  passthrough; no `--ide-governance-channel`)
- **Installer:** `scripts/install-project-hooks.py` → `.cursor/hooks.json` and
  `.cursor/codeclone-hooks.json` (`enforce_scope` `python` | `repo`)
