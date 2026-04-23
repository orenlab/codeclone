# AGENTS.md — CodeClone (AI Agent Playbook)

This document is the **source of truth** for agent operating rules in this repository.
It is optimized for **determinism**, **CI stability**, and **reproducible changes**.

For architecture, module ownership, and runtime behavior, the **current repository code is the source of truth**.
If AGENTS.md and code diverge, follow code and update AGENTS.md accordingly.

> Repository goal: maximize **honesty**, **reproducibility**, **determinism**, and **precision** for real‑world CI
> usage.

---

## 1) Operating principles (non‑negotiable)

1. **Do not break CI contracts.**
    - Treat baseline, cache, and report formats as **public APIs**.
    - Any contract change must be **versioned**, documented, and accompanied by tests.

2. **Determinism > cleverness.**
    - Outputs must be stable across runs given identical inputs (same repo, tool version, python tag).

3. **Evidence-based explainability.**
    - The core engine produces **facts/metrics**.
    - HTML/UI **renders facts**, it must not invent interpretations.

4. **Safety first.**
    - Never delete or overwrite user files outside repo.
    - Any write must be atomic where relevant (e.g., baseline `.tmp` + `os.replace`).

5. **Golden tests are contract sentinels.**
    - Do not update golden snapshots to “fix” failing tests unless the contract change is intentional, versioned where
      required, documented, and explicitly approved.
6. **Fingerprint-adjacent optimization policy**

    - Performance work must not change AST normalization, fingerprint inputs, or clone identity semantics while
      `FINGERPRINT_VERSION` remains unchanged.

    - If a change in AST/core analysis can affect fingerprint bytes, clone identity, NEW vs KNOWN classification, or
      baseline compatibility semantics, it is not a routine optimization. It must be treated as an explicit fingerprint
      contract change and requires:
        - `FINGERPRINT_VERSION` review or bump
        - documentation updates
        - migration/release notes
        - explicit maintainer approval
    - Performance alone is never a sufficient reason to change fingerprint semantics.

---

## 2) Quick orientation

CodeClone provides structural code quality analysis for Python. It supports:

- **function clones** (strongest signal)
- **block clones** (sliding window of statements, may be noisy on boilerplate)
- **segment clones** (report-only unless explicitly gated)

Key artifacts:

- `codeclone.baseline.json` — trusted baseline snapshot (for CI comparisons)
- `.cache/codeclone/cache.json` — analysis cache (integrity-checked)
- `.cache/codeclone/report.html|report.json|report.md|report.sarif|report.txt` — reports
- `codeclone-mcp` — optional read-only MCP server (install via `codeclone[mcp]`)
- `extensions/vscode-codeclone/` — preview VS Code extension as a native, read-only IDE client over `codeclone-mcp`
- `extensions/claude-desktop-codeclone/` — preview Claude Desktop `.mcpb` bundle as a local install wrapper over
  `codeclone-mcp`
- `plugins/codeclone/` + `.agents/plugins/marketplace.json` — preview Codex plugin as a native local discovery layer
  over `codeclone-mcp`, with a bundled CodeClone review skill
- MCP runs are in-memory only; review markers are session-local and must never
  leak into baseline/cache/report artifacts
- `docs/`, `mkdocs.yml`, `.github/workflows/docs.yml` — published documentation site and docs build pipeline

---

## 3) One command to validate your change

Run these locally before proposing changes:

```bash
uv run pre-commit run --all-files
```

