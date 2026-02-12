# 10. HTML Render

## Purpose
Document HTML rendering as a pure view layer over report data/facts.

## Public surface
- Main renderer: `codeclone/html_report.py:build_html_report`
- Escaping helpers: `codeclone/_html_escape.py`
- Snippet/highlight helpers: `codeclone/_html_snippets.py`
- Static template: `codeclone/templates.py:REPORT_TEMPLATE`

## Data model
Inputs to renderer:
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

Refs:
- `codeclone/_report_explain.py:build_block_group_facts`
- `codeclone/html_report.py:_render_group_explanation`
- `codeclone/html_report.py:report_meta_html`

## Invariants (MUST)
- All user/content fields are escaped for text/attributes before insertion.
- Missing file snippets render explicit fallback blocks.
- Novelty controls reflect baseline trust split note and per-group novelty flags.

Refs:
- `codeclone/_html_escape.py:_escape_attr`
- `codeclone/_html_snippets.py:_render_code_block`
- `codeclone/html_report.py:global_novelty_html`

## Failure modes
| Condition | Behavior |
| --- | --- |
| Source file unreadable for snippet | Render fallback snippet with message |
| Missing/invalid optional meta field | Render empty or `(none)`-equivalent display |
| Pygments unavailable | Escape-only fallback code rendering |

Refs:
- `codeclone/_html_snippets.py:_FileCache.get_lines_range`
- `codeclone/_html_snippets.py:_try_pygments`

## Determinism / canonicalization
- Section/group ordering follows sorted report inputs.
- Metadata rows are built in fixed order.

Refs:
- `codeclone/html_report.py:build_html_report`
- `codeclone/html_report.py:meta_rows`

## Locked by tests
- `tests/test_html_report.py::test_html_report_uses_core_block_group_facts`
- `tests/test_html_report.py::test_html_report_escapes_meta_and_title`
- `tests/test_html_report.py::test_html_report_escapes_script_breakout_payload`
- `tests/test_html_report.py::test_html_report_missing_source_snippet_fallback`
- `tests/test_html_report.py::test_html_and_json_group_order_consistent`

## Non-guarantees
- CSS/visual system and interaction details may evolve without schema bump.
- HTML command palette action set is not a baseline/cache/report contract.
