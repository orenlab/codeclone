# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from enum import IntEnum
from typing import Final

BASELINE_SCHEMA_VERSION: Final = "3.0"
# Version "3" carries two changes that land together and are not separable:
# the norm CFG (post-terminator statements become real unreachable blocks, and
# exception dispatch, `finally` routing and context-manager suppression become
# ordinary edges) and binding-aware symbol emission in the wire. The hash
# domain moves with it (`ccfp3:fn`), so a function whose normalization did not
# change still cannot collide across generations.
BASELINE_FINGERPRINT_VERSION: Final = "3"
# Version "2" emits every Name and Attribute by the role its symbol is bound
# to, in every expression position, replacing the four position-based
# preservation sites. Alpha-renaming a local no longer moves the wire, and a
# resolved import keeps its canonical identity where the old wire erased it.
WIRE_VERSION: Final = "2"
MODULE_IDENTITY_VERSION: Final = "2"
PORTABLE_PATH_PROFILE_VERSION: Final = "1"
SEMANTIC_EVENT_VERSION: Final = "1"
CONTRACT_IR_VERSION: Final = "1"
AUTHORITY_ANALYSIS_REVISION: Final = "1"
AUTHORITY_REGISTRY_VERSION: Final = "1"
OBSERVATION_DIGEST_VERSION: Final = "1"
# Algorithm revision of the ``coupling_cohesion_observations`` design-metric
# lane. Separate from OBSERVATION_DIGEST_VERSION so a change in how these
# metrics are *computed* invalidates only the lanes whose values moved.
# Revision "2" covers the 39Y changes: every defined function now carries a
# complexity fact (clone-lane floors no longer gate the population), CBO
# counts the imported-domain and resolved-instantiation edge lanes, and the
# coupling risk bands were re-derived from the measured distribution. Values
# from revision "1" are not comparable with revision "2" values, so a baseline
# carrying the old revision is untrusted rather than diffed. Until Wave D this
# revision also governed ``risk_observations``; that lane now moves with
# COMPLEXITY_ALGORITHM_REVISION below, so a complexity recount never
# invalidates coupling observations and vice versa.
DESIGN_METRICS_ALGORITHM_REVISION: Final = "2"
# Algorithm revision of the ``risk_observations`` lane — the lane carrying the
# per-unit complexity dimension. Revisions "1" and "2" (shared history with
# DESIGN_METRICS_ALGORITHM_REVISION above) computed ``cyclomatic_complexity``
# from the CFG; under revision "2" that meant full McCabe E-N+2P over the
# complete Y9 graph. Revision "3" is the Wave D split: the public
# ``cyclomatic_complexity`` is a deterministic source-level decision count
# over AST constructs (single owner:
# ``codeclone.metrics.source_decisions.SourceDecisionCounter``), and the CFG
# value survives only as the diagnostic ``cfg_cyclomatic_complexity``, which
# reaches no baseline lane and no gate. Bump discipline: move this revision
# whenever any cell of the ratified decision table changes — a construct's
# contribution, the match wildcard rule, the BoolOp arity rule, the nested
# scope boundary — or when the lane's population rule moves. Values across
# revisions are not comparable; a baseline carrying an older revision is
# untrusted for this lane rather than diffed.
COMPLEXITY_ALGORITHM_REVISION: Final = "3"
BASELINE_LANE_DESCRIPTOR_VERSION: Final = "1"
BASELINE_LANE_DIGEST_DOMAIN: Final = "codeclone.baseline.lane.v1\0"
BASELINE_ROOT_DIGEST_DOMAIN: Final = "codeclone.baseline.root.v1\0"
API_SURFACE_SIGNATURE_VERSION: Final = "1"
REPORT_ANALYSIS_FACTS_DIGEST_DOMAIN: Final = "codeclone.report.analysis_facts.v1\0"
REPORT_COMPARISON_DIGEST_DOMAIN: Final = "codeclone.report.comparison.v1\0"
REPORT_EVALUATION_DIGEST_DOMAIN: Final = "codeclone.report.evaluation.v1\0"
REPORT_ENVELOPE_DIGEST_DOMAIN: Final = "codeclone.report.envelope.v1\0"
GATE_LANE_MATRIX_VERSION: Final = "2"
HEALTH_INPUT_MANIFEST_VERSION: Final = "1"
OBSERVER_VOCABULARY_VERSION: Final = "3"
# Version "2" adds two life proofs, and nothing else moves. (1) A PEP 484
# explicit re-export - ``from x import y as y``, the ``as``-SAME-name
# spelling - livens its resolved target on its own; static ``__all__``
# membership remains the second, independent, stronger explicit contract.
# The proof fires only at module scope in a runtime-reachable branch of a
# production file: a renaming import is not a re-export, a
# ``TYPE_CHECKING``-guarded import livens nothing, and a dynamically built
# ``__all__`` stays UNRESOLVED rather than degrading into a heuristic.
# (2) A resolved pluggy hook marker decorator roots its function: a proven
# ``@hookspec`` livens a declaration and a proven ``@hookimpl`` livens an
# implementation - two INDEPENDENT roots, never a pair. "Resolved" means the
# decorator expression resolves to the canonical ``pluggy.HookspecMarker`` /
# ``pluggy.HookimplMarker`` identity through module-scope assignments and
# import aliases; the decorator NAME alone is never evidence. Bump this
# constant whenever what counts as LIVE changes; verdicts across versions
# are not comparable. Cached liveness inputs move with it by construction:
# the constant is an input of the module-dependent cache reuse profile
# (codeclone/cache/reuse.py), so a bump misses exactly the lane that
# carries ``referenced_qualnames``, dead candidates and live-root reasons,
# and never touches the neutral fingerprint lane.
LIVENESS_POLICY_VERSION: Final = "2"
SOURCE_KIND_POLICY_VERSION: Final = "1"
# Statement-level unreachability (39Y Y9). Version "1" is ONE predicate over
# ONE graph: a statement cannot run exactly when its block is not reachable
# from ``CFG.entry`` by directed traversal of ``Block.successors``. There is no
# separate clause for code after a terminator and none for a literal guard —
# the norm CFG builder already expresses both structurally, by emitting the
# post-terminator tail as a block with no incoming edge and by suppressing the
# edge into a branch whose guard is a literal ``ast.Constant`` that forbids
# entry. Exception dispatch, ``finally`` routing and context-manager
# suppression are likewise ordinary edges, so traversal answers them too.
# ``BlockOrigin`` names a cause for the reader and is evidence only: the block
# is already decided unreachable before any origin is consulted, and no verdict
# depends on it. No value inference and no propagation: the moment a name
# lookup counts as evidence the rule stops being this declared predicate.
STATEMENT_REACHABILITY_POLICY_VERSION: Final = "1"
# Maximum number of inserted, deleted or replaced normalized statements between
# two units that still group as the ``near_miss`` clone tier (39Y Y8). Integer
# by contract: the tier carries no similarity score and no tunable floor. A
# distance of zero is the exact tier's business and never enters near_miss.
NEAR_MISS_MAX_EDIT_STATEMENTS: Final = 1
# The near-miss lane's own algorithm identity. Revision "1" was the 39Y Y8
# single-divergence head-scan construction and was never published as a
# constant; "2" is the sequence Levenshtein verdict (insert, delete and
# replace each cost exactly one edit; equal costs zero) together with the
# canonical DP-backtrace witness law — one documented total order over
# equal-cost forks, so which statement is reported as the edit is as
# deterministic as the distance itself. "3" adds the declared renamed token
# domain (the CxB composition): the same Levenshtein verdict and witness law
# run a second time over statement tokens canonicalized by the
# renamed_structure ordinal rules, each domain on its own deletion index,
# with a pair confirmable in both domains reported once in the y8 domain.
# Bumping this never touches the exact lane: BASELINE_FINGERPRINT_VERSION
# and the statement-token wire are unchanged, and the tier still reaches no
# baseline lane and no gate.
NEAR_MISS_ALGORITHM_REVISION: Final = "3"
# The renamed-structure lane's own algorithm identity (Wave C). Revision "1"
# is ordinal canonicalization: LOCAL and ATTRIBUTE ordinals in separate
# numbering spaces, binding identity scope-qualified before assignment,
# first-occurrence ordering with parameters seeded by declaration position,
# imported identities and unprovable names rigid, terminal callees literal
# across the whole unit, and the equality pattern preserved. The tier is an
# exact match in its own digest domain — O(n), no pairwise matcher, no
# similarity score. Bumping this never touches the exact lane:
# BASELINE_FINGERPRINT_VERSION is unchanged, and the tier reaches no baseline
# lane and no gate.
RENAMED_STRUCTURE_ALGORITHM_REVISION: Final = "1"

