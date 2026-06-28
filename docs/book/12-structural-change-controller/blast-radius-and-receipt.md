## Blast Radius Payload

Core blast-radius graph traversal lives in `codeclone/analysis/blast_radius.py`
(consuming canonical report `Mapping` facts). MCP (`get_blast_radius`,
`start`/`finish` summaries) and CLI (`--blast-radius`) are presentation
adapters over that core — non-MCP surfaces must not import
`codeclone/surfaces/mcp/_blast_radius.py`.

`get_blast_radius` separates hard edit guardrails from review context:

- `do_not_touch`: actionable negative context such as baseline/cache state,
  generated CodeClone state, or explicit forbidden paths.
- `review_context`: report-only facts such as security boundary inventory,
  overloaded-module candidates, known baseline debt, and golden fixture
  surfaces.

Long context sections are bounded and include summaries with `total`, `shown`,
and `truncated`.

## Start Blast Artifact

`start_controlled_change` uses a slim blast-radius summary by default when it can
store an immutable audit-backed artifact for the full start-time projection. The
summary keeps edit-control and safety facts inline:

- `status`, `intent_id`, `edit_allowed`, scope, workspace blocking facts
- `radius_level`, `origin`, and bounded count summaries
- `do_not_touch` and `do_not_touch_summary`
- `guardrails`
- `blast_artifact` identity: `blast_artifact_id`, `run_id`,
  `projection_digest`, detail contract version, and retrieval route

The full omitted blast evidence is available through
`get_blast_artifact(root, run_id, blast_artifact_id)` or
`get_blast_artifact(root, projection_digest=...)` and is read from the audit
trail exactly as stored when `start_controlled_change` ran. If multiple lookup
keys are supplied, they must identify the same artifact. It is not recomputed
from the current workspace. `get_blast_radius(files=...)` remains useful for
current analysis-context inspection, but it is labelled as recomputation and is
not the exact drill-down path for evidence omitted from a previous start
summary.

Agents that need the old inline projection can request
`blast_radius_detail="full"`. If the artifact cannot be stored, start returns
full blast evidence inline rather than omitting evidence without a drill-down
route.

## Review Receipt Payload

`create_review_receipt` returns `format="markdown"` by default and can return a
structured JSON receipt with `format="json"`. The receipt is a composition of
stored MCP state; it does not run analysis and does not mutate source files,
baselines, cache, reports, or repository state.

The receipt includes:

- report provenance: digest, schema version, baseline trust state, run id, root
- verification profile: profile classification, reason, applicable/not-applicable
  checks, limitations
- scope: optional change intent, declared files, changed files, unexpected files
- blast radius summary: level, direct dependent count, clone cohort count,
  do-not-touch count
- reviewed evidence: session-local reviewed finding markers and notes
- patch contract: accepted, violated, or not checked from stored gate,
  structural delta, intent, and baseline-abuse signals
- human decision points: bounded list of clone divergence, scope expansion, and
  known-baseline-debt prompts
- claims not made: explicit reminders that Security Surfaces are boundary
  inventory, report-only signals are not gates, and known baseline debt is not
  new relative to the baseline

Receipt verdicts are `clean`, `incomplete`, or `needs_attention`. They summarize
receipt completeness only; they are not CI gates.
