# Change Log

## 0.1.0

- initial Cursor plugin for CodeClone
- 5 skills: production triage, hotspots, blast radius, review, change control
- 1 agent: structural reviewer with deterministic CodeClone-backed assessment
- 2 rules: MCP workflow discipline (always), Python file context (glob)
- 3 hooks: fail-closed `preToolUse` change-control gate, `postToolUse`
  Python edit reminder (`additional_context`), `stop` workflow intent cleanup
  (`followup_message`)
- MCP server bundle for `codeclone-mcp` over stdio