# 3.2 adds the two rule-3 fact families: per-class base resolution and
# per-method decorator evidence. Both gate the tri-state liveness verdict,
# so a cache that lacked them would make the verdict depend on cache state.
# It also carries the per-unit normalized statement sequence behind the
# ``near_miss`` tier (39Y Y8): grouping runs over units that a warm run serves
# straight off the wire, so a sequence that did not ride the cache would make a
# warm run report zero near-miss pairs. Everything this phase sanctions rides
# this one bump instead of adding a second.
#
# 3.3 carries the per-unit renamed-structure digest (Wave C) on the same
# reasoning: the digest is computed from the AST, a warm run never re-parses,
# and a unit served off a wire without it would make a warm run silently
# report zero renamed-structure groups.
#
# 3.4 carries the per-unit renamed-canonical statement sequence (the CxB
# composition), closing the same trap one lane over: the near-miss renamed
# token domain reads this sequence off the unit fact, so a warm run served
# off a 3.3 wire would silently report only y8-domain pairs. Its own key,
# absence rejects the entry, rejection just re-analyses the file.
#
# 3.5 (Wave D) widens the positional unit row by one column: index 7 stays the
# public ``cyclomatic_complexity`` (now the source-decision count) and a new
# trailing column carries the diagnostic ``cfg_cyclomatic_complexity``. Cached
# units also hold complexity computed by the pre-split CFG algorithm, so the
# bump is what forces every unit through the new counter instead of serving
# stale semantics off the wire.
CACHE_VERSION: Final = "3.5"
REPORT_SCHEMA_VERSION: Final = "3.0"
# Human-readable provenance stamp for a metrics artifact, reported to the
# operator and nothing more. It is NOT the compatibility authority and must not
# be described as one: no code branches on it. Whether a stored artifact may be
# compared with current values is decided in exactly one place,
# ``MetricsBaseline.verify_compatibility`` — per-lane ``algorithm_revision`` and
# ``payload_schema`` first (a stale design-metric lane raises
# INCOMPATIBLE_METRICS_CONTRACT), then ``BASELINE_SCHEMA_VERSION`` and the
# Python tag. That check is finer than this string: it names the lane that
# moved instead of failing the whole artifact.
#
# 1.3 records that the design-metric lanes moved to
# DESIGN_METRICS_ALGORITHM_REVISION "2"; the refusal to diff 1.2 values against
# current ones is delivered by the lane revision, not by this constant.
METRICS_BASELINE_SCHEMA_VERSION: Final = "1.3"
ENGINEERING_MEMORY_SCHEMA_VERSION: Final = "1.7"
# Semantic retrieval index. Derived, rebuildable sidecar — NOT
# covered by ENGINEERING_MEMORY_SCHEMA_VERSION. Bump to invalidate the index
# on an incompatible projection/row-format change (forces a rebuild, not a
# SQLite migration). v3 (Stage 2) adds the ``source_revision`` row column; the
# one-time full rebuild is actually forced by the backend schema check, not by
# this constant — it stays in sync so the reported ``index_version`` is honest.
SEMANTIC_INDEX_FORMAT_VERSION: Final = "3"
# Global escape hatch for the cheap per-row ``source_revision`` key (Stage 2
# incremental sourcing). Bump to invalidate EVERY semantic lane at once on a
# cross-cutting projection/row-format change. Per-source projection versions are
# folded into each source's content token instead, so a single-lane projector
# change re-embeds only that lane (see ``memory.semantic.projection``).
SEMANTIC_PROJECTION_REVISION_VERSION: Final = "1"
# Per-source projection versions folded into each source's ``source_revision``
# content token. Trajectory reuses TRAJECTORY_PROJECTION_VERSION below.
MEMORY_PROJECTION_VERSION: Final = "memory-v1"
AUDIT_PROJECTION_VERSION: Final = "audit-v1"
PATCH_TRAIL_SCHEMA_VERSION: Final = "1"
# Platform observability sqlite store (.codeclone/db/platform_observability.sqlite3):
# a runtime-profiling plane separate from audit/memory. Bump on an incompatible
# observability schema change.
PLATFORM_OBSERVABILITY_SCHEMA_VERSION: Final = "1.1"

