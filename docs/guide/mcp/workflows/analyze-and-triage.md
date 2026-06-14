<!-- doc-scope: MCP analyze and triage. class: guide max-lines: 120 -->

# Analyze & triage

### Phase 1: Analyze

| Tool                    | Purpose                                           |
|-------------------------|---------------------------------------------------|
| `analyze_repository`    | Full deterministic analysis of one repo root      |
| `analyze_changed_paths` | Diff-aware analysis with changed-files projection |

Both register the result as an in-memory run. All other tools read from
stored runs.

### Phase 2: Triage

| Tool                    | Purpose                                                    |
|-------------------------|------------------------------------------------------------|
| `get_run_summary`       | Cheapest snapshot: health, findings, baseline status       |
| `get_production_triage` | Production-first view: hotspots, suggestions, thresholds   |
| `list_hotspots`         | Priority-ranked hotspot views by kind                      |
| `compare_runs`          | Run-to-run delta: regressions, improvements, health change |

!!! tip "Start here"
    After analysis, call `get_run_summary` or `get_production_triage` first.
    Prefer `list_hotspots` or `check_*` before broad `list_findings` calls.

### Workspace hygiene tips

Selected MCP responses may include a non-blocking `tips[]` array with
structured workspace guidance. The first tip checks whether the repository
root `.gitignore` covers `.codeclone/` (or the broader `.cache/` tree).

| Field             | Example                     |
|-------------------|-----------------------------|
| `id`              | `gitignore-codeclone-cache` |
| `severity`        | `info`                      |
| `category`        | `workspace_hygiene`         |
| `suggested_entry` | `.codeclone/`               |

Tips are advisory only — not findings, gates, or failures. MCP never edits
`.gitignore` automatically; agents must declare scope before changing it.

Surfaces: `analyze_repository`, `get_run_summary`, `get_production_triage`,
`start_controlled_change`, and the CLI after a normal interactive analysis run
(suppressed in `--quiet`, CI, and non-TTY contexts).

## Health check

```
analyze_repository(root=<abs>)
  -> get_run_summary or get_production_triage
  -> list_hotspots or check_*
  -> get_finding -> get_remediation
```

## PR review

```
analyze_changed_paths(root=<abs>, changed_paths=[...] or git_diff_ref="HEAD~1")
  -> list_findings(sort_by="priority")
  -> get_finding -> get_remediation
  -> generate_pr_summary
```

## Implementation context

After analysis and triage, ask for bounded context around the files you expect
to inspect:

```
get_implementation_context(
  root=<abs>,
  paths=["codeclone/surfaces/mcp/service.py"],
  mode="implementation",
)
```

The response combines canonical structural facts with a live freshness delta.
Use `context_artifact_digest` to identify the source context artifact and
`context_projection_digest` when citing the exact bounded response. If
`freshness.status` is `drifted`, analyze again. This step informs scope; only
`start_controlled_change` can return `edit_allowed=true`.

With no explicit subject, the tool resolves current work deterministically:

1. active intent `allowed_files`;
2. otherwise the bounded live git-dirty set;
3. otherwise `status="no_current_work"`.

Use `changed_scope=true` to request the dirty set explicitly. Do not combine it
with `paths` or `symbols`.

Exact qualnames are also valid subjects:

```
get_implementation_context(
  root=<abs>,
  symbols=["codeclone.surfaces.mcp.service:CodeCloneMCPService"],
  mode="implementation",
)
```

Symbol resolution uses the analyzed Unit inventory plus public API rows.
Inspect both `subject.resolved_symbols` and `subject.unresolved_symbols`;
CodeClone reports unknown qualnames instead of inferring a likely match.

Structural import, importer, and test-importer roles appear as collapsed
`related_modules` entries with explicit `relations`. Read each collection's
summary: the global budget is shared across the response. Safety context is
allocated first; `safety_context_overflow` means even the hard cap could not
show every safety entry.

Once an intent is active, pass its `intent_id` with the same explicit paths.
The response then shows the declared scope, review context, do-not-touch
boundaries, and guards beside lane-separated memory evidence. Use
`mode="impact"` when you need transitive dependency context and
baseline-sensitive findings. The context tool mirrors authorization evidence;
it does not grant or widen authorization.

    | Tier | Tools | When to use |
    |------|-------|-------------|
    | Normal workflow | `analyze_repository`, `start_controlled_change`, `finish_controlled_change` | Every edit cycle |
    | Queue/recovery | `manage_change_intent` (promote, recover, reset, renew) | Multi-agent coordination, crash recovery |
    | Advanced/diagnostic | `get_blast_radius`, `check_patch_contract`, `validate_review_claims`, `create_review_receipt` | Deep inspection, step-by-step debugging |
