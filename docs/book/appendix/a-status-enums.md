<!-- doc-scope: APPENDIX — status enums and typed contracts.
     owns: enum value tables for intent, registry, verify, and profile statuses.
     does-not-own: main chapter content — reference back-links only. -->

# Appendix A. Status Enums

## Purpose

Centralize machine-readable status sets used across baseline/cache/report/CLI contracts.

## Public surface

- Baseline statuses: `codeclone/baseline/trust.py:BaselineStatus`
- Cache statuses: `codeclone/cache/versioning.py:CacheStatus`
- Exit categories: `codeclone/contracts/__init__.py:ExitCode`
- Intent status: `codeclone/surfaces/mcp/_intent.py:IntentStatus`
- Intent ownership: `codeclone/surfaces/mcp/_workspace_intents.py:IntentOwnership`
- Workspace intent status and PID liveness:
  `codeclone/surfaces/mcp/_workspace_intent_lifecycle.py`
- Patch contract: `codeclone/surfaces/mcp/_patch_contract.py:PatchContractStatus`
- Review receipt:
  `codeclone/surfaces/mcp/_review_receipt.py:ReceiptVerdict` /
  `ReceiptPatchStatus`
- Verification profile: `codeclone/surfaces/mcp/_verification_profile.py:VerificationProfile`
- Engineering Memory status and ingestion:
  `codeclone/memory/enums.py:MemoryStatus` / `IngestionRunStatus`
- Metrics baseline status:
  `codeclone/baseline/_metrics_baseline_contract.py:MetricsBaselineStatus`

## Data model

### BaselineStatus

- `ok`
- `missing`
- `too_large`
- `invalid_json`
- `invalid_type`
- `missing_fields`
- `mismatch_schema_version`
- `mismatch_fingerprint_version`
- `mismatch_python_version`
- `generator_mismatch`
- `integrity_missing`
- `integrity_failed`

### Baseline untrusted set

Defined by `BASELINE_UNTRUSTED_STATUSES`.

### CacheStatus

- `ok`
- `missing`
- `too_large`
- `unreadable`
- `invalid_json`
- `invalid_type`
- `version_mismatch`
- `python_tag_mismatch`
- `mismatch_fingerprint_version`
- `analysis_profile_mismatch`
- `integrity_failed`

### ExitCode

- `0` success
- `2` contract error
- `3` gating failure
- `5` internal error

### WorkspaceIntentStatus

- `active`
- `queued`
- `clean`
- `expanded`
- `violated`
- `expired`
- `orphaned`

Persisted workspace registry records use these lifecycle values. Terminal GC
statuses are `clean`, `expired`, and `orphaned`. Semantics:
[Intent registry & queue](../12-structural-change-controller/intent-registry-and-queue.md).

### IntentStatus (scope check / session lifecycle)

- `active`
- `queued`
- `clean`
- `expanded`
- `violated`
- `unverified`
- `expired`

Used by `manage_change_intent(check)` and session intent records. Finish
top-level `status: "unverified"` is a **response string**, not this enum value.

### IntentOwnership

- `own_active`
- `own_stale`
- `foreign_active`
- `foreign_stale`
- `recoverable`
- `expired`

Semantics:
[Intent registry & queue](../12-structural-change-controller/intent-registry-and-queue.md).

### PidLiveness

- `alive`
- `dead`
- `unknown`

Used by workspace-intent ownership classification. Dead owners make records
recoverable; unknown PID state is conservative and does not grant ownership.

### PatchContractStatus

- `accepted`
- `accepted_with_external_changes`
- `violated`
- `unverified`
- `expired`

Semantics:
[Patch contract verification](../12-structural-change-controller/patch-contract-verify.md).

### Workflow response strings

`start_controlled_change`:

- `active`
- `queued`
- `blocked`
- `needs_analysis`

`finish_controlled_change`:

- `accepted`
- `accepted_with_external_changes`
- `unverified`
- `violated`
- `expired`

These are response statuses, not necessarily persisted workspace registry
states. See
[payload semantics](../12-structural-change-controller/payload-semantics.md).

### Implementation-context freshness

- `fresh`
- `drifted`
- `unknown`

`freshness.status="drifted"` means the stored MCP run no longer matches live
workspace evidence closely enough for safe edit planning; re-analyze before
relying on that projection.

### ReceiptVerdict

- `clean`
- `incomplete`
- `needs_attention`

Receipt verdicts summarize receipt completeness and review attention, not CI
gates.

### ReceiptPatchStatus

- `accepted`
- `violated`
- `not_checked`

### VerificationProfile

- `state_artifact_change`
- `python_structural`
- `governance_config`
- `documentation_only`
- `non_python_patch`

Priority-ordered. A single file from a higher-priority category overrides
the entire patch. Semantics are defined in
[Structural Change Controller § Verification Profiles](../12-structural-change-controller/verification-profiles.md).

### MemoryStatus

Defined by `codeclone/memory/enums.py:MemoryStatus`. Semantics are defined in
[Engineering Memory § Staleness and anchor durability](../13-engineering-memory/staleness-and-anchors.md).

- `draft` — unapproved agent candidate
- `active` — trusted or system fact; default retrieval includes
- `historical` — anchor subject absent at `HEAD`; preserved, default retrieval includes
- `stale` — drift or ingest contradiction; excluded from default retrieval
- `superseded` — replaced by a newer record
- `rejected` — human rejected draft
- `archived` — explicitly archived

### IngestionRunStatus

- `running`
- `completed`
- `failed`
- `partial`

### MetricsBaselineStatus

- `ok`
- `missing`
- `too_large`
- `invalid_json`
- `invalid_type`
- `missing_fields`
- `mismatch_schema_version`
- `mismatch_python_version`
- `generator_mismatch`
- `integrity_missing`
- `integrity_failed`

## Contracts

- Status values are serialized into report metadata.
- CLI branches by enum/status values, not by human-facing message text.

Refs:

- `codeclone/surfaces/cli/report_meta.py:_build_report_meta`
- `codeclone/surfaces/cli/workflow.py:_main_impl`

## Locked by tests

- `tests/test_baseline.py::test_coerce_baseline_status`
- `tests/test_cache.py::test_cache_version_mismatch_warns`
- `tests/test_cli_unit.py::test_cli_help_text_consistency`

## Non-guarantees

- Human-readable status messages can change while enum values stay stable.