# Memory-derived projection/derivation versions. NOT persistence schema
# versions: bump to supersede previously derived rows on an incompatible
# projection/scoring/distillation change (re-projection, not a SQLite
# migration). Defined here so all version constants live in one place; the
# owning modules re-export these names.
TRAJECTORY_PROJECTION_VERSION: Final = "trajectory-v3"
TRAJECTORY_PROJECTION_VERSION_V1: Final = "trajectory-v1"
TRAJECTORY_QUALITY_SCORE_VERSION: Final = "2"
EXPERIENCE_DISTILLATION_VERSION: Final = "experience-v1"
# IDE governance HMAC attestation protocol version (IDE Memory channels).
IDE_GOVERNANCE_PROTOCOL_VERSION: Final = 2

# Corpus analytics store (.codeclone/analytics/corpus_clustering.sqlite3) and
# derived export/representation contracts. Bump independently from memory schema.
CORPUS_ANALYTICS_STORE_SCHEMA_VERSION: Final = "1.2"
CORPUS_EXPORT_SCHEMA_VERSION: Final = "1.3"
CORPUS_PROFILE_MANIFEST_SCHEMA_VERSION: Final = "1"
CORPUS_CONTROL_PLANE_CONTRACT_VERSION: Final = "1.0"
CORPUS_REPRESENTATION_CONTRACT_VERSION: Final = "3"
CORPUS_NORMALIZER_VERSION: Final = "1"
CORPUS_EMBEDDING_CONTRACT_VERSION: Final = "2"
CORPUS_AGENT_LABEL_CONTRACT_VERSION: Final = "1"
CORPUS_PARTITION_MAP_VERSION: Final = "1"

