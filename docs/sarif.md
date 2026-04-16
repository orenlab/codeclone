# SARIF for IDEs and Code Scanning

## Purpose

Explain how CodeClone projects canonical findings into SARIF and what IDEs or
code-scanning tools can rely on.

SARIF is a machine-readable projection layer. The canonical source of report
truth remains the JSON report document.

## Source files

- `codeclone/report/sarif.py`
- `codeclone/report/json_contract.py`
- `codeclone/report/findings.py`

## Design model

CodeClone builds SARIF from the already materialized canonical report document.
It does not recompute analysis in the SARIF layer.

That means:

- finding identities come from canonical finding IDs
- severity/confidence/category data comes from canonical report payloads
- SARIF ordering remains deterministic

## Path model

To improve IDE and code-scanning integration, SARIF uses repo-relative paths
anchored through `%SRCROOT%`.

Current behavior:

- `run.originalUriBaseIds["%SRCROOT%"]` points at the scan root when an
  absolute scan root is known
- `run.artifacts[*]` enumerates referenced files
- `artifactLocation.uri` uses repository-relative paths
- `artifactLocation.index` aligns locations with artifacts for stable linking
- `run.invocations[*].workingDirectory` mirrors the scan root URI when available
- `run.invocations[*].startTimeUtc` is emitted when analysis start time is
  available in canonical runtime meta
- `run.automationDetails.id` is unique per run so code-scanning systems can
  correlate uploads reliably

This helps consumers resolve results back to workspace files consistently.

## Result model

Current SARIF output includes:

- `tool.driver.rules[*]` with stable rule IDs and help links
- `results[*]` for clone groups, dead code, design findings, and structural findings
- `locations[*]` with primary file/line mapping
- `locations[*].message` and `relatedLocations[*].message` with
  human-readable role labels such as `Representative occurrence`
- `relatedLocations[*]` when the result has multiple relevant locations
- `partialFingerprints.primaryLocationLineHash` for stable per-location identity
  without encoding line numbers into the hash digest
- result `properties` with stable identity/context fields such as primary path,
  qualname, and region
- explicit `kind: "fail"` on results

For clone results, CodeClone also carries novelty-aware metadata when known:

- `baselineState`

This improves usefulness in IDE/code-scanning flows that distinguish new vs
known findings.

Coverage join can materialize `coverage` / `coverage_hotspot` and
`coverage_scope_gap` design findings when the canonical report already
contains valid `metrics.families.coverage_join` facts. SARIF projects those
findings like other design findings; it does not parse Cobertura XML or create
coverage-specific analysis truth.

## Rule metadata

Rule records are intentionally richer than a minimal SARIF export.

They include:

- stable rule IDs
- stable rule names derived from `ruleId`
- display name
- help text / markdown
- tags
- docs-facing help URI

The goal is not only schema compliance, but a better consumer experience in IDEs
and code-scanning platforms.

## What SARIF is good for here

SARIF is useful as:

- an IDE-facing findings stream
- a code-scanning upload format
- another deterministic machine-readable projection over canonical report data

It is not the source of truth for:

- report integrity digest
- gating semantics
- baseline compatibility

Those remain owned by the canonical report and baseline contracts.

## Limitations

- Consumer UX depends on the IDE/platform; not every SARIF field is shown by
  every tool.
- HTML-only presentation details are not carried into SARIF.
- SARIF wording may evolve as long as IDs, semantics, and deterministic
  structure remain stable.

## Validation and tests

Relevant tests:

- `tests/test_report.py`
- `tests/test_report_contract_coverage.py`
- `tests/test_report_branch_invariants.py`

Contract-adjacent coverage includes:

- reuse of canonical report document
- stable SARIF branch invariants
- deterministic artifacts/rules/results ordering

## See also

- [08. Report](book/08-report.md)
- [10. HTML Render](book/10-html-render.md)
- [Examples / Sample Report](examples/report.md)
