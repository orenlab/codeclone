---
title: "Contract: version and constant registry"
audience: internal
doc_type: contract
status: draft
source_commit: "60eac9c367d74deeba1478521461addfedd8e681"
source_packet: codeclone_mcp_module_map
---

## Purpose

This document specifies the core version and constant registry that governs CodeClone's structural contracts across the Python codebase. Every constant defined in `codeclone/contracts/__init__.py` serves as a binding contract: schema version markers, risk thresholds, default paths, and resource limits. Changes to these constants cascade into baseline interpretation, artifact semantics, and structural verification. This page documents the current contract bindings—their meaning, failure modes, and verification expectations.

## Contracts

### Version Contracts

Version constants bind artifact semantics to reader code. A mismatch between reader version and artifact version blocks artifact parsing.

| Constant | Value | Scope | Constraint |
|----------|-------|-------|-----------|
| `BASELINE_SCHEMA_VERSION` | `"3.0"` | baseline.json structure | Defines JSON schema for baseline artifacts. Bump only when baseline dict structure changes. |
| `BASELINE_FINGERPRINT_VERSION` | `"3"` | fingerprint algorithm | Never change without explicit `BASELINE_FINGERPRINT_VERSION` review. Alters cloning semantics. |
| `CACHE_VERSION` | `"4.0"` | analysis cache store | Invalidates `.codeclone/db/cache.sqlite3` on mismatch. Bump on cache schema or serialization change. See the note below. |
| `REPORT_SCHEMA_VERSION` | `"3.2"` | report artifact JSON | Governs report.json, report.sarif structure. Bump on schema shape change. |
| `METRICS_BASELINE_SCHEMA_VERSION` | `"1.3"` | metrics baseline JSON | Structure of the metrics baseline artifact used for regression gating. |
| `PATCH_TRAIL_SCHEMA_VERSION` | `"1"` | audit trail encoding | Controls patch_trail.json serialization in intent workspaces. |
| `AUDIT_PROJECTION_VERSION` | `"audit-v1"` | audit event marshaling | Semantic versioning for audit fact format. |
| `MEMORY_PROJECTION_VERSION` | `"memory-v1"` | engineering memory events | Semantic versioning for memory projection codec. |
| `TRAJECTORY_PROJECTION_VERSION` | `"trajectory-v3"` | trajectory artifact encoding | Current trajectory format. Legacy `TRAJECTORY_PROJECTION_VERSION_V1` ("trajectory-v1") exists for compatibility. |
| `EXPERIENCE_DISTILLATION_VERSION` | `"experience-v1"` | experience record format | Semantic version for distilled experience encoding. |
| `SEMANTIC_INDEX_FORMAT_VERSION` | `"3"` | semantic vector index | Governs vector DB schema and retrieval. |
| `SEMANTIC_PROJECTION_REVISION_VERSION` | `"1"` | semantic embedding metadata | Tracks revision of projection metadata format. |
| `ENGINEERING_MEMORY_SCHEMA_VERSION` | `"1.7"` | memory SQLite schema | Controls memory store structure. Must match MCP expectations. |
| `CORPUS_CONTROL_PLANE_CONTRACT_VERSION` | `"1.0"` | analytics control plane | Governance metadata serialization. |
| `CORPUS_ANALYTICS_STORE_SCHEMA_VERSION` | `"1.2"` | analytics database schema | Internal telemetry store layout. |
| `CORPUS_EMBEDDING_CONTRACT_VERSION` | `"2"` | embedding codec | Serialization format for embeddings. |
| `CORPUS_EXPORT_SCHEMA_VERSION` | `"1.3"` | export artifact format | Version for external corpus exports. |
| `CORPUS_REPRESENTATION_CONTRACT_VERSION` | `"3"` | corpus representation | Semantic representation format for code. |
| `CORPUS_AGENT_LABEL_CONTRACT_VERSION` | `"1"` | agent labeling schema | Agent-side labeling codec. |
| `CORPUS_NORMALIZER_VERSION` | `"1"` | source normalization | Canonical normalization for input sources. |
| `CORPUS_PARTITION_MAP_VERSION` | `"1"` | partition mapping | Corpus partition semantics. |
| `CORPUS_PROFILE_MANIFEST_SCHEMA_VERSION` | `"1"` | profile manifest | Profile metadata structure. |
| `IDE_GOVERNANCE_PROTOCOL_VERSION` | `2` (int) | IDE MCP protocol | Major version of IDE governance API. Bumps break all IDE clients. |
| `TRAJECTORY_QUALITY_SCORE_VERSION` | `"2"` | quality scoring algorithm | Determines how quality scores are computed. |
| `METRICS_BASELINE_SCHEMA_VERSION` | `"1.3"` | metrics baseline storage | Metrics artifact encoding version. |