DEFAULT_COMPLEXITY_THRESHOLD: Final = 20
DEFAULT_COUPLING_THRESHOLD: Final = 10
DEFAULT_COHESION_THRESHOLD: Final = 4
DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD: Final = 20
DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD: Final = 10
DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD: Final = 4
DEFAULT_HEALTH_THRESHOLD: Final = 60
DEFAULT_ROOT: Final = "."
DEFAULT_MIN_LOC: Final = 10
DEFAULT_MIN_STMT: Final = 6
DEFAULT_BLOCK_MIN_LOC: Final = 20
DEFAULT_BLOCK_MIN_STMT: Final = 8
DEFAULT_SEGMENT_MIN_LOC: Final = 20
DEFAULT_SEGMENT_MIN_STMT: Final = 10
DEFAULT_PROCESSES: Final = 4
DEFAULT_MAX_CACHE_SIZE_MB: Final = 256
DEFAULT_MAX_BASELINE_SIZE_MB: Final = 5
DEFAULT_COVERAGE_MIN: Final = 50
DEFAULT_BASELINE_PATH: Final = "codeclone.baseline.json"
DEFAULT_HTML_REPORT_PATH: Final = ".codeclone/report.html"
DEFAULT_JSON_REPORT_PATH: Final = ".codeclone/report.json"
DEFAULT_MARKDOWN_REPORT_PATH: Final = ".codeclone/report.md"
DEFAULT_SARIF_REPORT_PATH: Final = ".codeclone/report.sarif"
DEFAULT_TEXT_REPORT_PATH: Final = ".codeclone/report.txt"

COMPLEXITY_RISK_LOW_MAX: Final = 10
COMPLEXITY_RISK_MEDIUM_MAX: Final = 20
# Coupling risk bands, derived from the measured CBO distribution of a
# reference corpus (915 classes; avg 1.44, p50 0, p90 4, p95 7, p99 14,
# max 27) under the resolution-gated edge contract in ``metrics/coupling.py``.
# Both edges are percentiles of that distribution, so a class leaves a band
# only by being more coupled than a declared share of real classes:
#   low    -- the bulk, at or below the upper decile (p90);
#   medium -- the decile-to-ventile band (p90 .. p95);
#   high   -- the upper ventile, the 5% tail.
# p90 and p95 measured identically (4 and 7) on the production-only subset of
# the same corpus, so the edges describe the shape of the distribution rather
# than the filter applied to it. Owning test:
# tests/test_metrics_health_recalibration.py, which recomputes both percentiles
# from the recorded histogram.
COUPLING_RISK_LOW_MAX: Final = 4
COUPLING_RISK_MEDIUM_MAX: Final = 7
COHESION_RISK_MEDIUM_MAX: Final = 3

