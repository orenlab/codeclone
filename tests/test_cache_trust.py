# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Red-first trust laws for the cache persistence layer.

These pin three asserted persistence.trust review claims (Enacta @ ae8b4abf)
with executable evidence, not prose:

* Candidate 1 - the envelope ``v`` (the generation gate) must live inside the
  signed scope, so a migration/backup that rewrites ``v`` without re-signing is
  refused instead of trusted.
* Candidate 2 - the module-dependent reuse profile must be a function of every
  detector policy whose change can move a dependent-lane fact. The
  design-metrics algorithm revision is proven here; the closed-catalog families
  (security surfaces, runtime reachability) are pinned as documented,
  still-open gaps that need an owner-created contracts constant.
* Candidate 3 - the cache "signature" is a keyless checksum. This pins the
  CURRENT behavior (a hand-forged valid checksum is accepted) so the keyless
  nature is on the record while the vocabulary fork is an owner decision.

The last section generalizes candidate 2 from four named constants into the
class law they are instances of (X-02): a bump of ANY revision whose output is
stored in a cache payload must miss exactly the lane carrying that output.
X-03 then widens WHO the law is asked of: from a family recognised by the
spelling of its name to every constant of the contracts ring, because the
calibrated risk bands - whose verdict word IS a stored payload field - are not
spelled like a revision and rode a warm hit unnoticed.
"""

from __future__ import annotations

import copy
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Final, cast

import pytest

import codeclone.cache.reuse as cache_reuse
import codeclone.contracts as contracts
from codeclone.cache.integrity import cache_envelope_checksum
from codeclone.cache.reuse import (
    build_module_dependent_profile,
    build_module_neutral_profile,
)
from codeclone.cache.store import Cache
from codeclone.cache.versioning import CacheStatus
from codeclone.metrics.cohesion import cohesion_risk
from codeclone.metrics.complexity import risk_level
from codeclone.metrics.coupling import coupling_risk
from codeclone.models import DigestObject
from codeclone.paths.module_identity.manifest import build_module_identity_manifest
from tests.test_cache import (
    _bind_module_paths,
    _content_hit_decision,
    _load_cache_entry,
    _save_single_cache_entry,
)

_NEUTRAL = DigestObject(
    domain="codeclone.cache.profile.neutral.v1",
    algorithm="sha256",
    value="1" * 64,
)
_MANIFEST = DigestObject(
    domain="codeclone.module-registry.v1",
    algorithm="sha256",
    value="a" * 64,
)


def _reload_with_forged_envelope(
    cache_path: Path, mutate: Callable[[dict[str, object]], None]
) -> Cache:
    """Read the on-disk envelope, let a test forge it, then reload the cache."""

    raw = cast(dict[str, object], json.loads(cache_path.read_text("utf-8")))
    mutate(raw)
    cache_path.write_text(json.dumps(raw), "utf-8")
    loaded = Cache(cache_path, root=cache_path.parent)
    loaded.load()
    return loaded


def _dependent_profile_digest_under(
    monkeypatch: pytest.MonkeyPatch, policy_version_name: str
) -> tuple[str, str]:
    """Digest the dependent profile before/after shifting one policy version.

    A shift that the profile binds moves the digest; one it ignores (or a
    version name the profile never imports) does not. Missing names raise on
    ``setattr``, which the caller pins as a still-open gap.
    """

    baseline = build_module_dependent_profile(
        neutral_profile=_NEUTRAL,
        module_manifest_digest=_MANIFEST,
        collect_api_surface=False,
    )
    monkeypatch.setattr(cache_reuse, policy_version_name, "999")
    shifted = build_module_dependent_profile(
        neutral_profile=_NEUTRAL,
        module_manifest_digest=_MANIFEST,
        collect_api_surface=False,
    )
    return baseline.value, shifted.value


# --------------------------------------------------------------------------- #
# Candidate 1 - envelope ``v`` must be inside the signed scope.
# --------------------------------------------------------------------------- #


def test_cache_envelope_v_is_inside_signed_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rewriting only top-level ``v`` (payload/sig byte-identical) must fail.

    The review predicts the pre-fix code returns OK with fully decoded records:
    the sig covers only ``payload`` and ``v`` is compared before the sig check,
    so a runtime whose generation gate equals the forged mark trusts a payload
    it never signed under that mark. That is exactly the migration / backup /
    edit-in-place desync candidate 1 names.

    Cross-defect witness (Enacta): this test asserts one half of what was a
    coupled pair. The envelope-``v`` defect existed as the product of an unsigned
    ``v`` AND the ``{11, 17}`` unit-row decode tolerance in ``_wire_decode``;
    Wave D independently closed that other half by widening the row and decoding
    it strictly (``valid_lengths={18}``), so the tolerance no longer survives.
    Candidate 1 closes the ``v``-signing half here, and it is not redundant with
    the ``v == CACHE_VERSION`` gate on its own: the gate rejects a *wrong* ``v``,
    but only the signed scope rejects a ``v`` retagged to match the running
    generation while the payload stays byte-identical -- exactly the
    migration/backup/edit-in-place desync this test forges (the mutation run
    proves this pin goes red).
    """

    cache_path = tmp_path / "cache.json"
    _save_single_cache_entry(cache_path)

    genuine_mark = cast(str, json.loads(cache_path.read_text("utf-8"))["v"])
    forged_mark = f"{genuine_mark}-migrated"

    # Load with a runtime whose generation gate equals the forged mark, so the
    # version gate passes and only the signed scope can catch the desync.
    monkeypatch.setattr(Cache, "_CACHE_VERSION", forged_mark)
    # Tamper ONLY the generation gate; payload and sig stay byte-identical.
    loaded = _reload_with_forged_envelope(
        cache_path, lambda raw: raw.__setitem__("v", forged_mark)
    )

    assert loaded.load_status is CacheStatus.INTEGRITY_FAILED


def test_cache_envelope_checksum_binds_the_generation_gate() -> None:
    """The narrow form: the signed digest must change when ``v`` changes.

    Two envelopes differing only in ``v`` must not share a signature. Pre-fix
    there is no envelope signer that takes ``v`` at all (the input does not
    exist); post-fix the digest binds it.
    """

    payload = {"py": "cp314", "fp": "3", "files": {}}
    assert cache_envelope_checksum("3.4", payload) != cache_envelope_checksum(
        "3.5", payload
    )


