<!-- doc-scope: DOCS-SITE BUILD AND PUBLISHING only.
     owns: Zensical build flow, docs.yml workflow, sample report generation,
       local preview commands, maintenance rules.
     does-not-own: storefront sync (→ releasing.md), contract content (→ book/).
     rule: split from the former combined publishing page. Do not re-merge. -->

# Publishing the Docs Site

## Purpose

Document how the documentation site is built, validated, and published.

This page is operational, not contractual. The source of truth for behavior
remains the current repository code and CI workflow.

!!! note "Scope"
    This page covers docs-site build and publishing mechanics. Public behavior
    contracts still live in the book chapters and in the repository code.
    For integration distribution (storefront sync), see
    [Releasing & storefront sync](releasing.md).

## Current stack

- Site generator: `Zensical`
- Theme: Zensical built-in theme (Material-derived)
- Docs root: `docs/`
- Site config: `zensical.toml`
- Publish workflow: `.github/workflows/docs.yml`

## What gets published

The published site contains:

- the documentation tree under `docs/`
- the contract book under `docs/book/`
- guide pages such as architecture narrative and integration pages
- a live sample report for the current repository build under
  `Examples / Sample Report`

## Build flow

The docs workflow (`.github/workflows/docs.yml`) follows this order:

1. install project dependencies
2. build the site with `zensical build --clean --strict`
3. generate a live sample report into `site/examples/report/live`
4. upload the built site as a GitHub Pages artifact
5. deploy on pushes to `main`

Admonition indentation (`!!!` / `???` body must be indented 4 spaces) is enforced
in the main test workflow via `tests/test_docs_build_contract.py`, not in
`docs.yml`. Repair locally with
`python3 scripts/lint_admonitions.py docs/ --fix`.

Relevant files:

- `zensical.toml`
- `.github/workflows/docs.yml`
- `scripts/build_docs_example_report.py`

!!! warning "Generated output only"
    `site/` is a generated artifact. It is used for local preview and GitHub
    Pages deployment, but it should not be committed.

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

=== "Build the site"

    ```bash title="Validate the Zensical site"
    uv run --with zensical==0.0.46 zensical build --clean --strict
    ```

=== "Build the site and sample report"

    ```bash title="Generate the live sample report into site/"
    uv run --with zensical==0.0.46 zensical build --clean --strict
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
- Prefer documenting docs-site mechanics here, not inside contract chapters
  unless a public contract is affected.

## When to update this page

Update this page when you change:

- `zensical.toml`
- `.github/workflows/docs.yml`
- `scripts/build_docs_example_report.py`
- the site navigation model
- the sample report publishing path/layout
