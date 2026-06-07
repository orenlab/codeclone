<!-- doc-scope: Change control overview. class: guide max-lines: 120 -->
# Change control overview

CodeClone v2.1 requires agents to **declare scope before editing**, verify the
patch against structural boundaries, and finish with evidence-linked hygiene.

| Step | Action |
|------|--------|
| 1 | `analyze_repository` (or reuse valid run) |
| 2 | `start_controlled_change` → `edit_allowed=true` |
| 3 | `get_relevant_memory` (requires absolute `root`) |
| 4 | Edit inside declared scope only |
| 5 | After-run when profile requires it |
| 6 | `finish_controlled_change` with `changed_files` or `diff_ref` |

MCP recipe: [Change control workflow](../mcp/workflows/change-control.md).

Contract: [Structural Change Controller](../../book/12-structural-change-controller/index.md).