# --------------------------------------------------------------------------- #
# Candidate 2 - the dependent profile must version every guarded policy.
# --------------------------------------------------------------------------- #


def test_dependent_profile_versions_design_metrics_algorithm_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """class_metrics (cbo/lcom4/risk) ride the dependent lane; a design-metrics
    algorithm-revision bump must move the dependent-profile digest, or a warm
    hit serves stale metrics values.

    Pre-fix ``build_module_dependent_profile`` neither imports nor consumes
    ``DESIGN_METRICS_ALGORITHM_REVISION``, so this is red immediately.
    """

    baseline, shifted = _dependent_profile_digest_under(
        monkeypatch, "DESIGN_METRICS_ALGORITHM_REVISION"
    )
    assert baseline != shifted


def test_dependent_profile_versions_security_surface_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The security_surfaces category/scope/mode/evidence catalogs
    (analysis/security_surfaces.py) are closed, mutable and ride the dependent
    lane. Expanding one (a new sink category) with a warm hit would serve stale
    security facts as an honest-absence false negative. The catalog version must
    move the digest."""

    baseline, shifted = _dependent_profile_digest_under(
        monkeypatch, "SECURITY_SURFACE_CATALOG_VERSION"
    )
    assert baseline != shifted


def test_dependent_profile_versions_runtime_reachability_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runtime_reachability framework/edge/method catalogs
    (analysis/reachability.py) are closed, mutable and ride the dependent lane.
    Adding a framework with a warm hit would serve stale liveness roots. The
    catalog version must move the digest."""

    baseline, shifted = _dependent_profile_digest_under(
        monkeypatch, "RUNTIME_REACHABILITY_CATALOG_VERSION"
    )
    assert baseline != shifted


def test_dependent_profile_versions_structural_findings_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The structural finding-kind catalog (domain/findings.py) is closed,
    mutable and rides the dependent lane. Adding a detector kind with a warm hit
    would serve stale structural findings. The catalog version must move the
    digest."""

    baseline, shifted = _dependent_profile_digest_under(
        monkeypatch, "STRUCTURAL_FINDINGS_CATALOG_VERSION"
    )
    assert baseline != shifted


# --------------------------------------------------------------------------- #
# X-04 - the facts whose owner did not exist.
#
# X-02 and X-03 widened WHO the law is asked of, up to every public constant of
# the contracts ring. That membership rule is mechanical and it is still blind
# in one direction: the registry classifies constants, so a stored fact whose
# generation NO constant declares is invisible to it. Two dependent-lane fact
# families were in exactly that state - their producers
# (``codeclone/metrics/adoption.py``, ``codeclone/analysis/_module_walk.py``)
# import no contracts constant at all, so there was nothing to classify and
# nothing a bump could move.
#
# Measured before the fix, through the real CLI on a two-file repository:
# changing what ``_function_param_rows`` counts as a parameter moved the
# reported adoption from 57.1% to 66.7% on a cold run and left the warm run at
# 57.1%; dropping bare references from the relationship walk moved the stored
# record count from 2 to 1 cold and left it at 2 warm. Same code, same source,
# two different answers decided by cache state alone.
# --------------------------------------------------------------------------- #


def test_dependent_profile_versions_adoption_coverage_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``typing_coverage`` / ``docstring_coverage`` ride the dependent lane.

    What counts as an annotated parameter, an ``Any`` annotation or a documented
    public symbol is decided at extraction by ``metrics/adoption.py``, and the
    resulting counters are stored per module and rehydrated verbatim - they are
    the whole input of the ``adoption_counts`` observation lane and of the
    typing/docstring gates. The producer imports no contracts constant, so
    before this constant existed a policy change was invisible to every warm
    cache: the pre-change percentages were served under the new policy's name.
    """

    baseline, shifted = _dependent_profile_digest_under(
        monkeypatch, "ADOPTION_COVERAGE_POLICY_VERSION"
    )
    assert baseline != shifted