# Coupling health dimension: four bounded terms whose weights spend exactly the
# 100 points of the dimension, and the complexity dimension above uses the same
# four-term shape for the same reason. The complexity formula it replaced
# (100 - avg*2.5 - max*1.2 - high*8) was a function of the single worst
# function: on the measured post-norm distribution of this repository one
# 34-complexity function alone spent 40.8 points and five high-risk functions
# spent 40, pinning the dimension at 12 while the typical function sits at
# complexity 3. Its reference shares are MEASURED, not chosen.
#
# Wave D re-measured them for the source-decision metric
# (COMPLEXITY_ALGORITHM_REVISION): the same population (production functions
# outside tests/ and benchmarks/) now measures n=5438, avg 3.90,
# p90/p95/p99 = 8/11/21, max 98, with 321 above COMPLEXITY_RISK_LOW_MAX
# (59.03 per mille) and 56 above COMPLEXITY_RISK_MEDIUM_MAX (10.30 per mille).
# The two permilles below are a GENERATED calibration artifact, not hand
# numbers: they are the output of the calibration procedure
# (``tests/_complexity_calibration.py``) over its pinned reference
# distribution, and ``tests/test_complexity_calibration.py`` reds if either
# constant stops equalling that output. The retired Y9-CFG values were 28 and
# 1 (from n=5194, 146 above 10, 5 above 20). The complexity BANDS are
# unchanged: 10 and 20 were reviewed and kept, and the recalibration touched
# only these two permilles — never fail_health, never the bands, never the
# outlier term.
#
# Bounding is the point. The previous coupling formula
# (100 - avg*7 - max*2 - high*8) let one 27-collaborator class cost 54 points
# and 16 high-risk classes cost 128, which pinned the dimension at 0 on the
# reference distribution: it measured a single outlier, not the project, and
# could not move when the code improved.
#
# Two terms are shares rather than counts, so the dimension does not punish a
# project for being large; the reference share of each is implied by the band
# percentile above (a p90 edge leaves 100 per mille above it, a p95 edge 50),
# so bands and score share one derivation instead of two measurements.
HEALTH_COMPLEXITY_TYPICAL_WEIGHT: Final = 30
HEALTH_COMPLEXITY_ELEVATED_WEIGHT: Final = 30
HEALTH_COMPLEXITY_EXTREME_WEIGHT: Final = 30
HEALTH_COMPLEXITY_OUTLIER_WEIGHT: Final = 10
# Generated by the calibration procedure (tests/_complexity_calibration.py:
# reference_permilles()); pinned by tests/test_complexity_calibration.py. Do
# not hand-edit — recalibrate through the procedure with a fresh measurement
# and maintainer ratification.
HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE: Final = 59
HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE: Final = 10
HEALTH_COMPLEXITY_TAIL_SATURATION_MULTIPLE: Final = 4
HEALTH_COMPLEXITY_OUTLIER_SATURATION_MULTIPLE: Final = 3
HEALTH_COUPLING_TYPICAL_WEIGHT: Final = 30
HEALTH_COUPLING_ELEVATED_WEIGHT: Final = 30
HEALTH_COUPLING_EXTREME_WEIGHT: Final = 30
HEALTH_COUPLING_OUTLIER_WEIGHT: Final = 10
HEALTH_COUPLING_ELEVATED_REFERENCE_PERMILLE: Final = 100
HEALTH_COUPLING_EXTREME_REFERENCE_PERMILLE: Final = 50
# A tail this many times its reference share spends that term completely: at
# 4x, 40% of classes are above the low band and 20% above the medium band, so
# elevated coupling is the dominant mode rather than a tail. It also places the
# reference distribution at a quarter of each tail term, leaving both room to
# worsen and room to improve.
HEALTH_COUPLING_TAIL_SATURATION_MULTIPLE: Final = 4
# The single-worst-class term saturates once the maximum reaches this multiple
# of the high-risk band edge above it. Past that point the dimension stops
# responding to one class's magnitude, which is exactly the defect this
# replaces.
HEALTH_COUPLING_OUTLIER_SATURATION_MULTIPLE: Final = 3
HEALTH_DEPENDENCY_CYCLE_PENALTY: Final = 25
HEALTH_DEPENDENCY_DEPTH_LEVEL_PENALTY: Final = 4
HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER: Final = 2.0
HEALTH_DEPENDENCY_DEPTH_P95_MARGIN: Final = 1

