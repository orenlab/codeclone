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
Pass explicit repo-relative `paths`, exact qualnames in `symbols`, or both. Use
`mode="implementation"` for editing orientation or `mode="impact"` for
transitive dependency context and baseline-sensitive findings. Default
implementation facets include module role, direct imports, importers, public API
rows, blast radius, tests, docs, and memory. One global `budget` bounds emitted
evidence; each collection carries deterministic `total`, `shown`, and
`truncated` counts.

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

Symbol lookup uses an off-report, in-memory index built from analyzed function
units and public API rows. `subject.resolved_symbols` reports exact file and line
locations; `subject.unresolved_symbols` reports unknown qualnames without
guessing. A symbol-only query that resolves nothing returns
`status="subject_not_found"`. This index contributes to
`context_artifact_digest` but never changes the canonical report digest.

Inferred changed scope and call/reference relationships are additive Phase 30
slices. Until their owning slice lands, requesting them is rejected or reported
unavailable rather than fabricated.
