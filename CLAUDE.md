# CodeClone Project Rules

## Change control workflow

This repository uses CodeClone MCP for structural change control.
Before editing any files, follow this workflow:

1. Check workspace: `manage_change_intent(action="list_workspace",
   root="<absolute_path>")`
   — if other agents have active intents, review their scope
2. Run analysis: `analyze_repository(root="<absolute_path>")`
3. Declare intent: `manage_change_intent(action="declare", scope={...})`
   — if `concurrent_intents` is non-empty, narrow scope or ask the user
4. Check blast radius: `get_blast_radius(files=[...])`
5. Check budget: `check_patch_contract(mode="budget")`
6. Edit files within declared scope only
7. Re-run analysis: `analyze_repository(root="<absolute_path>")`
8. Verify: `manage_change_intent(action="check", ...)` then
   `check_patch_contract(mode="verify")`
9. Clear intent: `manage_change_intent(action="clear")`

### Rules

- Never edit files without declaring intent first.
- Never silently expand scope — redeclare with expanded scope.
- Treat `do_not_touch` as a hard boundary.
- Treat `review_context` as context, not an edit ban.
- Do not update baselines, cache, or generated reports as part of a
  functional change.
- If `list_workspace` shows another agent working on overlapping files,
  stop and coordinate with the user before proceeding.
- CodeClone is the source of truth — do not reinterpret findings.

### When to skip

Skip this workflow only when:

- No repository files will be changed (read-only tasks, specs only)
- CodeClone MCP is not available
- The user explicitly asks for analysis only
