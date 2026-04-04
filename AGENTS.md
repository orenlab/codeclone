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

---

## 4) Baseline contract (v2, stable)

### Baseline file structure (canonical)

```json
{
  "meta": {
    "generator": {
      "name": "codeclone",
      "version": "X.Y.Z"
    },
    "schema_version": "2.0",
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
- Runtime writes baseline schema `2.0`.
- Runtime accepts baseline schema `1.x` and `2.x` for compatibility checks.
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
    - `pip install dist/*.whl`
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

- **CLI / orchestration surface** (`codeclone/cli.py`, `codeclone/_cli_*.py`) parses args, resolves runtime mode,
  coordinates pipeline calls, and prints UX.
- **Pipeline orchestrator** (`codeclone/pipeline.py`) owns end-to-end flow: bootstrap → discovery → processing →
  analysis → report artifacts → gating.
- **Core analysis** (`codeclone/extractor.py`, `codeclone/cfg.py`, `codeclone/normalize.py`, `codeclone/blocks.py`,
  `codeclone/grouping.py`, `codeclone/scanner.py`) produces normalized structural facts and clone candidates.
- **Domain/contracts layer** (`codeclone/models.py`, `codeclone/contracts.py`, `codeclone/errors.py`,
  `codeclone/domain/*.py`) defines typed entities and stable enums/constants used across layers.
- **Persistence contracts** (`codeclone/baseline.py`, `codeclone/cache.py`, `codeclone/metrics_baseline.py`) store
  trusted comparison state and optimization state.
- **Canonical report + projections** (`codeclone/report/json_contract.py`, `codeclone/report/*.py`) converts analysis
  facts to deterministic, contract-shaped outputs.
- **HTML/UI rendering** (`codeclone/html_report.py`, `codeclone/_html_report/*`, `codeclone/_html_*.py`,
  `codeclone/templates.py`) renders views from report/meta facts.
- **Documentation/publishing surface** (`docs/`, `mkdocs.yml`, `.github/workflows/docs.yml`,
  `scripts/build_docs_example_report.py`) publishes contract docs and the live sample report.
- **MCP agent interface** (`codeclone/mcp_service.py`, `codeclone/mcp_server.py`) exposes the current pipeline as a
  deterministic, read-only MCP server for AI agents and MCP-capable clients.
- **VS Code extension surface** (`extensions/vscode-codeclone/*`) is a native, workspace-only IDE client over
  `codeclone-mcp`, with baseline-aware, triage-first, source-first review UX.
- **Claude Desktop bundle surface** (`extensions/claude-desktop-codeclone/*`) is a native `.mcpb` install wrapper for
  Claude Desktop that launches the same local `codeclone-mcp` server via local `stdio`.
- **Tests-as-spec** (`tests/`) lock behavior, contracts, determinism, and architecture boundaries.

Non-negotiable interpretation:

- Core produces facts; renderers present facts.
- Baseline/cache are persistence contracts, not analysis truth.
- UI/report must not invent gating semantics.
- MCP reuses pipeline/report contracts and must not create a second analysis truth path.
- The VS Code extension is a guided IDE view over MCP and must not introduce a second analysis or truth path.
- The Claude Desktop bundle is a local setup surface over `codeclone-mcp` and must not introduce a second server or
  truth path.

## 13) Module map

Use this map to route changes to the right owner module.

- `codeclone/cli.py` — public CLI entry and control-flow coordinator; add orchestration and top-level UX here; do not
  move core analysis logic here.
- `codeclone/_cli_*.py` — CLI support slices (args, config, runtime, summary, reports, baselines, gating); keep them
  thin and reusable; do not encode domain semantics that belong to pipeline/core/contracts.
- `codeclone/pipeline.py` — canonical orchestration and data plumbing between scanner/extractor/metrics/report/gating;
  change integration flow here; do not move HTML-only presentation logic here.
- `codeclone/extractor.py` — AST extraction, CFG fingerprint input preparation, symbol/declaration collection, and
  per-file metrics inputs; change parsing/extraction semantics here; do not couple this module to CLI/report
  rendering/baseline logic.
- `codeclone/grouping.py` / `codeclone/blocks.py` — clone grouping and block/segment mechanics; normalization-adjacent
  statement hashing lives with `codeclone/normalize.py`; do not mix grouping behavior with CLI/report UX concerns.
- `codeclone/metrics/` — metric computations and dead-code/dependency/health logic; change metric math and thresholds
  here; do not make metrics depend on renderer/UI concerns.
- `codeclone/structural_findings.py` — structural finding extraction/normalization policy; keep it report-layer factual
  and deterministic.
- `codeclone/suppressions.py` — inline `# codeclone: ignore[...]` parse/bind/index logic; keep it declaration-scoped and
  deterministic.
- `codeclone/baseline.py` — baseline schema/trust/integrity/compatibility contract; all baseline format changes go here
  with explicit contract process.
- `codeclone/cache.py` — cache schema/integrity/profile compatibility and serialization; cache remains
  optimization-only.
- `codeclone/report/json_contract.py` — canonical report schema builder/integrity payload; any JSON contract shape
  change belongs here.
- `codeclone/report/*.py` (other modules) — deterministic projections/format transforms (
  text/markdown/sarif/derived/findings/suggestions); avoid injecting new analysis heuristics here.
- `codeclone/mcp_service.py` — typed, in-process MCP service adapter over the current pipeline/report contracts; keep
  it deterministic; allow only session-local in-memory state such as reviewed markers, and never move shell UX or
  `sys.exit` behavior here.
- `codeclone/mcp_server.py` — optional MCP launcher/server wiring, transport config, and MCP tool/resource
  registration; keep dependency loading lazy so base installs/CI do not require MCP runtime packages.
- `tests/test_mcp_service.py`, `tests/test_mcp_server.py` — MCP contract and integration tests; run these when
  touching any MCP surface.
- `codeclone/html_report.py` — public HTML facade/re-export surface; preserve backward-compatible imports here; do not
  grow section/layout logic in this module.
- `codeclone/_html_report/*` — actual HTML assembly, context shaping, tabs, sections, and overview/navigation behavior;
  change report layout and interactive HTML UX here, not in the facade.
- `codeclone/_html_*.py` — shared HTML badges, CSS, JS, escaping, snippets, and data-attrs; keep these as render-only
  helpers.
- `codeclone/models.py` — shared typed models crossing modules; keep model changes contract-aware.
- `codeclone/domain/*.py` — centralized domain taxonomies/IDs (families, categories, source scopes, risk/severity
  levels); use these constants in pipeline/report/UI instead of scattering raw literals.
- `docs/`, `mkdocs.yml`, `.github/workflows/docs.yml`, `scripts/build_docs_example_report.py` — docs-site source,
  publication workflow, and live sample-report generation; keep published docs aligned with code contracts.
- `extensions/vscode-codeclone/*` — preview VS Code extension surface; keep it baseline-aware, triage-first,
  source-first, and faithful to MCP/canonical report semantics rather than building a second analyzer or report model.
- `extensions/claude-desktop-codeclone/*` — preview Claude Desktop bundle surface; keep it local-stdio-only,
  launcher-focused, and faithful to `codeclone-mcp` rather than re-implementing MCP semantics in the bundle layer.
- `tests/` — executable specification: architecture rules, contracts, goldens, invariants, regressions.

## 14) Dependency direction

Dependency direction is enforceable and partially test-guarded (`tests/test_architecture.py`):

- `codeclone.report.*` must not import `codeclone.cli`, `codeclone.html_report`, or `codeclone.ui_messages`.
- `codeclone.extractor` must not import `codeclone.report`, `codeclone.cli`, or `codeclone.baseline`.
- `codeclone.grouping` must not import `codeclone.cli`, `codeclone.baseline`, or `codeclone.html_report`.
- `codeclone.baseline` and `codeclone.cache` must not import `codeclone.cli`, `codeclone.ui_messages`, or
  `codeclone.html_report`.
- `codeclone.models` may import only `codeclone.contracts` and `codeclone.errors` from local modules.

Operational rules:

- Core/domain code must not depend on HTML/UI.
- Renderers depend on canonical report payload/model; canonical report code must not depend on renderer/UI.
- Metrics/report layers must not recompute or invent core facts in UI.
- CLI helper modules (`_cli_*`) must orchestrate/format, not own domain semantics.
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

| Change zone                                                                                                                         | Must update docs                                                                                                                                                    | Must update tests                                                                                                                                                   | Explicit approval required when                                                              | Contract-change trigger                                                                       |
|-------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------|
| Baseline schema/trust/integrity (`codeclone/baseline.py`)                                                                           | `docs/book/06-baseline.md`, `docs/book/14-compatibility-and-versioning.md`, `docs/book/appendix/b-schema-layouts.md`, `CHANGELOG.md`                                | `tests/test_baseline.py`, CI/CLI behavior tests (`tests/test_cli_inprocess.py`, `tests/test_cli_unit.py`)                                                           | schema/trust semantics, compatibility windows, payload integrity logic change                | baseline key layout/status semantics/compat rules change                                      |
| Cache schema/profile/integrity (`codeclone/cache.py`)                                                                               | `docs/book/07-cache.md`, `docs/book/appendix/b-schema-layouts.md`, `CHANGELOG.md`                                                                                   | `tests/test_cache.py`, pipeline/CLI cache integration tests                                                                                                         | cache schema/status/profile compatibility semantics change                                   | cache payload/version/status semantics change                                                 |
| Canonical report JSON shape (`codeclone/report/json_contract.py`, report projections)                                               | `docs/book/08-report.md` (+ `docs/book/10-html-render.md` if rendering contract impacted), `docs/sarif.md` when SARIF changes, `CHANGELOG.md`                       | `tests/test_report.py`, `tests/test_report_contract_coverage.py`, `tests/test_report_branch_invariants.py`, relevant report-format tests                            | finding/meta/summary schema changes                                                          | stable JSON fields/meaning/order guarantees change                                            |
| CLI flags/help/exit behavior (`codeclone/cli.py`, `_cli_*`, `contracts.py`)                                                         | `docs/book/09-cli.md`, `docs/book/03-contracts-exit-codes.md`, `README.md`, `CHANGELOG.md`                                                                          | `tests/test_cli_unit.py`, `tests/test_cli_inprocess.py`, `tests/test_cli_smoke.py`                                                                                  | exit-code semantics, script-facing behavior, flag contracts change                           | user-visible CLI contract changes                                                             |
| Fingerprint-adjacent analysis (`extractor/cfg/normalize/grouping`)                                                                  | `docs/book/05-core-pipeline.md`, `docs/cfg.md`, `docs/book/14-compatibility-and-versioning.md`, `CHANGELOG.md`                                                      | `tests/test_fingerprint.py`, `tests/test_extractor.py`, `tests/test_cfg.py`, golden tests (`tests/test_detector_golden.py`, `tests/test_golden_v2.py`)              | always (see Section 1.6)                                                                     | clone identity / NEW-vs-KNOWN / fingerprint inputs change                                     |
| Suppression semantics/reporting (`suppressions`, extractor dead-code wiring, report/UI counters)                                    | `docs/book/19-inline-suppressions.md`, `docs/book/16-dead-code-contract.md`, `docs/book/08-report.md`, and interface docs if surfaced (`09-cli`, `10-html-render`)  | `tests/test_suppressions.py`, `tests/test_extractor.py`, `tests/test_metrics_modules.py`, `tests/test_pipeline_metrics.py`, report/html/cli tests                   | declaration scope semantics, rule effect, or contract-visible counters/fields change         | suppression changes alter active finding output or contract-visible report payload            |
| MCP interface (`codeclone/mcp_service.py`, `codeclone/mcp_server.py`, packaging extra/launcher)                                     | `README.md`, `docs/book/20-mcp-interface.md`, `docs/mcp.md`, `docs/book/01-architecture-map.md`, `docs/book/14-compatibility-and-versioning.md`, `CHANGELOG.md`     | `tests/test_mcp_service.py`, `tests/test_mcp_server.py`, plus CLI/package tests if launcher/install semantics change                                                | tool/resource shapes, read-only semantics, optional-dependency packaging behavior change     | public MCP tool names, resource URIs, launcher/install behavior, or response semantics change |
| VS Code extension surface (`extensions/vscode-codeclone/*`)                                                                         | `README.md`, `docs/book/21-vscode-extension.md`, `docs/vscode-extension.md`, `docs/book/01-architecture-map.md`, `docs/README.md`, `CHANGELOG.md`                   | `node --check extensions/vscode-codeclone/src/support.js`, `node --check extensions/vscode-codeclone/src/mcpClient.js`, `node --check extensions/vscode-codeclone/src/extension.js`, `node --test extensions/vscode-codeclone/test/*.test.js`, plus local extension-host smoke and package smoke when surface/manifest/assets change | command/view UX, trust/runtime model, source-first review flow, or packaging metadata change | documented commands/views/setup/trust behavior, packaged assets, or publish metadata change   |
| Claude Desktop bundle surface (`extensions/claude-desktop-codeclone/*`)                                                             | `docs/book/22-claude-desktop-bundle.md`, `docs/claude-desktop-bundle.md`, `docs/mcp.md`, `docs/book/01-architecture-map.md`, `docs/README.md`, `CHANGELOG.md`      | `node --check extensions/claude-desktop-codeclone/server/index.js`, `node --check extensions/claude-desktop-codeclone/src/launcher.js`, `node --check extensions/claude-desktop-codeclone/scripts/build-mcpb.mjs`, `node --test extensions/claude-desktop-codeclone/test/*.test.js`, plus `.mcpb` build smoke | bundle install/runtime model, launcher UX, local-stdio constraints, or bundle metadata change | documented Claude Desktop install/setup/runtime behavior or packaged bundle semantics change   |
| Docs site / sample report publication (`docs/`, `mkdocs.yml`, `.github/workflows/docs.yml`, `scripts/build_docs_example_report.py`) | `docs/README.md`, `docs/publishing.md`, `docs/examples/report.md`, and any contract pages surfaced by the change, `CHANGELOG.md` when user-visible behavior changes | `mkdocs build --strict`, sample-report generation smoke path, and relevant report/html tests if generated examples or embeds change                                 | published docs navigation, sample-report generation, or Pages workflow semantics change      | published documentation behavior or sample-report generation contract changes                 |

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
- Baseline schema/trust semantics/integrity compatibility (`2.0` baseline contract family).
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

- Local helpers and formatting utilities (`_html_*`, many private `_as_*` normalizers, local transformers).
- Internal orchestration decomposition inside `_cli_*` modules.
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

## 20) Minimal checklist for PRs (agents)

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
