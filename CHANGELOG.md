# Changelog

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
