# 06. Baseline

## Purpose

Specify baseline schema v2.1, trust/compatibility checks, integrity hashing, and
runtime behavior.

## Public surface

- Baseline object lifecycle: `codeclone/baseline.py:Baseline`
- Baseline statuses: `codeclone/baseline.py:BaselineStatus`
- Baseline status coercion: `codeclone/baseline.py:coerce_baseline_status`
- CLI integration: `codeclone/cli.py:_main_impl`

## Data model

Canonical baseline shape:

- Required top-level keys: `meta`, `clones`
- Optional top-level keys: `metrics`, `api_surface` (unified baseline flow)
- `meta` required keys:
  `generator`, `schema_version`, `fingerprint_version`, `python_tag`,
  `created_at`, `payload_sha256`
- `clones` required keys: `functions`, `blocks`
- `functions` and `blocks` are sorted/unique `list[str]`

Refs:

- `codeclone/baseline.py:_TOP_LEVEL_REQUIRED_KEYS`
- `codeclone/baseline.py:_TOP_LEVEL_OPTIONAL_KEYS`
- `codeclone/baseline.py:_META_REQUIRED_KEYS`
- `codeclone/baseline.py:_CLONES_REQUIRED_KEYS`
- `codeclone/baseline.py:_require_sorted_unique_ids`

## Contracts

Compatibility gates (`verify_compatibility`):

- `generator == "codeclone"`
- `schema_version` major/minor must be supported by runtime
- `fingerprint_version == BASELINE_FINGERPRINT_VERSION`
- `python_tag == current_python_tag()`
- integrity verified via `payload_sha256`

Current runtime policy:

- New clone baseline saves write schema `2.1`.
- Runtime still accepts `2.0` and `2.1` within baseline major `2`.

Embedded metrics contract:

- Top-level `metrics` is allowed only for baseline schema `>= 2.0`.
- Clone baseline save preserves existing embedded `metrics` payload,
  optional `api_surface` payload, and the corresponding
  `meta.metrics_payload_sha256` / `meta.api_surface_payload_sha256` values.
- Embedded `api_surface` snapshots use a compact wire format: each symbol stores
  `local_name` relative to its containing `module`, and each module row stores
  `filepath` relative to the baseline directory when possible. Runtime
  reconstructs canonical full qualnames and runtime filepaths in memory before
  diffing.
- The default runtime flow is unified: clone baseline and metrics baseline
  usually share the same `codeclone.baseline.json` file unless the metrics path
  is explicitly overridden.
- In unified rewrite mode, disabled optional metric surfaces are omitted from
  the rewritten embedded payload instead of being preserved as stale baggage.

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
- `codeclone/baseline.py:_preserve_embedded_metrics`

## Invariants (MUST)

- Legacy top-level baselines (`functions`/`blocks` at root) are untrusted and
  require regeneration.
- Baseline writes are atomic (`*.tmp` + `os.replace`, same filesystem).
- Baseline diff is set-based and deterministic.

Refs:

- `codeclone/baseline.py:_is_legacy_baseline_payload`
- `codeclone/baseline.py:_atomic_write_json`
- `codeclone/baseline.py:Baseline.diff`

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

- Normal mode: untrusted baseline is ignored, diff runs against empty baseline.
- Gating mode (`--ci` / `--fail-on-new`): untrusted baseline is contract error
  (exit 2).

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
- `tests/test_cli_inprocess.py::test_cli_reports_include_audit_metadata_schema_mismatch`

## Non-guarantees

- Baseline generator version (`meta.generator.version`) is informational and not
  a compatibility gate.
- Baseline file indentation/style is not part of compatibility contract.
