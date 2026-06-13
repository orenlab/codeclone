<!-- doc-scope: MCP change control workflow. class: guide max-lines: 120 -->

# Change control workflow

Primary MCP edit cycle (sole sequence diagram for change control in the guide):

```mermaid
sequenceDiagram
    participant Agent
    participant MCP as CodeClone MCP
    Agent ->> MCP: analyze_repository(root=<abs>)
    MCP -->> Agent: run_id
    Agent ->> MCP: start_controlled_change(root=<abs>, scope, intent, dirty_scope_policy?)
    MCP -->> Agent: intent_id, blast_radius, budget, edit_allowed
    Agent ->> MCP: get_relevant_memory(root, scope|intent_id)
    MCP -->> Agent: ranked memory context
    Note over Agent: edit files
    opt Python structural / governance config
        Agent ->> MCP: analyze_repository
        MCP -->> Agent: after_run_id
    end
    Agent ->> MCP: finish_controlled_change(intent_id, changed_files|diff_ref, after_run_id?, claims_text?)
    MCP -->> Agent: status, summary, workspace_hygiene_after, intent_cleared
```

## Tool tiers

| Tier           | Tools                                                 | When                |
|----------------|-------------------------------------------------------|---------------------|
| Normal         | `start_controlled_change`, `finish_controlled_change` | Every edit cycle    |
| Queue/recovery | `manage_change_intent` (promote, recover, …)          | Multi-agent / crash |
| Advanced       | `get_blast_radius`, `check_patch_contract`, …         | Debugging only      |

Normative tool params: [MCP workflow tools](../../../book/25-mcp-interface/tools/workflow.md).
Finish pipeline and
hygiene: [finish_controlled_change](../../../book/12-structural-change-controller/finish-controlled-change.md),
[Finish hygiene](../../../book/12-structural-change-controller/finish-hygiene.md).

## Related recipes

- [Agent edit cycle](../../change-control/agent-cycle.md)
- [Queue & recovery](../../change-control/queue-and-recovery.md)
- [Atomic debug path](../../change-control/atomic-debug.md)
- [Engineering Memory recipes](memory-recipes.md)