### Risk Thresholds and Defaults

Thresholds define boundaries for finding classification. Defaults set baseline configuration when no explicit user config is provided.

| Constant | Value | Purpose | Notes |
|----------|-------|---------|-------|
| `COMPLEXITY_RISK_LOW_MAX` | `10` | Low complexity ceiling | Findings above this but below MEDIUM trigger low-risk. |
| `COMPLEXITY_RISK_MEDIUM_MAX` | `20` | Medium complexity ceiling | Findings above this are high-risk. |
| `COHESION_RISK_MEDIUM_MAX` | `3` | Cohesion split threshold | Modules with metric above this flag cohesion risk. |
| `COUPLING_RISK_LOW_MAX` | `5` | Low coupling ceiling | Low-risk coupling threshold. |
| `COUPLING_RISK_MEDIUM_MAX` | `10` | Medium coupling ceiling | Medium/high risk above this. |
| `DEFAULT_COMPLEXITY_THRESHOLD` | `20` | Reporting threshold | Only report complexity findings >= this. Aligns with COMPLEXITY_RISK_MEDIUM_MAX. |
| `DEFAULT_COHESION_THRESHOLD` | `4` | Reporting threshold | Only report cohesion findings >= this. |
| `DEFAULT_COUPLING_THRESHOLD` | `10` | Reporting threshold | Only report coupling findings >= this. Aligns with COUPLING_RISK_MEDIUM_MAX. |
| `DEFAULT_HEALTH_THRESHOLD` | `60` | Health reporting floor | Only report modules below this health score. |
| `DEFAULT_COVERAGE_MIN` | `50` | Coverage minimum | Treat coverage below 50% as lacking evidence. |
| `DEFAULT_MIN_LOC` | `10` | Minimum lines of code | Ignore fragments < 10 lines in clone detection. |
| `DEFAULT_MIN_STMT` | `6` | Minimum top-level statements | Ignore functions whose body holds < 6 top-level statements in clone detection; nested statements do not count. |
| `DEFAULT_BLOCK_MIN_LOC` | `20` | Clone block minimum LOC | Report only clone blocks >= 20 lines. |
| `DEFAULT_BLOCK_MIN_STMT` | `8` | Clone block minimum top-level statements | Report only clone blocks >= 8 consecutive top-level statements of a function body. |
| `DEFAULT_SEGMENT_MIN_LOC` | `20` | Segment minimum LOC | Ignore code segments < 20 lines. |
| `DEFAULT_SEGMENT_MIN_STMT` | `10` | Segment minimum top-level statements | Ignore segments shorter than 10 consecutive top-level statements of a function body. |

### Health Weighting

`HEALTH_WEIGHTS` is a dict mapping metric families to coefficients used in aggregate health scoring.

```
{
  "clones": 0.25,
  "cohesion": 0.15,
  "complexity": 0.2,
  "coupling": 0.1,
  "coverage": 0.1,
  "dead_code": 0.1,
  "dependencies": 0.1
}
```

All weights must sum to 1.0. Clones carry highest weight (25%); dependencies and coverage are equal contributors (10% each).

