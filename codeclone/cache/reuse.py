# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Single source-content hit authority for cache reuse."""

from __future__ import annotations

import hashlib
from pathlib import Path
from time import perf_counter_ns
from typing import Literal

import orjson

from ..baseline.trust import current_python_tag
from ..contracts import (
    ADOPTION_COVERAGE_POLICY_VERSION,
    API_SURFACE_SIGNATURE_VERSION,
    COHESION_RISK_MEDIUM_MAX,
    COMPLEXITY_ALGORITHM_REVISION,
    COMPLEXITY_RISK_LOW_MAX,
    COMPLEXITY_RISK_MEDIUM_MAX,
    COUPLING_RISK_LOW_MAX,
    COUPLING_RISK_MEDIUM_MAX,
    DESIGN_METRICS_ALGORITHM_REVISION,
    FUNCTION_RELATIONSHIP_ALGORITHM_REVISION,
    LIVENESS_POLICY_VERSION,
    RENAMED_STRUCTURE_ALGORITHM_REVISION,
    RUNTIME_REACHABILITY_CATALOG_VERSION,
    SECURITY_SURFACE_CATALOG_VERSION,
    SEMANTIC_EVENT_VERSION,
    STATEMENT_REACHABILITY_POLICY_VERSION,
    STRUCTURAL_FINDINGS_CATALOG_VERSION,
    WIRE_VERSION,
)
from ..models import (
    CacheEntryV3,
    CacheLaneReuseReason,
    CacheLaneVerdict,
    CacheReuseDecision,
    ContentIdentityVerdict,
    DigestObject,
    FileStat,
    GitBlobIdentity,
    GitContentSnapshot,
    PythonModuleIdentity,
)

_BINDING_CONTEXT_DOMAIN = b"codeclone.cache.binding-context.v1\x00"
_NEUTRAL_PROFILE_DOMAIN = b"codeclone.cache.profile.neutral.v1\x00"
_DEPENDENT_PROFILE_DOMAIN = b"codeclone.cache.profile.dependent.v1\x00"
_DEPENDENCY_OBSERVATION_REVISION = "2"


def _profile_digest(
    *,
    domain: Literal[
        "codeclone.cache.profile.neutral.v1",
        "codeclone.cache.profile.dependent.v1",
    ],
    tag: bytes,
    payload: object,
) -> DigestObject:
    canonical = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    return DigestObject(
        domain=domain,
        algorithm="sha256",
        value=hashlib.sha256(tag + canonical).hexdigest(),
    )


def build_module_neutral_profile(
    *,
    fingerprint_version: str,
    min_loc: int,
    min_stmt: int,
    block_min_loc: int,
    block_min_stmt: int,
    segment_min_loc: int,
    segment_min_stmt: int,
) -> DigestObject:
    return _profile_digest(
        domain="codeclone.cache.profile.neutral.v1",
        tag=_NEUTRAL_PROFILE_DOMAIN,
        payload={
            "fingerprint_version": fingerprint_version,
            "block_min_loc": block_min_loc,
            "block_min_stmt": block_min_stmt,
            # The neutral payload is not only the fingerprint: one cached unit
            # row also carries the public cyclomatic_complexity and its risk
            # band, the unreachable-statement set, the renamed-structure digest
            # and the renamed token sequence, and the file's semantic facts ride
            # beside it. Each of those is the OUTPUT of an algorithm whose
            # generation is declared by a contracts constant, and a warm hit
            # serves the stored output verbatim - so the constant has to key
            # this digest or a bump is a bump of the report stamp only, with the
            # pre-bump values underneath it (X-02). Bump discipline that relies
            # on some neighbouring constant moving at the same time is not a
            # trigger: CACHE_VERSION rode along by accident once and hid exactly
            # this for a whole generation.
            "complexity_algorithm_revision": COMPLEXITY_ALGORITHM_REVISION,
            # The risk BAND is not a threshold read at report time: the band
            # classifies at extraction and the resulting word is stored as
            # units[].risk, which rehydrate_cache_neutral serves without
            # re-classifying. A recalibration is admitted only by an independent
            # blind benchmark (the score-change law), and an unkeyed lane would
            # spend that whole procedure on nothing - every warm-cache user
            # would keep the pre-move classification under the new
            # calibration's name. Keyed here rather than left to
            # COMPLEXITY_ALGORITHM_REVISION moving alongside: bands and counter
            # are separately governed, and "some neighbour will move too" is the
            # exact discipline X-02 found had never held (X-03).
            "complexity_risk_low_max": COMPLEXITY_RISK_LOW_MAX,
            "complexity_risk_medium_max": COMPLEXITY_RISK_MEDIUM_MAX,
            "min_loc": min_loc,
            "min_stmt": min_stmt,
            "normalization": "ast-normalizer-v2",
            "parser": "python-ast",
            "python_tag": current_python_tag(),
            "renamed_structure_algorithm_revision": (
                RENAMED_STRUCTURE_ALGORITHM_REVISION
            ),
            "segment_algorithm": "stmt-window-v1",
            "segment_min_loc": segment_min_loc,
            "segment_min_stmt": segment_min_stmt,
            "semantic_event_version": SEMANTIC_EVENT_VERSION,
            "statement_reachability_policy_version": (
                STATEMENT_REACHABILITY_POLICY_VERSION
            ),
            # v3 (39Y Y5): unit facts are emitted for every defined function
            # instead of only clone-eligible ones. Entries written by v2 carry
            # the smaller population, so they must not be reused as-is.
            "unit_algorithm": "cfg-fingerprint-v3",
            # The canonical wire is the preimage of every stored fingerprint and
            # of every stored statement token, and its own generation does not
            # appear in those digests' domains. Binding it here is what makes a
            # wire generation independent of BASELINE_FINGERPRINT_VERSION
            # instead of dependent on the two being bumped together by hand.
            "wire_version": WIRE_VERSION,
        },
    )


