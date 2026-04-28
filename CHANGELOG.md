# Changelog

## [2.0.0b6]

The global package refactor lands here: the entire runtime moves onto the canonical module layout and legacy shims are
removed for good. On top of that, dependency-depth scoring is replaced with an adaptive project-relative model, and
the report/cache contracts advance to surface the new depth profile and the
report-only `security_surfaces` layer.

### Package layout and contracts

- Move the runtime fully onto the canonical package layout: `main` + `surfaces/cli`, `surfaces/mcp`, `core`, `analysis`,
  `baseline`, `cache`, `contracts`, `report/document`, `report/renderers`, and `report/html`.
- Remove remaining legacy root shims and stale compatibility modules in favor of direct canonical imports.
- Bump report schema to `2.10` and cache schema to `2.6` for additive
  `security_surfaces` and cache-persisted security-surface facts; keep clone
  baseline schema `2.1` and metrics-baseline schema `1.2` unchanged.
- Preserve deterministic contracts and read-only MCP semantics across the new layout.

### Dependency depth scoring

- Replace the old fixed dependency-depth penalty (`max_depth > 8`) with an adaptive internal-graph profile based on
  `avg_depth`, `p95_depth`, and `max_depth`.
- Keep dependency cycles as the hard signal; treat acyclic depth as adaptive pressure relative to the project's own
  dependency profile.
- Limit dependency-depth scoring to the internal module graph instead of external imports such as `typing` or
  `argparse`.
- Surface the dependency depth profile in the canonical report, HTML Dependencies tab, and CLI/CI summaries.
- Remove stale deleted-file cache entries and trim post-refactor import tails that were inflating dependency depth and
  clone pressure.

### Security surfaces

- Add `metrics.families.security_surfaces`: a report-only exact inventory of
  security-relevant capability surfaces and trust-boundary code.
- Surface compact `security_surfaces` facts in canonical report JSON,
  CLI Metrics, HTML Quality, text/markdown projections, and MCP summaries /
  `metrics_detail`.
- Keep the layer honest: no vulnerability claims, no score impact, no gates,
  no SARIF security findings, and no baseline truth.

### Tooling, docs, and UX

- Refresh AGENTS, docs/book, and changelog content for the b6 package layout and report schema `2.10`.
- Tighten preview client metadata and install guidance for VS Code, Claude Desktop, and Codex.
- Replace the Codex plugin shell snippet with a repo-local shell-free launcher, and parallelize VS Code post-run MCP
  artifact hydration.
- Add a quiet one-time VS Code extension hint in interactive VS Code terminals, tracked per CodeClone version next to
  the resolved project cache path.

## [2.0.0b5] - 2026-04-16

Expands the canonical contract with adoption, API-surface, and coverage-join layers; clarifies run interpretation
across MCP/HTML/clients; tightens MCP launcher/runtime behavior.

### Contracts, metrics, and review surfaces

- Report schema `2.8`: add `coverage_adoption`, `api_surface`, `coverage_join`, and optional
  `clones.suppressed.*` (for `golden_fixture_paths`); separate coverage hotspots vs scope gaps.
- Baselines: clone `2.1`, metrics `1.2`; compact `api_surface` payload (`local_name` on disk, qualnames at runtime);
  read-compatible with `2.0` / `1.1`.
- Add public/private visibility classification for public-symbol metrics (no clone/fingerprint changes).
- Add annotation/docstring adoption coverage: parameter, return, public docstrings, explicit `Any`.
- Add opt-in API surface inventory + baseline diff (snapshots, additions, breaking changes).
- Add coverage join (`--coverage`): per-function facts + findings for below-threshold or missing-in-scope functions;
  current-run only (not baseline truth, no fingerprint impact).
- Add `golden_fixture_paths`: exclude matching clone groups from health/gates while keeping suppressed facts.
- Add gates: `--min-typing-coverage`, `--min-docstring-coverage`, `--fail-on-typing-regression`,
  `--fail-on-docstring-regression`, `--fail-on-api-break`, `--fail-on-untested-hotspots`, `--coverage-min`.
- Surface adoption/API/coverage-join in MCP, CLI Metrics, report payloads, and HTML (Overview + Quality subtab).
- Preserve embedded metrics and optional `api_surface` in unified baselines.
- Cache `2.5`: make analysis-profile compatibility API-surface-aware; invalidate stale non-API warm caches; preserve
  parameter order; align warm/cold API diffs.

