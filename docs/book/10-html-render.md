# 10. HTML Render

## Purpose

Document HTML rendering as a pure view layer over report data/facts.

## Public surface

- Main renderer: `codeclone/html_report.py:build_html_report`
- HTML assembly package: `codeclone/_html_report/*`
- Overview materialization bridge: `codeclone/report/overview.py:materialize_report_overview`
- Escaping helpers: `codeclone/_html_escape.py`
- Snippet/highlight helpers: `codeclone/_html_snippets.py`
- Static template: `codeclone/templates.py:REPORT_TEMPLATE`

## Data model

Inputs to renderer:

- canonical report document (`report_document`) when available (preferred path)
- compatibility inputs for direct rendering path:
    - grouped clone data (`func_groups`, `block_groups`, `segment_groups`)
    - block explainability facts (`block_group_facts`)
    - novelty key sets (`new_function_group_keys`, `new_block_group_keys`)
    - shared report metadata (`report_meta`)

Output:

- single self-contained HTML string

Refs:

- `codeclone/html_report.py:build_html_report`

## Contracts

- HTML must not recompute detection semantics; it renders facts from core/report layers.
- Explainability hints shown in UI are sourced from `build_block_group_facts` data.
- Provenance panel mirrors report metadata contract.
- HTML may expose local UX affordances such as the health-grade badge dialog
  or provenance modal, but those actions are projections over already computed
  report/meta facts.
- Overview UI is a report projection:
    - KPI cards with baseline-aware tone (`✓ baselined` / `+N` regression)
    - Health gauge with baseline delta arc (improvement/degradation)
    - Executive Summary: issue breakdown (sorted bars) + source breakdown
    - Health Profile: full-width radar chart of dimension scores
    - Get Badge modal: grade-only / score+grade variants with shields.io embed
- Dead-code UI is a single top-level `Dead Code` tab with deterministic split
  sub-tabs: `Active` and `Suppressed`.
- IDE deep links:
    - An IDE picker in the topbar lets users choose their IDE. The selection is
      persisted in `localStorage` (key `codeclone-ide`).
    - Supported IDEs: PyCharm, IntelliJ IDEA, VS Code, Cursor, Fleet, Zed.
    - File paths across Clones, Quality, Suggestions, Dead Code, and Findings
      tabs are rendered as `<a class="ide-link">` elements with `data-file`
      (absolute path) and `data-line` attributes.
    - JetBrains IDEs use `jetbrains://` protocol (requires Toolbox); others use
      native URL schemes (`vscode://`, `cursor://`, `fleet://`, `zed://`).
    - The scan root is embedded as `data-scan-root` on `<html>` so that
      JetBrains links can derive the project name and relative path.
    - When no IDE is selected, links are inert (no `href`, default cursor).

Refs:

- `codeclone/report/explain.py:build_block_group_facts`
- `codeclone/report/overview.py:materialize_report_overview`
- `codeclone/_html_report/_sections/_clones.py:_render_group_explanation`
- `codeclone/_html_report/_sections/_meta.py:render_meta_panel`
- `codeclone/_html_js.py:_IDE_LINKS`
- `codeclone/_html_report/_assemble.py` (IDE picker topbar widget)

## Invariants (MUST)

- All user/content fields are escaped for text/attributes before insertion.
- Missing file snippets render explicit fallback blocks.
- Novelty controls reflect baseline trust split note and per-group novelty flags.
- Suppressed dead-code rows are rendered only from report dead-code suppression
  payloads and do not become active dead-code findings in UI tables.
- IDE link `data-file` and `data-line` attributes are escaped via
  `_escape_attr` before insertion into HTML.

Refs:

- `codeclone/_html_escape.py:_escape_attr`
- `codeclone/_html_snippets.py:_render_code_block`
- `codeclone/_html_report/_sections/_clones.py:render_clones_panel`
- `codeclone/_html_report/_tables.py` (path cell IDE links)
- `codeclone/report/findings.py` (structural findings IDE links)

## Failure modes

| Condition                           | Behavior                                    |
|-------------------------------------|---------------------------------------------|
| Source file unreadable for snippet  | Render fallback snippet with message        |
| Missing/invalid optional meta field | Render empty or `(none)`-equivalent display |
| Pygments unavailable                | Escape-only fallback code rendering         |

Refs:

- `codeclone/_html_snippets.py:_FileCache.get_lines_range`
- `codeclone/_html_snippets.py:_try_pygments`

## Determinism / canonicalization

- Section/group ordering follows sorted report inputs.
- Metadata rows are built in fixed order.

Refs:

- `codeclone/_html_report/_assemble.py:build_html_report`
- `codeclone/_html_report/_sections/_meta.py:render_meta_panel`

## Locked by tests

- `tests/test_html_report.py::test_html_report_uses_core_block_group_facts`
- `tests/test_html_report.py::test_html_report_escapes_meta_and_title`
- `tests/test_html_report.py::test_html_report_escapes_script_breakout_payload`
- `tests/test_html_report.py::test_html_report_missing_source_snippet_fallback`
- `tests/test_html_report.py::test_html_and_json_group_order_consistent`

## Non-guarantees

- CSS/visual system and interaction details may evolve without schema bump.
- HTML-only interaction affordances (theme toggle, IDE picker, provenance modal,
  badge modal, radar chart) are not baseline/cache/report contracts.
- IDE deep link behavior depends on the user's local IDE installation and
  protocol handler registration (e.g. JetBrains Toolbox for `jetbrains://`).
- Overview layout (KPI grid, executive summary, analytics) is a pure view
  concern; only the underlying data identity and ordering are contract-sensitive.
