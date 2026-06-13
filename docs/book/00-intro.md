<!-- doc-scope: BOOK CHARTER — goals, contract rule, reading paths.
     owns: what the book is, "code wins" rule, reading-path suggestions.
     does-not-own: the TOC (→ README.md), terminology (→ 01), architecture map (→ 02). -->

# 00. Intro

## Purpose

This book is the executable contract for CodeClone behavior in v2.x. It
describes only behavior that is present in code and/or locked by tests.

## Public surface

- CLI entrypoint: `codeclone/main.py:main`
- Package version: `codeclone/__init__.py:__version__`
- Global contract constants: `codeclone/contracts/__init__.py`

## Contracts

CodeClone provides these guarantees when inputs are identical (same repository content, same Python tag, same tool
version, same baseline/cache/report schemas):

- Deterministic clone grouping and report serialization.
- Explicit trust model for baseline/cache.
- Stable exit-code categories for contract vs gating vs internal failures.

Refs:

- `codeclone/report/document/builder.py:build_report_document`
- `codeclone/baseline/clone_baseline.py:Baseline.verify_compatibility`
- `codeclone/cache/store.py:Cache.load`
- `codeclone/contracts/__init__.py:ExitCode`

## Invariants (MUST)

- Contract errors and gating failures are separate categories.
- Baseline trust is explicit (`baseline_loaded`, `baseline_status`).
- Cache is optimization-only; invalid cache never becomes source of truth.

Refs:

- `codeclone/surfaces/cli/workflow.py:_main_impl`
- `codeclone/baseline/trust.py:BASELINE_UNTRUSTED_STATUSES`
- `codeclone/cache/store.py:Cache._ignore_cache`

## Failure modes

| Condition                                    | Behavior                                 |
|----------------------------------------------|------------------------------------------|
| Invalid/untrusted baseline in normal mode    | Warning + compare against empty baseline |
| Invalid/untrusted baseline in CI/gating mode | Contract error (exit 2)                  |
| New clones in gating mode                    | Gating failure (exit 3)                  |
| Unexpected runtime exception                 | Internal error (exit 5)                  |

Refs:

- `codeclone/surfaces/cli/workflow.py:_main_impl`
- `codeclone/main.py:main`

## Determinism / canonicalization

- Filesystem traversal is sorted before processing.
- Group keys and serialized arrays are sorted in report JSON/TXT.
- Baseline and cache payload hashing uses canonical JSON serialization.

Refs:

- `codeclone/scanner/__init__.py:iter_py_files`
- `codeclone/report/document/builder.py:build_report_document`
- `codeclone/baseline/trust.py:_compute_payload_sha256`
- `codeclone/cache/integrity.py:canonical_json`

## Locked by tests

- `tests/test_detector_golden.py::test_detector_output_matches_golden_fixture`
- `tests/test_report.py::test_report_json_deterministic_group_order`
- `tests/test_baseline.py::test_baseline_hash_canonical_determinism`
- `tests/test_cache.py::test_cache_signature_validation_ignores_json_whitespace`
- `tests/test_cli_unit.py::test_cli_help_text_consistency`

## Non-guarantees

- Cross-Python-tag clone IDs are not guaranteed identical.
- UI wording and visual layout may evolve without schema bumps.
- Performance characteristics are best-effort, not strict SLA.

## Recommended reading paths

- CI contract path:
  [09-exit-codes.md](09-exit-codes.md) →
  [07-baseline.md](07-baseline.md) →
  [08-cache.md](08-cache.md) →
  [05-report.md](05-report.md) →
  [11-cli.md](11-cli.md)
- Metrics governance path:
  [10-config-and-defaults.md](10-config-and-defaults.md) →
  [15-health-score.md](15-health-score.md) →
  [16-metrics-and-quality-gates.md](16-metrics-and-quality-gates.md) →
  [17-dead-code-contract.md](17-dead-code-contract.md) →
  [19-inline-suppressions.md](19-inline-suppressions.md) →
  [18-suggestions-and-clone-typing.md](18-suggestions-and-clone-typing.md)
- Determinism and compatibility path:
  [22-determinism.md](22-determinism.md) →
  [24-compatibility-and-versioning.md](24-compatibility-and-versioning.md)
- Benchmarking path:
  [22-determinism.md](22-determinism.md) →
  [20-benchmarking.md](20-benchmarking.md)