### Health Dependency Penalties

Penalties applied when computing health from dependency metrics.

| Constant | Value | Type | Purpose |
|----------|-------|------|---------|
| `HEALTH_DEPENDENCY_CYCLE_PENALTY` | `25` | int | Deduct 25 points per cycle detected. |
| `HEALTH_DEPENDENCY_DEPTH_LEVEL_PENALTY` | `4` | int | Deduct 4 points per depth level. |
| `HEALTH_DEPENDENCY_DEPTH_P95_MARGIN` | `1` | int | P95 depth tolerance margin. |
| `HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER` | `2.0` | float | Scale average depth by 2× before comparison. |

### Path and Resource Defaults

| Constant | Value | Purpose |
|----------|-------|---------|
| `DEFAULT_ROOT` | `"."` | Default repository root for CLI. |
| `DEFAULT_BASELINE_PATH` | `"codeclone.baseline.json"` | Baseline filename in repo root. |
| `DEFAULT_HTML_REPORT_PATH` | `".codeclone/report.html"` | HTML report destination. |
| `DEFAULT_JSON_REPORT_PATH` | `".codeclone/report.json"` | JSON report destination. |
| `DEFAULT_MARKDOWN_REPORT_PATH` | `".codeclone/report.md"` | Markdown report destination. |
| `DEFAULT_TEXT_REPORT_PATH` | `".codeclone/report.txt"` | Text report destination. |
| `DEFAULT_SARIF_REPORT_PATH` | `".codeclone/report.sarif"` | SARIF report destination. |
| `DEFAULT_PROCESSES` | `4` | Parallel workers for analysis. |
| `DEFAULT_MAX_BASELINE_SIZE_MB` | `5` | Max baseline file size (MB). |
| `DEFAULT_MAX_CACHE_SIZE_MB` | `256` | Max analysis cache size (MB). |

### Reporting Thresholds (Design Report)

Thresholds used specifically when generating design reports.

| Constant | Value | Purpose |
|----------|-------|---------|
| `DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD` | `20` | Only show complexity findings >= 20. |
| `DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD` | `4` | Only show cohesion findings >= 4. |
| `DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD` | `10` | Only show coupling findings >= 10. |

### URLs

| Constant | Value |
|----------|-------|
| `DOCS_URL` | `https://orenlab.github.io/codeclone/` |
| `REPOSITORY_URL` | `https://github.com/orenlab/codeclone` |
| `ISSUES_URL` | `https://github.com/orenlab/codeclone/issues` |

## Implementation map

All constants reside in `codeclone/contracts/__init__.py`. Import paths:

```python
from codeclone.contracts import (
    BASELINE_SCHEMA_VERSION,
    BASELINE_FINGERPRINT_VERSION,
    CACHE_VERSION,
    REPORT_SCHEMA_VERSION,
    # ... all others
)
```

When a constant is referenced, the source location is always `codeclone.contracts`. Callers must not copy values; they must import the canonical binding. This ensures a single source of truth.

## Failure modes

### Version Mismatches

- **Baseline artifact read fails**: Reader code compares the stored schema version against `BASELINE_SCHEMA_VERSION` with an exact match. Any other stored value — older or newer — makes the baseline untrusted (`MISMATCH_SCHEMA_VERSION`) and requires regeneration; the only cross-version path is the one-shot 2.1→3.0 migration in `codeclone/baseline/transition.py`.
- **Report artifact incompatibility**: CodeClone tools consuming reports check `REPORT_SCHEMA_VERSION`. A version mismatch blocks report loading.
- **Cache invalidation**: Analysis cache becomes invalid if `CACHE_VERSION` increments. Cached analysis is discarded on first run.
- **Cache generations are not run identities**: the JSON monolith and the backend-resident cache store are different generations and neither reads the other; there is no fallback, and the cache is disposable, so the regeneration cost is the whole cost. A cache generation never participates in run-store semantic identity, and cache tables never enter publication correctness.

