# Changelog

## [1.4.0] - 2026-02-08

### Overview

This release stabilizes the baseline contract for long-term CI use without changing
clone-detection algorithms.

### Baseline Contract Stabilization

- Baseline schema moved to a stable v1 contract with strict top-level
  `meta` + `clones` objects.
- `meta` fields are now explicit and versioned:
  `generator`, `schema_version`, `fingerprint_version`,
  `python_tag`, `created_at`, `payload_sha256` (`generator.name` / `generator.version`).
- `clones` currently stores only deterministic baseline keys:
  `functions`, `blocks`.
- Compatibility no longer depends on CodeClone patch/minor version.
  Baseline regeneration is required when `fingerprint_version` changes.
- Added deterministic compatibility checks and statuses:
  `mismatch_schema_version`, `mismatch_fingerprint_version`,
  `mismatch_python_version`, `missing_fields`, `invalid_json`, `invalid_type`.
- Legacy 1.3 baseline files are treated as untrusted (`missing_fields`) with explicit
  regeneration guidance.

### Integrity & IO Hardening

- Baseline integrity hash now uses canonical payload:
  `functions`, `blocks`, `python_tag`,
  `fingerprint_version`, `schema_version`.
- Baseline writes are now atomic (`*.tmp` + `os.replace`) for CI/interruption safety.
- Baseline and cache size guards remain configurable:
  `--max-baseline-size-mb`, `--max-cache-size-mb`.

### CLI & Reporting Behavior

- Trusted/untrusted baseline behavior is deterministic:
  normal mode ignores untrusted baseline with warning and compares against empty baseline;
  gating mode (`--fail-on-new`/`--ci`) fails fast with exit code `2`.
- Report metadata (HTML/TXT/JSON) now exposes baseline audit fields:
  `baseline_fingerprint_version`,
  `baseline_schema_version`, `baseline_python_tag`,
  `baseline_generator_version`, `baseline_loaded`, `baseline_status`.
- Block-clone explainability is now core-owned:
  Python report layer generates facts/hints (`match_rule`, `signature_kind`,
  `assert_ratio`, `consecutive_asserts`), HTML only renders them.
- HTML report API now expects precomputed `block_group_facts` from core (no UI-side semantics).

### Testing

- Expanded baseline validation matrix tests (types, missing fields, legacy, size limits,
  compatibility mismatches, integrity mismatch, canonical hash determinism).
- Full quality gates pass with `ruff`, `mypy`, and `pytest` at 100% coverage.

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
- Cache schema was extended to include segment data (`CACHE_VERSION=1.1`).
- Cache integrity uses constant-time signature checks and deep schema validation.
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