def test_dependent_profile_versions_function_relationship_algorithm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``function_relationship_facts`` rides the dependent lane.

    Which call and reference expressions become relationship records, and how
    each one resolves to a target qualname, is decided at extraction by
    ``analysis/_module_walk.py``; the records are stored per source function and
    rehydrated verbatim into the dead-code test-reference lane and the call
    graph. Same shape as the adoption family above and the same pre-fix hole:
    the producer imports no contracts constant, so no bump could miss the lane
    the facts ride.
    """

    baseline, shifted = _dependent_profile_digest_under(
        monkeypatch, "FUNCTION_RELATIONSHIP_ALGORITHM_REVISION"
    )
    assert baseline != shifted


# --------------------------------------------------------------------------- #
# Candidate 3 - the cache checksum is keyless: integrity, not authentication
# (owner ruling option a - the vocabulary now tells that truth).
# --------------------------------------------------------------------------- #


def test_cache_checksum_is_keyless_not_authentication(
    tmp_path: Path,
) -> None:
    """Pin the CURRENT behavior: a hand-forged valid checksum is accepted.

    An actor with only the public payload and the public algorithm - no secret
    material of any kind - injects a cached fact and re-mints a checksum that the
    loader accepts. This proves the mechanism is a checksum (catches accidental
    corruption) and not authentication (nothing an attacker cannot reproduce),
    which is exactly why the owner ruling renames the vocabulary rather than
    adding a key: cache trust equals source trust, so a key would buy nothing.
    It stays keyless after candidate 1: binding ``v`` into the checksummed scope
    changes WHAT is summed, not that the sum needs a secret; the forgery here
    re-mints over the current public envelope algorithm.
    """

    cache_path = tmp_path / "cache.json"
    _save_single_cache_entry(cache_path)

    def forge(raw: dict[str, object]) -> None:
        payload = cast(dict[str, object], raw["payload"])
        files = cast(dict[str, object], payload["files"])
        (genuine_key,) = tuple(files)
        # Inject a cached fact with no key, no secret - just the public payload.
        files["forged.py"] = copy.deepcopy(files[genuine_key])
        # Re-mint the checksum from the public algorithm alone (keyless).
        raw["checksum"] = cache_envelope_checksum(cast(str, raw["v"]), payload)

    loaded = _reload_with_forged_envelope(cache_path, forge)

    assert loaded.load_status is CacheStatus.OK
    assert loaded.get_file_entry("forged.py") is not None


def test_cache_integrity_vocabulary_is_checksum_not_signature() -> None:
    """Owner ruling (option a): the cache dir carries the SAME trust as the
    analyzed source, so a keyed signature buys nothing against a local adversary
    who already controls the source; the real guarantee is integrity against
    accidental desync. The vocabulary must tell that truth - checksum names, no
    signature names, and a durable threat-model note forbidding a re-introduced
    keyed signature."""

    import codeclone.cache.integrity as integ

    assert hasattr(integ, "cache_payload_checksum")
    assert hasattr(integ, "cache_envelope_checksum")
    assert hasattr(integ, "verify_cache_payload_checksum")
    assert hasattr(integ, "verify_cache_envelope_checksum")
    # The misleading signature vocabulary is gone (it claimed no authenticity).
    for retired in (
        "sign_cache_payload",
        "sign_cache_envelope",
        "verify_cache_payload_signature",
        "verify_cache_envelope_signature",
    ):
        assert not hasattr(integ, retired), retired
    # The threat-model note is durable in source.
    source = Path(integ.__file__).read_text("utf-8").lower()
    assert "cache trust equals source trust" in source
    assert "not authentication" in source


# --------------------------------------------------------------------------- #
# X-02 - the class law behind candidate 2.
#
# Candidate 2 pinned four named constants one test each. That form cannot catch
# the NEXT unbound revision, and it did not: the neutral lane carries the whole
# per-unit payload (complexity, statement reachability, renamed structure,
# semantic facts) and was an input of no algorithm revision at all, so a
# complexity recalibration served pre-recalibration values off a warm hit while
# stamping the new revision on the report. The bump discipline that was supposed
# to prevent it works only because an unrelated CACHE_VERSION bump happened to
# ride along - success under the neighbour.
#
# The law, stated once and enforced over the whole constant family:
#
#   A contracts constant whose OUTPUT IS STORED in a cache payload must be an
#   input of that payload's reuse profile. A constant with no stored output
#   must NOT be an input of either profile - over-invalidation throws away a
#   warm cache that is still correct, which is a defect in the other direction.
#
# X-03 - who the law is asked of.
#
# X-02 asked it of a family recognised by name: anything spelled with VERSION,
# REVISION, SCHEMA, CATALOG or POLICY. That rule covered 49 of the 110 constants
# in ``codeclone.contracts``, and the 61 it left out were assumed to be paths,
# URLs and option defaults. Five of them were not. The calibrated risk bands
# (COMPLEXITY_RISK_*_MAX, COUPLING_RISK_*_MAX, COHESION_RISK_MEDIUM_MAX) are the
# producers of ``units[].risk`` and ``class_metrics[].risk_coupling`` /
# ``risk_cohesion`` - stored payload fields, served verbatim off a warm hit - so
# a recalibration of a band left every warm-cache user's risk classification
# exactly as it was, under the new calibration's name. The score-change law
# admits a band move only after an independent blind benchmark; a silent warm
# lane would spend that whole procedure on nothing.
#
# So the membership rule is no longer a spelling. The question is asked of EVERY
# public constant of the contracts ring, which is the only mechanical rule that
# asks it of the constants nobody thought to name like a revision. (Limitation
# stated on purpose: a generation constant defined outside ``contracts`` is out
# of this registry's reach - ``CLAUDE.md`` requires them to live here, and
# ``_DEPENDENCY_OBSERVATION_REVISION`` is deliberately local to the profile
# module it keys.)
# --------------------------------------------------------------------------- #

#: Cache payload lanes (``CacheEntryV3.module_neutral`` / ``module_dependent``).
_LANE_NEUTRAL: Final = "neutral"
_LANE_DEPENDENT: Final = "dependent"
#: Not a direct profile input: carried into the dependent profile by the module
#: manifest digest, which the profile already consumes.
_LANE_MODULE_MANIFEST: Final = "module_manifest"
#: Not a direct profile input either, and for a sharper reason: the constant is
#: the DEFAULT of an analysis option, and what the profile binds is the option
#: value in force. Wiring the default itself would key the cache on a number the
#: run may not be using. The reason column names the profile input that carries
#: it, and the test below proves that input moves the digest.
_LANE_EFFECTIVE_CONFIG: Final = "effective_config"
#: Nothing this constant produces is stored in a cache payload.
_LANE_NONE: Final = "none"

#: Every public constant of ``codeclone.contracts``, classified by the cache
#: lane carrying its output.
_CACHE_LANE_BY_CONSTANT: Final[dict[str, tuple[str, str]]] = {
    # ── neutral lane · CacheNeutralPayload: units, blocks, segments, semantics
    "BASELINE_FINGERPRINT_VERSION": (_LANE_NEUTRAL, "units[].fingerprint"),
    "COMPLEXITY_ALGORITHM_REVISION": (
        _LANE_NEUTRAL,
        "units[].cyclomatic_complexity and units[].risk are the source-decision "
        "counter's output and are served verbatim off a warm hit (X-02)",
    ),
    "COMPLEXITY_RISK_LOW_MAX": (
        _LANE_NEUTRAL,
        "units[].risk IS this band's verdict word: metrics.complexity.risk_level "
        "classifies at extraction and rehydrate_cache_neutral serves the stored "
        "word without re-classifying (X-03)",
    ),
    "COMPLEXITY_RISK_MEDIUM_MAX": (
        _LANE_NEUTRAL,
        "units[].risk IS this band's verdict word: metrics.complexity.risk_level "
        "classifies at extraction and rehydrate_cache_neutral serves the stored "
        "word without re-classifying (X-03)",
    ),
    "RENAMED_STRUCTURE_ALGORITHM_REVISION": (
        _LANE_NEUTRAL,
        "units[].renamed_fingerprint and units[].renamed_statement_sequence are "
        "digested in domains that embed this revision",
    ),
    "SEMANTIC_EVENT_VERSION": (
        _LANE_NEUTRAL,
        "semantic_facts.events and .function_contract_summaries ride the neutral "
        "payload",
    ),
    "STATEMENT_REACHABILITY_POLICY_VERSION": (
        _LANE_NEUTRAL,
        "units[].unreachable_statements is the policy's verdict set",
    ),
    "WIRE_VERSION": (
        _LANE_NEUTRAL,
        "the canonical wire is the preimage of units[].fingerprint and of the "
        "near-miss statement tokens; both are stored",
    ),
    # ── dependent lane · CacheDependentPayload
    "ADOPTION_COVERAGE_POLICY_VERSION": (
        _LANE_DEPENDENT,
        "typing_coverage and docstring_coverage: what counts as an annotated "
        "parameter, an Any annotation and a documented public symbol is decided "
        "at extraction and the counters are rehydrated verbatim (X-04)",
    ),
    "API_SURFACE_SIGNATURE_VERSION": (_LANE_DEPENDENT, "api_surface"),
    "COHESION_RISK_MEDIUM_MAX": (
        _LANE_DEPENDENT,
        "class_metrics[].risk_cohesion IS this band's verdict word: "
        "analysis.class_metrics classifies at extraction and the cache row is "
        "rehydrated without re-classifying (X-03)",
    ),
    "COUPLING_RISK_LOW_MAX": (
        _LANE_DEPENDENT,
        "class_metrics[].risk_coupling IS this band's verdict word: "
        "analysis.class_metrics classifies at extraction and the cache row is "
        "rehydrated without re-classifying (X-03)",
    ),
    "COUPLING_RISK_MEDIUM_MAX": (
        _LANE_DEPENDENT,
        "class_metrics[].risk_coupling IS this band's verdict word: "
        "analysis.class_metrics classifies at extraction and the cache row is "
        "rehydrated without re-classifying (X-03)",
    ),
    "DESIGN_METRICS_ALGORITHM_REVISION": (
        _LANE_DEPENDENT,
        "class_metrics (cbo, lcom4, coupling/cohesion risk)",
    ),
    "FUNCTION_RELATIONSHIP_ALGORITHM_REVISION": (
        _LANE_DEPENDENT,
        "function_relationship_facts: which call and reference expressions "
        "become records, and the qualname each resolves to, are decided at "
        "extraction and the records are rehydrated verbatim (X-04)",
    ),
    "LIVENESS_POLICY_VERSION": (
        _LANE_DEPENDENT,
        "dead_candidates, referenced_qualnames and live-root reasons",
    ),
    "RUNTIME_REACHABILITY_CATALOG_VERSION": (_LANE_DEPENDENT, "runtime_reachability"),
    "SECURITY_SURFACE_CATALOG_VERSION": (_LANE_DEPENDENT, "security_surfaces"),
    "STRUCTURAL_FINDINGS_CATALOG_VERSION": (_LANE_DEPENDENT, "structural_findings"),
    # ── carried into the dependent profile by module_manifest_digest
    "MODULE_IDENTITY_VERSION": (
        _LANE_MODULE_MANIFEST,
        "inside the module identity manifest, whose digest the dependent "
        "profile already consumes",
    ),
    # ── carried by the option value in force; the reason names the profile
    #    input, and the test below proves that input moves the digest
    "DEFAULT_BLOCK_MIN_LOC": (_LANE_EFFECTIVE_CONFIG, "block_min_loc"),
    "DEFAULT_BLOCK_MIN_STMT": (_LANE_EFFECTIVE_CONFIG, "block_min_stmt"),
    "DEFAULT_MIN_LOC": (_LANE_EFFECTIVE_CONFIG, "min_loc"),
    "DEFAULT_MIN_STMT": (_LANE_EFFECTIVE_CONFIG, "min_stmt"),
    "DEFAULT_SEGMENT_MIN_LOC": (_LANE_EFFECTIVE_CONFIG, "segment_min_loc"),
    "DEFAULT_SEGMENT_MIN_STMT": (_LANE_EFFECTIVE_CONFIG, "segment_min_stmt"),
    # ── no stored output: computed per run OVER cached facts, never stored
    "AUTHORITY_ANALYSIS_REVISION": (_LANE_NONE, "aggregate authority pass, post-cache"),
    "AUTHORITY_REGISTRY_VERSION": (_LANE_NONE, "aggregate authority pass, post-cache"),
    "BASELINE_LANE_DESCRIPTOR_VERSION": (_LANE_NONE, "baseline lane descriptor"),
    "CANONICAL_MODEL_REVISION": (
        _LANE_NONE,
        "canonical semantic model (F-3); no cache payload stores its output — "
        "the run-store backend owns persistence from wave 2 on",
    ),
    "CANONICAL_WIRE_REVISION": (
        _LANE_NONE,
        "canonical JSON vNext wire grammar; an export projection, never a "
        "cache payload",
    ),
    "CONTRACT_IR_VERSION": (_LANE_NONE, "IR is built per run from cached summaries"),
    "STORAGE_SCHEMA_REVISION": (
        _LANE_NONE,
        "canonical run-store SQLite schema (wave 2); a separate persistence "
        "boundary by law — never a cache payload, and the cache is never "
        "required to reconstruct a published run",
    ),
    "GATE_LANE_MATRIX_VERSION": (_LANE_NONE, "gate projection, post-cache"),
    "HEALTH_INPUT_MANIFEST_VERSION": (_LANE_NONE, "health projection, post-cache"),
    "NEAR_MISS_ALGORITHM_REVISION": (
        _LANE_NONE,
        "governs what is COMPUTED OVER the stored statement tokens, never the "
        "tokens: their domain moves with RENAMED_STRUCTURE_ALGORITHM_REVISION "
        "(analysis/renamed_structure.py) and with the wire, both of which are "
        "neutral-lane inputs above",
    ),
    "OBSERVATION_DIGEST_VERSION": (
        _LANE_NONE,
        "observation lane digest, computed per run from facts",
    ),
    "OBSERVER_VOCABULARY_VERSION": (_LANE_NONE, "runtime observability vocabulary"),
    # ── no stored output: artifact/store schemas outside the analysis cache
    "AUDIT_PROJECTION_VERSION": (_LANE_NONE, "memory projection"),
    "BASELINE_SCHEMA_VERSION": (_LANE_NONE, "baseline artifact schema"),
    "CACHE_VERSION": (
        _LANE_NONE,
        "the cache's own generation gate: it rejects the whole envelope before "
        "any profile is consulted (see the version-mismatch tests above), so "
        "adding it to a profile would be a second, weaker copy of that gate",
    ),
    "CORPUS_AGENT_LABEL_CONTRACT_VERSION": (_LANE_NONE, "corpus analytics store"),
    "CORPUS_ANALYTICS_STORE_SCHEMA_VERSION": (_LANE_NONE, "corpus analytics store"),
    "CORPUS_CONTROL_PLANE_CONTRACT_VERSION": (_LANE_NONE, "corpus analytics store"),
    "CORPUS_EMBEDDING_CONTRACT_VERSION": (_LANE_NONE, "corpus analytics store"),
    "CORPUS_EXPORT_SCHEMA_VERSION": (_LANE_NONE, "corpus analytics store"),
    "CORPUS_NORMALIZER_VERSION": (_LANE_NONE, "corpus analytics store"),
    "CORPUS_PARTITION_MAP_VERSION": (_LANE_NONE, "corpus analytics store"),
    "CORPUS_PROFILE_MANIFEST_SCHEMA_VERSION": (_LANE_NONE, "corpus analytics store"),
    "CORPUS_REPRESENTATION_CONTRACT_VERSION": (_LANE_NONE, "corpus analytics store"),
    "ENGINEERING_MEMORY_SCHEMA_VERSION": (_LANE_NONE, "memory store schema"),
    "EXPERIENCE_DISTILLATION_VERSION": (_LANE_NONE, "memory projection"),
    "IDE_GOVERNANCE_PROTOCOL_VERSION": (_LANE_NONE, "IDE attestation protocol"),
    "MEMORY_PROJECTION_VERSION": (_LANE_NONE, "memory projection"),
    "METRICS_BASELINE_SCHEMA_VERSION": (_LANE_NONE, "metrics artifact stamp"),
    "PATCH_TRAIL_SCHEMA_VERSION": (_LANE_NONE, "audit artifact schema"),
    "PLATFORM_OBSERVABILITY_SCHEMA_VERSION": (_LANE_NONE, "observability store"),
    "REPORT_SCHEMA_VERSION": (_LANE_NONE, "report artifact schema"),
    "SEMANTIC_INDEX_FORMAT_VERSION": (_LANE_NONE, "memory semantic index"),
    "SEMANTIC_PROJECTION_REVISION_VERSION": (_LANE_NONE, "memory semantic index"),
    "TRAJECTORY_PROJECTION_VERSION": (_LANE_NONE, "memory projection"),
    "TRAJECTORY_PROJECTION_VERSION_V1": (_LANE_NONE, "memory projection"),
    "TRAJECTORY_QUALITY_SCORE_VERSION": (_LANE_NONE, "memory projection"),
    # ── no stored output: report-wire vocabulary, spelled into a document the
    #    report layer builds after the cache is read. The cache stores units,
    #    blocks, segments and semantic facts; which family a group belongs to
    #    and which kind it declares are decided when the report document is
    #    assembled, so none of these names reaches a stored payload.
    "CLONE_KIND_BLOCK": (_LANE_NONE, "report-wire clone kind, post-cache"),
    "CLONE_KIND_FUNCTION": (_LANE_NONE, "report-wire clone kind, post-cache"),
    "CLONE_KIND_SEGMENT": (_LANE_NONE, "report-wire clone kind, post-cache"),
    "FAMILY_CLONES": (_LANE_NONE, "report-wire family name, post-cache"),
    "BASELINE_TRACKED_GROUP_KEYS": (
        _LANE_NONE,
        "report-wire family container keys: the universe consumers walk in the "
        "assembled document, never a cached unit",
    ),
    "GROUP_KEY_STRUCTURAL": (_LANE_NONE, "report-wire container key, post-cache"),
    "GROUP_KEY_DEAD_CODE": (_LANE_NONE, "report-wire container key, post-cache"),
    "GROUP_KEY_DESIGN": (_LANE_NONE, "report-wire container key, post-cache"),
    "GROUP_KEY_AUTHORITY": (_LANE_NONE, "report-wire container key, post-cache"),
    "CLONE_GROUP_BUCKET_KEYS": (
        _LANE_NONE,
        "report-wire bucket keys of the clone family container, post-cache",
    ),
    "NESTED_GROUPS_KEY": (
        _LANE_NONE,
        "report-wire key each non-clone family nests its groups under, post-cache",
    ),
    "FINDING_GROUPS_PATH": (
        _LANE_NONE,
        "report-wire container address, built from the two names above",
    ),
    "SUPPRESSED_CONTAINER_KEY": (
        _LANE_NONE,
        "report-wire container key: it names where the report document nests "
        "suppressed clone groups, and suppression is applied to the assembled "
        "document, never to a cached unit",
    ),
    "SUPPRESSED_CONTAINER_PATH": (
        _LANE_NONE,
        "report-wire container address, built from the two names above",
    ),
    "TIER_STATE_COMPLETE": (
        _LANE_NONE,
        "report-wire execution witness of the advisory tier containers: the "
        "state is decided per run at document build time from the opt-in "
        "flags, and no cache payload stores it",
    ),
    "TIER_STATE_DISABLED": (
        _LANE_NONE,
        "report-wire execution witness, the disabled half of the pair above",
    ),
    # ── no stored output: not read by any production code today
    "PORTABLE_PATH_PROFILE_VERSION": (_LANE_NONE, "dead constant, no producer"),
    "SOURCE_KIND_POLICY_VERSION": (
        _LANE_NONE,
        "dead constant; source kind is derived per run from the path and is not "
        "stored in either payload",
    ),
    # ── no stored output: hash domains of artifacts outside the analysis cache
    "BASELINE_LANE_DIGEST_DOMAIN": (_LANE_NONE, "baseline container lane digest"),
    "BASELINE_ROOT_DIGEST_DOMAIN": (_LANE_NONE, "baseline container root digest"),
    "REPORT_ANALYSIS_FACTS_DIGEST_DOMAIN": (_LANE_NONE, "report integrity digest"),
    "REPORT_COMPARISON_DIGEST_DOMAIN": (_LANE_NONE, "report integrity digest"),
    "REPORT_ENVELOPE_DIGEST_DOMAIN": (_LANE_NONE, "report integrity digest"),
    "REPORT_EVALUATION_DIGEST_DOMAIN": (_LANE_NONE, "report integrity digest"),
    "REPORT_RUN_IDENTITY_TIER": (
        _LANE_NONE,
        "names which report integrity digest a run is called by; a wire key of "
        "a document built after the cache is read, so no cache payload stores "
        "it or anything derived from it",
    ),
    # ── no stored output: thresholds READ over stored facts, never stored with
    #    them. A gate threshold decides a verdict at report time; moving it must
    #    not re-parse a single file (the risk BANDS above are the opposite case
    #    precisely because their word is written into the payload).
    "DEFAULT_COHESION_THRESHOLD": (_LANE_NONE, "gate threshold over stored lcom4"),
    "DEFAULT_COMPLEXITY_THRESHOLD": (
        _LANE_NONE,
        "gate threshold over stored cyclomatic_complexity",
    ),
    "DEFAULT_COUPLING_THRESHOLD": (_LANE_NONE, "gate threshold over stored cbo"),
    "DEFAULT_COVERAGE_MIN": (_LANE_NONE, "gate threshold, post-cache"),
    "DEFAULT_HEALTH_THRESHOLD": (
        _LANE_NONE,
        "gate threshold over the health projection, post-cache",
    ),
    "DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD": (
        _LANE_NONE,
        "report presentation threshold, post-cache",
    ),
    "DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD": (
        _LANE_NONE,
        "report presentation threshold, post-cache",
    ),
    "DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD": (
        _LANE_NONE,
        "report presentation threshold, post-cache",
    ),
    # ── no stored output: locations, budgets, process shape and links
    "DEFAULT_BASELINE_PATH": (_LANE_NONE, "filesystem location"),
    "DEFAULT_HTML_REPORT_PATH": (_LANE_NONE, "filesystem location"),
    "DEFAULT_JSON_REPORT_PATH": (_LANE_NONE, "filesystem location"),
    "DEFAULT_MARKDOWN_REPORT_PATH": (_LANE_NONE, "filesystem location"),
    "DEFAULT_MAX_BASELINE_SIZE_MB": (_LANE_NONE, "artifact size budget"),
    "DEFAULT_MAX_CACHE_SIZE_MB": (_LANE_NONE, "cache size budget, not a payload fact"),
    "DEFAULT_PROCESSES": (
        _LANE_NONE,
        "worker count; every stored fact is per file and identical under any "
        "split of the work",
    ),
    "DEFAULT_ROOT": (_LANE_NONE, "filesystem location"),
    "DEFAULT_SARIF_REPORT_PATH": (_LANE_NONE, "filesystem location"),
    "DEFAULT_TEXT_REPORT_PATH": (_LANE_NONE, "filesystem location"),
    "DOCS_URL": (_LANE_NONE, "presentation link"),
    "ISSUES_URL": (_LANE_NONE, "presentation link"),
    "REPOSITORY_URL": (_LANE_NONE, "presentation link"),
    # ── no stored output: the health projection is computed per run OVER the
    #    stored facts. A weight, a reference permille or a saturation multiple
    #    changes the score, never a payload field.
    "HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE": (
        _LANE_NONE,
        "health projection, post-cache",
    ),
    "HEALTH_COMPLEXITY_ELEVATED_WEIGHT": (_LANE_NONE, "health projection, post-cache"),
    "HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE": (
        _LANE_NONE,
        "health projection, post-cache",
    ),
    "HEALTH_COMPLEXITY_EXTREME_WEIGHT": (_LANE_NONE, "health projection, post-cache"),
    "HEALTH_COMPLEXITY_OUTLIER_SATURATION_MULTIPLE": (
        _LANE_NONE,
        "health projection, post-cache",
    ),
    "HEALTH_COMPLEXITY_OUTLIER_WEIGHT": (_LANE_NONE, "health projection, post-cache"),
    "HEALTH_COMPLEXITY_TAIL_SATURATION_MULTIPLE": (
        _LANE_NONE,
        "health projection, post-cache",
    ),
    "HEALTH_COMPLEXITY_TYPICAL_WEIGHT": (_LANE_NONE, "health projection, post-cache"),
    "HEALTH_COUPLING_ELEVATED_REFERENCE_PERMILLE": (
        _LANE_NONE,
        "health projection, post-cache",
    ),
    "HEALTH_COUPLING_ELEVATED_WEIGHT": (_LANE_NONE, "health projection, post-cache"),
    "HEALTH_COUPLING_EXTREME_REFERENCE_PERMILLE": (
        _LANE_NONE,
        "health projection, post-cache",
    ),
    "HEALTH_COUPLING_EXTREME_WEIGHT": (_LANE_NONE, "health projection, post-cache"),
    "HEALTH_COUPLING_OUTLIER_SATURATION_MULTIPLE": (
        _LANE_NONE,
        "health projection, post-cache",
    ),
    "HEALTH_COUPLING_OUTLIER_WEIGHT": (_LANE_NONE, "health projection, post-cache"),
    "HEALTH_COUPLING_TAIL_SATURATION_MULTIPLE": (
        _LANE_NONE,
        "health projection, post-cache",
    ),
    "HEALTH_COUPLING_TYPICAL_WEIGHT": (_LANE_NONE, "health projection, post-cache"),
    "HEALTH_DEPENDENCY_CYCLE_PENALTY": (_LANE_NONE, "health projection, post-cache"),
    "HEALTH_DEPENDENCY_DEFERRED_CYCLE_PENALTY": (
        _LANE_NONE,
        "health projection, post-cache",
    ),
    "HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER": (
        _LANE_NONE,
        "health projection, post-cache",
    ),
    "HEALTH_DEPENDENCY_DEPTH_LEVEL_PENALTY": (
        _LANE_NONE,
        "health projection, post-cache",
    ),
    "HEALTH_DEPENDENCY_DEPTH_P95_MARGIN": (_LANE_NONE, "health projection, post-cache"),
    "HEALTH_WEIGHTS": (_LANE_NONE, "health projection, post-cache"),
    # ── no stored output: computed OVER stored tokens, like its own revision
    "NEAR_MISS_MAX_EDIT_STATEMENTS": (
        _LANE_NONE,
        "the near-miss tier groups over the stored statement tokens; the tokens "
        "themselves are not a function of this edit budget",
    ),
}


def _contracts_constant_names() -> frozenset[str]:
    """Membership: every public constant of the contracts ring, no name rule.

    X-02 asked the question of constants spelled VERSION/REVISION/SCHEMA/
    CATALOG/POLICY, which is a rule about naming habits rather than about where
    a value ends up. The risk bands are the counter-example that cost a
    generation of warm caches their risk classification, so the spelling is
    gone: a constant that lands in ``codeclone.contracts`` is asked whether its
    output is stored, whatever it is called.
    """

    return frozenset(
        name for name in dir(contracts) if name.isupper() and not name.startswith("_")
    )


def _shifted(value: object) -> object:
    if isinstance(value, bool):  # pragma: no cover - no bool constant today
        return not value
    if isinstance(value, int):
        return value + 1000
    return f"{value}-bumped"


def _bump_everywhere(
    monkeypatch: pytest.MonkeyPatch, name: str, *, value: object | None = None
) -> None:
    """Bump one contracts constant the way a real bump lands.

    A constant is consumed through ``from ..contracts import NAME``, so the
    value a caller sees is a module global of the IMPORTING module. Patching
    ``codeclone.contracts`` alone would therefore prove nothing. Every already
    imported ``codeclone`` module that holds this name at its current value is
    patched, which is exactly the state of the world one commit after an author
    edits the constant.

    ``value`` re-points the constant at a chosen number instead of shifting it
    out of range. A generic shift proves a digest is keyed on the constant; a
    chosen edge value proves the constant still DECIDES something for a real
    input, which is what a calibrated band has to be shown to do.
    """

    current = getattr(contracts, name)
    shifted = _shifted(current) if value is None else value
    monkeypatch.setattr(contracts, name, shifted)
    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith("codeclone.") or not isinstance(
            module, ModuleType
        ):
            continue
        if getattr(module, name, object()) == current:
            monkeypatch.setattr(module, name, shifted)


def _lane_hits_after_bump(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    *,
    value: object | None = None,
) -> tuple[bool, bool]:
    """Return (neutral_hit, dependent_hit) for a warm entry after one bump.

    The entry is written and read back BEFORE the bump, so it carries the
    profiles of the generation that produced it - the warm cache an author
    inherits. The reading cache is constructed AFTER the bump, so its profiles
    are the running generation's. That is the whole trigger, exercised through
    the public reuse decision rather than through the digest builders.

    Limitation stated on purpose: the module registry handle used here carries a
    fixture manifest digest, so a constant that reaches the dependent profile
    ONLY through that digest reads as a miss-free "none" in this harness. There
    is exactly one such constant and it has its own test below.
    """

    cache_path = tmp_path / "cache.json"
    _save_single_cache_entry(cache_path)
    _, entry = _load_cache_entry(cache_path, "x.py")

    _bump_everywhere(monkeypatch, name, value=value)

    reader = Cache(cache_path, root=tmp_path)
    _bind_module_paths(reader, "x.py")
    decision = _content_hit_decision(reader, entry)
    return decision.neutral.hit, decision.dependent.hit


def test_every_contracts_constant_declares_its_cache_lane() -> None:
    """A new contracts constant must be classified before it can ship.

    This is the half that makes the law a class law instead of a longer list of
    named guards: the author of the next constant cannot stay silent about
    whether its output is cached. X-03 removed the name filter that stood here,
    because the constants that escaped it were exactly the ones nobody thought
    of as generations - calibrated numbers whose verdict word is a stored field.
    """

    declared = frozenset(_CACHE_LANE_BY_CONSTANT)
    actual = _contracts_constant_names()
    assert actual - declared == frozenset(), (
        "unclassified contracts constants - declare the cache lane whose payload "
        f"stores their output, or _LANE_NONE with a reason: {sorted(actual - declared)}"
    )
    assert declared - actual == frozenset(), (
        f"classified constants that no longer exist: {sorted(declared - actual)}"
    )


@pytest.mark.parametrize(
    "constant",
    sorted(
        name
        for name, (lane, _reason) in _CACHE_LANE_BY_CONSTANT.items()
        if lane == _LANE_NEUTRAL
    ),
)
def test_neutral_lane_revision_bump_misses_the_neutral_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, constant: str
) -> None:
    """Bumping a revision whose output rides units[]/semantic_facts must miss.

    Pre-fix this is red for every constant except BASELINE_FINGERPRINT_VERSION:
    the neutral profile binds no algorithm revision at all, so a warm hit serves
    the previous generation's units while the run stamps the new revision.
    """

    neutral_hit, _dependent_hit = _lane_hits_after_bump(tmp_path, monkeypatch, constant)
    assert not neutral_hit, (
        f"{constant} bumped, yet the neutral lane still hit: a warm run serves "
        f"pre-bump {_CACHE_LANE_BY_CONSTANT[constant][1]}"
    )


@pytest.mark.parametrize(
    "constant",
    sorted(
        name
        for name, (lane, _reason) in _CACHE_LANE_BY_CONSTANT.items()
        if lane == _LANE_DEPENDENT
    ),
)
def test_dependent_lane_policy_bump_misses_only_the_dependent_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, constant: str
) -> None:
    """The dependent policies must miss their own lane and spare the neutral one.

    The second half is the over-invalidation guard: re-parsing every unit
    because a security-surface catalog gained a sink throws away a warm cache
    that is still correct for fingerprints, complexity and reachability.
    """

    neutral_hit, dependent_hit = _lane_hits_after_bump(tmp_path, monkeypatch, constant)
    assert not dependent_hit, (
        f"{constant} bumped, yet the dependent lane still hit: a warm run serves "
        f"pre-bump {_CACHE_LANE_BY_CONSTANT[constant][1]}"
    )
    assert neutral_hit, (
        f"{constant} is a dependent-lane policy but its bump also invalidated the "
        "neutral lane - over-invalidation, not a trigger"
    )


@pytest.mark.parametrize(
    "constant",
    sorted(
        name
        for name, (lane, _reason) in _CACHE_LANE_BY_CONSTANT.items()
        if lane == _LANE_NONE
    ),
)
def test_non_cached_constant_bump_invalidates_no_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, constant: str
) -> None:
    """Nothing a cache payload stores is an output of these constants.

    The reverse skew is a defect too: a profile that keys on a report schema or
    a memory projection version discards a correct warm cache on every unrelated
    bump.
    """

    neutral_hit, dependent_hit = _lane_hits_after_bump(tmp_path, monkeypatch, constant)
    assert neutral_hit and dependent_hit, (
        f"{constant} declares no cached output ({_CACHE_LANE_BY_CONSTANT[constant][1]})"
        " yet its bump invalidated a lane: over-invalidation"
    )


def test_module_identity_version_is_carried_by_the_manifest_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one constant that reaches a profile through another digest.

    ``module_manifest_digest`` is already a dependent-profile input, and the
    manifest embeds this version, so the carriage is real rather than declared.
    Proving it here is what lets the loop above read the fixture-digest harness
    honestly instead of silently excusing this constant.
    """

    def digest() -> str:
        return build_module_identity_manifest(
            root=tmp_path,
            paths=(),
            import_mounts=(),
            strategy="root",
        ).manifest_digest

    before = digest()
    _bump_everywhere(monkeypatch, "MODULE_IDENTITY_VERSION")
    assert digest() != before


