# Changelog

## [1.2.1] - 2026-02-XX

## Overview

This release focuses on security hardening, robustness, and long-term maintainability.
No breaking API changes were introduced.

The goal of this release is to provide users with a safe, deterministic, and CI-friendly
tool suitable for security-sensitive and large-scale environments.

---

## Security & Robustness

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

---

## Performance Improvements

- **Optimized AST Normalization**  
  Replaced expensive `deepcopy` operations with in-place AST normalization, significantly
  reducing CPU and memory overhead.

- **Improved Memory Efficiency**  
  Added an LRU cache for file reading and optimized string concatenation during fingerprint
  generation.

- **HTML Report Memory Bounds**  
  HTML reports now read only the required line ranges instead of entire files, reducing peak
  memory usage on large codebases.

---

## Architecture & Maintainability

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

---

## CLI & User Experience

- Added a sequential execution fallback when process pools are unavailable (for example, in
  restricted or sandboxed environments).
- Emit clear, user-visible warnings when cache validation fails instead of silently ignoring
  corrupted state.
- HTML report template hardened to safely embed JS template literals and cleaned up to meet
  lint requirements.

---

## Testing & Quality

- Expanded unit and integration test coverage across the CLI, CFG construction, cache
  handling, scanner, and HTML reporting paths.
- Added security regression tests for dot-dot traversal and symlinked sensitive directories,
  and tightened cache mismatch assertions to verify state reset.
- Achieved and enforced 98%+ line coverage, with coverage configuration added to
  `pyproject.toml`.
- Added GitHub Actions workflow with Python 3.10–3.14 test matrix plus ruff and mypy checks.

---

## Fixed

- **CFG Exception Handling**  
  Fixed incorrect control-flow linking for `try`/`except` blocks.

- **Pattern Matching Support**  
  Added missing structural handling for `match`/`case` statements in the CFG.

- **Block Detection Scaling**  
  Made `MIN_LINE_DISTANCE` dynamic based on block size to improve clone detection accuracy
  across differently sized functions.

## [1.2.0] - 2026-02-02

### BREAKING CHANGES

- **CLI Arguments**: Renamed output flags for brevity and consistency:
    - `--json-out` → `--json`
    - `--text-out` → `--text`
    - `--html-out` → `--html`
    - `--cache` → `--cache-dir`
- **Baseline Behavior**:
    - The default baseline file location has changed from `~/.config/codeclone/baseline.json` to
      `./codeclone.baseline.json`. This encourages committing the baseline file to the repository, simplifying CI/CD
      integration.
    - The CLI now warns if a baseline file is expected but missing (unless `--update-baseline` is used).

### Added

- **Detection Engine**:
    - **Deep CFG Analysis**: Added support for constructing control flow graphs for `try`/`except`/`finally`, `with`/
      `async with`, and `match`/`case` (Python 3.10+) statements. The tool now analyzes the internal structure of these
      blocks instead of treating them as opaque statements.
    - **Normalization**: Implemented normalization for Augmented Assignments. Code using `x += 1` is now detected as a
      clone of `x = x + 1`.
- **Rich Output**: Integrated `rich` library for professional CLI output, including:
    - Color-coded status messages (Success/Warning/Error).
    - Progress bars and spinners for long-running tasks.
    - Formatted summary tables.
- **CI/CD Improvements**: Clearer separation of arguments in `--help` output (Target, Tuning, Baseline, Reporting).

### Improved

- **Baseline**: Enhanced `Baseline` class with safer JSON loading (error handling for corrupted files), better typing (
  using `set` instead of `Set`), and cleaner API for creating instances (`from_groups` accepts path).
- **Cache**: Refactored `Cache` to handle corrupted cache files gracefully by starting fresh instead of crashing.
  Updated typing to modern standards.
- **Normalization**: Added `copy.deepcopy` to AST normalization to prevent side effects on the original AST nodes during
  fingerprinting. This ensures the AST remains intact for any subsequent operations.
- **Typing**: General typing improvements across `report.py` and other modules to align with Python 3.10+ practices.

## [1.1.0] — 2026-01-19

### Added

- Control Flow Graph (CFG v1) for structural clone detection
- Deterministic CFG-based function fingerprints
- Interactive HTML report with syntax highlighting
- Dark/light theme toggle in HTML report
- Block-level clone visualization

### Changed

- Function clone detection now based on CFG instead of pure AST
- Improved robustness against refactoring and control-flow changes

### Documentation

- Added `docs/cfg.md` with CFG semantics and limitations
- Added `docs/architecture.md` describing system design

---

## [1.0.0] — 2026-01-17

### Initial release

- AST-based function clone detection
- Block-level clone detection (Type-3-lite)
- Baseline workflow for CI
- JSON and text reports