### Threshold Violations

- **Misconfigured thresholds**: If a user config supplies a complexity threshold below `COMPLEXITY_RISK_LOW_MAX` (10), findings are misclassified. No automatic correction occurs; the finding is reported as configured.
- **Health weight imbalance**: If `HEALTH_WEIGHTS` do not sum to 1.0, or any weight is negative, the aggregate stops being a weighted mean and leaves [0, 100] — where `_clamp_score` folds the overflow onto an ordinary-looking 100. This is a contract violation, and `codeclone.metrics.health._convex_weights` refuses it at the aggregate with `ContractInvariantError` rather than scoring through it.
- **Penalty overflow**: If `HEALTH_DEPENDENCY_CYCLE_PENALTY` > 100, a single cycle can drive health below 0. No clamping is applied; result may be nonsensical.

### Path and Resource Exhaustion

- **Cache overflow**: With `DEFAULT_MAX_CACHE_SIZE_MB = 256`, a cache file above the cap is ignored on load with a warning (`TOO_LARGE`), and every run falls back to cold analysis. No spillover mechanism exists; the cap remains a memory and decompression-bomb guard.
- **Process pool contention**: `DEFAULT_PROCESSES = 4` may starve system resources on low-core machines or in containerized environments.

## Verification

### Contract Invariants

1. All version constants must be strings or integers. No dynamic computation is allowed.
2. Risk thresholds must be ordered: `COMPLEXITY_RISK_LOW_MAX < COMPLEXITY_RISK_MEDIUM_MAX` (10 < 20). Violations break finding classification.
3. Health weights must be a convex combination: every weight ≥ 0 and the total 1.0 within `_weight_sum_slack(n) = (n + 1) × ulp(1.0) / 2` ≈ 8.9e-16 for the seven shipped dimensions. The slack is a float-representation bound re-derived from how decimal weights are stored, not a tolerance for mis-authored values: a ±0.001 window would accept a weight typed as 0.1009.
4. Path constants must be relative (no absolute /home, /usr prefixes).
5. Default parameters must be reasonable: processes > 0, size limits > 0, LOC/statement thresholds >= 1.

### Test Coverage

The test suite **must** verify:

- Constants are importable and non-None.
- Version strings are unique per artifact family.
- Thresholds are ordered correctly.
- Health weights sum to 1.0 and none is negative — pinned on the sum itself, not on a re-run of the aggregate formula, which stays green for any vector.
- Baseline and report versions are stable (immutable once released).

Run verification:
```bash
uv run pytest -q tests/test_defaults_contract.py
```

If the constant registry is edited, rerun the full test suite:
```bash
uv run pytest -q
```

### Editorial Approval

- **Version bumps** require review and explicit approval. Never increment a version in a routine fix.
- **Threshold adjustments** require impact analysis: which findings will be reclassified? Run before/after analysis to measure the effect.
- **New constants** must follow naming convention: `DEFAULT_<NAME>` for defaults, `<METRIC>_RISK_<LEVEL>_MAX` for thresholds, `<ARTIFACT>_VERSION` for versions.

## Evidence index

| Evidence | Location | Status | Notes |
|----------|----------|--------|-------|
| Constant registry | `codeclone/contracts/__init__.py` | Source of truth | All constants defined here. |
| Test suite | `tests/test_defaults_contract.py` | Verification | Validates constant values and invariants. |
| Schema versions | BASELINE_SCHEMA_VERSION, REPORT_SCHEMA_VERSION, CACHE_VERSION | Current artifact specs | Tied to reader/writer code. |
| Risk thresholds | COMPLEXITY_RISK_*, COUPLING_RISK_*, COHESION_RISK_* | Finding classification | Must be ordered; tested in test_defaults_contract.py. |
| Health model | HEALTH_WEIGHTS, HEALTH_DEPENDENCY_* | Scoring algorithm | Weights must be convex: sum 1.0, none negative; enforced at the aggregate. |
