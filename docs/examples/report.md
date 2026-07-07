---
title: "Example report"
audience: public
doc_type: example
status: draft
source_commit: "5d76c10fa9538052e2a4dc130e5dce254063c21e"
---

# Example report

## What this is

Every time this documentation site is published, CI runs CodeClone against
this repository's own source and stages the result here. It is a real report,
not a mockup: the same HTML, JSON, and SARIF output you get from running
CodeClone on your own project.

## View the live report

- <a href="https://orenlab.github.io/codeclone/examples/report/live/index.html">Interactive HTML report</a> —
  the same report a local `codeclone .` run produces, including the Module Map,
  Findings, and Health Score panels.
- <a href="https://orenlab.github.io/codeclone/examples/report/live/report.json">Raw JSON report</a> —
  the canonical machine-readable payload consumed by the MCP server and other tooling.
- <a href="https://orenlab.github.io/codeclone/examples/report/live/report.sarif">SARIF findings</a> —
  the same findings rendered as SARIF for Code Scanning / editor integrations.
- <a href="https://orenlab.github.io/codeclone/examples/report/live/manifest.json">Build manifest</a> —
  the CodeClone version and commit this specific report was generated from.

## What's inside

The report is generated on every docs build with:

```bash
uv run python scripts/build_docs_example_report.py --output-dir site/examples/report/live
```

This runs `codeclone . --html --json --sarif` against the repository, with
`--no-fail-on-new` and `--no-fail-on-new-metrics` set — the example is a
preview of report output, not a CI gate. It does not reflect this repository's
actual pre-commit/CI policy, which is stricter.

| File            | Contents                                                    |
|------------------|--------------------------------------------------------------|
| `index.html`     | Full interactive HTML report (Module Map, Findings, Metrics) |
| `report.json`    | Canonical JSON report                                        |
| `report.sarif`   | SARIF-formatted findings                                     |
| `manifest.json`  | CodeClone version, commit SHA, and generation timestamp      |

Use this page to see what a real report looks like before installing
CodeClone on your own repository.
