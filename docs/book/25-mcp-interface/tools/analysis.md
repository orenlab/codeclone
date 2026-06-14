### Analysis and run-level tools

| Tool                         | Key parameters                                                                                                                                                                              | Purpose                                                              |
|------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------|
| `analyze_repository`         | `root`, `analysis_mode`, thresholds, `api_surface`, `coverage_xml`, `baseline_path`, `metrics_baseline_path`, `cache_policy`, `allow_external_artifacts`, `changed_paths` or `git_diff_ref` | Full deterministic analysis; registers an in-memory run              |
| `analyze_changed_paths`      | `root`, `changed_paths` or `git_diff_ref`, `analysis_mode`, thresholds, `api_surface`, `coverage_xml`, `cache_policy`, `allow_external_artifacts`                                           | Diff-aware analysis with changed-files projection                    |
| `get_run_summary`            | `run_id`                                                                                                                                                                                    | Cheapest run-level snapshot: health, findings, baseline/cache status |
| `get_production_triage`      | `run_id`, `max_hotspots`, `max_suggestions`                                                                                                                                                 | Production-first first-pass view                                     |
| `get_implementation_context` | `root`, `paths`, `symbols`, `intent_id`, `mode`, `include`, `depth`, `detail_level`, `budget`, `run_id`                                                                                         | Bounded, drift-aware structural context from one stored run          |
| `compare_runs`               | `run_id_before`, `run_id_after`, `focus`                                                                                                                                                    | Run-to-run delta; returns `incomparable` when roots/settings differ  |
| `evaluate_gates`             | `run_id`, gate flags, threshold overrides, `coverage_min`                                                                                                                                   | Preview CI gating decisions without mutating state                   |
| `help`                       | `topic`, `detail`                                                                                                                                                                           | Bounded workflow/contract guidance                                   |

`allow_external_artifacts` (default `false`): when `true`, optional artifact
path parameters may resolve to absolute or out-of-repo locations. See
[Security Model](../../21-security-model.md).

Selected analysis and workflow responses may include non-blocking `tips[]`
entries for workspace hygiene (for example when `.codeclone/` is not
covered by the repository root `.gitignore`). The CLI prints the same
advisory after interactive analysis runs (suppressed in `--quiet`, CI, and
non-TTY contexts). Tips are advisory only; MCP and CLI never edit
`.gitignore` automatically.

## Implementation context

`get_implementation_context` is a read-only projection over one stored run.
Pass explicit repo-relative `paths`, exact qualnames in `symbols`, or both. With
no explicit subject, CodeClone uses an active intent's `allowed_files`; without
an intent it uses the bounded live git-dirty set. A clean tree returns
`no_current_work`, never whole-repository context. Set `changed_scope=true` to
select the dirty set explicitly; combining it with explicit paths or symbols is
a contract error.

Use `mode="implementation"` for editing orientation or `mode="impact"` for
transitive dependency context and baseline-sensitive findings. Default
implementation facets include module role, imports/importers, public API rows,
blast radius, tests, docs, and memory.

```mermaid
flowchart LR
    R["Stored MCP run"] --> C["Canonical report facts"]
    R --> M["Run manifest"]
    C --> P["Bounded context projection"]
    M --> F["Live freshness delta"]
    F --> P
    P --> A["context_artifact_digest"]
    P --> E["context_projection_digest"]
```

The artifact digest binds the canonical run and off-report context artifact.
The projection digest additionally binds the normalized request and exact
bounded evidence returned. Presentation hints are excluded. A missing run
returns `needs_analysis`; invalid facets and paths outside the root raise a
contract error. `freshness.status="drifted"` means analyze again before relying
on the projection. The tool never changes `edit_allowed`.

With `intent_id`, the selected active intent pins the source run and adds a
`change_control` block:

- `allowed_files` and `allowed_related` from the declared scope;
- report-derived `review_context`;
- explicit and built-in `do_not_touch` boundaries;
- the original guards and `authorization_source="start_controlled_change"`.

Engineering Memory remains evidence, not authority. Its records, test anchors,
doc anchors, trajectories, and Experiences are projected into separate bounded
lanes with the memory retrieval policy intact.

Import, importer, and test-importer roles are collapsed by module/path into
`structural_context.related_modules`. Each entry carries deterministic
`relations` such as `imports`, `imported_by`, or `tested_by`, so one neighbor is
not repeated in several lanes.

`budget` is one global evidence-entry cap, not a per-facet limit. Every bounded
collection reports `total`, `shown`, `truncated`, and `omitted`. Intent
`do_not_touch` and review-required entries consume the budget first. The
effective limit expands up to the server hard cap so a small requested budget
cannot hide safety context. If safety entries alone exceed that cap, the
response uses `status="safety_context_overflow"` and reports the omitted count.

Symbol lookup uses an off-report, in-memory index built from analyzed function
units and public API rows. `subject.resolved_symbols` reports exact file and line
locations; `subject.unresolved_symbols` reports unknown qualnames without
guessing. A symbol-only query that resolves nothing returns
`status="subject_not_found"`. This index contributes to
`context_artifact_digest` but never changes the canonical report digest.

Call/reference relationships are an additive Phase 30 slice. Until that owning
slice lands, they are reported unavailable rather than fabricated.