HEALTH_WEIGHTS: Final[dict[str, float]] = {
    "clones": 0.25,
    "complexity": 0.20,
    "coupling": 0.10,
    "cohesion": 0.15,
    "dead_code": 0.10,
    "dependencies": 0.10,
    "coverage": 0.10,
}


class ExitCode(IntEnum):
    SUCCESS = 0
    CONTRACT_ERROR = 2
    GATING_FAILURE = 3
    INTERNAL_ERROR = 5


REPOSITORY_URL: Final = "https://github.com/orenlab/codeclone"
ISSUES_URL: Final = "https://github.com/orenlab/codeclone/issues"
DOCS_URL: Final = "https://orenlab.github.io/codeclone/"


def cli_help_epilog() -> str:
    return "\n".join(
        [
            "Exit codes:",
            "  0  Success.",
            "  2  Contract error: untrusted or invalid baseline, invalid output",
            "     configuration, incompatible versions, or unreadable sources in",
            "     CI/gating mode.",
            "  3  Gating failure: new clones, threshold violations, or metrics",
            "     quality gate failures.",
            "  5  Internal error: unexpected exception.",
            "",
            f"Repository: {REPOSITORY_URL}",
            f"Issues:     {ISSUES_URL}",
            f"Docs:       {DOCS_URL}",
        ]
    )


