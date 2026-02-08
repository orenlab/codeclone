# Changelog

## [1.3.0] - 2026-02-08

### Overview

This release improves clone-detection precision and explainability with deterministic
normalization and CFG upgrades, adds segment-level internal clone reporting, refreshes
the HTML report UI, and introduces baseline versioning.

**Breaking change:** CI workflows that reuse old baselines must regenerate them.

### Clone Detection Accuracy

- **Commutative normalization**  
  Canonicalized operand order for `+`, `*`, `|`, `&`, `^` only for provably safe constant
  domains. Symbolic operands are no longer reordered.

- **Local logical equivalence**  
  Normalized `not (x in y)` to `x not in y` and `not (x is y)` to `x is not y` without
  De Morgan transformations or broader boolean rewrites.

- **Call-target preservation**  
  Kept symbolic call targets during normalization to avoid conflating different APIs
  (for example, `load_user(...)` vs `delete_user(...)`).

### CFG Precision

- **Short‑circuit modeling**  
  Represented `and`/`or` as micro‑CFGs with explicit branch splits after each operand.

- **Exception linking**  
  Linked `try/except` only to statements that may raise (calls, attribute access, indexing,
  `await`, `yield from`, `raise`) instead of blanket links.

### Detection Integrity

- **Internal CFG marker hardening**  
  Switched CFG metadata markers to an internal namespace (`__CC_META__::...`) emitted as
  synthetic AST names, preventing collisions with user string literals.

- **Ordered control-flow semantics**  
  Modeled `break`/`continue` as terminating loop transitions, added correct `for/while ... else`
  semantics, preserved `match case` evaluation order, and preserved `except` handler order.

- **Deterministic traversal order**  
  Sorted Python file discovery to stabilize processing and report ordering across runs/platforms.

### Segment‑Level Detection

- **Window fingerprints**  
  Added deterministic segment windows inside functions for internal clone discovery.

- **Candidate generation**  
  Used an order‑insensitive signature for candidate grouping and a strict segment hash for
  final confirmation. Segment matches do not affect baseline or CI failure logic.

- **Noise reduction (report‑only)**  
  Merged overlapping segment windows into a single span per function and suppressed
  boilerplate-only groups (attribute assignment wiring) with deterministic AST criteria.

### Baseline & CI

- Baselines are now **versioned** and include a schema version.
- Mismatched baseline versions **fail fast** and require regeneration.
- Baseline loading is now strict: invalid schema/types or oversized baseline files
  fail fast to preserve CI integrity.
- Added baseline tamper-evident integrity for v1.3+ files (`generator`, `payload_sha256`)
  while keeping legacy baseline behavior as explicit regeneration-required fail-fast.
- Added configurable size guards (`--max-baseline-size-mb`, `--max-cache-size-mb`):
  oversized baseline fails fast, oversized cache is ignored with warning.
- Behavioral hardening (CLI): baseline validation is now an explicit contract
  (legacy/version/schema/python/integrity/size states) with deterministic fail-fast behavior.

**Breaking (CI):** baseline version mismatch now fails hard; CI requires baseline regeneration on upgrade.

Update the baseline:

```bash
codeclone . --update-baseline
```

### CLI UX (CI)

- Added `--version` for standard version output.
- Added `--cache-path` (legacy alias: `--cache-dir`) and clarified cache help text.
- Added `--ci` preset (`--fail-on-new --no-color --quiet`).
- Improved `--fail-on-new` output with aggregated counts and clear next steps.
- Added strict report output extension validation (`.html`, `.json`, `.txt`).
- Centralized user-facing CLI strings in `codeclone/ui_messages.py` to keep text contracts
  consistent and maintainable.
- Refined Summary output: a single compact table with deterministic metric order and
  explicit `Files analyzed` semantics (cache-aware), plus stable compact output for
  `--quiet/--ci`.

### HTML Report UI

- **Visual refresh**  
  Introduced a modernized HTML report layout with a sticky top bar and improved spacing.

- **Interactive tooling**  
  Added a command palette, keyboard shortcuts, toast notifications, and quick actions
  (export, stats, charts, navigation).

- **Reporting widgets**  
  Added a stats dashboard and chart container for high-level clone metrics.

- **Icon system**  
  Replaced emoji glyphs with inline SVG icons for consistent rendering and a fully
  self-contained UI.

- **Segment reporting**  
  Added a dedicated “Segment clones” section and summary metric in HTML/TXT/JSON outputs.

- **Escaping and snippet resilience**  
  Hardened HTML escaping for text and attribute contexts, and added a safe fallback when
  source snippets are unavailable during report rendering.

### Cache & Internals

- Extended cache schema to store segment fingerprints (cache version bump).
- Default cache location moved to `<root>/.cache/codeclone/cache.json` (project‑local).
- Added a legacy cache warning for `~/.cache/codeclone/cache.json` with guidance to
  delete it and add `.cache/` to `.gitignore`.
- Strengthened cache integrity handling with constant-time signature checks and explicit
  warnings for oversized cache files.
- Added deterministic deep-schema cache entry validation (`stat/units/blocks/segments`);
  invalid cache entries are ignored instead of affecting analysis results.

### Packaging

- Removed an invalid PyPI classifier from the package metadata.

### Documentation

- Updated architecture and CFG documentation to reflect new normalization, CFG, and
  segment‑level detection behavior.
- Updated README, SECURITY, and CONTRIBUTING guidance for 1.3.0.

### Testing & Security

- Expanded security tests (HTML escaping and safety checks).
- Added regression tests for deterministic report ordering across HTML/TXT/JSON,
  baseline/cache integrity edge cases, and symlink traversal/loop safety.

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