### MCP, HTML, and client interpretation

- Surface effective analysis profile in report meta, MCP summary/triage, and HTML subtitle.
- Add `health_scope`, `focus`, `new_by_source_kind` to MCP summary/triage.
- Make baseline mismatch explicit (python tags + no-valid-baseline signal).
- Surface `Coverage Join` facts and the optional `coverage` MCP help topic in
  the VS Code extension when the connected server supports them.
- Prefer workspace-local launchers over `PATH` (Poetry fallback).
- Add `workspace_root` to force project `.venv` selection.

### Safety and maintenance

- Validate `git_diff_ref` as safe single-revision expressions.
- Replace segment digest `repr()` with canonical JSON bytes (determinism).
- Align CI coverage gate (`fail_under = 99`) and refresh `actions/checkout` pin.
- Refresh branch metadata/docs for `2.0.0b5`; update README badge to `89 (B)`.

## [2.0.0b4] - 2026-04-05

### MCP server

- Add `help(topic=...)` tool for workflow guidance, baseline semantics, analysis profile, and review-state routing
  (tool count: 20 → 21).
- Add `analysis_profile` help topic for explicit conservative-first / deeper-review threshold guidance.
- Enrich `_SERVER_INSTRUCTIONS` with triage-first workflow, budget-aware drill-down, and conservative-first threshold
  guidance so MCP-capable clients receive structured behavioral context on connect.
- Optimize MCP payloads: short finding IDs (sha256-based for block clones), compact `derived` section projection,
  bounded `metrics_detail` with pagination.
- Fix MCP initialize metadata so `serverInfo.version` reports the CodeClone package version rather than the underlying
  `mcp` runtime version.

### Report contract

- Bump canonical report schema to `2.3`.
- Add `metrics.overloaded_modules` — report-only module-hotspot ranking by size, complexity, and coupling pressure.
- Surface Overloaded Modules across JSON, text/markdown, HTML, and MCP without affecting findings, health, or gates.
- Normalize the canonical family name and MCP/report output to `overloaded_modules`; `god_modules` remains accepted as a
  read-only MCP input alias during transition.

### CLI and HTML

- Align CLI and HTML scope summaries with canonical inventory totals.
- Redesign Overview tab: Executive Summary becomes 2-column (Issue Breakdown + Source Breakdown) with scan scope in
  the section subtitle; Overloaded Modules section replaces the earlier stretched module-hotspot layout.

### Documentation

- Add Health Score chapter: scoring inputs, report-only layers, phased expansion policy.
- Document that future releases may lower scores due to broader scoring model, not only worse code.

### IDE and client integration (preview)

- Add VS Code extension (`codeclone-mcp` client) with baseline-aware triage, source drill-down, Explorer decorations,
  and HTML-report bridging.
- Add conservative, deeper-review, and custom analysis profiles to the VS Code extension and pass them through to MCP.
- Add limited Restricted Mode: onboarding works in untrusted workspaces, analysis stays gated until trust is granted.
- Add Node unit tests, extension-host smoke tests, and `.vsix` packaging.
- Tighten the VS Code extension to current VS Code UX guidance: one primary editor action, titled Quick Picks,
  per-view icons, non-button tree details, and a hard minimum local CodeClone version gate (`>= 2.0.0b4`).
- Add Claude Desktop `.mcpb` bundle wrapper for the local `codeclone-mcp` launcher with pre-loaded review instructions,
  explicit launcher settings, platform auto-discovery (macOS, Linux, Windows), local-stdio enforcement, signal
  forwarding, and deterministic package build smoke.
- Add a native Codex plugin with repo-local discovery metadata, bundled `codeclone-mcp` config, pre-loaded instructions,
  and two skills: conservative-first full review and quick hotspot discovery.

### Internal

- Extract shared `_json_io` module for deterministic JSON serialization across baseline, cache, and report paths.
- Remove low-signal structural clone noise surfaced by stricter analysis passes without touching golden fixture debt.

## [2.0.0b3] - 2026-04-01

2.0.0b3 is the release where CodeClone stops looking like "a strong analyzer with extras" and starts looking like a
coherent platform: canonical-report-first, agent-facing, CI-native, and product-grade.

### Licensing & packaging

- Re-license source code to MPL-2.0 while keeping documentation under MIT.
- Ship dual `LICENSE` / `LICENSE-docs` files and sync SPDX headers.

