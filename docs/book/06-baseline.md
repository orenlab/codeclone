# 06. Baseline

## Purpose

Specify clone-baseline schema `2.1`, trust/compatibility checks, integrity
hashing, and runtime behavior.

## Public surface

- Baseline object lifecycle: `codeclone/baseline/clone_baseline.py:Baseline`
- Baseline statuses: `codeclone/baseline/trust.py:BaselineStatus`
- Baseline status coercion: `codeclone/baseline/trust.py:coerce_baseline_status`
- CLI integration: `codeclone/surfaces/cli/baseline_state.py`

## Data model

Canonical baseline shape:

- required top-level keys: `meta`, `clones`
- optional top-level keys: `metrics`, `api_surface` (unified baseline flow)
- `meta` required keys:
  `generator`, `schema_version`, `fingerprint_version`, `python_tag`,
  `created_at`, `payload_sha256`
- `clones` required keys: `functions`, `blocks`
- `functions` and `blocks` are sorted, unique `list[str]`

Refs:

- `codeclone/baseline/clone_baseline.py:_TOP_LEVEL_REQUIRED_KEYS`
- `codeclone/baseline/clone_baseline.py:_TOP_LEVEL_OPTIONAL_KEYS`
- `codeclone/baseline/clone_baseline.py:_META_REQUIRED_KEYS`
- `codeclone/baseline/clone_baseline.py:_CLONES_REQUIRED_KEYS`
- `codeclone/baseline/trust.py:_require_sorted_unique_ids`

## Contracts

Compatibility gates:

- `generator.name == "codeclone"`
- supported `schema_version`
- `fingerprint_version == BASELINE_FINGERPRINT_VERSION`
- `python_tag == current_python_tag()`
- integrity verified via `payload_sha256`

Current runtime policy:

- new clone baseline saves write schema `2.1`
- runtime accepts `1.0`, `2.0`, and `2.1`

Unified-baseline contract:

- top-level `metrics` is allowed only for baseline schema `>= 2.0`
- the default runtime flow is unified: clone and metrics comparison state both
  live in `codeclone.baseline.json` unless `--metrics-baseline` is redirected
- unified rewrites preserve current embedded metric sections that remain enabled
  and drop disabled optional sections instead of keeping stale baggage

Integrity payload includes only:

- `clones.functions`
- `clones.blocks`
- `meta.fingerprint_version`
- `meta.python_tag`

Refs:

- `codeclone/baseline/clone_baseline.py:Baseline.verify_compatibility`
- `codeclone/baseline/trust.py:_compute_payload_sha256`
- `codeclone/baseline/metrics_baseline.py:MetricsBaseline.save`

## Invariants (MUST)

- Legacy top-level baselines (`functions`/`blocks` at root) are untrusted and require regeneration.
- Baseline writes are atomic (`*.tmp` + `os.replace`).
- Baseline diff is set-based and deterministic.

Refs:

- `codeclone/baseline/clone_baseline.py:_is_legacy_baseline_payload`
- `codeclone/baseline/clone_baseline.py:_atomic_write_json`
- `codeclone/baseline/clone_baseline.py:Baseline.diff`

## Failure modes

| Condition                     | Status                            |
|-------------------------------|-----------------------------------|
| File missing                  | `missing`                         |
| Too large                     | `too_large`                       |
| JSON decode failure           | `invalid_json`                    |
| Top-level shape/type mismatch | `invalid_type` / `missing_fields` |
| Schema mismatch               | `mismatch_schema_version`         |
| Fingerprint mismatch          | `mismatch_fingerprint_version`    |
| Python tag mismatch           | `mismatch_python_version`         |
| Generator mismatch            | `generator_mismatch`              |
| Hash missing/invalid          | `integrity_missing`               |
| Hash mismatch                 | `integrity_failed`                |

CLI behavior:

- normal mode: untrusted baseline is ignored and diff runs against empty baseline
- gating mode (`--ci` / `--fail-on-new`): untrusted baseline is a contract error

Refs:

- `codeclone/baseline/trust.py:BaselineStatus`
- `codeclone/surfaces/cli/baseline_state.py:resolve_clone_baseline_state`

## Determinism / canonicalization

- Clone IDs are serialized sorted.
- Hash serialization uses canonical JSON.
- Integrity verification uses constant-time comparison.

Refs:

- `codeclone/baseline/clone_baseline.py:_baseline_payload`
- `codeclone/baseline/trust.py:_compute_payload_sha256`
- `codeclone/baseline/clone_baseline.py:Baseline.verify_integrity`

## Locked by tests

- `tests/test_baseline.py::test_baseline_roundtrip_v1`
- `tests/test_baseline.py::test_baseline_payload_fields_contract_invariant`
- `tests/test_baseline.py::test_baseline_payload_sha256_independent_of_schema_version`
- `tests/test_baseline.py::test_baseline_verify_python_tag_mismatch`
- `tests/test_cli_inprocess.py::test_cli_reports_include_audit_metadata_schema_mismatch`

## Non-guarantees

- `meta.generator.version` is informational and not a compatibility gate.
- Baseline file indentation/style is not part of compatibility contract.
