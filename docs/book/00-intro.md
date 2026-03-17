# 00. Intro

## Purpose

This book is the executable contract for CodeClone behavior in v2.x. It
describes only behavior that is present in code and/or locked by tests.

## Public surface

- CLI entrypoint: `codeclone/cli.py:main`
- Package version: `codeclone/__init__.py:__version__`
- Global contract constants: `codeclone/contracts.py`

## Contracts

CodeClone provides these guarantees when inputs are identical (same repository content, same Python tag, same tool
version, same baseline/cache/report schemas):

- Deterministic clone grouping and report serialization.
- Explicit trust model for baseline/cache.
- Stable exit-code categories for contract vs gating vs internal failures.

Refs:

- `codeclone/report/json_contract.py:build_report_document`
- `codeclone/baseline.py:Baseline.verify_compatibility`
- `codeclone/cache.py:Cache.load`
- `codeclone/contracts.py:ExitCode`

## Invariants (MUST)

- Contract errors and gating failures are separate categories.
- Baseline trust is explicit (`baseline_loaded`, `baseline_status`).
- Cache is optimization-only; invalid cache never becomes source of truth.

Refs:

- `codeclone/cli.py:_main_impl`
- `codeclone/baseline.py:BASELINE_UNTRUSTED_STATUSES`
- `codeclone/cache.py:Cache._ignore_cache`

## Failure modes

| Condition                                    | Behavior                                 |
|----------------------------------------------|------------------------------------------|
| Invalid/untrusted baseline in normal mode    | Warning + compare against empty baseline |
| Invalid/untrusted baseline in CI/gating mode | Contract error (exit 2)                  |
| New clones in gating mode                    | Gating failure (exit 3)                  |
| Unexpected runtime exception                 | Internal error (exit 5)                  |

Refs:

- `codeclone/cli.py:_main_impl`
- `codeclone/cli.py:main`

## Determinism / canonicalization

- Filesystem traversal is sorted before processing.
- Group keys and serialized arrays are sorted in report JSON/TXT.
- Baseline and cache payload hashing uses canonical JSON serialization.

Refs:

- `codeclone/scanner.py:iter_py_files`
- `codeclone/report/json_contract.py:build_report_document`
- `codeclone/baseline.py:_compute_payload_sha256`
- `codeclone/cache.py:_canonical_json`

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
  [03-contracts-exit-codes.md](03-contracts-exit-codes.md) ->
  [06-baseline.md](06-baseline.md) ->
  [07-cache.md](07-cache.md) ->
  [08-report.md](08-report.md) ->
  [09-cli.md](09-cli.md)
- Metrics governance path:
  [04-config-and-defaults.md](04-config-and-defaults.md) ->
  [15-metrics-and-quality-gates.md](15-metrics-and-quality-gates.md) ->
  [16-dead-code-contract.md](16-dead-code-contract.md) ->
  [19-inline-suppressions.md](19-inline-suppressions.md) ->
  [17-suggestions-and-clone-typing.md](17-suggestions-and-clone-typing.md)
- Determinism and compatibility path:
  [12-determinism.md](12-determinism.md) ->
  [14-compatibility-and-versioning.md](14-compatibility-and-versioning.md)
- Benchmarking path:
  [12-determinism.md](12-determinism.md) ->
  [18-benchmarking.md](18-benchmarking.md)