def build_module_dependent_profile(
    *,
    neutral_profile: DigestObject,
    module_manifest_digest: DigestObject,
    collect_api_surface: bool,
) -> DigestObject:
    return _profile_digest(
        domain="codeclone.cache.profile.dependent.v1",
        tag=_DEPENDENT_PROFILE_DOMAIN,
        payload={
            # typing_coverage and docstring_coverage are counted at extraction
            # by metrics/adoption.py and rehydrated verbatim - a warm run
            # re-reads no annotation and no docstring - so the policy deciding
            # what those counters count has to key this lane. The producer
            # imports no contracts constant of its own, which is why nothing
            # here moved when the policy did: the counters had no declaring
            # generation at all until this constant existed (X-04).
            "adoption_coverage_policy_version": ADOPTION_COVERAGE_POLICY_VERSION,
            "api_surface": collect_api_surface,
            "api_surface_signature_version": API_SURFACE_SIGNATURE_VERSION,
            "call_resolution_version": "1",
            # The coupling and cohesion bands classify at extraction exactly as
            # the complexity band does on the neutral lane, and their words are
            # stored as class_metrics[].risk_coupling / .risk_cohesion. They ride
            # THIS lane only, so a band move re-derives the class rows and leaves
            # the fingerprints, complexity and reachability of a still-correct
            # warm cache alone (X-03).
            "cohesion_risk_medium_max": COHESION_RISK_MEDIUM_MAX,
            "coupling_risk_low_max": COUPLING_RISK_LOW_MAX,
            "coupling_risk_medium_max": COUPLING_RISK_MEDIUM_MAX,
            "dependency_observation_revision": _DEPENDENCY_OBSERVATION_REVISION,
            # class_metrics (cbo, lcom4, coupling/cohesion risk) ride the
            # dependent lane, and their values are a function of the
            # design-metrics algorithm revision. That revision only reaches this
            # digest transitively today, through the embedded neutral_profile;
            # binding it directly means a design-metrics revision that does NOT
            # coincide with a neutral-lane change still misses exactly this lane
            # instead of serving stale cbo/lcom4/risk off a warm hit.
            "design_metrics_algorithm_revision": DESIGN_METRICS_ALGORITHM_REVISION,
            # function_relationship_facts - the per-function call and reference
            # records with their resolved targets - ride this lane and are
            # rehydrated verbatim, so the revision governing which expressions
            # become records and what they resolve to keys it here. Same hole as
            # the adoption counters above: analysis/_module_walk.py imports no
            # contracts constant, so the facts had no declaring generation and
            # the anonymous "call_resolution_version" literal beside them is
            # reachable from no producer (X-04).
            "function_relationship_algorithm_revision": (
                FUNCTION_RELATIONSHIP_ALGORITHM_REVISION
            ),
            # The dependent lane carries referenced_qualnames, dead candidates
            # and live-root reasons - everything the liveness verdict reads -
            # so a liveness policy bump must miss exactly this lane, never the
            # neutral fingerprint lane.
            "liveness_policy_version": LIVENESS_POLICY_VERSION,
            "module_manifest_digest": module_manifest_digest.value,
            "neutral_profile": neutral_profile.value,
            "resolver_version": "2",
            # Closed detector catalogs whose EXPANSION changes an emitted
            # dependent-lane fact for unchanged source (a new security-surface
            # sink, a new reachability framework, a new structural finding kind).
            # Each rides this lane only, so its catalog version must move the
            # digest or a warm hit serves the pre-expansion result as an
            # honest-absence false negative.
            "runtime_reachability_catalog_version": (
                RUNTIME_REACHABILITY_CATALOG_VERSION
            ),
            "security_surface_catalog_version": SECURITY_SURFACE_CATALOG_VERSION,
            "structural_findings_catalog_version": (
                STRUCTURAL_FINDINGS_CATALOG_VERSION
            ),
        },
    )


