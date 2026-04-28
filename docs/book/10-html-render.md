# 10. HTML Render

## Purpose

Document HTML rendering as a pure view layer over canonical report data.

## Public surface

- Main renderer: `codeclone/report/html/assemble.py:build_html_report`
- Package entrypoint: `codeclone/report/html/__init__.py:build_html_report`
- Context shaping: `codeclone/report/html/_context.py`
- Escaping helpers: `codeclone/report/html/primitives/escape.py`
- Snippet/highlight helpers: `codeclone/report/html/widgets/snippets.py`
- Sections/widgets/assets: `codeclone/report/html/sections/*`,
  `codeclone/report/html/widgets/*`, `codeclone/report/html/assets/*`

## Data model

Inputs to the renderer:

- canonical `report_document` (preferred path)
- shared `report_meta`
- optional runtime snippet sources for code excerpts

Output:

- one self-contained HTML string

## Contracts

- HTML must not recompute detection semantics; it renders facts from report/core layers.
- Provenance panels mirror canonical report/meta facts.
- Overview, Quality, Suggestions, Dead Code, and Clones tabs are projections over canonical report sections.
- Quality may include report-only subtabs such as `Coverage Join` and
  `Security Surfaces`; these remain factual projections over canonical metrics
  families rather than HTML-only analysis.
- IDE deep links are HTML-only UX over canonical path/line facts.
- Missing snippets or optional meta fields render safe factual fallbacks rather than invented data.

Refs:

- `codeclone/report/html/assemble.py:build_html_report`
- `codeclone/report/html/sections/_clones.py:_render_group_explanation`
- `codeclone/report/html/sections/_meta.py:render_meta_panel`
- `codeclone/report/html/assets/js.py:_IDE_LINKS`
- `codeclone/report/overview.py:materialize_report_overview`

## Invariants (MUST)

- User/content fields are escaped before insertion into HTML.
- Missing file snippets render explicit fallback blocks.
- Novelty badges reflect baseline trust and per-group novelty flags.
- Suppressed dead-code rows render only from report suppression payloads.
- Path-link `data-file` and `data-line` attributes are escaped before insertion.

Refs:

- `codeclone/report/html/primitives/escape.py:_escape_html`
- `codeclone/report/html/widgets/snippets.py:_render_code_block`
- `codeclone/report/html/widgets/tables.py`

## Failure modes

| Condition                           | Behavior                               |
|-------------------------------------|----------------------------------------|
| Source file unreadable for snippet  | Render fallback snippet with message   |
| Missing/invalid optional meta field | Render empty or `(none)`-style display |
| Pygments unavailable                | Escape-only fallback code rendering    |

Refs:

- `codeclone/report/html/widgets/snippets.py:_FileCache`
- `codeclone/report/html/widgets/snippets.py:_try_pygments`

## Determinism / canonicalization

- Section and group ordering follow sorted canonical report inputs.
- Metadata rows are built in fixed order.

Refs:

- `codeclone/report/html/assemble.py:build_html_report`
- `codeclone/report/html/sections/_meta.py:render_meta_panel`

## Locked by tests

- `tests/test_html_report.py::test_html_report_uses_core_block_group_facts`
- `tests/test_html_report.py::test_html_report_escapes_meta_and_title`
- `tests/test_html_report.py::test_html_report_escapes_script_breakout_payload`
- `tests/test_html_report.py::test_html_report_missing_source_snippet_fallback`
- `tests/test_html_report.py::test_html_and_json_group_order_consistent`
- `tests/test_html_report.py::test_html_report_quality_includes_security_surfaces_subtab`

## Non-guarantees

- CSS, layout, and interaction details may evolve without a schema bump.
- IDE deep link behavior depends on local IDE installation and protocol handlers.
