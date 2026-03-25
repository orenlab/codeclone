# Publishing and Docs Site

## Purpose

Document how the documentation site is built, validated, and published.

This page is operational, not contractual. The source of truth for behavior
remains the current repository code and CI workflow.

## Current stack

- Site generator: `MkDocs`
- Theme: `Material for MkDocs`
- Docs root: `docs/`
- Site config: `mkdocs.yml`
- Publish workflow: `.github/workflows/docs.yml`

## What gets published

The published site contains:

- the documentation tree under `docs/`
- the contract book under `docs/book/`
- deep-dive pages such as architecture and CFG notes
- a live sample report for the current repository build under
  `Examples / Sample Report`

## Build flow

The docs workflow follows this order:

1. install project dependencies
2. build the MkDocs site with `mkdocs build --strict`
3. generate a live sample report into `site/examples/report/live`
4. upload the built site as a GitHub Pages artifact
5. deploy on pushes to `main`

Relevant files:

- `mkdocs.yml`
- `.github/workflows/docs.yml`
- `scripts/build_docs_example_report.py`

## Sample report generation

The sample report is generated from the current `codeclone` repository tree.

Generated artifacts:

- `site/examples/report/live/index.html`
- `site/examples/report/live/report.json`
- `site/examples/report/live/report.sarif`
- `site/examples/report/live/manifest.json`

The sample report is generated during docs publishing and is not committed to
git. `site/` remains ignored.

## Local preview

Build the site:

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict
```

Generate the sample report into the built site:

```bash
uv run python scripts/build_docs_example_report.py --output-dir site/examples/report/live
```

Then open:

- `site/index.html`
- `site/examples/report/live/index.html`

## Maintenance rules

- Keep `docs/` as the single source tree for site content.
- Do not commit generated `site/` artifacts.
- Keep docs publishing deterministic: no timestamps in published docs paths.
- Keep the sample report generated from the same commit as the site itself.
- Prefer documenting docs-site mechanics here or in adjacent deep-dive pages,
  not inside contract chapters unless a public contract is affected.

## When to update this page

Update this page when you change:

- `mkdocs.yml`
- `.github/workflows/docs.yml`
- `scripts/build_docs_example_report.py`
- the site navigation model
- the sample report publishing path/layout