def binding_context_digest(module: PythonModuleIdentity | None) -> DigestObject:
    """Digest the binding-context inputs that are not in the file's own bytes.

    Every binding fact the scope graph needs is read from the source itself,
    with one exception: a relative import resolves through the importing
    module's package position. Move the same bytes to a different mount and the
    resolved identity changes, so the fingerprint changes while the content
    digest does not. That difference has to be part of the cache key, or a warm
    run answers with the other mount's fingerprint (39Y-FP section 3a).
    """

    payload: object = (
        None
        if module is None
        else {
            "is_package": module.is_package,
            "module": module.module,
            "mount_path": module.mount_path,
            "package": module.package,
        }
    )
    canonical = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    return DigestObject(
        domain="codeclone.cache.binding-context.v1",
        algorithm="sha256",
        value=hashlib.sha256(_BINDING_CONTEXT_DOMAIN + canonical).hexdigest(),
    )


def cache_reuse_decision(
    *,
    content: ContentIdentityVerdict,
    entry: CacheEntryV3,
    neutral_profile: DigestObject,
    dependent_profile: DigestObject,
    binding_context: DigestObject,
) -> CacheReuseDecision:
    if not content.hit:
        miss = CacheLaneVerdict(hit=False, reason="content_miss")
        return CacheReuseDecision(neutral=miss, dependent=miss)
    # The neutral lane carries the units, and a unit's fingerprint is a
    # function of (AST x binding context). The same bytes under a moved mount
    # describe a different function, so the binding context gates this lane
    # beside the profile. The dependent lane already keys on the whole module
    # manifest, which moves whenever any module identity does.
    binding_hit = entry.binding_context_digest == binding_context
    neutral_hit = entry.module_neutral_profile == neutral_profile and binding_hit
    dependent_hit = entry.module_dependent_profile == dependent_profile
    neutral_reason: CacheLaneReuseReason = "hit"
    if not binding_hit:
        neutral_reason = "binding_context_mismatch"
    elif not neutral_hit:
        neutral_reason = "neutral_profile_mismatch"
    return CacheReuseDecision(
        neutral=CacheLaneVerdict(hit=neutral_hit, reason=neutral_reason),
        dependent=CacheLaneVerdict(
            hit=dependent_hit,
            reason="hit" if dependent_hit else "dependent_profile_mismatch",
        ),
    )


def source_content_digest(raw_source: bytes) -> DigestObject:
    return DigestObject(
        domain="codeclone.source-content.v1",
        algorithm="sha256",
        value=hashlib.sha256(raw_source).hexdigest(),
    )


def git_blob_identity_for_parsed_source(
    *,
    path: Path,
    source_digest: DigestObject,
    git_snapshot: GitContentSnapshot,
) -> GitBlobIdentity | None:
    tracked = git_snapshot.tracked_content(path)
    if tracked is None or git_snapshot.fallback_reason(path) is not None:
        return None
    if tracked.source_content_digest != source_digest:
        return None
    return tracked.blob


def prove_cached_source_identity(
    *,
    path: Path,
    entry: CacheEntryV3,
    current_stat: FileStat,
    git_snapshot: GitContentSnapshot,
) -> ContentIdentityVerdict:
    """Prove one hit from current bytes; envelope/stat alone never authorize it."""

    if current_stat != entry.stat:
        return ContentIdentityVerdict(
            hit=False,
            reason="stat_mismatch",
            git_fallback_reason=None,
            digest_verify_cost_us=0,
            stat_fast_reject=True,
        )

    fallback_reason = git_snapshot.fallback_reason(path)
    tracked = git_snapshot.tracked_content(path)
    expected_blob = entry.git_blob_id_at_write
    if (
        fallback_reason is None
        and tracked is not None
        and expected_blob is not None
        and tracked.blob == expected_blob
    ):
        return ContentIdentityVerdict(
            hit=True,
            reason="blob_hit",
            git_fallback_reason=None,
            digest_verify_cost_us=0,
            stat_fast_reject=False,
        )

    started = perf_counter_ns()
    try:
        current_digest = source_content_digest(path.read_bytes())
    except OSError:
        current_digest = None
    elapsed_us = max(0, (perf_counter_ns() - started) // 1_000)
    hit = current_digest is not None and current_digest == entry.source_content_digest
    return ContentIdentityVerdict(
        hit=hit,
        reason="digest_hit" if hit else "digest_miss",
        git_fallback_reason=fallback_reason,
        digest_verify_cost_us=elapsed_us,
        stat_fast_reject=False,
    )


__all__ = [
    "binding_context_digest",
    "build_module_dependent_profile",
    "build_module_neutral_profile",
    "cache_reuse_decision",
    "git_blob_identity_for_parsed_source",
    "prove_cached_source_identity",
    "source_content_digest",
]