__all__ = [
    "API_SURFACE_SIGNATURE_VERSION",
    "AUDIT_PROJECTION_VERSION",
    "AUTHORITY_ANALYSIS_REVISION",
    "AUTHORITY_REGISTRY_VERSION",
    "BASELINE_FINGERPRINT_VERSION",
    "BASELINE_LANE_DESCRIPTOR_VERSION",
    "BASELINE_LANE_DIGEST_DOMAIN",
    "BASELINE_ROOT_DIGEST_DOMAIN",
    "BASELINE_SCHEMA_VERSION",
    "CACHE_VERSION",
    "COHESION_RISK_MEDIUM_MAX",
    "COMPLEXITY_ALGORITHM_REVISION",
    "COMPLEXITY_RISK_LOW_MAX",
    "COMPLEXITY_RISK_MEDIUM_MAX",
    "CONTRACT_IR_VERSION",
    "CORPUS_AGENT_LABEL_CONTRACT_VERSION",
    "CORPUS_ANALYTICS_STORE_SCHEMA_VERSION",
    "CORPUS_CONTROL_PLANE_CONTRACT_VERSION",
    "CORPUS_EMBEDDING_CONTRACT_VERSION",
    "CORPUS_EXPORT_SCHEMA_VERSION",
    "CORPUS_NORMALIZER_VERSION",
    "CORPUS_PARTITION_MAP_VERSION",
    "CORPUS_PROFILE_MANIFEST_SCHEMA_VERSION",
    "CORPUS_REPRESENTATION_CONTRACT_VERSION",
    "COUPLING_RISK_LOW_MAX",
    "COUPLING_RISK_MEDIUM_MAX",
    "DEFAULT_BASELINE_PATH",
    "DEFAULT_BLOCK_MIN_LOC",
    "DEFAULT_BLOCK_MIN_STMT",
    "DEFAULT_COHESION_THRESHOLD",
    "DEFAULT_COMPLEXITY_THRESHOLD",
    "DEFAULT_COUPLING_THRESHOLD",
    "DEFAULT_COVERAGE_MIN",
    "DEFAULT_HEALTH_THRESHOLD",
    "DEFAULT_HTML_REPORT_PATH",
    "DEFAULT_JSON_REPORT_PATH",
    "DEFAULT_MARKDOWN_REPORT_PATH",
    "DEFAULT_MAX_BASELINE_SIZE_MB",
    "DEFAULT_MAX_CACHE_SIZE_MB",
    "DEFAULT_MIN_LOC",
    "DEFAULT_MIN_STMT",
    "DEFAULT_PROCESSES",
    "DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD",
    "DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD",
    "DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD",
    "DEFAULT_ROOT",
    "DEFAULT_SARIF_REPORT_PATH",
    "DEFAULT_SEGMENT_MIN_LOC",
    "DEFAULT_SEGMENT_MIN_STMT",
    "DEFAULT_TEXT_REPORT_PATH",
    "DESIGN_METRICS_ALGORITHM_REVISION",
    "DOCS_URL",
    "ENGINEERING_MEMORY_SCHEMA_VERSION",
    "EXPERIENCE_DISTILLATION_VERSION",
    "GATE_LANE_MATRIX_VERSION",
    "HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE",
    "HEALTH_COMPLEXITY_ELEVATED_WEIGHT",
    "HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE",
    "HEALTH_COMPLEXITY_EXTREME_WEIGHT",
    "HEALTH_COMPLEXITY_OUTLIER_SATURATION_MULTIPLE",
    "HEALTH_COMPLEXITY_OUTLIER_WEIGHT",
    "HEALTH_COMPLEXITY_TAIL_SATURATION_MULTIPLE",
    "HEALTH_COMPLEXITY_TYPICAL_WEIGHT",
    "HEALTH_COUPLING_ELEVATED_REFERENCE_PERMILLE",
    "HEALTH_COUPLING_ELEVATED_WEIGHT",
    "HEALTH_COUPLING_EXTREME_REFERENCE_PERMILLE",
    "HEALTH_COUPLING_EXTREME_WEIGHT",
    "HEALTH_COUPLING_OUTLIER_SATURATION_MULTIPLE",
    "HEALTH_COUPLING_OUTLIER_WEIGHT",
    "HEALTH_COUPLING_TAIL_SATURATION_MULTIPLE",
    "HEALTH_COUPLING_TYPICAL_WEIGHT",
    "HEALTH_DEPENDENCY_CYCLE_PENALTY",
    "HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER",
    "HEALTH_DEPENDENCY_DEPTH_LEVEL_PENALTY",
    "HEALTH_DEPENDENCY_DEPTH_P95_MARGIN",
    "HEALTH_INPUT_MANIFEST_VERSION",
    "HEALTH_WEIGHTS",
    "IDE_GOVERNANCE_PROTOCOL_VERSION",
    "ISSUES_URL",
    "LIVENESS_POLICY_VERSION",
    "MEMORY_PROJECTION_VERSION",
    "METRICS_BASELINE_SCHEMA_VERSION",
    "MODULE_IDENTITY_VERSION",
    "NEAR_MISS_ALGORITHM_REVISION",
    "NEAR_MISS_MAX_EDIT_STATEMENTS",
    "OBSERVATION_DIGEST_VERSION",
    "OBSERVER_VOCABULARY_VERSION",
    "PATCH_TRAIL_SCHEMA_VERSION",
    "PLATFORM_OBSERVABILITY_SCHEMA_VERSION",
    "PORTABLE_PATH_PROFILE_VERSION",
    "RENAMED_STRUCTURE_ALGORITHM_REVISION",
    "REPORT_ANALYSIS_FACTS_DIGEST_DOMAIN",
    "REPORT_COMPARISON_DIGEST_DOMAIN",
    "REPORT_ENVELOPE_DIGEST_DOMAIN",
    "REPORT_EVALUATION_DIGEST_DOMAIN",
    "REPORT_SCHEMA_VERSION",
    "REPOSITORY_URL",
    "SEMANTIC_EVENT_VERSION",
    "SEMANTIC_INDEX_FORMAT_VERSION",
    "SEMANTIC_PROJECTION_REVISION_VERSION",
    "SOURCE_KIND_POLICY_VERSION",
    "STATEMENT_REACHABILITY_POLICY_VERSION",
    "TRAJECTORY_PROJECTION_VERSION",
    "TRAJECTORY_PROJECTION_VERSION_V1",
    "TRAJECTORY_QUALITY_SCORE_VERSION",
    "WIRE_VERSION",
    "ExitCode",
    "cli_help_epilog",
]
