<!-- doc-scope: Atomic change control debug path. class: guide max-lines: 120 -->

# Atomic debug path

For legacy MCP servers or step-by-step debugging:

```
manage_change_intent(action="list_workspace")
  -> analyze_repository
  -> manage_change_intent(action="declare", scope={...})
  -> get_blast_radius(files=[...])
  -> check_patch_contract(mode="budget")
  -> [edit within scope]
  -> analyze_repository
  -> manage_change_intent(action="check", intent_id=..., changed_files=[...])
  -> check_patch_contract(mode="verify", after_run_id=..., intent_id=...)
  -> validate_review_claims(text="...", patch_health_delta=...)
  -> create_review_receipt
  -> manage_change_intent(action="clear")
```

Prefer [start/finish workflow](../mcp/workflows/change-control.md) when available.

Tool params: [Atomic change control tools](../../book/25-mcp-interface/tools/atomic-change-control.md).
