<!-- doc-scope: SARIF contract. class: contract max-lines: 150 -->

# SARIF

Guide: [SARIF export](../../guide/integrations/sarif/export.md).

## Source files

- `codeclone/report/renderers/sarif.py`
- `codeclone/report/document/builder.py`
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

- `run.originalUriBaseIds["%SRCROOT%"]` points at the scan root when known
- `run.artifacts[*]` enumerates referenced files
- `artifactLocation.uri` uses repository-relative paths
- `artifactLocation.index` aligns locations with artifacts for stable linking
- `run.invocations[*].workingDirectory` mirrors the scan root URI when available
- `run.automationDetails.id` is unique per run

## Result model

Current SARIF output includes:

- `tool.driver.rules[*]` with stable rule IDs and help links
- `results[*]` for clone groups, dead code, design findings, and structural findings
- `locations[*]` with primary file/line mapping
- `relatedLocations[*]` for multi-location findings
- `partialFingerprints.primaryLocationLineHash` for stable per-location identity
- explicit `kind: "fail"` on results

Coverage Join may materialize coverage design findings only when the canonical
report already contains valid `metrics.families.coverage_join` facts.

## Validation and tests

Relevant tests:

- `tests/test_report.py`
- `tests/test_report_contract_coverage.py`
- `tests/test_report_branch_invariants.py`

Contract-adjacent coverage includes:

- reuse of the canonical report document
- stable SARIF branch invariants
- deterministic artifacts/rules/results ordering