If you touched baseline/cache/report contracts, also run the repo’s audit runner (or the scenario script if present).
If you touched `docs/`, `mkdocs.yml`, docs publishing workflow, or sample-report generation, also run:

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict
```

If you touched the MCP surface, also run:

```bash
uv run pytest -q tests/test_mcp_service.py tests/test_mcp_server.py
```

If you touched the VS Code extension surface, also run:

```bash
node --check extensions/vscode-codeclone/src/support.js
node --check extensions/vscode-codeclone/src/mcpClient.js
node --check extensions/vscode-codeclone/src/extension.js
node --test extensions/vscode-codeclone/test/*.test.js
node extensions/vscode-codeclone/test/runExtensionHost.js
```

If you touched VS Code extension packaging metadata (`package.json`,
README/changelog/license, media assets, or `.vscodeignore`), also run a package
smoke:

```bash
cd extensions/vscode-codeclone
vsce package --pre-release --out /tmp/codeclone.vsix
```

If you touched the Claude Desktop bundle surface, also run:

```bash
node --check extensions/claude-desktop-codeclone/server/index.js
node --check extensions/claude-desktop-codeclone/src/launcher.js
node --check extensions/claude-desktop-codeclone/scripts/build-mcpb.mjs
node --test extensions/claude-desktop-codeclone/test/*.test.js
node extensions/claude-desktop-codeclone/scripts/build-mcpb.mjs --out /tmp/codeclone-claude-desktop.mcpb
```

If you touched the Codex plugin surface, also run:

```bash
python3 -m json.tool plugins/codeclone/.codex-plugin/plugin.json >/tmp/codeclone-codex-plugin.json
python3 -m json.tool plugins/codeclone/.mcp.json >/tmp/codeclone-codex-mcp.json
python3 -m json.tool .agents/plugins/marketplace.json >/tmp/codeclone-codex-marketplace.json
uv run pytest -q tests/test_codex_plugin.py
```

---

## 4) Baseline contract (v2, stable)

### Versioned constants (single source of truth)

All schema/version constants live in `codeclone/contracts/__init__.py`. **Always read them from code, never copy
from another doc.** Current values (verified at write time):

| Constant                          | Source                            | Current value |
|-----------------------------------|-----------------------------------|---------------|
| `BASELINE_SCHEMA_VERSION`         | `codeclone/contracts/__init__.py` | `2.1`         |
| `BASELINE_FINGERPRINT_VERSION`    | `codeclone/contracts/__init__.py` | `1`           |
| `CACHE_VERSION`                   | `codeclone/contracts/__init__.py` | `2.5`         |
| `REPORT_SCHEMA_VERSION`           | `codeclone/contracts/__init__.py` | `2.8`         |
| `METRICS_BASELINE_SCHEMA_VERSION` | `codeclone/contracts/__init__.py` | `1.2`         |

When updating any doc that mentions a version, re-read `codeclone/contracts/__init__.py` first. Do not derive
versions from another document.

### Baseline file structure (canonical)

```json
{
  "meta": {
    "generator": {
      "name": "codeclone",
      "version": "X.Y.Z"
    },
    "schema_version": "2.1",
    "fingerprint_version": "1",
    "python_tag": "cp313",
    "created_at": "2026-02-08T14:20:15Z",
    "payload_sha256": "…"
  },
  "clones": {
    "functions": [],
    "blocks": []
  },
  "metrics": {
    "...": "optional embedded snapshot"
  }
}
```

### Rules

- `schema_version` is **baseline schema**, not package version.
- Runtime writes baseline schema `2.1`.
- Runtime accepts baseline schema `1.0` and `2.0`–`2.1` (governed by
  `_BASELINE_SCHEMA_MAX_MINOR_BY_MAJOR` in `codeclone/baseline/trust.py`).
- Compatibility is tied to:
    - `fingerprint_version`
    - `python_tag`
    - `generator.name == "codeclone"`
- `payload_sha256` is computed from a **canonical payload**:
    - stable key order
    - clone id lists are **sorted and unique**
    - integrity check uses constant‑time compare (e.g., `hmac.compare_digest`)

### Trust model

- A baseline is either **trusted** (`baseline_status = ok`) or **untrusted**.
- **Normal mode**:
    - warn
    - ignore untrusted baseline
    - compare vs empty baseline
- **CI gating mode** (`--ci` / `--fail-on-new`):
    - fail‑fast if baseline untrusted
    - exit code **2** for untrusted baseline

### Legacy behavior

- Legacy baselines (<= 1.3.x layout) must be treated as **untrusted** with explicit messaging and tests.

---

## 5) Cache contract (integrity + size guards)

- Cache is an **optimization**, never a source of truth.
- If cache is invalid or too large:
    - warn
    - proceed without cache
    - ensure report meta reflects `cache_used=false`

Never “fix” cache by silently mutating it; prefer regenerate.

---

## 6) Reports and explainability

Reports come in:

- HTML (`--html`)
- JSON (`--json`)
- Markdown (`--md`)
- SARIF (`--sarif`)
- Text (`--text`)

MCP is a separate optional interface, not a report format. It must remain a
read-only agent layer over the same canonical report/baseline/cache contracts.
Session review markers are allowed only as ephemeral MCP process state.

### Report invariants

- Ordering must be deterministic (stable sort keys).
- All provenance fields must be consistent across formats:
    - baseline loaded / status
    - baseline fingerprint + schema versions
    - baseline generator version
    - cache path / cache used
- SARIF `partialFingerprints.primaryLocationLineHash` must remain stable across
  line-only shifts for the same finding identity.
- SARIF `automationDetails.id` must be unique per run; result `kind` should be
  explicit when emitted.

### Explainability contract (core owns facts)

For each clone group (especially block clones), the **core** should be able to provide factual fields such as:

- `match_rule`
- `signature_kind`
- `window_size` (block size) / `segment_size`
- `merged_regions` flag and counts
- `stmt_type_sequence` (normalized)
- `stmt_type_histogram`
- `has_control_flow` (if/for/while/try/match)
- ratios (assert / assign / call)
- `max_consecutive_<type>` (e.g., consecutive asserts)

UI can show **hints** only when the predicate is **formal & exact** (100% confidence), e.g.:

- `assert_only_block` (assert_ratio == 1.0 and consecutive_asserts == block_len)
- `repeated_stmt_hash` (single stmt hash repeated across window)

No UI-only heuristics that affect gating.

---

## 7) Noise policy (what is and isn’t a “fix”)

### Acceptable fixes

- Merge/report-layer improvements (e.g., merge sliding windows into maximal regions) **without changing gating**.
- Better evidence surfaced in HTML to explain matches.

### Not acceptable as a “quick fix”

- Weakening detection rules to hide noisy test patterns, unless:
    - it is configurable
    - default remains honest
    - the change is justified by real-world repos
    - it includes tests for false-negative risk

### Preferred remediation for test-only FPs

- Refactor tests to avoid long repetitive statement sequences:
    - replace chains of `assert "... in html"` with loops or aggregated checks.

---

## 8) How to propose changes (agent workflow)

When you implement something:

1. **State the intent** (what user-visible issue does it solve?)
2. **List files touched** and why.
3. **Call out contracts affected**:
    - baseline / cache / report schema
    - CLI exit codes / messages
4. **Add/adjust tests** for:
    - normal-mode behavior
    - CI gating behavior
    - determinism (identical output on rerun)
    - legacy/untrusted scenarios where applicable
5. Run:
    - `ruff`, `mypy`, `pytest`

Avoid changing unrelated files (locks, roadmap) unless required.

---

## 9) CLI behavior and exit codes

Agents must preserve these semantics:

- **0** — success (including “new clones detected” in non-gating mode)
- **2** — baseline gating failure (untrusted/missing baseline when CI requires trusted baseline; invalid output
  extension, etc.)
- **3** — analysis gating failure (e.g., `--fail-threshold` exceeded or new clones in `--ci` as designed)
- **5** — internal error (unexpected exception escaped top-level CLI handling)

Changed-scope flags are contract-sensitive:

- `--changed-only` keeps the canonical analysis/report full, but applies clone
  summary/threshold evaluation to the changed-files projection.
- `--diff-against` requires `--changed-only`.
- `--paths-from-git-diff` implies `--changed-only`.

If you introduce a new exit reason, document it and add tests.

---

## 10) Release hygiene (for agent-assisted releases)

Before cutting a release:

- Confirm baseline schema compatibility is unchanged, or properly versioned.
- Ensure changelog has:
    - user-facing changes
    - migration notes if any
- Validate `twine check dist/*` for built artifacts.
- Smoke test install in a clean venv:
    - `uv pip install dist/*.whl`
    - `codeclone --version`
    - `codeclone . --ci` in a sample repo with baseline.

---

## 11) “Don’t do this” list

- Don’t add hidden behavior differences between report formats.
- Don’t make baseline compatibility depend on package patch/minor version.
- Don’t add project-root hashes or unstable machine-local fields to baseline.
- Don’t embed suppressions into baseline unless explicitly designed as a versioned contract.
- Don’t introduce nondeterministic ordering (dict iteration, set ordering, filesystem traversal without sort).
- Don’t make the base `codeclone` install depend on optional MCP runtime packages.
- Don’t let MCP mutate baselines, source files, or repo state.
- Don’t let MCP re-synthesize design findings from raw metrics; read canonical `findings.groups.design` only.

---

## 12) Repository architecture

Architecture is layered, but grounded in current code (not aspirational diagrams):

- **CLI entry + orchestration surface** (`codeclone/main.py`, `codeclone/surfaces/cli/*`, `codeclone/ui_messages/*`)
  owns argument parsing, runtime/config resolution, summaries, report writes, and exit routing.
- **Config layer** (`codeclone/config/*`) is the single source of truth for option specs, parser construction,
  `pyproject.toml` loading, and CLI > pyproject > defaults resolution.
- **Core orchestration** (`codeclone/core/*`) owns bootstrap → discovery → worker processing → project metrics →
  report/gate integration. It does not own shell UX.
- **Analysis layer** (`codeclone/analysis/*`, `codeclone/blocks/*`, `codeclone/paths/*`, `codeclone/qualnames/*`)
  parses source, normalizes AST/CFG facts, extracts units, and prepares deterministic analysis inputs.
- **Clone/finding derivation layer** (`codeclone/findings/*`, `codeclone/metrics/*`) groups clones and computes
  structural and quality signals from already-extracted facts.
- **Domain/contracts layer** (`codeclone/models.py`, `codeclone/contracts/*`, `codeclone/domain/*`) defines typed
  entities, enums, schema/version constants, and typed exceptions used across layers.
- **Persistence contracts** (`codeclone/baseline/*`, `codeclone/cache/*`) store trusted comparison state and
  optimization state. They are contracts, not analysis truth.
- **Canonical report + projections** (`codeclone/report/document/*`, `codeclone/report/gates/*`,
  `codeclone/report/renderers/*`, `codeclone/report/*.py`) converts analysis facts into deterministic report payloads
  and deterministic projections.
- **HTML/UI rendering** (`codeclone/report/html/*`) renders views from canonical report/meta
  facts. HTML is render-only.
- **MCP agent interface** (`codeclone/surfaces/mcp/*`) exposes the same pipeline/report contracts as a deterministic,
  read-only MCP surface for AI agents and MCP-capable clients.
- **Documentation/publishing surface** (`docs/`, `mkdocs.yml`, `.github/workflows/docs.yml`,
  `scripts/build_docs_example_report.py`) publishes contract docs and the live sample report.
- **VS Code extension surface** (`extensions/vscode-codeclone/*`) is a native, workspace-only IDE client over
  `codeclone-mcp`, with baseline-aware, triage-first, source-first review UX.
- **Claude Desktop bundle surface** (`extensions/claude-desktop-codeclone/*`) is a native `.mcpb` install wrapper for
  Claude Desktop that launches the same local `codeclone-mcp` server via local `stdio`.
- **Codex plugin surface** (`plugins/codeclone/*`, `.agents/plugins/marketplace.json`) is a native local Codex plugin
  over `codeclone-mcp`, with repo-local discovery metadata and a bundled CodeClone review skill.
- **Tests-as-spec** (`tests/`) lock behavior, contracts, determinism, and architecture boundaries.

Non-negotiable interpretation:

- Core produces facts; renderers present facts.
- Baseline/cache are persistence contracts, not analysis truth.
- UI/report must not invent gating semantics.
- MCP reuses pipeline/report contracts and must not create a second analysis truth path.
- The VS Code extension is a guided IDE view over MCP and must not introduce a second analysis or truth path.
- The Claude Desktop bundle is a local setup surface over `codeclone-mcp` and must not introduce a second server or
  truth path.
- The Codex plugin is a local discovery and guidance surface over `codeclone-mcp` and must not introduce a second
  analyzer, MCP server, or truth path.

## 13) Module map

Use this map to route changes to the right owner module.

- `codeclone/main.py` — public CLI entrypoint only. Keep it tiny.
- `codeclone/surfaces/cli/workflow.py` — top-level CLI orchestration and exit routing. Add CLI control flow here, not
  in `main.py`.
- `codeclone/surfaces/cli/*` — CLI support slices (startup, runtime, execution, post-run handling, summaries,
  reports, changed-scope logic, baseline state, console helpers). Keep them orchestration/UX-focused.
- `codeclone/config/*` — parser construction, option specs/defaults, pyproject loading, config resolution. Do not
  duplicate option semantics elsewhere.
- `codeclone/core/*` — canonical runtime pipeline and payload plumbing. Change integration flow here; do not move shell
  UX or HTML-only logic here.
- `codeclone/analysis/*` — AST parsing, CFG/fingerprint preparation, declaration/reference collection, and unit
  extraction. Change parsing/extraction semantics here; keep it independent from CLI/report/baseline UX.
- `codeclone/findings/clones/grouping.py` + `codeclone/blocks/*` — clone grouping and block/segment mechanics.
- `codeclone/findings/structural/detectors.py` — structural finding extraction/normalization policy; keep it factual
  and deterministic.
- `codeclone/metrics/*` — metric computations and dead-code/dependency/health logic; change metric math and thresholds
  here; do not make metrics depend on renderer/UI concerns.
- `codeclone/suppressions.py` — inline `# codeclone: ignore[...]` parse/bind/index logic; keep it declaration-scoped
  and deterministic.
- `codeclone/baseline/clone_baseline.py` + `codeclone/baseline/trust.py` — clone baseline schema/trust/integrity/
  compatibility contract; all clone-baseline format changes go here with explicit contract process.
- `codeclone/baseline/metrics_baseline.py` + `codeclone/baseline/_metrics_baseline_*` — metrics-baseline schema,
  validation, payload hashing, and unified-baseline merge logic.
- `codeclone/cache/store.py`, `codeclone/cache/versioning.py`, `codeclone/cache/integrity.py`,
  `codeclone/cache/_wire_*`, `codeclone/cache/projection.py` — cache schema/status/profile compatibility, canonical
  JSON/signing, wire encoding/decoding, and segment projection persistence. Cache remains optimization-only.
- `codeclone/report/document/*` — canonical report schema builder and integrity payload. Any JSON contract shape change
  belongs here.
- `codeclone/report/renderers/*` — deterministic text/markdown/SARIF/JSON projections over the canonical report.
- `codeclone/report/html/*` — actual HTML assembly, context shaping, tabs, sections, widgets, CSS/JS/escaping, and
  snippets. Change report layout and interactive HTML UX here, not in report builders.
- `codeclone/report/gates/*` — metric-gate reason derivation over canonical metrics state.
- `codeclone/report/*.py` (other modules) — deterministic report support slices such as explainability, suggestions,
  merge, overview, findings helpers, and source-kind routing.
- `codeclone/surfaces/mcp/service.py` — typed, in-process MCP service over the current pipeline/report contracts;
  keep it deterministic and read-only except for session-local in-memory markers.
- `codeclone/surfaces/mcp/server.py` — optional MCP launcher/server wiring, transport config, and MCP tool/resource
  registration; keep dependency loading lazy so base installs/CI do not require MCP runtime packages.
- `tests/test_mcp_service.py`, `tests/test_mcp_server.py` — MCP contract and integration tests; run these when
  touching any MCP surface.
- `codeclone/contracts/*` — version constants, schema types, exit enum, URLs, and typed exceptions. Treat as contract
  surface.
- `codeclone/models.py` — shared typed models crossing modules; keep model changes contract-aware.
- `codeclone/domain/*.py` — centralized domain taxonomies/IDs (families, categories, source scopes, risk/severity
  levels); use these constants in pipeline/report/UI instead of scattering raw literals.
- `codeclone/ui_messages/*` — CLI text/marker/help constants and formatter helpers. Keep message policy centralized.
- `docs/`, `mkdocs.yml`, `.github/workflows/docs.yml`, `scripts/build_docs_example_report.py` — docs-site source,
  publication workflow, and live sample-report generation; keep published docs aligned with code contracts.
- `extensions/vscode-codeclone/*` — preview VS Code extension surface; keep it baseline-aware, triage-first,
  source-first, and faithful to MCP/canonical report semantics rather than building a second analyzer or report model.
- `extensions/claude-desktop-codeclone/*` — preview Claude Desktop bundle surface; keep it local-stdio-only,
  launcher-focused, and faithful to `codeclone-mcp` rather than re-implementing MCP semantics in the bundle layer.
- `plugins/codeclone/*`, `.agents/plugins/marketplace.json` — preview Codex plugin surface; keep it Codex-native,
  conservative-first, skills-guided, and faithful to `codeclone-mcp` rather than inventing plugin-only analysis logic.
- `tests/` — executable specification: architecture rules, contracts, goldens, invariants, regressions.

## 14) Dependency direction

Dependency direction is enforceable and partially test-guarded (`tests/test_architecture.py`):

- `codeclone.report.*` must not import `codeclone.ui_messages`, `codeclone.surfaces.cli`, or HTML consumers outside
  `codeclone.report.html.*`.
- `codeclone.baseline` and `codeclone.cache` must not import `codeclone.surfaces.cli`, `codeclone.ui_messages`, or
  `codeclone.report.html`.
- `codeclone.core` must not import `codeclone.surfaces.*` or `codeclone.config`.
- `codeclone.analysis`, `codeclone.findings`, and `codeclone.metrics` must not import `codeclone.surfaces.*`; analysis
  and findings must also stay independent from config/report-builder wiring.
- `codeclone.models` may import only `codeclone.contracts` from local modules.
- `codeclone.domain.*` must remain leaf domain modules.

Operational rules:

- Core/domain code must not depend on HTML/UI or MCP.
- Renderers depend on canonical report payload/model; canonical report builders must not depend on renderer/UI.
- Metrics/report layers must not recompute or invent core facts in UI.
- CLI support modules under `codeclone/surfaces/cli/*` must orchestrate/format, not own domain semantics.
- Persistence semantics (baseline/cache trust/integrity) must stay in persistence/domain modules, not in render/UI
  layers.
- MCP may depend on pipeline/report/contracts, but core/persistence/report layers must not depend on MCP modules.

## 15) Suppression policy

Inline suppressions are explicit local policy, not analysis truth.

- Supported syntax is `# codeclone: ignore[rule-id,...]` via `codeclone/suppressions.py`.
- Binding scope is declaration-only (`def`, `async def`, `class`) using:
    - leading comment on the line immediately before declaration
    - inline comment on the declaration header start line
    - inline comment on the declaration header closing line for multiline signatures
- Binding is target-specific (`filepath`, `qualname`, declaration span, kind). No file-wide/global implicit scope.
- Unknown/malformed directives are ignored safely; analysis must not fail because of suppression syntax issues.
- Current active semantic effect is dead-code suppression (`dead-code`) through `extractor.py` →
  `DeadCandidate.suppressed_rules` → `metrics/dead_code.py`.
- Suppressed dead-code findings are excluded from active dead-code findings and health impact, but remain observable in
  report surfaces where implemented (JSON summary/details, text/markdown/html, CLI counters).
- Suppressions must not silently alter unrelated finding families.

Prefer explicit inline suppressions for runtime/dynamic false positives instead of broad framework heuristics.

## 16) Change routing

If you change a contract-sensitive zone, route docs/tests/approval deliberately.

| Change zone                                                                                                                         | Must update docs                                                                                                                                                    | Must update tests                                                                                                                                                                                                                                                                                                                    | Explicit approval required when                                                                       | Contract-change trigger                                                                                    |
|-------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------|
| Baseline schema/trust/integrity (`codeclone/baseline/clone_baseline.py`, `codeclone/baseline/trust.py`)                             | `docs/book/06-baseline.md`, `docs/book/14-compatibility-and-versioning.md`, `docs/book/appendix/b-schema-layouts.md`, `CHANGELOG.md`                                | `tests/test_baseline.py`, CI/CLI behavior tests (`tests/test_cli_inprocess.py`, `tests/test_cli_unit.py`)                                                                                                                                                                                                                            | schema/trust semantics, compatibility windows, payload integrity logic change                         | baseline key layout/status semantics/compat rules change                                                   |
| Cache schema/profile/integrity (`codeclone/cache/store.py`, `codeclone/cache/versioning.py`, `codeclone/cache/integrity.py`)        | `docs/book/07-cache.md`, `docs/book/appendix/b-schema-layouts.md`, `CHANGELOG.md`                                                                                   | `tests/test_cache.py`, pipeline/CLI cache integration tests                                                                                                                                                                                                                                                                          | cache schema/status/profile compatibility semantics change                                            | cache payload/version/status semantics change                                                              |
| Canonical report JSON shape (`codeclone/report/document/*`, report projections)                                                     | `docs/book/08-report.md` (+ `docs/book/10-html-render.md` if rendering contract impacted), `docs/sarif.md` when SARIF changes, `CHANGELOG.md`                       | `tests/test_report.py`, `tests/test_report_contract_coverage.py`, `tests/test_report_branch_invariants.py`, relevant report-format tests                                                                                                                                                                                             | finding/meta/summary schema changes                                                                   | stable JSON fields/meaning/order guarantees change                                                         |
| CLI flags/help/exit behavior (`codeclone/main.py`, `codeclone/surfaces/cli/*`, `codeclone/config/*`, `codeclone/contracts/*`)       | `docs/book/09-cli.md`, `docs/book/03-contracts-exit-codes.md`, `README.md`, `CHANGELOG.md`                                                                          | `tests/test_cli_unit.py`, `tests/test_cli_inprocess.py`, `tests/test_cli_smoke.py`                                                                                                                                                                                                                                                   | exit-code semantics, script-facing behavior, flag contracts change                                    | user-visible CLI contract changes                                                                          |
| Fingerprint-adjacent analysis (`extractor/cfg/normalize/grouping`)                                                                  | `docs/book/05-core-pipeline.md`, `docs/cfg.md`, `docs/book/14-compatibility-and-versioning.md`, `CHANGELOG.md`                                                      | `tests/test_fingerprint.py`, `tests/test_extractor.py`, `tests/test_cfg.py`, golden tests (`tests/test_detector_golden.py`, `tests/test_golden_v2.py`)                                                                                                                                                                               | always (see Section 1.6)                                                                              | clone identity / NEW-vs-KNOWN / fingerprint inputs change                                                  |
| Suppression semantics/reporting (`suppressions`, extractor dead-code wiring, report/UI counters)                                    | `docs/book/19-inline-suppressions.md`, `docs/book/16-dead-code-contract.md`, `docs/book/08-report.md`, and interface docs if surfaced (`09-cli`, `10-html-render`)  | `tests/test_suppressions.py`, `tests/test_extractor.py`, `tests/test_metrics_modules.py`, `tests/test_pipeline_metrics.py`, report/html/cli tests                                                                                                                                                                                    | declaration scope semantics, rule effect, or contract-visible counters/fields change                  | suppression changes alter active finding output or contract-visible report payload                         |
| MCP interface (`codeclone/surfaces/mcp/*`, packaging extra/launcher)                                                                | `README.md`, `docs/book/20-mcp-interface.md`, `docs/mcp.md`, `docs/book/01-architecture-map.md`, `docs/book/14-compatibility-and-versioning.md`, `CHANGELOG.md`     | `tests/test_mcp_service.py`, `tests/test_mcp_server.py`, plus CLI/package tests if launcher/install semantics change                                                                                                                                                                                                                 | tool/resource shapes, read-only semantics, optional-dependency packaging behavior change              | public MCP tool names, resource URIs, launcher/install behavior, or response semantics change              |
| VS Code extension surface (`extensions/vscode-codeclone/*`)                                                                         | `README.md`, `docs/book/21-vscode-extension.md`, `docs/vscode-extension.md`, `docs/book/01-architecture-map.md`, `docs/README.md`, `CHANGELOG.md`                   | `node --check extensions/vscode-codeclone/src/support.js`, `node --check extensions/vscode-codeclone/src/mcpClient.js`, `node --check extensions/vscode-codeclone/src/extension.js`, `node --test extensions/vscode-codeclone/test/*.test.js`, plus local extension-host smoke and package smoke when surface/manifest/assets change | command/view UX, trust/runtime model, source-first review flow, or packaging metadata change          | documented commands/views/setup/trust behavior, packaged assets, or publish metadata change                |
| Claude Desktop bundle surface (`extensions/claude-desktop-codeclone/*`)                                                             | `docs/book/22-claude-desktop-bundle.md`, `docs/claude-desktop-bundle.md`, `docs/mcp.md`, `docs/book/01-architecture-map.md`, `docs/README.md`, `CHANGELOG.md`       | `node --check extensions/claude-desktop-codeclone/server/index.js`, `node --check extensions/claude-desktop-codeclone/src/launcher.js`, `node --check extensions/claude-desktop-codeclone/scripts/build-mcpb.mjs`, `node --test extensions/claude-desktop-codeclone/test/*.test.js`, plus `.mcpb` build smoke                        | bundle install/runtime model, launcher UX, local-stdio constraints, or bundle metadata change         | documented Claude Desktop install/setup/runtime behavior or packaged bundle semantics change               |
| Codex plugin surface (`plugins/codeclone/*`, `.agents/plugins/marketplace.json`)                                                    | `docs/book/23-codex-plugin.md`, `docs/codex-plugin.md`, `docs/mcp.md`, `docs/book/01-architecture-map.md`, `docs/README.md`, `CHANGELOG.md`                         | `python3 -m json.tool plugins/codeclone/.codex-plugin/plugin.json`, `python3 -m json.tool plugins/codeclone/.mcp.json`, `python3 -m json.tool .agents/plugins/marketplace.json`, `tests/test_codex_plugin.py`                                                                                                                        | plugin discovery/runtime model, bundled MCP config, bundled skill behavior, or plugin metadata change | documented Codex plugin install/discovery/runtime behavior or plugin manifest/marketplace semantics change |
| Docs site / sample report publication (`docs/`, `mkdocs.yml`, `.github/workflows/docs.yml`, `scripts/build_docs_example_report.py`) | `docs/README.md`, `docs/publishing.md`, `docs/examples/report.md`, and any contract pages surfaced by the change, `CHANGELOG.md` when user-visible behavior changes | `mkdocs build --strict`, sample-report generation smoke path, and relevant report/html tests if generated examples or embeds change                                                                                                                                                                                                  | published docs navigation, sample-report generation, or Pages workflow semantics change               | published documentation behavior or sample-report generation contract changes                              |

Golden rule: do not “fix” failures by snapshot refresh unless the underlying contract change is intentional, documented,
and approved.

## 17) Testing taxonomy

Treat tests as specification with explicit intent:

- **Unit tests** — module-level behavior and edge conditions (e.g., `tests/test_cfg.py`, `tests/test_normalize.py`,
  `tests/test_metrics_modules.py`, `tests/test_suppressions.py`).
- **Contract tests** — baseline/cache/report/CLI public semantics (e.g., `tests/test_baseline.py`,
  `tests/test_cache.py`, `tests/test_report_contract_coverage.py`, `tests/test_cli_unit.py`).
- **Golden tests** — snapshot sentinels for stable outputs (`tests/test_detector_golden.py`, `tests/test_golden_v2.py`).
- **Determinism/invariant tests** — ordering, branch-path invariants, and canonical stability (e.g.,
  `tests/test_report_branch_invariants.py`, `tests/test_core_branch_coverage.py`).
- **Scenario/regression tests** — multi-step integration and process-level behavior (e.g.,
  `tests/test_cli_inprocess.py`, `tests/test_pipeline_process.py`, `tests/test_cli_smoke.py`).

Policy:

- Expand the closest taxonomy bucket when changing behavior.
- If a change touches a public surface, include/adjust contract tests, not only unit tests.
- Goldens validate intended contract shifts; they are not a substitute for reasoning or routing.

## 18) Public vs internal surfaces

### Public / contract-sensitive surfaces

- CLI flags, defaults, exit codes, and stable script-facing messages.
- Baseline schema/trust semantics/integrity compatibility (`BASELINE_SCHEMA_VERSION` contract family).
- Cache schema/status/profile compatibility/integrity (`CACHE_VERSION` contract family).
- Canonical report JSON schema/payload semantics (`REPORT_SCHEMA_VERSION` contract family).
- Documented report projections and their machine/user-facing semantics (HTML/Markdown/SARIF/Text).
- Documented MCP launcher/install behavior, tool names, resource URIs, and read-only semantics.
- Session-local MCP review state semantics (`mark_finding_reviewed`, `exclude_reviewed`) as documented public behavior.
- Documented VS Code extension behavior: commands, views, setup guidance, trusted-workspace model, and its
  baseline-aware triage workflow over MCP.
- Documented finding families/kinds/ids and suppression-facing report fields.
- Metrics baseline schema/compatibility where used by CI/gating.
- Benchmark schema/outputs if consumed as a reproducible contract surface.

### Internal implementation surfaces

- Local helpers and formatting utilities (`codeclone/report/html/widgets/*`,
  `codeclone/report/html/primitives/*`, many private `_as_*` normalizers, local transformers).
- Internal orchestration decomposition inside `codeclone/surfaces/cli/*`.
- Private utility refactors that do not change public payloads, exit semantics, ordering, or trust rules.

If classification is ambiguous, treat it as contract-sensitive and add tests/docs before merging.

## 19) Python language + typing rules (3.10 → 3.14)

These rules are **repo policy**. If you need to violate one, you must explain why in the PR.

### Supported Python versions

- **Must run on Python 3.10, 3.11, 3.12, 3.13, 3.14**.
- Do not rely on behavior that is new to only the latest version unless you provide a fallback.
- Prefer **standard library** features that exist in 3.10+.

### Modern syntax (allowed / preferred)

Use modern syntax when it stays compatible with 3.10+:

- `X | Y` unions, `list[str]` / `dict[str, int]` generics (PEP 604 / PEP 585)
- `from __future__ import annotations` is allowed, but keep behavior consistent across 3.10–3.14.
- `match/case` (PEP 634) is allowed, but only if it keeps determinism/readability.
- `typing.Self` (3.11+) **avoid** in public APIs unless you gate it with `typing_extensions`.
- Prefer `pathlib.Path` over `os.path` for new code (but keep hot paths pragmatic).

### Typing standards

- **Type hints are required** for all public functions, core pipeline surfaces, and any code that touches:
  baseline, cache, fingerprints, report models, serialization, CLI exit behavior.
- Keep **`Any` to an absolute minimum**:
    - `Any` is allowed only at IO boundaries (JSON parsing, `argparse`, `subprocess`) and must be
      *narrowed immediately* into typed structures (dataclasses / TypedDict / Protocol / enums).
    - If `Any` appears in “core/domain” code, add a comment: `# Any: <reason>` and a TODO to remove.
- Prefer **`Literal` / enums** for finite sets (e.g., status codes, kinds).
- Prefer **`dataclasses`** (frozen where reasonable) for data models; keep models JSON‑serializable.
- Use `collections.abc` types (`Iterable`, `Sequence`, `Mapping`) for inputs where appropriate.
- Avoid `cast()` unless you also add an invariant check nearby.

### Dataclasses / models

- Models that cross module boundaries should be:
    - explicitly typed
    - immutable when possible (`frozen=True`)
    - validated at construction (or via a dedicated `validate_*` function) if they are user‑provided.

### Error handling

- Prefer explicit, typed error types over stringly‑typed errors.
- Exit codes are part of the public contract; do not change them without updating tests + docs.

### Determinism requirements (language-level)

- Never iterate over unordered containers (`set`, `dict`) without sorting first when it affects:
  hashes, IDs, report ordering, baseline payloads, or UI output.
- Use stable formatting (sorted keys, stable ordering) in JSON output.

### Key PEPs to keep in mind

- PEP 8, PEP 484 (typing), PEP 526 (variable annotations)
- PEP 563 / PEP 649 (annotation evaluation changes across versions) — avoid relying on evaluation timing
- PEP 585 (built-in generics), PEP 604 (X | Y unions)
- PEP 634 (structural pattern matching)
- PEP 612 (ParamSpec) / PEP 646 (TypeVarTuple) — only if it clearly helps, don’t overcomplicate

Prefer these rules:

- **Domain / contracts / enums** live near the domain owner (baseline statuses in baseline domain).
- If a module becomes an “overloaded module”, split by:
    - model (types)
    - io/serialization
    - rules/validation
    - ui rendering

Avoid deep package hierarchies unless they clearly reduce coupling.

---

## 20) Agent safety rules

These rules exist because of real incidents in this repo. They are non-negotiable.

### Scope discipline

- Touch only files directly related to your current task.
- Do not "clean up", reformat, or refactor code in files outside your task scope.
- Do not delete functions, classes, blocks, or whole files written by other contributors unless
  deletion is the explicit goal of your task.
- If you discover unrelated issues, report them in your final message — do not fix them silently.
- Before starting work, run `git status` and review uncommitted/untracked changes. They may belong
  to a parallel agent or to the maintainer; do not delete or overwrite them without explicit approval.

### Documentation hygiene

- Every doc claim about code (schema version, module path, function name, MCP tool count, exit code,
  CLI flag) must be verified against the **current** code before writing or editing.
- Always read version constants from `codeclone/contracts/__init__.py` (see Section 4 table), never from
  another doc.
- When updating a file that mentions schema versions, verify **every** version reference in that
  file — not only the one you came to change.
- Do not remove narrative content from docs you did not author. Add or correct only.
- Do not replace a multi-section doc with a "pointer" stub unless the maintainer explicitly asks for it.
- Do not create new `*.md` design specs ("PROPOSED", "FUTURE", "RFC") inside `docs/`. Use the
  maintainer's planning channel instead — orphaned specs become stale and misleading.

### Audit completeness

- When the maintainer asks to audit "all" of something, list every file you actually opened in your
  final report. Selective audits silently skip the most error-prone files.
- Prefer parallel `Explore` agents partitioned by file group over a single sequential pass —
  coverage is the contract, not effort.

### Shared helpers

- HTML/UI helpers (`codeclone/report/html/widgets/*`, `codeclone/report/html/primitives/*`,
  `codeclone/report/html/assets/*`) are imported, not duplicated locally inside
  `codeclone/report/html/sections/*`.
  If you need a helper that doesn't exist, add it to the shared module.
- Glossary terms used in stat-card labels live in `codeclone/report/html/widgets/glossary.py`. Adding a
  new label without a glossary entry is a contract gap.

### Conflict avoidance

- Do not force-push, `git reset --hard`, or `git checkout --` over uncommitted work without
  explicit maintainer approval.
- If your changes conflict with recent commits or other agents' work, rebase or merge cleanly —
  never silently drop the other side.
- Never use `--no-verify` to bypass pre-commit hooks; fix the underlying issue.

### Verification before "done"

- A task that touches HTML rendering is not complete until
  `pytest tests/test_html_report.py -x -q` is green.
- A task that touches MCP is not complete until
  `pytest tests/test_mcp_service.py tests/test_mcp_server.py -x -q` is green.
- A task that touches docs schema/version claims is not complete until you have grep'd the whole
  file for *all* version-shaped strings and verified each against `codeclone/contracts/__init__.py`.

---

## 21) Minimal checklist for PRs (agents)

- [ ] Change is deterministic.
- [ ] Contracts preserved or versioned.
- [ ] Tests added for new behavior.
- [ ] `ruff`, `mypy`, `pytest` green.
- [ ] CLI messages remain helpful and stable (don’t break scripts).
- [ ] Reports contain provenance fields and reflect trust model correctly.
- [ ] Golden snapshots were **not** updated just to satisfy failing tests.
- [ ] If any golden snapshot changed, the corresponding contract change is intentional, documented, and approved.

---

If you are an AI agent and something here conflicts with an instruction from a maintainer in the PR/issue thread, **ask
for clarification in the thread** and default to this document until resolved.
