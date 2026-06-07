### Trajectory labels and step names

Each projected trajectory carries a sorted **`labels`** list in
`memory_trajectories.labels_json`. Labels are deterministic tags derived from audit
event cores — not free-form agent text.

| Label | When set |
|-------|----------|
| `change_control_workflow` | Any change-controller event (`intent.*`, `patch_contract.*`, …) |
| `verified_finish` | `patch_contract.verified` with accepted outcome |
| `scope_clean` | `intent.checked` with status `clean` or `expanded` |
| `scope_expanded` | `intent.expanded` present |
| `queue_used` | `intent.queued` present |
| `patch_trail_recorded` | `patch_trail.computed` present |
| `receipt_issued` | `review_receipt.created` present |
| `claim_validated` | `claim_validation.completed` present |
| `analysis_observed` | Standalone `analysis.completed` workflow (no change-control events) |
| `memory_used` | `manage_engineering_memory` tool use in the stream |
| `recovered` | `intent.promoted` (queue recovery) |
| `foreign_conflict_seen` | Workspace conflict |
| `hook_blocked` | Hook surface warn/error |
| `claim_guard_failed` | Claim validation violated |
| `baseline_abuse_detected` | Baseline abuse |
| `external_changes_accepted` | Finish accepted with external changes |

Routine successful edit cycles should carry **`change_control_workflow`** and
**`verified_finish`** at minimum. Empty `labels` indicates a projection bug or a
legacy row that needs `memory trajectory rebuild`.

Each step in MCP `trajectory_get` includes **`step_label`** — a human-readable name
from `codeclone/memory/trajectory/step_labels.py` (event catalog + status). CLI
`memory trajectory show` prints labels and step labels.

See also: [Trajectory memory](trajectory-and-patch-trail.md).
