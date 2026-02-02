# Changelog

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