### MCP server (new)

- Add optional `codeclone[mcp]` extra with `codeclone-mcp` launcher (`stdio` and `streamable-http`).
- Introduce a read-only MCP surface with 20 tools, fixed resources, and run-scoped URIs for analysis, changed-files
  review, run comparison, findings / hotspots / remediation, granular checks, and gate preview.
- Add bounded run retention (`--history-limit`), `--allow-remote` guard, and reject `cache_policy=refresh` to preserve
  read-only semantics.
- Optimize MCP payloads for agents with short ids, compact summaries/cards, bounded `metrics_detail`, and slim
  changed-files / compare-runs responses — without changing the canonical report contract.
- Make MCP explicitly triage-first and budget-aware: clients are guided toward summary/triage → hotspots / `check_*` →
  single-finding drill-down instead of broad early listing.
- Add `cache.freshness` marker and `get_production_triage` / `codeclone://latest/triage` for compact production-first
  overview.
- Improve run-comparison honesty: `compare_runs` now reports `mixed` / `incomparable`, and `clones_only` runs surface
  `health: unavailable` instead of placeholder values.
- Harden repository safety: MCP analysis now requires an absolute repository root and rejects relative roots like `.`
  to avoid analyzing the wrong directory.
- Fix hotlist key resolution for `production_hotspots` and `test_fixture_hotspots`.
- Bump cache schema to `2.3` (stale metric entries rebuilt, not reused).

### Report contract

- Bump canonical report schema to `2.2`.
- Add canonical `meta.analysis_thresholds.design_findings` provenance and move threshold-aware design findings fully
  into the canonical report, so MCP and HTML read the same design-finding universe.
- Add `derived.overview.directory_hotspots` and render it in the HTML Overview tab as `Hotspots by Directory`.

### CLI

- Add `--changed-only`, `--diff-against`, and `--paths-from-git-diff` for changed-scope review and gating with
  first-class summary output.

### SARIF

- Stabilize `primaryLocationLineHash` (line numbers excluded), add run-unique `automationDetails.id` /
  `startTimeUtc`, set explicit `kind: "fail"`, and move ancillary fields to `properties`.

### HTML report

- Add `Hotspots by Directory` to the Overview tab, surfacing directory-level concentration for `all`, `clones`, and
  low-cohesion findings with scope-aware badges and compact counts.
- Add IDE picker (PyCharm, IDEA, VS Code, Cursor, Fleet, Zed) with persistent selection.
- Add clickable file-path deep links across all tabs and stable `finding-{id}` anchors.

### GitHub Action

- Ship Composite Action v2 with configurable quality gates, SARIF upload to Code Scanning, and PR summary comments.

## [2.0.0b2] - 2026-03-28

### Dependencies

- Upgrade requests (dev dep) to 2.33.0 for extract_zipped_paths security fix (CVE-2026-25645)

### HTML