@pytest.mark.parametrize(
    ("constant", "profile_input"),
    sorted(
        (name, reason)
        for name, (lane, reason) in _CACHE_LANE_BY_CONSTANT.items()
        if lane == _LANE_EFFECTIVE_CONFIG
    ),
)
def test_option_default_is_carried_by_the_effective_profile_input(
    constant: str, profile_input: str
) -> None:
    """The clone floors reach the profile as the value in force, not as defaults.

    These constants are the only ones that would read as over-invalidation in
    the harness above for the wrong reason, so they get a carriage proof of
    their own instead of a silent excuse. What matters is that the neutral
    profile is a FUNCTION of the floor the run is using: change the floor and a
    unit becomes clone-eligible that was not, so the stored population moves.
    Wiring the default itself would key the cache on a number a configured run
    is not using at all.

    The reason column of the registry is the profile keyword, so this test also
    stops that column from rotting into prose - a wrong keyword is a TypeError,
    not a comment nobody re-reads.
    """

    baseline_kwargs: dict[str, object] = {
        "fingerprint_version": contracts.BASELINE_FINGERPRINT_VERSION,
        "min_loc": contracts.DEFAULT_MIN_LOC,
        "min_stmt": contracts.DEFAULT_MIN_STMT,
        "block_min_loc": contracts.DEFAULT_BLOCK_MIN_LOC,
        "block_min_stmt": contracts.DEFAULT_BLOCK_MIN_STMT,
        "segment_min_loc": contracts.DEFAULT_SEGMENT_MIN_LOC,
        "segment_min_stmt": contracts.DEFAULT_SEGMENT_MIN_STMT,
    }
    assert baseline_kwargs[profile_input] == getattr(contracts, constant)

    moved_kwargs = dict(baseline_kwargs)
    moved_kwargs[profile_input] = cast(int, baseline_kwargs[profile_input]) + 1
    baseline = build_module_neutral_profile(**baseline_kwargs)  # type: ignore[arg-type]
    moved = build_module_neutral_profile(**moved_kwargs)  # type: ignore[arg-type]
    assert baseline.value != moved.value, (
        f"{profile_input} moved and the neutral profile did not: the floor in "
        f"force is not an input, so {constant} reaches the cache through nothing"
    )


