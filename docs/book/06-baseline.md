# 06. Baseline

## Purpose
Specify baseline schema v1, trust/compatibility checks, integrity hashing, and runtime behavior.

## Public surface
- Baseline object lifecycle: `codeclone/baseline.py:Baseline`
- Baseline statuses: `codeclone/baseline.py:BaselineStatus`
- Baseline status coercion: `codeclone/baseline.py:coerce_baseline_status`
- CLI integration: `codeclone/cli.py:_main_impl`

## Data model
Canonical baseline shape:
- Top-level keys: `meta`, `clones`
- `meta` required keys: `generator`, `schema_version`, `fingerprint_version`, `python_tag`, `created_at`, `payload_sha256`
- `clones` required keys: `functions`, `blocks`
- `functions` and `blocks` are sorted/unique `list[str]`

Refs:
- `codeclone/baseline.py:_TOP_LEVEL_KEYS`
- `codeclone/baseline.py:_META_REQUIRED_KEYS`
- `codeclone/baseline.py:_CLONES_REQUIRED_KEYS`
- `codeclone/baseline.py:_require_sorted_unique_ids`

## Contracts
Compatibility gates (`verify_compatibility`):
- `generator == "codeclone"`
- `schema_version` major/minor compatible with supported schema
- `fingerprint_version == BASELINE_FINGERPRINT_VERSION`
- `python_tag == current_python_tag()`
- integrity verified via `payload_sha256`

Integrity payload includes only:
- `clones.functions`
- `clones.blocks`
- `meta.fingerprint_version`
- `meta.python_tag`

Integrity payload excludes:
- `meta.schema_version`
- `meta.generator.*`
- `meta.created_at`

Refs:
- `codeclone/baseline.py:Baseline.verify_compatibility`
- `codeclone/baseline.py:_compute_payload_sha256`

## Invariants (MUST)
- Legacy top-level baselines (`functions`/`blocks` at root) are untrusted and require regeneration.
- Baseline writes are atomic (`*.tmp` + `os.replace`, same filesystem).
- Baseline diff is set-based and ignores deleted baseline keys.

Refs:
- `codeclone/baseline.py:_is_legacy_baseline_payload`
- `codeclone/baseline.py:_atomic_write_json`
- `codeclone/baseline.py:Baseline.diff`

## Failure modes
| Condition | Status |
| --- | --- |
| File missing | `missing` |
| Too large | `too_large` |
| JSON decode failure | `invalid_json` |
| Top-level shape/type mismatch | `invalid_type` / `missing_fields` |
| Schema mismatch | `mismatch_schema_version` |
| Fingerprint mismatch | `mismatch_fingerprint_version` |
| Python tag mismatch | `mismatch_python_version` |
| Generator mismatch | `generator_mismatch` |
| Hash missing/invalid | `integrity_missing` |
| Hash mismatch | `integrity_failed` |

CLI behavior:
- Normal mode: untrusted baseline is ignored, diff runs against empty baseline.
- Gating mode (`--ci` / `--fail-on-new`): untrusted baseline is contract error (exit 2).

Refs:
- `codeclone/baseline.py:BaselineStatus`
- `codeclone/cli.py:_main_impl`

## Determinism / canonicalization
- Clone IDs are serialized sorted.
- Hash serialization uses canonical JSON (`sort_keys=True`, compact separators).
- `payload_sha256` uses `hmac.compare_digest` during verification.

Refs:
- `codeclone/baseline.py:_baseline_payload`
- `codeclone/baseline.py:_compute_payload_sha256`
- `codeclone/baseline.py:Baseline.verify_integrity`

## Locked by tests
- `tests/test_baseline.py::test_baseline_roundtrip_v1`
- `tests/test_baseline.py::test_baseline_payload_fields_contract_invariant`
- `tests/test_baseline.py::test_baseline_payload_sha256_independent_of_schema_version`
- `tests/test_baseline.py::test_baseline_verify_python_tag_mismatch`
- `tests/test_cli_inprocess.py::test_cli_untrusted_baseline_fails_in_ci`

## Non-guarantees
- Baseline generator version (`meta.generator.version`) is informational and not a compatibility gate.
- Baseline file ordering/indentation style is not part of compatibility contract.