- Fix page-level horizontal scrolling in wide table tabs by constraining overflow to local table wrappers (#14).
- Fix mobile header brand block layout on narrow viewports (#15).
- Make mobile navigation tabs sticky and horizontally scrollable with scroll-shadow affordance.
- Keep Overview KPI micro-badges inside cards at extreme browser/mobile widths.
- Restyle Report Provenance summary badges to match the card-style badge language used across the report.

## [2.0.0b1] - 2026-03-25

Major upgrade: CodeClone evolves from a structural clone detector into a
**baseline-aware code-health and CI governance tool** for Python.

### Architecture

- Stage-based pipeline (`pipeline.py`): discovery → processing → analysis → reporting → gating.
- Domain layers: `models.py`, `metrics/`, `report/`, `grouping.py`.
- Baseline schema `2.0`, report schema `2.1`, cache schema `2.2`; `fingerprint_version` remains `1`.

### Code-Health Analysis

- Seven health dimensions: clones, complexity, coupling, cohesion, dead code, dependencies, coverage.
- Piecewise clone scoring curve: mild penalty below 5% density, steep 5–20%, aggressive above 20%.
- Dimension weights: clones 25%, complexity 20%, cohesion 15%, coupling 10%, dead code 10%, dependencies 10%, coverage
  10%.
- Grade bands: A ≥90, B ≥75, C ≥60, D ≥40, F <40.

### Detection Thresholds

- Lowered function-level `--min-loc` from 15 to 10 (configurable via CLI/pyproject.toml).
- Lowered block fragment gate from loc≥40/stmt≥10 to loc≥20/stmt≥8.
- Lowered segment fragment gate from loc≥30/stmt≥12 to loc≥20/stmt≥10.
- All six thresholds configurable via `[tool.codeclone]` in `pyproject.toml`.

### Detection Quality

- Conservative dead-code detector: skips tests, dunders, visitors, protocol stubs.
- Module-level PEP 562 hooks (`__getattr__`, `__dir__`) are treated as non-actionable dead-code candidates.
- Exact qualname-based liveness with import-alias resolution.
- Canonical inline suppression syntax: `# codeclone: ignore[dead-code]` on declarations.
- Structural finding families: `duplicated_branches`, `clone_guard_exit_divergence`, `clone_cohort_drift`.

### Configuration and CLI

- Config from `pyproject.toml` under `[tool.codeclone]`; precedence: CLI > pyproject.toml > defaults.
- Optional-value report flags: `--html`, `--json`, `--md`, `--sarif`, `--text` with deterministic default paths.
- `--open-html-report`, `--timestamped-report-paths`, `--ci` preset.
- Explicit `--no-progress`/`--progress`, `--no-color`/`--color` flag pairs.

### HTML Report

- Overview: KPI grid with health gauge (baseline delta arc), Executive Summary (issue breakdown + source breakdown),
  Health Profile radar chart.
- KPI cards show baseline-aware tone: `✓ baselined` pill when all items are accepted debt, `+N` red badge for
  regressions.
- Get Badge modal: grade-only and score+grade variants, shields.io preview, Markdown/HTML embeds, copy feedback.
- Report Provenance modal with section cards, SVG icons, boolean badges.
- Responsive layout with dark/light theme toggle and system theme detection.

### Baseline and Contracts

- Unified baseline flow: clone keys + optional metrics in one file.
- Metrics snapshot integrity via `meta.metrics_payload_sha256`.
- Report contract: canonical `meta`/`inventory`/`findings`/`metrics` + derived `suggestions`/`overview` + `integrity`.
- SARIF: `%SRCROOT%` anchoring, `baselineState`, rich rule metadata.
- Cache compatibility now keys off the full six-threshold analysis profile
  (function + block + segment thresholds), not only the top-level function gate.

### Performance

- Unified AST collection pass (merged 3 separate walks).
- Suppression fast-path: skip tokenization when `codeclone:` absent.
- Cache dirty flag: skip `save()` on warm path when nothing changed.
- Adaptive multiprocessing, batch statement hashing, deferred HTML import.

### Docs and Publishing

- MkDocs site with Material theme and GitHub Pages workflow.
- Live sample reports (HTML, JSON, SARIF).
- PyPI-facing README now uses published docs URLs instead of repo-relative doc links.

### Packaging

- Package metadata stays explicitly beta (`2.0.0b1`, `Development Status :: 4 - Beta`).
- `pyproject.toml` moved to SPDX-style `license = "MIT"` and `project.license-files`
  for modern setuptools builds without release-time deprecation warnings.

### Stability

- Exit codes unchanged: `0`/`2`/`3`/`5`.
- Fingerprint contract unchanged: `BASELINE_FINGERPRINT_VERSION = "1"`.
- Coverage gate: `>=99%`.

## [1.4.4] - 2026-03-14

### Performance

- Backported report hot-path optimizations from `2.0.0b1` to the `1.4.x` line:
    - file snippets now reuse cached full-file lines and slice ranges without
      repeated full-file scans
    - Pygments modules are loaded once per importer identity instead of
      re-importing for each snippet
- Optimized block explainability range stats:
    - replaced repeated full `ast.walk()` scans per range with a per-file
      statement index + `bisect` window lookup

### Tests

- Preserved existing golden/contract behavior for `1.4.x` and kept report output
  semantics unchanged while improving runtime overhead.

### Contract Notes

- No baseline/cache/report schema changes.
- No clone detection or fingerprint semantic changes.

## [1.4.3] - 2026-03-03

### Cache Contract

- Cache schema bumped from `v1.2` to `v1.3`.
- Added signed analysis profile to cache payload:
    - `payload.ap.min_loc`
    - `payload.ap.min_stmt`
- Cache compatibility now requires `payload.ap` to match current CLI analysis thresholds. On mismatch, cache is ignored
  with `cache_status=analysis_profile_mismatch` and analysis continues without cache.

### CLI

- CLI now constructs cache context with effective `--min-loc` and `--min-stmt` values, so cache reuse is consistent
  with active analysis thresholds.

### Tests

- Added regression coverage for analysis-profile cache mismatch/match behavior in:
    - `tests/test_cache.py`
    - `tests/test_cli_inprocess.py`

### Contract Notes

- Baseline contract is unchanged (`schema v1.0`, `fingerprint version 1`).
- Report schema is unchanged (`v1.1`); cache metadata adds a new `cache_status` enum value.

## [1.4.2] - 2026-02-17

### Overview

This patch release is a maintenance update. Determinism remains guaranteed: reports are stable and ordering is
unchanged.

### Performance & Implementation Cleanup

- `process_file()` now uses a single `os.stat()` call to obtain both size (size guard) and `st_mtime_ns`/`st_size` (file
  stat signature), removing a redundant `os.path.getsize()` call.
- Discovery logic was deduplicated by extracting `_discover_files()`; quiet/non-quiet behavior differs only by UI status
  wrapper, not by semantics or filtering.
- Cache path wiring now precomputes `wire_map` so `_wire_filepath_from_runtime()` is evaluated once per key.

### Hash Reuse for Block/Segment Analysis

- `extract_blocks()` and `extract_segments()` accept optional `precomputed_hashes`. When provided, they reuse hashes
  instead of recomputing.
- The extractor computes function body hashes once and passes them to both block and segment extraction when both
  analyses run for the same function.

### Scanner Efficiency (No Semantic Change)

- `iter_py_files()` now filters candidates before sorting, so only valid candidates are sorted. The final order remains
  deterministic and equivalent to previous behavior.

### Contract Tightening

- `precomputed_hashes` type strengthened: `list[str] | None` → `Sequence[str] | None` (read-only intent in the type
  contract).
- Added `assert len(precomputed_hashes) == len(body)` in both `extract_blocks()` and `extract_segments()` to catch
  mismatched inputs early (development-time invariant).

### Testing & Determinism

- Byte-identical JSON reports verified across repeated runs; differences, when present, are limited to
  volatile/provenance meta fields (e.g., cache status/path, timestamps), while semantic payload remains stable.
- Unit tests updated to mock `os.stat` instead of `os.path.getsize` where applicable (`test_process_file_stat_error`,
  `test_process_file_size_limit`).

### Notes

- No changes to:
    - detection semantics / fingerprints
    - baseline hash inputs (`payload_sha256` semantic payload)
    - exit code contract and precedence
    - schema versions (baseline v1.0, cache v1.2, report v1.1)

---

## [1.4.1] - 2026-02-15

### CLI

- Semantic summary colors: clone counts → `bold yellow`, file metrics → neutral `bold`
- Phase separator, bold report paths, "Done in X.Xs" timing line

### HTML Report

- HiDPI chart canvas, hit-line markers with Pygments, cross-browser `<select>`
- Platform-aware shortcut labels (`⌘` / `Ctrl+`), color-coded section borders
- Compact code lines, proper tab-bar for novelty filter, polished transitions
- Rounded-rect badges (`6px`), tighter card radii (`10px`), cleaner empty states

---

## [1.4.0] - 2026-02-12

### Overview

This release stabilizes the baseline contract for long-term CI reuse without changing clone-detection semantics. Key
improvements include baseline schema standardization, enhanced cache efficiency, and hardened IO/contract behavior for
CI environments.

---

### Baseline Schema & Compatibility

**Stable v1 Schema**

- Baseline now uses stable v1 schema with strict top-level `meta` + `clones` objects
- Compatibility gated by `schema_version`, `fingerprint_version`, and `python_tag` (independent of package patch/minor
  version)
- Trust validation requires `meta.generator.name` to be `codeclone`
- Legacy 1.3 baseline layouts treated as untrusted with explicit regeneration guidance

**Integrity & Hash Calculation**

- Baseline integrity uses canonical `payload_sha256` over semantic payload (`functions`, `blocks`,
  `fingerprint_version`, `python_tag`)
- Intentionally excluded from `payload_sha256`:
    - `schema_version` (compatibility gate only)
    - `meta.generator.name` (trust gate only)
    - `meta.generator.version` and `meta.created_at` (informational only)
- Hash inputs remain stable across future 1.x patch/minor releases
- Baseline regeneration required only when `fingerprint_version` or `python_tag` changes

**Migration Notes**

- Early 1.4.0 development snapshots (before integrity canonicalization fix) may require one-time
  `codeclone . --update-baseline`
- After this one-time update, baselines are stable for long-term CI use

---

### File System & Storage

**Atomic Operations**

- Baseline writes use atomic `*.tmp` + `os.replace` pattern (same filesystem requirement)
- Configurable size guards:
    - `--max-baseline-size-mb`
    - `--max-cache-size-mb`

**Baseline Trust Model**

- **Normal mode**: Untrusted baseline triggers warning and comparison against empty baseline
- **CI preset** (`--ci`): Untrusted baseline causes fast-fail with exit code `2`
- Deterministic behavior ensures predictable CI outcomes

---

### CLI & Exit Codes

**Exit Code Contract** (explicit and stable)

- `0` - Success
- `2` - Contract error (unreadable files, untrusted baseline, integrity failures)
- `3` - Gating failure (new clones, threshold violations)
- `5` - Internal error

**Exit Code Priority**

- Contract errors (exit `2`) override gating failures (exit `3`) when both conditions present

**CI/Gating Modes**

- In CI/gating modes (`--ci`, `--fail-on-new`, `--fail-threshold`):
    - Unreadable or decode-failed source files treated as contract errors (exit `2`)
    - Prevents incomplete analysis from passing CI checks

**Error Handling**

- Standardized internal error UX: `INTERNAL ERROR` with reason and actionable next steps
- New `--debug` flag (also `CODECLONE_DEBUG=1`) includes traceback + runtime environment details
- CLI help now includes canonical exit-code descriptions plus `Repository` / `Issues` / `Docs` links

---

### Reporting Enhancements

**JSON Report (v1.1 Schema)**

- Compact deterministic layout with top-level `meta` + `files` + `groups`
- Explicit `group_item_layout` for array-based group records
- New `groups_split` structure with `new`/`known` keys per section
- Deterministic `meta.groups_counts` aggregates
- Legacy alias sections removed (`function_clones`, `block_clones`, `segment_clones`)

**TXT Report (aligned to report meta v1.1)**

- Normalized metadata/order as stable contract
- Explicit section metrics: `loc` for functions, `size` for blocks/segments
- Sections split into `(NEW)` and `(KNOWN)` for functions/blocks/segments
- With untrusted baseline: `(KNOWN)` sections empty, all groups in `(NEW)`

**HTML Report (aligned to report meta v1.1)**

- New baseline split controls: `New duplicates` / `Known duplicates`
- Consistent filtering behavior across report types
- Block explainability now core-owned (`block_group_facts`)
- Expanded `Report Provenance` section displays full meta information block

**Cross-Format Metadata**

- All formats (HTML/TXT/JSON) now include:
    - `baseline_payload_sha256` and `baseline_payload_sha256_verified` for audit traceability
    - Cache contract fields: `cache_schema_version`, `cache_status`, `cache_used`
    - Baseline audit fields and trust status

### Documentation

- Added the contract documentation book `docs/book/`.

---

### Testing

**Baseline Contract Testing**

- Expanded matrix coverage:
    - Legacy format handling
    - Type/shape validation
    - Compatibility mismatch scenarios
    - Integrity failure cases
    - Canonical hash determinism

**Golden Snapshot Testing**

- New detector golden snapshot fixture with canonical runtime policy
- Golden assertions run on `cp313` (consistency)
- Full invariant suite maintains matrix-wide coverage
- Golden tests use same core `python_tag` source as CLI/baseline checks (prevents cross-layer drift)

---

### Roadmap Note

Version 1.4.0 establishes a stable baseline/CI contract but revealed internal structure needs cleanup. Version 1.5 will
focus on architecture refactoring for maintainability and orchestration, with strict constraints:

**No changes to:**

- Detection semantics
- Fingerprint algorithms
- Baseline hash inputs
- Determinism guarantees

The 1.4.0 contract remains stable and reliable for long-term CI integration.

## [1.3.0] - 2026-02-08

### Overview

This release improves detection precision, determinism, and auditability, adds
segment-level reporting, refreshes the HTML report UI, and hardens baseline/cache
contracts for CI usage.

**Breaking (CI):** baseline contract checks are stricter. Legacy or mismatched baselines
must be regenerated.

### Detection Engine

- Safe normalization upgrades: local logical equivalence, proven-domain commutative
  canonicalization, and preserved symbolic call targets.
- Internal CFG metadata markers were moved to the `__CC_META__::...` namespace and emitted
  as synthetic AST names to prevent collisions with user string literals.
- CFG precision upgrades: short-circuit micro-CFG, selective `try/except` raise-linking,
  loop `break`/`continue` jump semantics, `for/while ... else`, and ordered `match`/`except`.
- Deterministic traversal and ordering improvements for stable clone grouping/report output.
- Segment-level internal detection added with strict candidate->hash confirmation; remains
  report-only (not part of baseline/CI fail criteria).
- Segment report noise reduction: overlapping windows are merged and boilerplate-only groups
  are suppressed using deterministic AST criteria.

### Baseline & CI

- Baseline format is versioned (`baseline_version`, `schema_version`) and legacy baselines
  fail fast with regeneration guidance.
- Added tamper-evident baseline integrity for v1.3+ (`generator`, `payload_sha256`).
- Added configurable size guards: `--max-baseline-size-mb`, `--max-cache-size-mb`.
- Behavioral hardening: in normal mode, untrusted baseline states are ignored with warning
  and compared as empty; in `--fail-on-new` / `--ci`, they fail fast with deterministic exit codes.

Update baseline after upgrade:

```bash
codeclone . --update-baseline
```

### CLI & Reports

- Added `--version`, `--cache-path` (legacy alias: `--cache-dir`), and `--ci` preset.
- Added strict output extension validation for `--html/.html`, `--json/.json`, `--text/.txt`.
- Summary output was redesigned for deterministic, cache-aware metrics across standard and CI modes.
- User-facing CLI messages were centralized in `codeclone/ui_messages.py`.
- HTML/TXT/JSON reports now include consistent provenance metadata (baseline/cache status fields).
- Clone group/report ordering is deterministic and aligned across HTML/TXT/JSON outputs.

### HTML UI

- Refreshed layout with improved navigation and dashboard widgets.
- Added command palette and keyboard shortcuts.
- Replaced emoji icons with inline SVG icons.
- Hardened escaping (text + attribute context) and snippet fallback behavior.

### Cache & Security

- Cache default moved to `<root>/.cache/codeclone/cache.json` with legacy path warning.
- Cache schema moved to compact signed payload format (`CACHE_VERSION=1.2`) with
  relative file keys and fixed-array entries for faster IO and smaller files.
- Cache integrity uses constant-time signature checks and deep schema validation.
- Legacy `.cache_secret` is now treated as obsolete and triggers an explicit cleanup warning.
- Invalid/oversized cache is ignored deterministically and rebuilt from source.
- Added security regressions for traversal safety, report escaping, baseline/cache integrity,
  and deterministic report ordering across formats.
- Fixed POSIX parser CPU guard to avoid lowering `RLIMIT_CPU` hard limit.

### Documentation & Packaging

- Updated README and docs (`architecture`, `cfg`, `SECURITY`, `CONTRIBUTING`) to reflect
  current contracts and behaviors.
- Removed an invalid PyPI classifier from package metadata.

---

## [1.2.1] - 2026-02-02

### Overview

This release focuses on security hardening, robustness, and long-term maintainability.
No breaking API changes were introduced.

The goal of this release is to provide users with a safe, deterministic, and CI-friendly
tool suitable for security-sensitive and large-scale environments.

### Security & Robustness

- **Path Traversal Protection**
  Implemented strict path validation to prevent scanning outside the project root or
  accessing sensitive system directories, including macOS `/private` paths.

- **Cache Integrity Protection**
  Added HMAC-SHA256 signing for cache files to prevent cache poisoning and detect tampering.

- **Parser Safety Limits**
  Introduced AST parsing time limits to mitigate risks from pathological or adversarial inputs.

- **Resource Exhaustion Protection**
  Enforced a maximum file size limit (10MB) and a maximum file count per scan to prevent
  excessive memory or CPU usage.

- **Structured Error Handling**
  Introduced a dedicated exception hierarchy (`ParseError`, `CacheError`, etc.) and replaced
  broad exception handling with graceful, user-friendly failure reporting.

### Performance Improvements

- **Optimized AST Normalization**
  Replaced expensive `deepcopy` operations with in-place AST normalization, significantly
  reducing CPU and memory overhead.

- **Improved Memory Efficiency**
  Added an LRU cache for file reading and optimized string concatenation during fingerprint
  generation.

- **HTML Report Memory Bounds**
  HTML reports now read only the required line ranges instead of entire files, reducing peak
  memory usage on large codebases.

### Architecture & Maintainability

- **Strict Type Safety**
  Migrated all optional typing to Python 3.10+ `| None` syntax and achieved 100% `mypy` strict
  compliance.

- **Modular CFG Design**
  Split CFG data structures and builder logic into separate modules (`cfg_model.py` and
  `cfg.py`) for improved clarity and extensibility.

- **Template Extraction**
  Extracted HTML templates into a dedicated `templates.py` module.

- Added a `py.typed` marker for downstream type checkers.
- Added `__slots__` to performance-critical classes to reduce per-object memory overhead.

### CLI & User Experience

- Added a sequential execution fallback when process pools are unavailable (for example, in
  restricted or sandboxed environments).
- Emit clear, user-visible warnings when cache validation fails instead of silently ignoring
  corrupted state.
- Hardened HTML report template to safely embed JavaScript template literals and aligned it
  with linting requirements.

### Testing & Quality

- Expanded unit and integration test coverage across the CLI, CFG construction, cache
  handling, scanner, and HTML reporting paths.
- Added security regression tests for dot-dot traversal and symlinked sensitive directories.
- Tightened cache mismatch assertions to verify full state reset.
- Achieved and enforced 98%+ line coverage, with coverage configuration added to
  `pyproject.toml`.
- Added GitHub Actions workflow with Python 3.10–3.14 test matrix, including `ruff` and
  `mypy` checks.
- CI baseline enforcement now runs on a single pinned Python version to avoid AST dump
  differences across interpreter versions.

### Python Version Consistency for Baseline Checks

Due to inherent differences in Python’s AST between interpreter versions, baseline
generation and verification must be performed using the same Python version.

The baseline file now stores the Python version (`major.minor`) used during generation.
When running with `--fail-on-new`, codeclone verifies that the current interpreter version
matches the baseline and exits with code 2 if they differ.

This design ensures deterministic and reproducible clone detection results while preserving
support for Python 3.10–3.14 across the test matrix.

### Fixed

- **CFG Exception Handling**
  Fixed incorrect control-flow linking for `try`/`except` blocks.

- **Pattern Matching Support**
  Added missing structural handling for `match`/`case` statements in the CFG.

- **Block Detection Scaling**
  Made `MIN_LINE_DISTANCE` dynamic based on block size to improve clone detection accuracy
  across differently sized functions.

---

## [1.2.0] - 2026-02-02

### BREAKING CHANGES

- **CLI Arguments**
  Renamed output flags for brevity and consistency:
    - `--json-out` → `--json`
    - `--text-out` → `--text`
    - `--html-out` → `--html`
    - `--cache` → `--cache-dir`

- **Baseline Behavior**
    - The default baseline file location changed from
      `~/.config/codeclone/baseline.json` to `./codeclone.baseline.json`.
    - The CLI now warns if a baseline file is expected but missing (unless
      `--update-baseline` is used).

### Added

- **Detection Engine**
    - Deep CFG analysis for `try`/`except`/`finally`, `with`/`async with`, and
      `match`/`case` (Python 3.10+) statements.
    - Normalization for augmented assignments (`x += 1` vs `x = x + 1`).

- **Rich Output**
    - Color-coded status messages.
    - Progress indicators for long-running tasks.
    - Formatted summary tables.

- **CI/CD Improvements**
    - Clearer argument grouping in `--help` output.

### Improved

- **Baseline**
    - Safer JSON loading.
    - Improved typing and cleaner construction API.

- **Cache**
    - Graceful recovery from corrupted cache files.
    - Updated typing to modern Python standards.

- **Typing**
    - General typing improvements across reporting and normalization modules.

---

## [1.1.0] - 2026-01-19

### Added

- Control Flow Graph (CFG v1) for structural clone detection.
- Deterministic CFG-based function fingerprints.
- Interactive HTML report with syntax highlighting.
- Block-level clone visualization.

### Changed

- Function clone detection now based on CFG instead of pure AST.
- Improved robustness against refactoring and control-flow changes.

### Documentation

- Added `docs/cfg.md` with CFG semantics and limitations.
- Added `docs/architecture.md` describing system design.

---

## [1.0.0] - 2026-01-17

### Initial release

- AST-based function clone detection.
- Block-level clone detection (Type-3-lite).
- Baseline workflow for CI.
- JSON and text reports.