# --------------------------------------------------------------------------- #
# X-03 - the bands decide, and the decision is stored.
#
# The three tests below are the reachability half of the law. A parametrized
# bump proves a digest is keyed on a constant; it does not prove the constant
# still decides anything, and a band wired into a profile while classifying
# nothing would be exactly the theatre this project forbids. Each test names a
# real input - a measurement sitting on the band edge - moves the edge by one,
# and shows the same input now earns a DIFFERENT stored word. That is what makes
# the warm hit a lie rather than a stale-looking number.
#
# The move is a monkeypatch inside the test. The shipped calibration is not
# touched: moving a published band is a user-facing score change and is governed
# by the blind-benchmark law, which is precisely why the warm lane must not
# silently absorb it.
# --------------------------------------------------------------------------- #


def test_complexity_band_move_changes_the_word_stored_in_units_risk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``units[].risk`` is the band's verdict, and it is served verbatim."""

    edge = contracts.COMPLEXITY_RISK_LOW_MAX
    assert risk_level(edge) == "low"

    neutral_hit, _dependent_hit = _lane_hits_after_bump(
        tmp_path, monkeypatch, "COMPLEXITY_RISK_LOW_MAX", value=edge - 1
    )

    assert risk_level(edge) == "medium", (
        "no input reaches the moved band - the guard would be unreachable"
    )
    assert not neutral_hit, (
        "the complexity band moved and the neutral lane still hit: a warm run "
        "serves the pre-move risk word for a function whose classification the "
        "recalibration changed"
    )


