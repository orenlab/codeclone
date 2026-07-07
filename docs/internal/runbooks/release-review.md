---
title: "Runbook: release review"
audience: internal
doc_type: runbook
status: draft
source_commit: "d88c17f0f19cf753b9d43870528e0747b3161b9c"
source_packet: codeclone_mcp_module_map
---

## Purpose

Release review validates that a patch bundle ready for packaging meets structural contracts, passes change-control verification, and has durably recorded all relevant evidence. This runbook provides steps for MCP-backed release review and decision gates.

## Contracts

The release process expects these version and threshold contracts:

| Contract | Value | Purpose |
|----------|-------|---------|
| `BASELINE_SCHEMA_VERSION` | 2.1 | Baseline artifact format agreement |
| `PATCH_TRAIL_SCHEMA_VERSION` | 1 | Audit trail format for patch forensics |
| `REPORT_SCHEMA_VERSION` | 2.12 | Report payload structure |
| `BASELINE_FINGERPRINT_VERSION` | 1 | Clone-detection fingerprint logic version |
| `CACHE_VERSION` | 2.10 | Analysis cache compatibility |
| `ENGINEERING_MEMORY_SCHEMA_VERSION` | 1.7 | Memory store schema |

All artifacts must match these versions before release. Do not upgrade versions within a release; version changes require explicit contract amendment.

## Implementation map

```mermaid
graph TD
    A["Release candidate branch"] -->|analyze_repository| B["Full structural run"]
    B -->|get_run_summary| C{Hotspots or findings?}
    C -->|Yes| D["Review each finding"]
    C -->|No| E["get_blast_radius review"]
    D -->|validate_review_claims| F["Claim check against report"}
    E -->|all clear| G["start_controlled_change"]
    F -->|all valid| G
    G -->|status=active| H["Package + verify artifacts"]
    H -->|after_run_id| I["finish_controlled_change"]
    I -->|status=accepted| J["create_review_receipt"]
    J -->|markdown receipt| K["Release approved"]
    I -->|status=violated| L["Resolve scope violations"]
    L -->|fix tree| I
```

**Pre-release workflow:**

1. Ensure all patches under review have active intents: `manage_change_intent(action=list_workspace)`
2. Run `analyze_repository(root=...)` on the release branch to capture baseline-relative structural state
3. Call `get_run_summary()` to scan hotspots and findings
4. For each structural finding, invoke `get_finding()` and review evidence
5. Validate all review claims via `validate_review_claims()` against the canonical report
6. Call `check_patch_contract(mode='verify')` to confirm all patches meet the derived verification profile

**Packaging + release gates:**

7. When all structural checks pass, call `start_controlled_change()` with declared release scope
8. Confirm `status='active'` and `edit_allowed=true`; if `queued`, wait for foreign intents to clear
9. Apply packaging changes (version bumps, changelog, wheel metadata)
10. Run `analyze_repository()` again to capture post-edit state
11. Call `finish_controlled_change(intent_id=..., after_run_id=...)` to verify scope closure
12. If `status='accepted'` and `scope_check.status='clean'`, generate receipt: `create_review_receipt(intent_id=..., format='markdown')`
13. Archive the receipt in release notes; proceed to publish

## Failure modes

| Symptom | Root Cause | Recovery |
|---------|-----------|----------|
| `status: "unverified"` on finish | Before/after runs do not match; same scope changed under analysis | Re-run `analyze_repository` with a fresh `run_id`, pass `after_run_id` to `finish` again on the **same** `intent_id` |
| `status: "violated"` on finish | In-scope files were edited outside declared scope | Expand scope via `start_controlled_change` with wider scope, then retry finish on the new intent |
| `finish_block_reason: "missing_evidence"` | Changed files not reported to finish | List all changed files, pass as `changed_files=[...]` to finish; re-call analyze if Python structural files were touched |
| `status: "queued"` on start | Foreign intent active in workspace | Call `manage_change_intent(action=promote, intent_id=<yours>)` after foreign intent clears, or narrow scope to avoid overlap |
| Intent eviction: "Unknown change intent id" on finish | New intent declared via start before previous finish | Never call start twice without finish in between; one active intent per session |

## Verification

Use these commands to validate pre-release state:

```bash
# Full structural analysis
codeclone . --json /tmp/release-run.json

# Inspect the produced report for high-risk findings
jq '.findings' /tmp/release-run.json

```

Claim validation before review is an MCP-only capability (`validate_review_claims`); there is no CLI equivalent.

**MCP verification:**

```python
# Get implementation context for release scope
get_implementation_context(root=..., scope={"packages": ["codeclone.surfaces.mcp", ...]})

# Confirm no unverified dependencies
check_patch_contract(mode='verify', scope=..., before_run_id=..., after_run_id=...)
```

All receipts must include:
- Blast radius and scope boundaries
- Count of reviewed findings and their baseline novelty
- Patch contract status (accepted / unverified / violated)
- Engineering memory records created during review (if any)

## Evidence index

This runbook depends on the following technical facts from Engineering Memory:

- **mem-21b67e91cf2441f981daf7e0b51e4d34**: Packaging topology — MCP extras and edit-cycle isolation. Confirms that change-control workflows are MCP-surface-only; base CLI is read-only. [path_only: background on separation of concerns]

- **mem-527db78f1ce24eb98ad06ce507f0de93**: MCP session intent exclusivity — exactly ONE trackable active intent per session. Critical for preventing intent eviction on premature start calls. [path_only: risk constraint]

- **mem-6859f67ef1234556981b7ccb36673f77**: PID liveness tri-state — security hardening to detect unknown foreign owners. Affects intent locking and coordination visibility during release. [path_only: hardening context]

- **mem-6e6628aa24504020ae2f1f8628365ddc**: Phase 30 freshness invariant — MCP runs capture mtime+size signatures and dirty snapshots to detect content rewrites. Ensures post-packaging analysis detects real changes. [path_only: drift detection model]

See `codeclone/surfaces/mcp/_workspace_intent_lifecycle.py`, `pyproject.toml`, and `codeclone/surfaces/mcp/_workspace_drift.py` for implementation.