def test_coupling_band_move_changes_the_word_stored_in_class_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``class_metrics[].risk_coupling`` is the band's verdict, stored per class."""

    edge = contracts.COUPLING_RISK_LOW_MAX
    assert coupling_risk(edge) == "low"

    neutral_hit, dependent_hit = _lane_hits_after_bump(
        tmp_path, monkeypatch, "COUPLING_RISK_LOW_MAX", value=edge - 1
    )

    assert coupling_risk(edge) == "medium", (
        "no input reaches the moved band - the guard would be unreachable"
    )
    assert not dependent_hit, (
        "the coupling band moved and the dependent lane still hit: a warm run "
        "serves the pre-move risk_coupling word"
    )
    assert neutral_hit, (
        "a coupling band is a dependent-lane fact; invalidating the neutral "
        "lane too would re-parse every unit for nothing"
    )


def test_cohesion_band_move_changes_the_word_stored_in_class_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``class_metrics[].risk_cohesion`` is the band's verdict, stored per class."""

    edge = contracts.COHESION_RISK_MEDIUM_MAX
    assert cohesion_risk(edge) == "medium"

    neutral_hit, dependent_hit = _lane_hits_after_bump(
        tmp_path, monkeypatch, "COHESION_RISK_MEDIUM_MAX", value=edge - 1
    )

    assert cohesion_risk(edge) == "high", (
        "no input reaches the moved band - the guard would be unreachable"
    )
    assert not dependent_hit, (
        "the cohesion band moved and the dependent lane still hit: a warm run "
        "serves the pre-move risk_cohesion word"
    )
    assert neutral_hit, (
        "a cohesion band is a dependent-lane fact; invalidating the neutral "
        "lane too would re-parse every unit for nothing"
    )
