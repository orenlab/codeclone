# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Acceptance corpus for report semantic identity: v2 (RULING-2026-08-31)
and v3 (the projection-owner boundary, 2026-09-05).

Six collision probes were measured on 2026-08-31 against the v1 identity
(`integrity.digests.evaluation`): five distinct (tree x config x engine)
states shared one ``run_id`` because findings, tier containers, policy
parameters and evaluation outputs were outside the hashed preimage.  Each
v2 probe below pins the ratified law:

    Two runs share a ``run_id`` iff they utter the same canonical set of
    semantic statements under the same realized contract of their
    derivation.

Identity v3 closed the next measured class.  Generation 2 digested the
FINDINGS projection of a family and called it the family digest, so every
statement a family utters outside that projection reached no preimage:
an abstention whose ``reason``, ``reachability`` and ``witness`` all
changed kept its ``run_id``; so did ``coupled_classes`` below the design
threshold (real trees: ``Alpha`` coupled to ``Beta`` versus ``Gamma`` at
``cbo=1``, one ``run_id``), the CFG cyclomatic complexity of every function,
the suppressed dead-code verdicts, the rule-3 abstentions with their base
names, the live-root reasons and the coverage rows below the hotspot
threshold.  In the other direction ``novelty`` -- a COMPARISON-domain fact
-- was hashed inside the ANALYSIS family digests, so the tier meant to be
the hierarchy's fixed point moved on a baseline-derived fact.  The v3
probes pin both directions and the law they serve:

    Every user-visible analysis-semantic assertion is represented in
    exactly one identity-bearing semantic-family projection at its
    natural tier.

The corpus is permanent.  Every probe that asserts inequality was
verbatim-equal before its generation's preimage landed; every equality
probe guards the other boundary and must stay green across generations.
Each v3 gap probe is paired with a control on the same lane, so a SAME
verdict is never read as the absence of a mechanism.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from codeclone.models import (
    LaneTrust,
    NearMissMember,
    NearMissPair,
    RenamedStructureGroup,
    RenamedStructureMember,
    SemanticAuthorityResult,
    StructuralFindingGroup,
    StructuralFindingOccurrence,
    SuppressedCloneGroup,
    TrustVector,
)
from codeclone.utils.mapping_paths import section
from codeclone.utils.run_identity import report_run_identity

from ._report_fixtures import build_test_report_document

if TYPE_CHECKING:  # pragma: no cover - typing only
    from codeclone.cache.store import Cache

_FIXTURES = Path(__file__).parent / "fixtures" / "report_identity"

_FP = "c7d3c7b84d0ee440d27f547cb0ac1845845ffd34ee01669bcbd623adb9d3f56b"
#: A canonical fp-v2 function clone group key (the observation bundle refuses
#: any other spelling), shared by the novelty probes and the maximal document.
_CLONE_KEY = f"{_FP}|0-19"


def _near_miss_pair() -> NearMissPair:
    return NearMissPair(
        pair_key="pkg/module.py:pkg.module:alpha:1|pkg/module.py:pkg.module:beta:15",
        members=(
            NearMissMember(
                qualname="pkg.module:alpha",
                filepath="pkg/module.py",
                start_line=1,
                end_line=12,
                differing_start_line=6,
                differing_end_line=6,
            ),
            NearMissMember(
                qualname="pkg.module:beta",
                filepath="pkg/module.py",
                start_line=15,
                end_line=26,
                differing_start_line=20,
                differing_end_line=20,
            ),
        ),
        edit_statements=1,
        edit_kind="replace",
    )


def _document(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "func_groups": {},
        "block_groups": {},
        "segment_groups": {},
    }
    kwargs.update(overrides)
    return build_test_report_document(**kwargs)  # type: ignore[arg-type]


def _health_metrics(
    *,
    dead_code_items: int,
    files_found: int = 10,
    files_analyzed_or_cached: int = 10,
) -> dict[str, object]:
    """A real health family from the score's own producer — no caller ever
    types a score, so a recalibration moves this fixture with the metric.

    The two counters are the population probes' input and default to the
    complete run every other caller wants; ``compute_health`` decides the
    ``population`` word from them through its owner, so no test types that
    word either.
    """

    from codeclone.metrics.health import (
        HealthInputs,
        compute_health,
        health_report_fields,
    )

    family = health_report_fields(
        compute_health(
            HealthInputs(
                files_found=files_found,
                files_analyzed_or_cached=files_analyzed_or_cached,
                function_clone_groups=0,
                block_clone_groups=0,
                complexity_avg=2.0,
                complexity_max=5,
                high_risk_functions=0,
                elevated_complexity_functions=0,
                complexity_function_population=40,
                coupling_avg=1.0,
                coupling_max=3,
                high_risk_classes=0,
                elevated_coupling_classes=0,
                coupling_class_population=20,
                cohesion_avg=0.9,
                low_cohesion_classes=0,
                import_dependency_cycles=0,
                deferred_dependency_cycles=0,
                dependency_max_depth=2,
                dependency_avg_depth=1.0,
                dependency_p95_depth=2,
                dead_code_items=dead_code_items,
            )
        )
    )
    return {"health": family}


# ---------------------------------------------------------------------------
# Collision probes: semantic differences MUST move the identity.
# ---------------------------------------------------------------------------


def test_probe_p3_disabled_vs_complete_moves_identity() -> None:
    """Measured 2026-08-31: ``state=disabled`` and ``state=complete, count=1``
    shared run_id ``8a631508...`` — the MCP run store replaced one run with the
    other under a single key."""

    disabled = _document(near_miss_pairs=None)
    complete = _document(near_miss_pairs=[_near_miss_pair()])
    assert report_run_identity(disabled) != report_run_identity(complete)


def test_probe_p1_pair_set_change_moves_identity() -> None:
    """Measured: a source edit flipping ``near_miss`` 1 -> 0 left run_id and
    the observation digest untouched across nine of ten lanes."""

    one_pair = _document(near_miss_pairs=[_near_miss_pair()])
    no_pairs = _document(near_miss_pairs=[])
    assert report_run_identity(one_pair) != report_run_identity(no_pairs)


def test_complete_empty_differs_from_disabled() -> None:
    """count = 0 is a completed measurement; absence of execution is not a
    zero.  The two states must not share an identity."""

    complete_empty = _document(near_miss_pairs=[])
    disabled = _document(near_miss_pairs=None)
    assert report_run_identity(complete_empty) != report_run_identity(disabled)


@pytest.mark.parametrize(
    ("policy_binding", "changed_value"),
    [
        pytest.param(
            "NEAR_MISS_ALGORITHM_REVISION",
            "4",
            id="p2b-algorithm-revision",
        ),
        pytest.param(
            "NEAR_MISS_MAX_EDIT_STATEMENTS",
            2,
            id="p2c-policy-budget",
        ),
    ],
)
def test_probe_p2_policy_change_moves_identity(
    monkeypatch: pytest.MonkeyPatch,
    policy_binding: str,
    changed_value: object,
) -> None:
    """Measured p2b: bumping NEAR_MISS_ALGORITHM_REVISION "3" -> "4" moved no
    digest but the envelope — the sanctioned version lever was disconnected
    from identity.  Measured p2c (the ratified policy law): an
    output-affecting policy value is a live parameter; its canonical digest
    moves the identity automatically, without a manual revision bump."""

    baseline = _document(near_miss_pairs=[_near_miss_pair()])
    monkeypatch.setattr(
        f"codeclone.report.document._findings_groups.{policy_binding}",
        changed_value,
    )
    changed = _document(near_miss_pairs=[_near_miss_pair()])
    assert report_run_identity(baseline) != report_run_identity(changed)


def test_probe_health_output_moves_identity() -> None:
    """Measured: health 98 -> 100 under an identical run_id ``33cd01a0...``.
    The uttered verdict is an evaluation family output and must move the
    identity."""

    clean = _document(metrics=_health_metrics(dead_code_items=0))
    indebted = _document(metrics=_health_metrics(dead_code_items=25))
    clean_score = section(clean, "metrics.families.health.summary").get("score")
    indebted_score = section(indebted, "metrics.families.health.summary").get("score")
    assert clean_score != indebted_score  # the probe must vary the verdict
    assert report_run_identity(clean) != report_run_identity(indebted)


def test_probe_health_params_move_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the measured health probe: recalibrating the weights
    is an evaluation policy change and must move the identity even when the
    uttered score happens to coincide."""

    import codeclone.contracts as contracts

    before = _document(metrics=_health_metrics(dead_code_items=0))
    monkeypatch.setattr(
        contracts,
        "HEALTH_WEIGHTS",
        {**contracts.HEALTH_WEIGHTS, "dead_code": 0.60},
    )
    after = _document(metrics=_health_metrics(dead_code_items=0))
    assert report_run_identity(before) != report_run_identity(after)


# ---------------------------------------------------------------------------
# Equality probes: non-semantic differences MUST NOT move the identity.
# ---------------------------------------------------------------------------


def test_analysis_mode_moves_identity() -> None:
    """The analysis population is a semantic statement: a clones-only run and
    a full run are different measurements even over identical utterances."""

    clones_only = _document(meta={"analysis_mode": "clones_only"})
    full = _document(meta={"analysis_mode": "full"})
    assert report_run_identity(clones_only) != report_run_identity(full)


def test_clone_floor_params_move_identity() -> None:
    """The clone-lane floors are live producer parameters: two runs admitting
    different unit populations must not share an identity even when their
    uttered groups coincide."""

    def _profile(min_loc: int) -> dict[str, object]:
        return {
            "analysis_profile": {
                "min_loc": min_loc,
                "min_stmt": 4,
                "block_min_loc": 20,
                "block_min_stmt": 8,
                "segment_min_loc": 20,
                "segment_min_stmt": 10,
            }
        }

    narrow = _document(meta=_profile(6))
    wide = _document(meta=_profile(10))
    profile = section(narrow, "integrity.semantic.realized_contracts.analysis").get(
        "clones"
    )
    assert isinstance(profile, dict) and profile["params"] != {}  # floors realized
    assert report_run_identity(narrow) != report_run_identity(wide)


def test_world_contract_params_move_identity() -> None:
    """RULING 2026-09-01 §5: the world contract is a realized parameter of
    the dead-code derivation. Two runs over one tree that answer under
    different worlds utter different verdicts, so they may not share a name
    even when both happen to utter zero dead findings."""

    def _dead_code(world: str) -> dict[str, object]:
        return {"dead_code": {"summary": {"world_contract": world}}}

    open_world = _document(metrics=_dead_code("open"))
    closed_world = _document(metrics=_dead_code("closed"))
    realized = section(open_world, "integrity.semantic.realized_contracts.analysis")
    dead_code = realized.get("dead_code")
    assert isinstance(dead_code, dict)
    assert dead_code["params"] == {"world_contract": "open"}
    assert report_run_identity(open_world) != report_run_identity(closed_world)


def test_identity_is_deterministic() -> None:
    first = _document(near_miss_pairs=[_near_miss_pair()])
    second = _document(near_miss_pairs=[_near_miss_pair()])
    assert report_run_identity(first) == report_run_identity(second)


def test_provenance_does_not_move_identity() -> None:
    """Measured d3_otherroot: the same content from another directory kept its
    run_id.  Wall-clock, interpreter tag and machine-local paths are
    provenance, never identity."""

    plain = _document(near_miss_pairs=[_near_miss_pair()])
    stamped = _document(
        near_miss_pairs=[_near_miss_pair()],
        meta={
            "python_tag": "cp399",
            "runtime": {
                "analysis_started_at_utc": "1999-01-01T00:00:00Z",
                "scan_root_absolute": "/somewhere/else/entirely",
            },
        },
    )
    assert report_run_identity(plain) == report_run_identity(stamped)


def test_disabled_producer_revision_stays_outside_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ruling's subtlety: a producer that utters only ``state=disabled``
    does not smuggle its configured algorithm revision into the identity."""

    import codeclone.contracts as contracts

    before = _document(near_miss_pairs=None)
    # A true engine-wide revision change touches both spellings: the
    # container producer's binding and the registry's live constant.
    monkeypatch.setattr(
        "codeclone.report.document._findings_groups.NEAR_MISS_ALGORITHM_REVISION",
        "9",
    )
    monkeypatch.setattr(contracts, "NEAR_MISS_ALGORITHM_REVISION", "9")
    after = _document(near_miss_pairs=None)
    assert report_run_identity(before) == report_run_identity(after)


# ---------------------------------------------------------------------------
# Generations: an old fixture stays honestly interpretable in its own one.
# ---------------------------------------------------------------------------


def _fixture_document(name: str) -> dict[str, object]:
    loaded = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_v1_generation_document_still_verifies() -> None:
    """A document produced by the v1 builder (captured before the v2 preimage
    landed) must keep verifying under its own generation's rules."""

    from codeclone.report.document.integrity import verify_report_integrity

    assert verify_report_integrity(_fixture_document("report_document_v1.json")) is None


def test_v2_generation_document_still_verifies() -> None:
    """A document sealed by the v2 engine (captured at bc7e4ffc, before the v3
    preimage landed) verifies under the frozen generation-2 rules: the
    findings-projection family digests, no comparison tier."""

    from codeclone.report.document.integrity import verify_report_integrity

    document = _fixture_document("report_document_v2.json")
    assert section(document, "integrity").get("semantic_identity_version") == "2"
    assert tuple(section(document, "integrity.semantic.family_digests")) == (
        "analysis",
        "evaluation",
    )
    assert verify_report_integrity(document) is None


def test_v2_fixture_is_interpreted_never_reinterpreted() -> None:
    """The same generation-2 block read under generation-3 rules refuses:
    dispatch is by the document's own marker, and a marker does not carry a
    body sealed under another generation.  The first spelled-twice fact the
    generation-3 rules meet is the population — generation 3 quantifies over
    fourteen producers, the frozen generation-2 row over nine — so that is
    the refusal named; the tier-set refusal behind it is pinned by the
    ``_tamper_family_tiers`` case."""

    from codeclone.report.document.integrity import verify_report_integrity

    document = _fixture_document("report_document_v2.json")
    _mutable(document, "integrity")["semantic_identity_version"] = "3"
    assert verify_report_integrity(document) == (
        "report semantic population does not recompute from the document"
    )


def test_current_document_declares_its_identity_generation() -> None:
    from codeclone.contracts import REPORT_SEMANTIC_IDENTITY_VERSION
    from codeclone.report.document.integrity import (
        _CURRENT_GENERATION,
        _generation_marker,
    )

    document = _document()
    integrity = document["integrity"]
    assert isinstance(integrity, dict)
    assert (
        integrity.get("semantic_identity_version") == REPORT_SEMANTIC_IDENTITY_VERSION
    )
    assert _generation_marker(_CURRENT_GENERATION) == REPORT_SEMANTIC_IDENTITY_VERSION
    assert REPORT_SEMANTIC_IDENTITY_VERSION == "3"
    assert tuple(section(document, "integrity.semantic.family_digests")) == (
        "analysis",
        "comparison",
        "evaluation",
    )


def test_generation_family_domains_are_distinct() -> None:
    """One projection digested under the two generation rows must not
    collide: the family domain names its generation (the wire-integrity
    precedent: a domain literal older than its generation printed the wrong
    one)."""

    from codeclone.contracts import (
        REPORT_ANALYSIS_IDENTITY_DOMAIN_V2,
        REPORT_ANALYSIS_IDENTITY_DOMAIN_V3,
        REPORT_COMPARISON_IDENTITY_DOMAIN_V2,
        REPORT_COMPARISON_IDENTITY_DOMAIN_V3,
        REPORT_EVALUATION_IDENTITY_DOMAIN_V2,
        REPORT_EVALUATION_IDENTITY_DOMAIN_V3,
        REPORT_FAMILY_DIGEST_DOMAIN_V2,
        REPORT_FAMILY_DIGEST_DOMAIN_V3,
    )
    from codeclone.report.document.integrity import (
        _GENERATION_THREE,
        _GENERATION_TWO,
        _family_digest_value,
    )

    projection: dict[str, object] = {"findings.groups.dead_code": {"groups": []}}
    assert _family_digest_value(
        "dead_code", projection, generation=_GENERATION_TWO
    ) != _family_digest_value("dead_code", projection, generation=_GENERATION_THREE)
    for v2_domain, v3_domain in (
        (REPORT_ANALYSIS_IDENTITY_DOMAIN_V2, REPORT_ANALYSIS_IDENTITY_DOMAIN_V3),
        (REPORT_COMPARISON_IDENTITY_DOMAIN_V2, REPORT_COMPARISON_IDENTITY_DOMAIN_V3),
        (REPORT_EVALUATION_IDENTITY_DOMAIN_V2, REPORT_EVALUATION_IDENTITY_DOMAIN_V3),
        (REPORT_FAMILY_DIGEST_DOMAIN_V2, REPORT_FAMILY_DIGEST_DOMAIN_V3),
    ):
        assert v2_domain != v3_domain
        assert v2_domain.endswith("v2\0") and v3_domain.endswith("v3\0")


# ---------------------------------------------------------------------------
# Producer registry: totality and the population law.
# ---------------------------------------------------------------------------


def test_every_registered_report_section_has_exactly_one_identity_owner() -> None:
    """The ratchet's quantification domain (identity v3 landing).  It first
    quantified over ``findings.groups`` alone, and the user's analysis
    semantics live outside it — measured 2026-09-05 on a real document:
    five whole metric families differed on the wire while every tier stayed
    the same.  The domain is now every findings group the report utters AND
    every report section the metric-family registry names; each has exactly
    one registered owner, and every owned section exists in the maximal
    document (an owned section nothing carries would be a dead declaration).
    """

    from codeclone.contracts.report_identity import (
        REPORT_SEMANTIC_PRODUCERS,
        spec_family,
    )
    from codeclone.metrics.registry import METRIC_FAMILIES
    from codeclone.report.document.family_projection import (
        document_section,
        report_section_owners,
        unowned_report_sections,
    )

    document = _maximal_document()
    findings = section(document, "findings")
    metrics = section(document, "metrics")
    owners = report_section_owners()
    assert unowned_report_sections(findings=findings, metrics=metrics) == ()
    registered = {
        f"metrics.families.{family.report_section}"
        for family in METRIC_FAMILIES.values()
    }
    uttered = {f"findings.groups.{name}" for name in section(findings, "groups")}
    uttered.update(f"metrics.families.{name}" for name in section(metrics, "families"))
    assert registered <= set(owners)
    assert uttered <= set(owners)
    assert set(owners) <= registered | uttered  # no owner names a phantom section
    for section_path in owners:
        assert (
            document_section(section_path, findings=findings, metrics=metrics)
            is not None
        ), section_path
    families = [spec_family(spec) for spec in REPORT_SEMANTIC_PRODUCERS]
    assert families == sorted(families)
    assert len(families) == len(set(families))


def test_a_section_declared_by_two_producers_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One section, one owner: a registry where two producers claim one
    section is refused by the owner map, never resolved by table order."""

    import codeclone.report.document.family_projection as family_projection
    from codeclone.contracts.report_identity import (
        REPORT_SEMANTIC_PRODUCERS,
        ReportIdentityRegistryError,
        spec_family,
    )

    doubled = tuple(
        {**spec, "document_sections": ("metrics.families.security_surfaces",)}
        if spec_family(spec) == "structural"
        else spec
        for spec in REPORT_SEMANTIC_PRODUCERS
    )
    monkeypatch.setattr(family_projection, "REPORT_SEMANTIC_PRODUCERS", doubled)
    with pytest.raises(ReportIdentityRegistryError, match="two producers"):
        family_projection.report_section_owners()


def test_build_refuses_a_registered_family_without_an_identity_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The totality law at the seal: a metric family the registry names and
    no producer owns cannot be sealed into a document — the refusal names
    the section, so the owner is declared before the surface ships."""

    import dataclasses

    import codeclone.report.document.family_projection as family_projection
    from codeclone.contracts.report_identity import ReportIdentityRegistryError
    from codeclone.metrics.registry import METRIC_FAMILIES

    grown = dict(METRIC_FAMILIES)
    grown["taint_flow"] = dataclasses.replace(
        METRIC_FAMILIES["security_surfaces"],
        name="taint_flow",
        report_section="taint_flow",
    )
    monkeypatch.setattr(family_projection, "METRIC_FAMILIES", grown)
    with pytest.raises(
        ReportIdentityRegistryError, match=r"no registered identity owner"
    ) as refusal:
        _document()
    assert "metrics.families.taint_flow" in str(refusal.value)


def test_current_generation_row_quantifies_over_every_registered_family() -> None:
    """A generation row's family list is frozen with the row, and the
    current row must name every registered producer: a family registered
    without joining the current generation would seal no digest, and one
    joining a frozen generation would stop its documents recomputing (the
    v2 fixture's population names nine producers, and it still verifies)."""

    from codeclone.contracts.report_identity import registered_families, spec_family
    from codeclone.report.document.integrity import (
        _CURRENT_GENERATION,
        _GENERATION_TWO,
        _generation_producers,
    )

    current = tuple(
        spec_family(spec) for spec in _generation_producers(_CURRENT_GENERATION)
    )
    assert current == registered_families()
    frozen = tuple(spec_family(spec) for spec in _generation_producers(_GENERATION_TWO))
    v2_population = section(
        _fixture_document("report_document_v2.json"),
        "integrity.semantic.population.producers",
    )
    assert frozen == tuple(sorted(v2_population))
    assert set(frozen) < set(current)


def test_family_digests_cover_only_executed_families() -> None:
    """A family that never executed is population state, never an empty
    measurement: no digest may exist for it in any tier (count=0 is only
    ever the result of an executed measurement)."""

    document = _document(near_miss_pairs=None)
    family_digests = section(document, "integrity.semantic.family_digests")
    analysis_digests = section(document, "integrity.semantic.family_digests.analysis")
    comparison_digests = section(
        document, "integrity.semantic.family_digests.comparison"
    )
    producers = section(document, "integrity.semantic.population.producers")

    assert producers["near_miss"] == "disabled"
    assert "near_miss" not in analysis_digests
    assert "near_miss" not in comparison_digests
    for family, state in producers.items():
        if family in {"health", "gates"}:
            continue
        assert (family in analysis_digests) == (state == "complete"), family
        assert family not in comparison_digests or state == "complete", family
    assert set(family_digests) == {"analysis", "comparison", "evaluation"}


# ---------------------------------------------------------------------------
# Verifier witnesses: every spelled-twice fact, tampered, names its refusal.
# Each pin is also a mutation witness — killing the corresponding check in
# the verifier turns exactly one of these red.
# ---------------------------------------------------------------------------


def _tampered(document: dict[str, object]) -> dict[str, object]:
    return copy.deepcopy(document)


def _verify(document: dict[str, object]) -> str | None:
    from codeclone.report.document.integrity import verify_report_integrity

    return verify_report_integrity(document)


def _mutable(document: dict[str, object], path: str) -> dict[str, object]:
    """Narrow one addressed sub-mapping to its live dict for tampering."""

    target = section(document, path)
    assert isinstance(target, dict)
    return target


def _tamper_v1_observation(document: dict[str, object]) -> None:
    _mutable(document, "integrity.digests.observation")["value"] = None


def _tamper_v1_schema(document: dict[str, object]) -> None:
    del document["report_schema_version"]


def _tamper_v1_analysis_facts(document: dict[str, object]) -> None:
    _mutable(document, "integrity.digests.analysis_facts")["value"] = "0" * 64


@pytest.mark.parametrize(
    ("tamper", "expected"),
    [
        (_tamper_v1_observation, "report observation digest is missing"),
        (_tamper_v1_schema, "report schema version is missing"),
        (_tamper_v1_analysis_facts, "report analysis_facts digest mismatch"),
    ],
)
def test_v1_verify_names_each_tamper(
    tamper: object,
    expected: str,
) -> None:
    document = _tampered(_fixture_document("report_document_v1.json"))
    tamper(document)  # type: ignore[operator]
    assert _verify(document) == expected


def test_v1_verify_refuses_missing_observation_tier() -> None:
    document = _tampered(_fixture_document("report_document_v1.json"))
    del _mutable(document, "integrity.digests")["observation"]
    assert _verify(document) == (
        "report digest set must contain exactly five named tiers"
    )


def _tamper_population(document: dict[str, object]) -> None:
    # ``authority`` is the producer every corpus document leaves disabled
    # (no ``semantic_authority`` lane), so the flip is never a no-op.
    producers = _mutable(document, "integrity.semantic.population.producers")
    assert producers["authority"] == "disabled"
    producers["authority"] = "complete"


def _tamper_params_digest(document: dict[str, object]) -> None:
    _mutable(document, "integrity.semantic.realized_contracts.analysis.clones")[
        "params_digest"
    ] = "0" * 64


def _tamper_comparison(document: dict[str, object]) -> None:
    _mutable(document, "integrity.semantic.realized_contracts.comparison.baseline")[
        "status"
    ] = "tampered"


def _tamper_gates(document: dict[str, object]) -> None:
    _mutable(document, "integrity.semantic.realized_contracts.evaluation.gates")[
        "thresholds_digest"
    ] = "0" * 64


def _tamper_analysis_family(document: dict[str, object]) -> None:
    _mutable(document, "integrity.semantic.family_digests.analysis")["clones"] = (
        "0" * 64
    )


def _tamper_comparison_family(document: dict[str, object]) -> None:
    _mutable(document, "integrity.semantic.family_digests.comparison")["clones"] = (
        "0" * 64
    )


def _tamper_family_tiers(document: dict[str, object]) -> None:
    del _mutable(document, "integrity.semantic.family_digests")["comparison"]


def _tamper_observation(document: dict[str, object]) -> None:
    _mutable(document, "integrity.digests.observation")["value"] = None


def _tamper_schema(document: dict[str, object]) -> None:
    document["report_schema_version"] = 5


def _tamper_semantic_block(document: dict[str, object]) -> None:
    _mutable(document, "integrity")["semantic"] = {}


_SEMANTIC_TAMPERS: tuple[tuple[object, str], ...] = (
    (
        _tamper_population,
        "report semantic population does not recompute from the document",
    ),
    (
        _tamper_params_digest,
        "report realized contract for 'clones' does not match its params digest",
    ),
    (
        _tamper_comparison,
        "report realized comparison contract does not recompute from meta",
    ),
    (
        _tamper_gates,
        "report realized gate thresholds disagree with the evaluation",
    ),
    (
        _tamper_analysis_family,
        "report analysis family digests do not recompute",
    ),
    (_tamper_observation, "report observation digest is missing"),
    (_tamper_schema, "report schema version is missing"),
    (_tamper_semantic_block, "report semantic identity block is missing"),
)


@pytest.mark.parametrize(
    ("tamper", "expected"),
    [
        *_SEMANTIC_TAMPERS,
        (
            _tamper_comparison_family,
            "report comparison family digests do not recompute",
        ),
        (
            _tamper_family_tiers,
            "report family digests do not name this generation's tiers",
        ),
    ],
)
def test_v3_verify_names_each_tamper(tamper: object, expected: str) -> None:
    document = _tampered(_document(near_miss_pairs=None))
    tamper(document)  # type: ignore[operator]
    assert _verify(document) == expected


@pytest.mark.parametrize(("tamper", "expected"), list(_SEMANTIC_TAMPERS))
def test_v2_fixture_verify_names_each_tamper(tamper: object, expected: str) -> None:
    """The frozen generation-2 rules run for real on the v2 fixture: every
    spelled-twice check names the same refusal it named when it sealed."""

    document = _tampered(_fixture_document("report_document_v2.json"))
    tamper(document)  # type: ignore[operator]
    assert _verify(document) == expected


def test_v3_verify_refuses_near_miss_container_disagreement() -> None:
    from codeclone.report.document.integrity import _params_digest

    entry_path = "integrity.semantic.realized_contracts.analysis.near_miss"
    document = _tampered(_document(near_miss_pairs=[_near_miss_pair()]))
    _mutable(document, f"{entry_path}.algorithm_revisions")["near_miss"] = "9"
    assert _verify(document) == (
        "report near_miss realized revision disagrees with its container"
    )

    document = _tampered(_document(near_miss_pairs=[_near_miss_pair()]))
    params = _mutable(document, f"{entry_path}.params")
    params["max_edit_statements"] = 5
    _mutable(document, entry_path)["params_digest"] = _params_digest(params)
    assert _verify(document) == (
        "report near_miss realized budget disagrees with its container"
    )


def test_v3_verify_refuses_tampered_health_family_digest() -> None:
    document = _tampered(_document(metrics=_health_metrics(dead_code_items=0)))
    _mutable(document, "integrity.semantic.family_digests.evaluation")["health"] = (
        "0" * 64
    )
    assert _verify(document) == "report evaluation family digests do not recompute"


def test_verify_refuses_unknown_identity_generation() -> None:
    document = _tampered(_document())
    _mutable(document, "integrity")["semantic_identity_version"] = "99"
    error = _verify(document)
    assert error is not None
    assert error.startswith("report semantic identity generation '99'")
    assert error.endswith("(knows: absent, '2', '3')")


def test_registry_names_evaluation_families_and_refuses_unknown() -> None:
    from codeclone.contracts.report_identity import (
        ReportIdentityRegistryError,
        evaluation_families,
        producer_spec,
    )

    assert evaluation_families() == ("gates", "health")
    with pytest.raises(ReportIdentityRegistryError, match="no registered producer"):
        producer_spec("nonexistent_family")


# ---------------------------------------------------------------------------
# Identity v3: the measured gaps.  Each family digest was built from the
# findings projection; these are the statements that projection dropped.
# Every case below printed SAME on every tier under generation 2
# (probe_before_v2, 2026-09-05) and is paired with a control on its lane.
# ---------------------------------------------------------------------------


def _dead_code_metrics(
    *,
    reason: str = "declared_reexport",
    reachability: str = "externally_reachable",
    witness: str = "declared_reexport:pkg",
    world: str = "open",
    dead_reason: str = "unreferenced",
    suppressed_confidence: str = "high",
    override_bases: tuple[str, ...] = ("ExternalBase",),
    live_roots: tuple[tuple[str, str], ...] = (),
    unresolved_count: int = 1,
    line_shift: int = 0,
) -> dict[str, object]:
    """The dead_code family as ``core.metrics_payload`` publishes it: every
    lane the report projects, with the abstention explanation as the knob."""

    unresolved = [
        {
            "qualname": f"pkg.module:maybe_{index}",
            "filepath": "pkg/module.py",
            "start_line": 20 + index * 10 + line_shift,
            "end_line": 25 + index * 10 + line_shift,
            "kind": "function",
            "reason": reason,
            "reachability": reachability,
            "witness": witness,
            "world_contract": world,
        }
        for index in range(unresolved_count)
    ]
    return {
        "dead_code": {
            "items": [
                {
                    "qualname": "pkg.module:dead_one",
                    "filepath": "pkg/module.py",
                    "start_line": 10,
                    "end_line": 12,
                    "kind": "function",
                    "confidence": "high",
                    "reason": dead_reason,
                    "test_reference_sources": [],
                }
            ],
            "suppressed_items": [
                {
                    "qualname": "pkg.module:quiet",
                    "filepath": "pkg/module.py",
                    "start_line": 40,
                    "end_line": 42,
                    "kind": "function",
                    "confidence": suppressed_confidence,
                    "reason": "unreferenced",
                    "test_reference_sources": [],
                    "suppressed_by": [{"rule": "dead-code", "source": "inline"}],
                }
            ],
            "unresolved_overrides": [
                {
                    "qualname": "pkg.module:Child.render",
                    "filepath": "pkg/module.py",
                    "start_line": 50,
                    "end_line": 52,
                    "kind": "method",
                    "class_qualname": "pkg.module:Child",
                    "base_names": list(override_bases),
                    "reason": "unresolved_external_base",
                }
            ],
            "unresolved": unresolved,
            "unreachable_statements": [],
            "live_root_reasons": [
                {"qualname": qualname, "reason": root_reason}
                for qualname, root_reason in live_roots
            ],
            "summary": {
                "total": 1,
                "high_confidence": 1,
                "suppressed": 1,
                "unresolved_external_override": 1,
                "unresolved": unresolved_count,
                "world_contract": world,
                "unreachable_statements": 0,
                "live_roots": len(live_roots),
            },
        }
    }


def _design_metrics(
    *,
    coupled: tuple[str, ...] = ("Beta",),
    cbo: int = 1,
    cfg: int = 5,
    cc: int = 5,
    coupling_risk: str = "low",
    coverage_permille: int = 300,
) -> dict[str, object]:
    """The three design metric families the measured gaps live in."""

    return {
        "complexity": {
            "functions": [
                {
                    "qualname": "pkg.module:work",
                    "filepath": "pkg/module.py",
                    "start_line": 1,
                    "end_line": 30,
                    "cyclomatic_complexity": cc,
                    "cfg_cyclomatic_complexity": cfg,
                    "nesting_depth": 2,
                    "risk": "low",
                }
            ],
            "summary": {"total": 1, "average": float(cc), "max": cc, "high_risk": 0},
        },
        "coupling": {
            "classes": [
                {
                    "qualname": "pkg.module:Alpha",
                    "filepath": "pkg/module.py",
                    "start_line": 40,
                    "end_line": 60,
                    "cbo": cbo,
                    "risk": coupling_risk,
                    "coupled_classes": list(coupled),
                }
            ],
            "summary": {"total": 1, "average": float(cbo), "max": cbo, "high_risk": 0},
        },
        "coverage_join": {
            "summary": {
                "status": "ok",
                "source": "coverage.xml",
                "files": 1,
                "units": 1,
                "measured_units": 1,
                "overall_executable_lines": 10,
                "overall_covered_lines": 3,
                "overall_permille": coverage_permille,
                "missing_from_report_units": 0,
                "coverage_hotspots": 0,
                "scope_gap_hotspots": 0,
                "hotspot_threshold_percent": 50,
                "invalid_reason": None,
            },
            "items": [
                {
                    "filepath": "pkg/module.py",
                    "qualname": "pkg.module:work",
                    "start_line": 1,
                    "end_line": 30,
                    "cyclomatic_complexity": cc,
                    "risk": "low",
                    "executable_lines": 10,
                    "covered_lines": 3,
                    "coverage_permille": coverage_permille,
                    "coverage_status": "measured",
                    "coverage_hotspot": False,
                    "scope_gap_hotspot": False,
                }
            ],
        },
    }


def _tiers(document: Mapping[str, object]) -> dict[str, str]:
    """Every identity-bearing value of one document, by name: the three
    semantic tiers, the run id and each family digest of each tier."""

    digests = section(document, "integrity.digests")
    values: dict[str, str] = {
        name: str(section(digests, name).get("value"))
        for name in ("analysis_facts", "comparison", "evaluation")
    }
    values["run_id"] = report_run_identity(document)
    family_digests = section(document, "integrity.semantic.family_digests")
    for tier in family_digests:
        for family, value in section(family_digests, tier).items():
            values[f"family.{tier}.{family}"] = str(value)
    return values


def _assert_moved(
    left: Mapping[str, object],
    right: Mapping[str, object],
    *,
    moved: tuple[str, ...],
    held: tuple[str, ...] = (),
) -> None:
    left_tiers, right_tiers = _tiers(left), _tiers(right)
    for name in moved:
        assert left_tiers[name] != right_tiers[name], f"{name} did not move"
    for name in held:
        assert left_tiers[name] == right_tiers[name], f"{name} moved"


def _assert_complete(document: Mapping[str, object], *families: str) -> None:
    """Probe validity: a SAME verdict on a family that never ran would be a
    verdict about population, not about the projection."""

    producers = section(document, "integrity.semantic.population.producers")
    for family in families:
        assert producers.get(family) == "complete", family


_DEAD_CODE_MOVED = ("family.analysis.dead_code", "analysis_facts", "run_id")
_DESIGN_MOVED = ("family.analysis.design", "analysis_facts", "run_id")


@pytest.mark.parametrize(
    ("label", "changed"),
    [
        pytest.param(
            "unresolved explanation",
            _dead_code_metrics(
                reason="module_getattr",
                reachability="unresolved",
                witness="module_getattr:pkg",
            ),
            id="unresolved-reason-reachability-witness",
        ),
        pytest.param(
            "unresolved row count",
            _dead_code_metrics(unresolved_count=2),
            id="unresolved-count",
        ),
        pytest.param(
            "suppressed verdict confidence",
            _dead_code_metrics(suppressed_confidence="medium"),
            id="suppressed-items-confidence",
        ),
        pytest.param(
            "unresolved override base names",
            _dead_code_metrics(override_bases=("OtherBase",)),
            id="unresolved-overrides-base-names",
        ),
        pytest.param(
            "live root reasons",
            _dead_code_metrics(live_roots=(("pkg.module:main", "entrypoint"),)),
            id="live-root-reasons",
        ),
    ],
)
def test_v3_dead_code_statement_outside_the_findings_moves_identity(
    label: str,
    changed: dict[str, object],
) -> None:
    """Measured 2026-09-05 under generation 2: each of these left every tier
    and the run id SAME.  The dead_code family digest is now built from the
    family's own projection, so the statement moves it — and with it
    ``analysis_facts`` and ``run_id``."""

    base = _document(metrics=_dead_code_metrics())
    other = _document(metrics=changed)
    _assert_complete(base, "dead_code")
    assert section(base, "metrics.families.dead_code") != section(
        other, "metrics.families.dead_code"
    ), label  # the probe must vary the wire
    _assert_moved(base, other, moved=_DEAD_CODE_MOVED)


def test_v3_dead_code_controls_on_the_same_lane() -> None:
    """Positive controls (DIFFERENT under both generations): the realized
    world contract, and a DEAD verdict's reason, which the findings
    projection always carried."""

    base = _document(metrics=_dead_code_metrics())
    _assert_moved(
        base,
        _document(metrics=_dead_code_metrics(world="closed")),
        moved=("analysis_facts", "run_id"),
    )
    _assert_moved(
        base,
        _document(metrics=_dead_code_metrics(dead_reason="test_only_reference")),
        moved=_DEAD_CODE_MOVED,
    )


@pytest.mark.parametrize(
    ("label", "changed"),
    [
        pytest.param(
            "coupled_classes below the threshold",
            _design_metrics(coupled=("Gamma",)),
            id="coupled-classes-below-threshold",
        ),
        pytest.param(
            "cfg_cyclomatic_complexity",
            _design_metrics(cfg=9),
            id="cfg-cyclomatic-complexity",
        ),
    ],
)
def test_v3_design_statement_outside_the_findings_moves_identity(
    label: str,
    changed: dict[str, object],
) -> None:
    """Measured on real trees: ``Alpha`` coupled to ``Beta`` versus ``Gamma``
    at ``cbo=1`` shared run_id ``ede38970`` — the count was represented (the
    coupling observation lane), its witness was not.  The other two rows are
    threshold-independent statements the design findings never carry."""

    base = _document(metrics=_design_metrics())
    other = _document(metrics=changed)
    _assert_complete(base, "design")
    assert section(base, "metrics.families") != section(other, "metrics.families"), (
        label
    )
    _assert_moved(base, other, moved=_DESIGN_MOVED)


def test_v3_design_control_above_the_threshold() -> None:
    """Positive control on the same lane: above the coupling threshold the
    finding itself carries ``coupled_classes``, so the change moved the
    identity under generation 2 as well."""

    _assert_moved(
        _document(metrics=_design_metrics(cbo=15, coupled=("Beta",))),
        _document(metrics=_design_metrics(cbo=15, coupled=("Gamma",))),
        moved=_DESIGN_MOVED,
    )


# ---------------------------------------------------------------------------
# Identity v3: representation is not identity (the other boundary).
# ---------------------------------------------------------------------------

_EVERY_TIER = ("family.analysis.dead_code", "analysis_facts", "comparison", "run_id")


def test_v3_line_spans_stay_navigation_provenance() -> None:
    """The analyzer invariant: a comment edit shifts every span of the
    abstention rows and moves nothing — the whole-object projection must
    still strip the bare positions."""

    _assert_moved(
        _document(metrics=_dead_code_metrics()),
        _document(metrics=_dead_code_metrics(line_shift=100)),
        moved=(),
        held=_EVERY_TIER,
    )


def test_v3_provenance_stays_outside_every_tier() -> None:
    _assert_moved(
        _document(metrics=_dead_code_metrics()),
        _document(
            metrics=_dead_code_metrics(),
            meta={
                "python_tag": "cp399",
                "runtime": {
                    "analysis_started_at_utc": "1999-01-01T00:00:00Z",
                    "scan_root_absolute": "/elsewhere",
                },
            },
        ),
        moved=(),
        held=_EVERY_TIER,
    )


# ---------------------------------------------------------------------------
# Identity v3: the reverse direction.  A COMPARISON-domain fact is
# represented at the comparison tier and nowhere else, so ANALYSIS is the
# fixed point the ratified hierarchy builds COMPARISON on.
# ---------------------------------------------------------------------------


def _clone_item(qualname: str, start: int) -> dict[str, object]:
    return {
        "qualname": qualname,
        "filepath": "pkg/module.py",
        "start_line": start,
        "end_line": start + 11,
        "loc": 12,
        "stmt_count": 8,
        "fingerprint": _FP,
        "loc_bucket": "0-19",
        "cyclomatic_complexity": 3,
        "nesting_depth": 1,
        "risk": "low",
        "raw_hash": "raw-" + _FP[:8],
    }


def _functions_lane_trusted() -> TrustVector:
    return TrustVector(
        root_verified=True,
        lanes=(
            LaneTrust(name="clones.functions", status="trusted", reason="compatible"),
        ),
    )


def _compared_clone_document(*, new: bool) -> dict[str, object]:
    return _document(
        func_groups={
            _CLONE_KEY: [
                _clone_item("pkg.module:alpha", 1),
                _clone_item("pkg.module:beta", 20),
            ]
        },
        baseline_trust=_functions_lane_trusted(),
        new_function_group_keys={_CLONE_KEY} if new else set(),
        observed_function_clone_keys=[_CLONE_KEY],
    )


def test_v3_novelty_is_represented_at_the_comparison_tier() -> None:
    """Measured under generation 2: the same tree, compared against a baseline
    that calls its one clone group ``known`` versus ``new``, produced
    DIFFERENT analysis family digests and a DIFFERENT ``analysis_facts`` —
    the analysis tier moved on a baseline-derived fact.  Now the comparison
    family digest carries it, the analysis tier holds still, and the run id
    still differs (a different comparison is a different run)."""

    known = _compared_clone_document(new=False)
    new = _compared_clone_document(new=True)
    novelty = [
        section(document, "findings.groups.clones")["functions"][0]["novelty"]  # type: ignore[index]
        for document in (known, new)
    ]
    assert novelty == ["known", "new"]  # the probe must vary the statement
    _assert_moved(
        known,
        new,
        moved=("family.comparison.clones", "comparison", "run_id"),
        held=("family.analysis.clones", "analysis_facts"),
    )


def test_v3_analysis_facts_are_independent_of_the_baseline() -> None:
    """The same tree with and without a trusted baseline lane: every novelty
    word changes, the analysis tier does not."""

    compared = _compared_clone_document(new=True)
    uncompared = _document(
        func_groups={
            _CLONE_KEY: [
                _clone_item("pkg.module:alpha", 1),
                _clone_item("pkg.module:beta", 20),
            ]
        },
        observed_function_clone_keys=[_CLONE_KEY],
    )
    _assert_moved(
        compared,
        uncompared,
        moved=("family.comparison.clones", "comparison", "run_id"),
        held=("family.analysis.clones", "analysis_facts"),
    )


def test_v3_routed_novelty_keeps_its_entity_address() -> None:
    """A routed statement travels with the identity keys of its entity, so
    two groups swapping novelty words are two different comparison
    statements and not one multiset."""

    from codeclone.report.document.family_projection import (
        comparison_semantic_projection,
    )

    def _groups(first: str, second: str) -> Mapping[str, object]:
        return {
            "groups": {
                "dead_code": {
                    "groups": [
                        {"id": "dead_code:a", "novelty": first, "novelty_reason": None},
                        {
                            "id": "dead_code:b",
                            "novelty": second,
                            "novelty_reason": None,
                        },
                    ]
                }
            }
        }

    swapped_one = comparison_semantic_projection(
        "dead_code", findings=_groups("new", "known"), metrics={}
    )
    swapped_two = comparison_semantic_projection(
        "dead_code", findings=_groups("known", "new"), metrics={}
    )
    assert swapped_one != swapped_two
    assert swapped_one == {
        "findings.groups.dead_code": {
            "groups": [
                {"id": "dead_code:a", "novelty": "new", "novelty_reason": None},
                {"id": "dead_code:b", "novelty": "known", "novelty_reason": None},
            ]
        }
    }


def test_v3_routed_statement_moves_the_comparison_tier() -> None:
    """The comparison family digests are members of the comparison tier's
    preimage in their own right: a dead-code group's novelty has no sibling
    in the baseline projection (only clone novelty lives there), so when it
    changes, only the routed digest can move the tier — and the analysis tier
    holds still."""

    document = _document(metrics=_dead_code_metrics())
    compared = copy.deepcopy(document)
    groups = section(compared, "findings.groups.dead_code")["groups"]
    assert isinstance(groups, list) and groups
    group = groups[0]
    assert isinstance(group, dict) and group["novelty"] == "unavailable"
    group["novelty"] = "new"
    group["novelty_reason"] = None
    compared = _resealed(compared)
    assert _verify(compared) is None
    assert section(document, "baseline") == section(compared, "baseline")
    _assert_moved(
        document,
        compared,
        moved=("family.comparison.dead_code", "comparison", "run_id"),
        held=("family.analysis.dead_code", "analysis_facts"),
    )


# ---------------------------------------------------------------------------
# Identity v3: an evaluation-policy output has no analysis-tier identity.
# ---------------------------------------------------------------------------


def test_v3_risk_band_word_is_not_an_analysis_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The band word is decided by registered evaluation parameters
    (``COMPLEXITY_RISK_*``, ``COUPLING_RISK_*``, ``COHESION_RISK_MEDIUM_MAX``
    are realized health params).  The same numerator under two band words
    keeps the analysis tier; recalibrating the band itself moves the run id
    through the realized evaluation contract — the tier where the policy
    lives."""

    import codeclone.contracts as contracts

    metrics = {**_design_metrics(cbo=15), **_health_metrics(dead_code_items=0)}
    low = _document(metrics=metrics)
    high = _document(
        metrics={
            **_design_metrics(cbo=15, coupling_risk="high"),
            **_health_metrics(dead_code_items=0),
        }
    )
    finding_items = section(low, "findings.groups.design")["groups"]
    assert isinstance(finding_items, list) and finding_items  # above threshold
    _assert_moved(
        low, high, moved=(), held=("family.analysis.design", "analysis_facts")
    )

    monkeypatch.setattr(
        contracts, "COUPLING_RISK_LOW_MAX", contracts.COUPLING_RISK_LOW_MAX + 1
    )
    recalibrated = _document(metrics=metrics)
    _assert_moved(
        low, recalibrated, moved=("evaluation", "run_id"), held=("analysis_facts",)
    )


# ---------------------------------------------------------------------------
# Identity v3: the architecture test.  A new semantic lane enters the
# identity with no edit to any digest function, and it is surfaced by the
# census — never dropped silently.
# ---------------------------------------------------------------------------


def _resealed(document: dict[str, object]) -> dict[str, object]:
    """Seal a document body again through the production integrity owner:
    the same path the builder takes, over a body a producer may have grown."""

    from codeclone.report.document.integrity import (
        _build_integrity_payload,
        finalize_envelope_digest,
    )

    body = copy.deepcopy(document)
    body["integrity"] = _build_integrity_payload(
        report_schema_version=str(body["report_schema_version"]),
        observation_digest=str(section(body, "integrity.digests.observation")["value"]),
        source_facts=section(body, "source_facts"),
        baseline=section(body, "baseline"),
        evaluation=section(body, "evaluation"),
        meta=section(body, "meta"),
        inventory=section(body, "inventory"),
        findings=section(body, "findings"),
        metrics=section(body, "metrics"),
    )
    return finalize_envelope_digest(body)


_SYNTHETIC_LANE = [
    {
        "qualname": "pkg.module:ambiguous",
        "relative_path": "pkg/module.py",
        "start_line": 70,
        "end_line": 74,
        "kind": "function",
        "reason": "ambiguous_internal_binding",
        "witness": "binding:pkg.module:ambiguous|pkg.other:ambiguous",
    }
]


def test_v3_a_new_semantic_lane_enters_the_identity_naturally() -> None:
    """The fourth dead-code lane criterion C adds (``unresolved_bindings``),
    staged here synthetically: injected into the family container and
    resealed through the production owner, it moves the family digest and
    the run id, the resealed document verifies, and no digest function was
    edited to admit it.  The control reseal of the untouched body reproduces
    every digest byte-for-byte."""

    from codeclone.report.document.family_projection import semantic_member_census

    document = _document(metrics=_dead_code_metrics())
    assert _tiers(_resealed(document)) == _tiers(document)  # reseal is exact

    grown = copy.deepcopy(document)
    _mutable(grown, "metrics.families.dead_code")["unresolved_bindings"] = (
        copy.deepcopy(_SYNTHETIC_LANE)
    )
    grown = _resealed(grown)
    assert _verify(grown) is None
    _assert_moved(document, grown, moved=_DEAD_CODE_MOVED)
    census = semantic_member_census(
        "dead_code",
        findings=section(grown, "findings"),
        metrics=section(grown, "metrics"),
    )
    assert "metrics.families.dead_code/unresolved_bindings[].reason" in census
    assert "metrics.families.dead_code/unresolved_bindings[].witness" in census
    assert (
        "metrics.families.dead_code/unresolved_bindings[].start_line"
        " => navigation_provenance"
    ) in census


def test_v3_a_classified_key_does_not_enter_the_identity() -> None:
    """The opposite boundary of the lane test: the same rows placed under a
    presentation key are classified out, and the census says so."""

    from codeclone.report.document.family_projection import semantic_member_census

    document = _document(metrics=_dead_code_metrics())
    decorated = copy.deepcopy(document)
    _mutable(decorated, "metrics.families.dead_code")["display_facts"] = copy.deepcopy(
        _SYNTHETIC_LANE
    )
    decorated = _resealed(decorated)
    assert _verify(decorated) is None
    _assert_moved(document, decorated, moved=(), held=_EVERY_TIER)
    census = semantic_member_census(
        "dead_code",
        findings=section(decorated, "findings"),
        metrics=section(decorated, "metrics"),
    )
    assert "metrics.families.dead_code/display_facts => presentation" in census


# ---------------------------------------------------------------------------
# Identity v3: the classification is total, closed, and never eats an
# identity key.  The census over the maximal document is the executable
# inventory of every semantic member: a producer field that appears or
# vanishes reddens the pin with its name.
# ---------------------------------------------------------------------------


def _semantic_authority_result() -> SemanticAuthorityResult:
    """A real result object, so the observation bundle enables the
    ``semantic_authority`` lane the way the pipeline does and the authority
    producer is ``complete`` in the maximal document."""

    from codeclone.models import (
        AuthorityGovernedSink,
        AuthorityGraph,
        AuthorityRegistry,
        AuthorityRegistryEntry,
        ContractIRBuildResult,
    )

    return SemanticAuthorityResult(
        algorithm_revision="1",
        contract_ir=ContractIRBuildResult(contracts=(), sccs=(), fixpoint_iterations=1),
        graph=AuthorityGraph(nodes=(), edges=()),
        sinks=(),
        candidates=(),
        registry=AuthorityRegistry(
            version="1",
            entries=(
                AuthorityRegistryEntry(
                    contract_id="example.contract/v1",
                    canonical_owner="pkg.module:owner",
                    allowed_adapters=(),
                    forbidden_raw_inputs=(),
                    required_provenance=("producer:pkg.module:owner",),
                ),
            ),
        ),
        governed_sinks=(
            AuthorityGovernedSink(
                contract_id="example.contract/v1",
                sink_identity="pkg.module:owner",
                authority_status="authoritative",
                producer_root_ids=("producer:pkg.module:owner",),
                effect_signature="1" * 64,
                resolution_state="resolved",
            ),
        ),
    )


def _semantic_authority_metrics() -> dict[str, object]:
    """The semantic_authority family as ``core.metrics_payload`` publishes
    it: one row of each item kind, the registry and the contract IR."""

    return {
        "semantic_authority": {
            "summary": {
                "enabled": True,
                "report_only": False,
                "enforcement_enabled": True,
                "algorithm_revision": "1",
                "registry_version": "1",
                "registry_contracts": 1,
                "contracts": 1,
                "sinks": 1,
                "candidates": 1,
                "governed_sinks": 1,
                "violations": 1,
                "active_violations": 1,
                "suppressed_violations": 0,
                "scc_count": 1,
                "fixpoint_iterations": 1,
                "sinks_by_status": {
                    "authoritative": 1,
                    "adapter": 0,
                    "shadow": 0,
                    "mixed": 0,
                    "unavailable": 0,
                },
            },
            "items": [
                {
                    "item_kind": "sink",
                    "sink_identity": "pkg.module:owner",
                    "authority_status": "authoritative",
                    "producer_root_ids": ["producer:pkg.module:owner"],
                    "effect_signature": "1" * 64,
                    "resolution_state": "resolved",
                    "algorithm_revision": "1",
                },
                {
                    "item_kind": "candidate",
                    "candidate_id": "exact_contract_ir-5-pkg.module:owner",
                    "level": "exact_contract_ir",
                    "score": 5,
                    "producers": ["pkg.module:owner", "pkg.other:writer"],
                    "shared_fact": "effect:artifact_write:os.replace",
                    "independence": True,
                    "semantic_divergence": False,
                    "sink_statuses": ["authoritative"],
                    "algorithm_revision": "1",
                },
                {
                    "item_kind": "governed_sink",
                    "contract_id": "example.contract/v1",
                    "sink_identity": "pkg.module:owner",
                    "authority_status": "authoritative",
                    "producer_root_ids": ["producer:pkg.module:owner"],
                    "effect_signature": "1" * 64,
                    "resolution_state": "resolved",
                    "unresolved_reasons": [],
                    "algorithm_revision": "1",
                },
                {
                    "item_kind": "violation",
                    "violation_id": "v-1",
                    "contract_id": "example.contract/v1",
                    "kind": "shadow_producer",
                    "sink_identity": "pkg.module:owner",
                    "canonical_owner": "pkg.module:owner",
                    "authority_status": "shadow",
                    "producer_root_ids": ["producer:pkg.other:writer"],
                    "effect_signature": "2" * 64,
                    "resolution_state": "resolved",
                    "producers": ["pkg.other:writer"],
                    "suppressed": False,
                    "locations": [
                        {
                            "relative_path": "pkg/other.py",
                            "start_line": 3,
                            "end_line": 9,
                            "qualname": "pkg.other:writer",
                        }
                    ],
                    "algorithm_revision": "1",
                },
            ],
            "registry": [
                {
                    "contract_id": "example.contract/v1",
                    "canonical_owner": "pkg.module:owner",
                    "allowed_adapters": [],
                    "forbidden_raw_inputs": [],
                    "required_provenance": ["producer:pkg.module:owner"],
                }
            ],
            "contract_ir": [
                {
                    "function": "pkg.module:owner",
                    "wire": "effect(artifact_write)",
                    "effect_signature": "1" * 64,
                    "producer_root_ids": ["producer:pkg.module:owner"],
                }
            ],
        }
    }


def _metrics_only_families() -> dict[str, object]:
    """The families whose statements live in no findings group, as their
    producers publish them (``core.security_surfaces_payload``,
    ``metrics.overloaded_modules``, ``core.coverage_payload``,
    ``core.api_surface_payload`` plus the metrics-diff enrichment): the
    surfaces the findings-only ratchet never quantified over."""

    return {
        "security_surfaces": {
            "summary": {
                "items": 1,
                "modules": 1,
                "exact_items": 1,
                "category_count": 1,
                "categories": {"process_boundary": 1},
                "by_source_kind": {
                    "production": 1,
                    "tests": 0,
                    "fixtures": 0,
                    "other": 0,
                },
                "production": 1,
                "tests": 0,
                "fixtures": 0,
                "other": 0,
                "report_only": True,
            },
            "items": [
                {
                    "category": "process_boundary",
                    "capability": "subprocess_run",
                    "module": "pkg.module",
                    "filepath": "pkg/module.py",
                    "qualname": "pkg.module:run_shell",
                    "start_line": 80,
                    "end_line": 82,
                    "source_kind": "production",
                    "location_scope": "callable",
                    "classification_mode": "exact_call",
                    "evidence_kind": "call",
                    "evidence_symbol": "subprocess.run",
                }
            ],
        },
        "overloaded_modules": {
            "summary": {
                "total": 1,
                "candidates": 0,
                "population_status": "limited",
                "top_score": 0.45,
                "average_score": 0.45,
                "candidate_score_cutoff": 0.45,
            },
            "detection": {
                "version": "1",
                "scope": "report_only",
                "strategy": "project_relative_composite",
                "minimum_population": 20,
                "size_signals": ["loc", "callable_count", "complexity_total"],
                "dependency_signals": [
                    "fan_in",
                    "fan_out",
                    "total_deps",
                    "import_edges",
                ],
                "shape_signals": ["hub_balance", "reimport_ratio"],
            },
            "items": [
                {
                    "module": "pkg.module",
                    "filepath": "pkg/module.py",
                    "source_kind": "production",
                    "loc": 90,
                    "functions": 4,
                    "methods": 3,
                    "classes": 1,
                    "callable_count": 7,
                    "complexity_total": 30,
                    "complexity_max": 25,
                    "fan_in": 1,
                    "fan_out": 1,
                    "total_deps": 2,
                    "import_edges": 1,
                    "reimport_edges": 0,
                    "reimport_ratio": 0.0,
                    "instability": 0.5,
                    "hub_balance": 1.0,
                    "size_score": 1.0,
                    "dependency_score": 1.0,
                    "shape_score": 1.0,
                    "score": 0.45,
                    "candidate_status": "ranked_only",
                    "candidate_reasons": ["size_pressure"],
                }
            ],
        },
        "coverage_adoption": {
            "summary": {
                "modules": 1,
                "params_total": 6,
                "params_annotated": 5,
                "param_permille": 833,
                "returns_total": 4,
                "returns_annotated": 3,
                "return_permille": 750,
                "public_symbol_total": 4,
                "public_symbol_documented": 2,
                "docstring_permille": 500,
                "typing_any_count": 1,
                "baseline_diff_available": True,
                "param_delta": 83,
                "return_delta": 0,
                "docstring_delta": -50,
            },
            "items": [
                {
                    "module": "pkg.module",
                    "filepath": "pkg/module.py",
                    "callable_count": 4,
                    "params_total": 6,
                    "params_annotated": 5,
                    "param_permille": 833,
                    "returns_total": 4,
                    "returns_annotated": 3,
                    "return_permille": 750,
                    "any_annotation_count": 1,
                    "public_symbol_total": 4,
                    "public_symbol_documented": 2,
                    "docstring_permille": 500,
                }
            ],
        },
        "api_surface": {
            "summary": {
                "enabled": True,
                "modules": 1,
                "public_symbols": 1,
                "added": 1,
                "breaking": 1,
                "strict_types": False,
                "baseline_diff_available": True,
            },
            "items": [
                {
                    "record_kind": "symbol",
                    "module": "pkg.module",
                    "filepath": "pkg/module.py",
                    "qualname": "pkg.module:work",
                    "start_line": 1,
                    "end_line": 30,
                    "symbol_kind": "function",
                    "exported_via": "__all__",
                    "params_total": 1,
                    "params": [
                        {
                            "name": "items",
                            "kind": "positional_or_keyword",
                            "has_default": False,
                            "annotated": True,
                        }
                    ],
                    "returns_annotated": True,
                },
                {
                    "record_kind": "breaking_change",
                    "module": "pkg.module",
                    "filepath": "pkg/module.py",
                    "qualname": "pkg.module:removed",
                    "start_line": 0,
                    "end_line": 0,
                    "symbol_kind": "function",
                    "change_kind": "removed",
                    "detail": "public symbol removed",
                },
            ],
        },
    }


def _maximal_document() -> dict[str, object]:
    """Every family complete and every lane populated: the inventory the
    census law quantifies over.  Built fresh through the production builder
    on every run, so a findings-builder change reaches the census."""

    metrics: dict[str, object] = {
        **_dead_code_metrics(live_roots=(("pkg.module:main", "entrypoint"),)),
        **_design_metrics(cc=25, cfg=27),
        **_metrics_only_families(),
        **_semantic_authority_metrics(),
        "cohesion": {
            "classes": [
                {
                    "qualname": "pkg.module:Alpha",
                    "filepath": "pkg/module.py",
                    "start_line": 40,
                    "end_line": 60,
                    "lcom4": 1,
                    "risk": "low",
                    "method_count": 3,
                    "instance_var_count": 2,
                }
            ],
            "summary": {"total": 1, "average": 1.0, "max": 1, "low_cohesion": 0},
        },
        "dependencies": {
            "modules": 2,
            "edges": 2,
            "max_depth": 1,
            "avg_depth": 1.0,
            "p95_depth": 1,
            "cycles": [["pkg.a", "pkg.b"]],
            "cycle_details": [
                {
                    "modules": ["pkg.a", "pkg.b"],
                    "kind": "import_cycle",
                    "member_paths": ["pkg/a.py", "pkg/b.py"],
                }
            ],
            "longest_chains": [["pkg.a", "pkg.b"]],
            "edge_list": [
                {
                    "source": "pkg.a",
                    "target": "pkg.b",
                    "import_type": "import",
                    "line": 1,
                    "binding": "import_time",
                    "is_lazy": False,
                },
            ],
            "summary": {"baseline_diff_available": False, "new_cycles": 0},
        },
        **_health_metrics(dead_code_items=1),
    }
    dead_code = metrics["dead_code"]
    assert isinstance(dead_code, dict)
    dead_code["unreachable_statements"] = [
        {
            "qualname": "pkg.module:work",
            "filepath": "pkg/module.py",
            "start_line": 27,
            "end_line": 29,
            "reason": "after_return",
            "statement_count": 2,
            "confidence": "high",
        }
    ]
    coverage_join = metrics["coverage_join"]
    assert isinstance(coverage_join, dict)
    items = coverage_join["items"]
    assert isinstance(items, list)
    items[0]["coverage_hotspot"] = True
    items[0]["risk"] = "high"
    return _document(
        func_groups={
            _CLONE_KEY: [
                _clone_item("pkg.module:alpha", 1),
                _clone_item("pkg.module:beta", 20),
            ]
        },
        meta={
            "analysis_profile": {
                "min_loc": 6,
                "min_stmt": 4,
                "block_min_loc": 20,
                "block_min_stmt": 8,
                "segment_min_loc": 20,
                "segment_min_stmt": 10,
            },
            "analysis_mode": "full",
        },
        baseline_trust=_functions_lane_trusted(),
        new_function_group_keys={_CLONE_KEY},
        observed_function_clone_keys=[_CLONE_KEY],
        metrics=metrics,
        structural_findings=[
            StructuralFindingGroup(
                finding_kind="duplicated_branches",
                finding_key="dup-1",
                signature={"stmt_seq": "assign;return", "terminal": "return"},
                items=(
                    StructuralFindingOccurrence(
                        finding_kind="duplicated_branches",
                        finding_key="dup-1",
                        file_path="pkg/module.py",
                        qualname="pkg.module:work",
                        start=3,
                        end=6,
                        signature={"stmt_seq": "assign;return", "terminal": "return"},
                    ),
                    StructuralFindingOccurrence(
                        finding_kind="duplicated_branches",
                        finding_key="dup-1",
                        file_path="pkg/module.py",
                        qualname="pkg.module:work",
                        start=8,
                        end=11,
                        signature={"stmt_seq": "assign;return", "terminal": "return"},
                    ),
                ),
            )
        ],
        suppressed_clone_groups=(
            SuppressedCloneGroup(
                kind="function",
                group_key="golden-group",
                items=(_clone_item("tests.fixtures.golden.a:run", 10),),
                matched_patterns=("tests/fixtures/golden_*",),
                suppression_rule="golden_fixture",
                suppression_source="project_config",
            ),
        ),
        near_miss_pairs=[_near_miss_pair()],
        renamed_structure_groups=[
            RenamedStructureGroup(
                group_key="rs-1",
                members=(
                    RenamedStructureMember(
                        qualname="pkg.module:alpha",
                        filepath="pkg/module.py",
                        start_line=1,
                        end_line=12,
                        fingerprint="fp-alpha",
                    ),
                    RenamedStructureMember(
                        qualname="pkg.module:gamma",
                        filepath="pkg/other.py",
                        start_line=1,
                        end_line=12,
                        fingerprint="fp-gamma",
                    ),
                ),
                distinct_exact_fingerprints=2,
            )
        ],
        semantic_authority=_semantic_authority_result(),
    )


def _projected_families() -> tuple[str, ...]:
    """Every registered family with an identity projection — analysis and
    evaluation alike — in registry order."""

    from codeclone.contracts.report_identity import (
        producer_spec,
        registered_families,
        spec_document_sections,
    )

    return tuple(
        family
        for family in registered_families()
        if spec_document_sections(producer_spec(family))
    )


_SEMANTIC_MEMBER_CENSUS_V3: dict[str, tuple[str, ...]] = {
    "api_surface": (
        "metrics.families.api_surface/items[].change_kind",
        "metrics.families.api_surface/items[].detail",
        "metrics.families.api_surface/items[].end_line => navigation_provenance",
        "metrics.families.api_surface/items[].exported_via",
        "metrics.families.api_surface/items[].module",
        "metrics.families.api_surface/items[].params[].annotated",
        "metrics.families.api_surface/items[].params[].has_default",
        "metrics.families.api_surface/items[].params[].kind",
        "metrics.families.api_surface/items[].params[].name",
        "metrics.families.api_surface/items[].params_total",
        "metrics.families.api_surface/items[].qualname",
        "metrics.families.api_surface/items[].record_kind",
        "metrics.families.api_surface/items[].relative_path",
        "metrics.families.api_surface/items[].returns_annotated",
        "metrics.families.api_surface/items[].start_line => navigation_provenance",
        "metrics.families.api_surface/items[].symbol_kind",
        "metrics.families.api_surface/items[record_kind=breaking_change] => comparison",
        "metrics.families.api_surface/items_truncated",
        "metrics.families.api_surface/summary.added => comparison",
        "metrics.families.api_surface/summary.baseline_diff_available => comparison",
        "metrics.families.api_surface/summary.breaking => comparison",
        "metrics.families.api_surface/summary.enabled",
        "metrics.families.api_surface/summary.modules",
        "metrics.families.api_surface/summary.public_symbols",
        "metrics.families.api_surface/summary.strict_types",
    ),
    "authority": (
        "findings.groups.authority/groups[].category",
        "findings.groups.authority/groups[].confidence",
        "findings.groups.authority/groups[].count",
        "findings.groups.authority/groups[].facts.algorithm_revision",
        "findings.groups.authority/groups[].facts.authority_status",
        "findings.groups.authority/groups[].facts.canonical_owner",
        "findings.groups.authority/groups[].facts.contract_id",
        "findings.groups.authority/groups[].facts.effect_signature",
        "findings.groups.authority/groups[].facts.producer_root_ids[]",
        "findings.groups.authority/groups[].facts.producers[]",
        "findings.groups.authority/groups[].facts.resolution_state",
        "findings.groups.authority/groups[].facts.sink_identity",
        "findings.groups.authority/groups[].facts.violation_id",
        "findings.groups.authority/groups[].facts.violation_kind",
        "findings.groups.authority/groups[].family",
        "findings.groups.authority/groups[].id",
        "findings.groups.authority/groups[].items[].end_line => navigation_provenance",
        "findings.groups.authority/groups[].items[].qualname",
        "findings.groups.authority/groups[].items[].relative_path",
        "findings.groups.authority/groups[].items[].source_kind",
        "findings.groups.authority/groups[].items[].start_line"
        " => navigation_provenance",
        "findings.groups.authority/groups[].kind",
        "findings.groups.authority/groups[].novelty => comparison",
        "findings.groups.authority/groups[].novelty_reason => comparison",
        "findings.groups.authority/groups[].priority",
        "findings.groups.authority/groups[].severity",
        "findings.groups.authority/groups[].source_scope.breakdown.fixtures",
        "findings.groups.authority/groups[].source_scope.breakdown.other",
        "findings.groups.authority/groups[].source_scope.breakdown.production",
        "findings.groups.authority/groups[].source_scope.breakdown.tests",
        "findings.groups.authority/groups[].source_scope.dominant_kind",
        "findings.groups.authority/groups[].source_scope.impact_scope",
        "findings.groups.authority/groups[].spread.files",
        "findings.groups.authority/groups[].spread.functions",
        "metrics.families.semantic_authority/contract_ir[].effect_signature",
        "metrics.families.semantic_authority/contract_ir[].function",
        "metrics.families.semantic_authority/contract_ir[].producer_root_ids[]",
        "metrics.families.semantic_authority/contract_ir[].wire",
        "metrics.families.semantic_authority/items[].algorithm_revision",
        "metrics.families.semantic_authority/items[].authority_status",
        "metrics.families.semantic_authority/items[].candidate_id",
        "metrics.families.semantic_authority/items[].canonical_owner",
        "metrics.families.semantic_authority/items[].contract_id",
        "metrics.families.semantic_authority/items[].effect_signature",
        "metrics.families.semantic_authority/items[].independence",
        "metrics.families.semantic_authority/items[].item_kind",
        "metrics.families.semantic_authority/items[].kind",
        "metrics.families.semantic_authority/items[].level",
        "metrics.families.semantic_authority/items[].locations",
        "metrics.families.semantic_authority/items[].locations[].end_line"
        " => navigation_provenance",
        "metrics.families.semantic_authority/items[].locations[].qualname",
        "metrics.families.semantic_authority/items[].locations[].relative_path",
        "metrics.families.semantic_authority/items[].locations[].start_line"
        " => navigation_provenance",
        "metrics.families.semantic_authority/items[].producer_root_ids",
        "metrics.families.semantic_authority/items[].producer_root_ids[]",
        "metrics.families.semantic_authority/items[].producers",
        "metrics.families.semantic_authority/items[].producers[]",
        "metrics.families.semantic_authority/items[].resolution_state",
        "metrics.families.semantic_authority/items[].score",
        "metrics.families.semantic_authority/items[].semantic_divergence",
        "metrics.families.semantic_authority/items[].shared_fact",
        "metrics.families.semantic_authority/items[].sink_identity",
        "metrics.families.semantic_authority/items[].sink_statuses",
        "metrics.families.semantic_authority/items[].sink_statuses[]",
        "metrics.families.semantic_authority/items[].source_kind",
        "metrics.families.semantic_authority/items[].suppressed",
        "metrics.families.semantic_authority/items[].unresolved_reasons",
        "metrics.families.semantic_authority/items[].violation_id",
        "metrics.families.semantic_authority/items_truncated",
        "metrics.families.semantic_authority/registry[].allowed_adapters",
        "metrics.families.semantic_authority/registry[].canonical_owner",
        "metrics.families.semantic_authority/registry[].contract_id",
        "metrics.families.semantic_authority/registry[].forbidden_raw_inputs",
        "metrics.families.semantic_authority/registry[].required_provenance[]",
        "metrics.families.semantic_authority/summary.active_violations",
        "metrics.families.semantic_authority/summary.algorithm_revision",
        "metrics.families.semantic_authority/summary.candidates",
        "metrics.families.semantic_authority/summary.contracts",
        "metrics.families.semantic_authority/summary.enabled",
        "metrics.families.semantic_authority/summary.enforcement_enabled",
        "metrics.families.semantic_authority/summary.fixpoint_iterations",
        "metrics.families.semantic_authority/summary.governed_sinks",
        "metrics.families.semantic_authority/summary.registry_contracts",
        "metrics.families.semantic_authority/summary.registry_version",
        "metrics.families.semantic_authority/summary.report_only",
        "metrics.families.semantic_authority/summary.scc_count",
        "metrics.families.semantic_authority/summary.sinks",
        "metrics.families.semantic_authority/summary.sinks_by_status.adapter",
        "metrics.families.semantic_authority/summary.sinks_by_status.authoritative",
        "metrics.families.semantic_authority/summary.sinks_by_status.mixed",
        "metrics.families.semantic_authority/summary.sinks_by_status.shadow",
        "metrics.families.semantic_authority/summary.sinks_by_status.unavailable",
        "metrics.families.semantic_authority/summary.suppressed_violations",
        "metrics.families.semantic_authority/summary.violations",
    ),
    "clones": (
        "findings.groups.clones/blocks",
        "findings.groups.clones/functions[].category",
        "findings.groups.clones/functions[].clone_kind",
        "findings.groups.clones/functions[].clone_type",
        "findings.groups.clones/functions[].confidence",
        "findings.groups.clones/functions[].count",
        "findings.groups.clones/functions[].facts.group_arity",
        "findings.groups.clones/functions[].facts.group_key",
        "findings.groups.clones/functions[].facts.loc_buckets[]",
        "findings.groups.clones/functions[].family",
        "findings.groups.clones/functions[].id",
        "findings.groups.clones/functions[].items[].cyclomatic_complexity",
        "findings.groups.clones/functions[].items[].end_line => navigation_provenance",
        "findings.groups.clones/functions[].items[].fingerprint",
        "findings.groups.clones/functions[].items[].loc",
        "findings.groups.clones/functions[].items[].loc_bucket",
        "findings.groups.clones/functions[].items[].nesting_depth",
        "findings.groups.clones/functions[].items[].qualname",
        "findings.groups.clones/functions[].items[].raw_hash",
        "findings.groups.clones/functions[].items[].relative_path",
        "findings.groups.clones/functions[].items[].risk => evaluation_policy_output",
        "findings.groups.clones/functions[].items[].start_line"
        " => navigation_provenance",
        "findings.groups.clones/functions[].items[].stmt_count",
        "findings.groups.clones/functions[].kind",
        "findings.groups.clones/functions[].novelty => comparison",
        "findings.groups.clones/functions[].novelty_reason => comparison",
        "findings.groups.clones/functions[].priority",
        "findings.groups.clones/functions[].severity",
        "findings.groups.clones/functions[].source_scope.breakdown.fixtures",
        "findings.groups.clones/functions[].source_scope.breakdown.other",
        "findings.groups.clones/functions[].source_scope.breakdown.production",
        "findings.groups.clones/functions[].source_scope.breakdown.tests",
        "findings.groups.clones/functions[].source_scope.dominant_kind",
        "findings.groups.clones/functions[].source_scope.impact_scope",
        "findings.groups.clones/functions[].spread.files",
        "findings.groups.clones/functions[].spread.functions",
        "findings.groups.clones/segments",
        "findings.groups.clones/suppressed.blocks",
        "findings.groups.clones/suppressed.functions[].category",
        "findings.groups.clones/suppressed.functions[].clone_kind",
        "findings.groups.clones/suppressed.functions[].clone_type",
        "findings.groups.clones/suppressed.functions[].confidence",
        "findings.groups.clones/suppressed.functions[].count",
        "findings.groups.clones/suppressed.functions[].facts.group_arity",
        "findings.groups.clones/suppressed.functions[].facts.group_key",
        "findings.groups.clones/suppressed.functions[].facts.loc_buckets[]",
        "findings.groups.clones/suppressed.functions[].family",
        "findings.groups.clones/suppressed.functions[].id",
        "findings.groups.clones/suppressed.functions[].items[].cyclomatic_complexity",
        "findings.groups.clones/suppressed.functions[].items[].end_line"
        " => navigation_provenance",
        "findings.groups.clones/suppressed.functions[].items[].fingerprint",
        "findings.groups.clones/suppressed.functions[].items[].loc",
        "findings.groups.clones/suppressed.functions[].items[].loc_bucket",
        "findings.groups.clones/suppressed.functions[].items[].nesting_depth",
        "findings.groups.clones/suppressed.functions[].items[].qualname",
        "findings.groups.clones/suppressed.functions[].items[].raw_hash",
        "findings.groups.clones/suppressed.functions[].items[].relative_path",
        "findings.groups.clones/suppressed.functions[].items[].risk"
        " => evaluation_policy_output",
        "findings.groups.clones/suppressed.functions[].items[].start_line"
        " => navigation_provenance",
        "findings.groups.clones/suppressed.functions[].items[].stmt_count",
        "findings.groups.clones/suppressed.functions[].kind",
        "findings.groups.clones/suppressed.functions[].matched_patterns[]",
        "findings.groups.clones/suppressed.functions[].priority",
        "findings.groups.clones/suppressed.functions[].severity",
        "findings.groups.clones/suppressed.functions[].source_scope.breakdown.fixtures",
        "findings.groups.clones/suppressed.functions[].source_scope.breakdown.other",
        "findings.groups.clones/suppressed.functions[].source_scope.breakdown."
        "production",
        "findings.groups.clones/suppressed.functions[].source_scope.breakdown.tests",
        "findings.groups.clones/suppressed.functions[].source_scope.dominant_kind",
        "findings.groups.clones/suppressed.functions[].source_scope.impact_scope",
        "findings.groups.clones/suppressed.functions[].spread.files",
        "findings.groups.clones/suppressed.functions[].spread.functions",
        "findings.groups.clones/suppressed.functions[].suppression_rule",
        "findings.groups.clones/suppressed.functions[].suppression_source",
        "findings.groups.clones/suppressed.segments",
    ),
    "coverage_adoption": (
        "metrics.families.coverage_adoption/items[].any_annotation_count",
        "metrics.families.coverage_adoption/items[].callable_count",
        "metrics.families.coverage_adoption/items[].docstring_permille",
        "metrics.families.coverage_adoption/items[].module",
        "metrics.families.coverage_adoption/items[].param_permille",
        "metrics.families.coverage_adoption/items[].params_annotated",
        "metrics.families.coverage_adoption/items[].params_total",
        "metrics.families.coverage_adoption/items[].public_symbol_documented",
        "metrics.families.coverage_adoption/items[].public_symbol_total",
        "metrics.families.coverage_adoption/items[].relative_path",
        "metrics.families.coverage_adoption/items[].return_permille",
        "metrics.families.coverage_adoption/items[].returns_annotated",
        "metrics.families.coverage_adoption/items[].returns_total",
        "metrics.families.coverage_adoption/items_truncated",
        "metrics.families.coverage_adoption/summary.baseline_diff_available"
        " => comparison",
        "metrics.families.coverage_adoption/summary.docstring_delta => comparison",
        "metrics.families.coverage_adoption/summary.docstring_permille",
        "metrics.families.coverage_adoption/summary.modules",
        "metrics.families.coverage_adoption/summary.param_delta => comparison",
        "metrics.families.coverage_adoption/summary.param_permille",
        "metrics.families.coverage_adoption/summary.params_annotated",
        "metrics.families.coverage_adoption/summary.params_total",
        "metrics.families.coverage_adoption/summary.public_symbol_documented",
        "metrics.families.coverage_adoption/summary.public_symbol_total",
        "metrics.families.coverage_adoption/summary.return_delta => comparison",
        "metrics.families.coverage_adoption/summary.return_permille",
        "metrics.families.coverage_adoption/summary.returns_annotated",
        "metrics.families.coverage_adoption/summary.returns_total",
        "metrics.families.coverage_adoption/summary.typing_any_count",
    ),
    "coverage_join": (
        "metrics.families.coverage_join/items[].coverage_hotspot"
        " => evaluation_policy_output",
        "metrics.families.coverage_join/items[].coverage_permille",
        "metrics.families.coverage_join/items[].coverage_status",
        "metrics.families.coverage_join/items[].covered_lines",
        "metrics.families.coverage_join/items[].cyclomatic_complexity",
        "metrics.families.coverage_join/items[].end_line => navigation_provenance",
        "metrics.families.coverage_join/items[].executable_lines",
        "metrics.families.coverage_join/items[].qualname",
        "metrics.families.coverage_join/items[].relative_path",
        "metrics.families.coverage_join/items[].risk => evaluation_policy_output",
        "metrics.families.coverage_join/items[].scope_gap_hotspot"
        " => evaluation_policy_output",
        "metrics.families.coverage_join/items[].start_line => navigation_provenance",
        "metrics.families.coverage_join/items_truncated",
        "metrics.families.coverage_join/summary.coverage_hotspots"
        " => evaluation_policy_output",
        "metrics.families.coverage_join/summary.files",
        "metrics.families.coverage_join/summary.hotspot_threshold_percent"
        " => evaluation_policy_output",
        "metrics.families.coverage_join/summary.invalid_reason",
        "metrics.families.coverage_join/summary.measured_units",
        "metrics.families.coverage_join/summary.missing_from_report_units",
        "metrics.families.coverage_join/summary.overall_covered_lines",
        "metrics.families.coverage_join/summary.overall_executable_lines",
        "metrics.families.coverage_join/summary.overall_permille",
        "metrics.families.coverage_join/summary.scope_gap_hotspots"
        " => evaluation_policy_output",
        "metrics.families.coverage_join/summary.source => configuration_provenance",
        "metrics.families.coverage_join/summary.status",
        "metrics.families.coverage_join/summary.units",
    ),
    "dead_code": (
        "findings.groups.dead_code/groups[].category",
        "findings.groups.dead_code/groups[].confidence",
        "findings.groups.dead_code/groups[].count",
        "findings.groups.dead_code/groups[].facts.confidence",
        "findings.groups.dead_code/groups[].facts.kind",
        "findings.groups.dead_code/groups[].facts.policy_version",
        "findings.groups.dead_code/groups[].facts.reason",
        "findings.groups.dead_code/groups[].facts.statement_count",
        "findings.groups.dead_code/groups[].facts.test_reference_sources",
        "findings.groups.dead_code/groups[].family",
        "findings.groups.dead_code/groups[].id",
        "findings.groups.dead_code/groups[].items[].end_line => navigation_provenance",
        "findings.groups.dead_code/groups[].items[].qualname",
        "findings.groups.dead_code/groups[].items[].relative_path",
        "findings.groups.dead_code/groups[].items[].start_line"
        " => navigation_provenance",
        "findings.groups.dead_code/groups[].kind",
        "findings.groups.dead_code/groups[].novelty => comparison",
        "findings.groups.dead_code/groups[].novelty_reason => comparison",
        "findings.groups.dead_code/groups[].priority",
        "findings.groups.dead_code/groups[].severity",
        "findings.groups.dead_code/groups[].source_scope.breakdown.fixtures",
        "findings.groups.dead_code/groups[].source_scope.breakdown.other",
        "findings.groups.dead_code/groups[].source_scope.breakdown.production",
        "findings.groups.dead_code/groups[].source_scope.breakdown.tests",
        "findings.groups.dead_code/groups[].source_scope.dominant_kind",
        "findings.groups.dead_code/groups[].source_scope.impact_scope",
        "findings.groups.dead_code/groups[].spread.files",
        "findings.groups.dead_code/groups[].spread.functions",
        "metrics.families.dead_code/items[].confidence",
        "metrics.families.dead_code/items[].end_line => navigation_provenance",
        "metrics.families.dead_code/items[].kind",
        "metrics.families.dead_code/items[].qualname",
        "metrics.families.dead_code/items[].reason",
        "metrics.families.dead_code/items[].relative_path",
        "metrics.families.dead_code/items[].start_line => navigation_provenance",
        "metrics.families.dead_code/items[].test_reference_sources",
        "metrics.families.dead_code/items_truncated",
        "metrics.families.dead_code/live_root_reasons[].qualname",
        "metrics.families.dead_code/live_root_reasons[].reason",
        "metrics.families.dead_code/summary.baseline_diff_available => comparison",
        "metrics.families.dead_code/summary.high_confidence",
        "metrics.families.dead_code/summary.live_roots",
        "metrics.families.dead_code/summary.new_items => comparison",
        "metrics.families.dead_code/summary.suppressed",
        "metrics.families.dead_code/summary.total",
        "metrics.families.dead_code/summary.unreachable_statements",
        "metrics.families.dead_code/summary.unresolved",
        "metrics.families.dead_code/summary.unresolved_external_override",
        "metrics.families.dead_code/summary.world_contract",
        "metrics.families.dead_code/suppressed_items[].confidence",
        "metrics.families.dead_code/suppressed_items[].end_line"
        " => navigation_provenance",
        "metrics.families.dead_code/suppressed_items[].kind",
        "metrics.families.dead_code/suppressed_items[].qualname",
        "metrics.families.dead_code/suppressed_items[].reason",
        "metrics.families.dead_code/suppressed_items[].relative_path",
        "metrics.families.dead_code/suppressed_items[].start_line"
        " => navigation_provenance",
        "metrics.families.dead_code/suppressed_items[].suppressed_by[].rule",
        "metrics.families.dead_code/suppressed_items[].suppressed_by[].source",
        "metrics.families.dead_code/suppressed_items[].suppression_rule",
        "metrics.families.dead_code/suppressed_items[].suppression_source",
        "metrics.families.dead_code/suppressed_items[].test_reference_sources",
        "metrics.families.dead_code/unreachable_statements[].confidence",
        "metrics.families.dead_code/unreachable_statements[].end_line"
        " => navigation_provenance",
        "metrics.families.dead_code/unreachable_statements[].qualname",
        "metrics.families.dead_code/unreachable_statements[].reason",
        "metrics.families.dead_code/unreachable_statements[].relative_path",
        "metrics.families.dead_code/unreachable_statements[].start_line"
        " => navigation_provenance",
        "metrics.families.dead_code/unreachable_statements[].statement_count",
        "metrics.families.dead_code/unresolved[].end_line => navigation_provenance",
        "metrics.families.dead_code/unresolved[].kind",
        "metrics.families.dead_code/unresolved[].qualname",
        "metrics.families.dead_code/unresolved[].reachability",
        "metrics.families.dead_code/unresolved[].reason",
        "metrics.families.dead_code/unresolved[].relative_path",
        "metrics.families.dead_code/unresolved[].start_line => navigation_provenance",
        "metrics.families.dead_code/unresolved[].witness",
        "metrics.families.dead_code/unresolved[].world_contract",
        "metrics.families.dead_code/unresolved_overrides[].base_names[]",
        "metrics.families.dead_code/unresolved_overrides[].class_qualname",
        "metrics.families.dead_code/unresolved_overrides[].end_line"
        " => navigation_provenance",
        "metrics.families.dead_code/unresolved_overrides[].kind",
        "metrics.families.dead_code/unresolved_overrides[].qualname",
        "metrics.families.dead_code/unresolved_overrides[].reason",
        "metrics.families.dead_code/unresolved_overrides[].relative_path",
        "metrics.families.dead_code/unresolved_overrides[].start_line"
        " => navigation_provenance",
    ),
    "design": (
        "findings.groups.design/groups[].category",
        "findings.groups.design/groups[].confidence",
        "findings.groups.design/groups[].count",
        "findings.groups.design/groups[].facts.coverage_hotspot",
        "findings.groups.design/groups[].facts.coverage_permille",
        "findings.groups.design/groups[].facts.coverage_status",
        "findings.groups.design/groups[].facts.covered_lines",
        "findings.groups.design/groups[].facts.cycle_length",
        "findings.groups.design/groups[].facts.cyclomatic_complexity",
        "findings.groups.design/groups[].facts.detail",
        "findings.groups.design/groups[].facts.executable_lines",
        "findings.groups.design/groups[].facts.hotspot_threshold_percent",
        "findings.groups.design/groups[].facts.measured",
        "findings.groups.design/groups[].facts.nesting_depth",
        "findings.groups.design/groups[].facts.scope_gap_hotspot",
        "findings.groups.design/groups[].family",
        "findings.groups.design/groups[].id",
        "findings.groups.design/groups[].items[].coverage_hotspot",
        "findings.groups.design/groups[].items[].coverage_permille",
        "findings.groups.design/groups[].items[].coverage_status",
        "findings.groups.design/groups[].items[].covered_lines",
        "findings.groups.design/groups[].items[].cyclomatic_complexity",
        "findings.groups.design/groups[].items[].end_line => navigation_provenance",
        "findings.groups.design/groups[].items[].executable_lines",
        "findings.groups.design/groups[].items[].module",
        "findings.groups.design/groups[].items[].nesting_depth",
        "findings.groups.design/groups[].items[].qualname",
        "findings.groups.design/groups[].items[].relative_path",
        "findings.groups.design/groups[].items[].risk => evaluation_policy_output",
        "findings.groups.design/groups[].items[].scope_gap_hotspot",
        "findings.groups.design/groups[].items[].source_kind",
        "findings.groups.design/groups[].items[].start_line => navigation_provenance",
        "findings.groups.design/groups[].kind",
        "findings.groups.design/groups[].novelty => comparison",
        "findings.groups.design/groups[].novelty_reason => comparison",
        "findings.groups.design/groups[].priority",
        "findings.groups.design/groups[].severity",
        "findings.groups.design/groups[].source_scope.breakdown.fixtures",
        "findings.groups.design/groups[].source_scope.breakdown.other",
        "findings.groups.design/groups[].source_scope.breakdown.production",
        "findings.groups.design/groups[].source_scope.breakdown.tests",
        "findings.groups.design/groups[].source_scope.dominant_kind",
        "findings.groups.design/groups[].source_scope.impact_scope",
        "findings.groups.design/groups[].spread.files",
        "findings.groups.design/groups[].spread.functions",
        "metrics.families.cohesion/items[].end_line => navigation_provenance",
        "metrics.families.cohesion/items[].instance_var_count",
        "metrics.families.cohesion/items[].lcom4",
        "metrics.families.cohesion/items[].method_count",
        "metrics.families.cohesion/items[].qualname",
        "metrics.families.cohesion/items[].relative_path",
        "metrics.families.cohesion/items[].risk => evaluation_policy_output",
        "metrics.families.cohesion/items[].start_line => navigation_provenance",
        "metrics.families.cohesion/items_truncated",
        "metrics.families.cohesion/summary.average",
        "metrics.families.cohesion/summary.low_cohesion => evaluation_policy_output",
        "metrics.families.cohesion/summary.max",
        "metrics.families.cohesion/summary.total",
        "metrics.families.complexity/items[].cfg_cyclomatic_complexity",
        "metrics.families.complexity/items[].cyclomatic_complexity",
        "metrics.families.complexity/items[].end_line => navigation_provenance",
        "metrics.families.complexity/items[].nesting_depth",
        "metrics.families.complexity/items[].qualname",
        "metrics.families.complexity/items[].relative_path",
        "metrics.families.complexity/items[].risk => evaluation_policy_output",
        "metrics.families.complexity/items[].start_line => navigation_provenance",
        "metrics.families.complexity/items_truncated",
        "metrics.families.complexity/summary.average",
        "metrics.families.complexity/summary.baseline_diff_available => comparison",
        "metrics.families.complexity/summary.high_risk => evaluation_policy_output",
        "metrics.families.complexity/summary.max",
        "metrics.families.complexity/summary.new_high_risk => comparison",
        "metrics.families.complexity/summary.total",
        "metrics.families.coupling/items[].cbo",
        "metrics.families.coupling/items[].coupled_classes[]",
        "metrics.families.coupling/items[].end_line => navigation_provenance",
        "metrics.families.coupling/items[].qualname",
        "metrics.families.coupling/items[].relative_path",
        "metrics.families.coupling/items[].risk => evaluation_policy_output",
        "metrics.families.coupling/items[].start_line => navigation_provenance",
        "metrics.families.coupling/items_truncated",
        "metrics.families.coupling/summary.average",
        "metrics.families.coupling/summary.baseline_diff_available => comparison",
        "metrics.families.coupling/summary.high_risk => evaluation_policy_output",
        "metrics.families.coupling/summary.max",
        "metrics.families.coupling/summary.new_high_risk => comparison",
        "metrics.families.coupling/summary.total",
        "metrics.families.dependencies/cycle_details[].kind",
        "metrics.families.dependencies/cycle_details[].member_paths[]",
        "metrics.families.dependencies/cycle_details[].modules[]",
        "metrics.families.dependencies/cycles[][]",
        "metrics.families.dependencies/dynamic_boundaries",
        "metrics.families.dependencies/items[].binding",
        "metrics.families.dependencies/items[].import_type",
        "metrics.families.dependencies/items[].is_lazy",
        "metrics.families.dependencies/items[].line => navigation_provenance",
        "metrics.families.dependencies/items[].source",
        "metrics.families.dependencies/items[].target",
        "metrics.families.dependencies/items_truncated",
        "metrics.families.dependencies/longest_chains[][]",
        "metrics.families.dependencies/summary.avg_depth",
        "metrics.families.dependencies/summary.baseline_diff_available => comparison",
        "metrics.families.dependencies/summary.cycles",
        "metrics.families.dependencies/summary.deferred_cycles",
        "metrics.families.dependencies/summary.edges",
        "metrics.families.dependencies/summary.import_cycles",
        "metrics.families.dependencies/summary.max_depth",
        "metrics.families.dependencies/summary.modules",
        "metrics.families.dependencies/summary.new_cycles => comparison",
        "metrics.families.dependencies/summary.new_deferred_cycles => comparison",
        "metrics.families.dependencies/summary.new_import_cycles => comparison",
        "metrics.families.dependencies/summary.p95_depth",
    ),
    "health": (
        "metrics.families.health/items",
        "metrics.families.health/items_truncated",
        "metrics.families.health/summary.baseline_diff_available",
        "metrics.families.health/summary.delta",
        "metrics.families.health/summary.dimensions.clones",
        "metrics.families.health/summary.dimensions.cohesion",
        "metrics.families.health/summary.dimensions.complexity",
        "metrics.families.health/summary.dimensions.coupling",
        "metrics.families.health/summary.dimensions.coverage",
        "metrics.families.health/summary.dimensions.dead_code",
        "metrics.families.health/summary.dimensions.dependencies",
        "metrics.families.health/summary.grade",
        "metrics.families.health/summary.population => consumed_analysis_fact",
        "metrics.families.health/summary.score",
    ),
    "near_miss": (
        "findings.groups.near_miss/algorithm_revision",
        "findings.groups.near_miss/count",
        "findings.groups.near_miss/gate_relevant",
        "findings.groups.near_miss/max_edit_statements",
        "findings.groups.near_miss/novelty => comparison",
        "findings.groups.near_miss/pairs[].edit_kind",
        "findings.groups.near_miss/pairs[].edit_statements",
        "findings.groups.near_miss/pairs[].members[].differing_end_line"
        " => navigation_provenance",
        "findings.groups.near_miss/pairs[].members[].differing_start_line"
        " => navigation_provenance",
        "findings.groups.near_miss/pairs[].members[].end_line => navigation_provenance",
        "findings.groups.near_miss/pairs[].members[].qualname",
        "findings.groups.near_miss/pairs[].members[].relative_path",
        "findings.groups.near_miss/pairs[].members[].start_line"
        " => navigation_provenance",
        "findings.groups.near_miss/pairs[].pair_key",
        "findings.groups.near_miss/pairs[].token_domain",
        "findings.groups.near_miss/state",
        "findings.groups.near_miss/tier",
    ),
    "overloaded_modules": (
        "metrics.families.overloaded_modules/detection.dependency_signals[]",
        "metrics.families.overloaded_modules/detection.minimum_population",
        "metrics.families.overloaded_modules/detection.scope",
        "metrics.families.overloaded_modules/detection.shape_signals[]",
        "metrics.families.overloaded_modules/detection.size_signals[]",
        "metrics.families.overloaded_modules/detection.strategy",
        "metrics.families.overloaded_modules/detection.version",
        "metrics.families.overloaded_modules/items[].callable_count",
        "metrics.families.overloaded_modules/items[].candidate_reasons[]",
        "metrics.families.overloaded_modules/items[].candidate_status",
        "metrics.families.overloaded_modules/items[].classes",
        "metrics.families.overloaded_modules/items[].complexity_max",
        "metrics.families.overloaded_modules/items[].complexity_total",
        "metrics.families.overloaded_modules/items[].dependency_score",
        "metrics.families.overloaded_modules/items[].fan_in",
        "metrics.families.overloaded_modules/items[].fan_out",
        "metrics.families.overloaded_modules/items[].functions",
        "metrics.families.overloaded_modules/items[].hub_balance",
        "metrics.families.overloaded_modules/items[].import_edges",
        "metrics.families.overloaded_modules/items[].instability",
        "metrics.families.overloaded_modules/items[].loc => navigation_provenance",
        "metrics.families.overloaded_modules/items[].methods",
        "metrics.families.overloaded_modules/items[].module",
        "metrics.families.overloaded_modules/items[].reimport_edges",
        "metrics.families.overloaded_modules/items[].reimport_ratio",
        "metrics.families.overloaded_modules/items[].relative_path",
        "metrics.families.overloaded_modules/items[].score",
        "metrics.families.overloaded_modules/items[].shape_score",
        "metrics.families.overloaded_modules/items[].size_score",
        "metrics.families.overloaded_modules/items[].source_kind",
        "metrics.families.overloaded_modules/items[].total_deps",
        "metrics.families.overloaded_modules/items_truncated",
        "metrics.families.overloaded_modules/summary.average_score",
        "metrics.families.overloaded_modules/summary.candidate_score_cutoff",
        "metrics.families.overloaded_modules/summary.candidates",
        "metrics.families.overloaded_modules/summary.population_status",
        "metrics.families.overloaded_modules/summary.top_score",
        "metrics.families.overloaded_modules/summary.total",
    ),
    "renamed_structure": (
        "findings.groups.renamed_structure/algorithm_revision",
        "findings.groups.renamed_structure/count",
        "findings.groups.renamed_structure/gate_relevant",
        "findings.groups.renamed_structure/groups[].distinct_exact_fingerprints",
        "findings.groups.renamed_structure/groups[].group_key",
        "findings.groups.renamed_structure/groups[].member_count",
        "findings.groups.renamed_structure/groups[].members[].end_line"
        " => navigation_provenance",
        "findings.groups.renamed_structure/groups[].members[].fingerprint",
        "findings.groups.renamed_structure/groups[].members[].qualname",
        "findings.groups.renamed_structure/groups[].members[].relative_path",
        "findings.groups.renamed_structure/groups[].members[].start_line"
        " => navigation_provenance",
        "findings.groups.renamed_structure/novelty => comparison",
        "findings.groups.renamed_structure/state",
        "findings.groups.renamed_structure/tier",
    ),
    "security_surfaces": (
        "metrics.families.security_surfaces/items[].capability",
        "metrics.families.security_surfaces/items[].category",
        "metrics.families.security_surfaces/items[].classification_mode",
        "metrics.families.security_surfaces/items[].end_line => navigation_provenance",
        "metrics.families.security_surfaces/items[].evidence_kind",
        "metrics.families.security_surfaces/items[].evidence_symbol",
        "metrics.families.security_surfaces/items[].location_scope",
        "metrics.families.security_surfaces/items[].module",
        "metrics.families.security_surfaces/items[].qualname",
        "metrics.families.security_surfaces/items[].relative_path",
        "metrics.families.security_surfaces/items[].source_kind",
        "metrics.families.security_surfaces/items[].start_line"
        " => navigation_provenance",
        "metrics.families.security_surfaces/items_truncated",
        "metrics.families.security_surfaces/summary.by_source_kind.fixtures",
        "metrics.families.security_surfaces/summary.by_source_kind.other",
        "metrics.families.security_surfaces/summary.by_source_kind.production",
        "metrics.families.security_surfaces/summary.by_source_kind.tests",
        "metrics.families.security_surfaces/summary.categories.process_boundary",
        "metrics.families.security_surfaces/summary.category_count",
        "metrics.families.security_surfaces/summary.exact_items",
        "metrics.families.security_surfaces/summary.fixtures",
        "metrics.families.security_surfaces/summary.items",
        "metrics.families.security_surfaces/summary.modules",
        "metrics.families.security_surfaces/summary.other",
        "metrics.families.security_surfaces/summary.production",
        "metrics.families.security_surfaces/summary.report_only",
        "metrics.families.security_surfaces/summary.tests",
    ),
    "structural": (
        "findings.groups.structural/groups[].category",
        "findings.groups.structural/groups[].confidence",
        "findings.groups.structural/groups[].count",
        "findings.groups.structural/groups[].facts.call_bucket",
        "findings.groups.structural/groups[].facts.non_overlapping",
        "findings.groups.structural/groups[].facts.occurrence_count",
        "findings.groups.structural/groups[].facts.raise_bucket",
        "findings.groups.structural/groups[].family",
        "findings.groups.structural/groups[].id",
        "findings.groups.structural/groups[].items[].end_line => navigation_provenance",
        "findings.groups.structural/groups[].items[].qualname",
        "findings.groups.structural/groups[].items[].relative_path",
        "findings.groups.structural/groups[].items[].start_line"
        " => navigation_provenance",
        "findings.groups.structural/groups[].kind",
        "findings.groups.structural/groups[].novelty => comparison",
        "findings.groups.structural/groups[].novelty_reason => comparison",
        "findings.groups.structural/groups[].priority",
        "findings.groups.structural/groups[].severity",
        "findings.groups.structural/groups[].signature.debug.stmt_seq",
        "findings.groups.structural/groups[].signature.debug.terminal",
        "findings.groups.structural/groups[].signature.stable.control_flow.has_loop",
        "findings.groups.structural/groups[].signature.stable.control_flow.has_try",
        "findings.groups.structural/groups[].signature.stable.control_flow.nested_if",
        "findings.groups.structural/groups[].signature.stable.family",
        "findings.groups.structural/groups[].signature.stable.stmt_shape",
        "findings.groups.structural/groups[].signature.stable.terminal_kind",
        "findings.groups.structural/groups[].signature.version",
        "findings.groups.structural/groups[].source_scope.breakdown.fixtures",
        "findings.groups.structural/groups[].source_scope.breakdown.other",
        "findings.groups.structural/groups[].source_scope.breakdown.production",
        "findings.groups.structural/groups[].source_scope.breakdown.tests",
        "findings.groups.structural/groups[].source_scope.dominant_kind",
        "findings.groups.structural/groups[].source_scope.impact_scope",
        "findings.groups.structural/groups[].spread.files",
        "findings.groups.structural/groups[].spread.functions",
    ),
}


def test_v3_semantic_member_census_is_acknowledged() -> None:
    """Every key the projection owner met over the maximal document, with
    the class of each one it did not keep.  A member that appears here for
    the first time entered the identity naturally and is surfaced by name:
    acknowledge it in this table or classify it in the registry — silence
    is the one outcome the law forbids."""

    from codeclone.report.document.family_projection import semantic_member_census

    document = _maximal_document()
    producers = section(document, "integrity.semantic.population.producers")
    findings = section(document, "findings")
    metrics = section(document, "metrics")
    assert set(_SEMANTIC_MEMBER_CENSUS_V3) == set(_projected_families())
    for family in _projected_families():
        # Probe validity: the pin quantifies over families that RAN in the
        # maximal document; a family missing here would be a verdict about
        # the fixture's population, never about its projection.
        assert producers.get(family) == "complete", family
        census = semantic_member_census(family, findings=findings, metrics=metrics)
        pinned = _SEMANTIC_MEMBER_CENSUS_V3[family]
        assert census == pinned, (
            f"{family}: new semantic members {sorted(set(census) - set(pinned))}; "
            f"vanished members {sorted(set(pinned) - set(census))}"
        )


def test_v3_every_scoped_declaration_is_observed() -> None:
    """A scoped declaration nothing utters is a dead witness (the c04
    precedent: a declaration quantifying over a population nothing held).
    Row routes are declarations too: one row with the routed discriminator
    must exist, or the route classifies nothing."""

    from codeclone.report.document.family_projection import (
        unobserved_key_declarations,
    )

    document = _maximal_document()
    findings = section(document, "findings")
    metrics = section(document, "metrics")
    for family in _projected_families():
        assert (
            unobserved_key_declarations(family, findings=findings, metrics=metrics)
            == ()
        ), family


def test_v3_key_classes_are_closed() -> None:
    """Every declaration names a registered family and a ratified class.

    Key declarations quantify over EVERY registered family, not the analysis
    ones alone: an evaluation family is walked by the same projection owner,
    so a key it must not own is classified in the same table.  Row ROUTES
    stay analysis-only — a route sends a row to the comparison tier, and
    ``evaluation_semantic_projection`` refuses an evaluation family that
    classifies anything as comparison.
    """

    from codeclone.contracts.report_identity import (
        KEY_CLASSES,
        SCOPED_KEY_CLASSES,
        SCOPED_ROW_CLASSES,
        UNIVERSAL_KEY_CLASSES,
        analysis_families,
        registered_families,
    )

    assert len(KEY_CLASSES) == len(set(KEY_CLASSES))
    assert set(UNIVERSAL_KEY_CLASSES.values()) <= set(KEY_CLASSES)
    for family, declarations in SCOPED_KEY_CLASSES.items():
        assert family in registered_families()
        assert set(declarations.values()) <= set(KEY_CLASSES)
    for family, routes in SCOPED_ROW_CLASSES.items():
        assert family in analysis_families()
        for (_section, path), (_discriminator, classes) in routes.items():
            assert path.endswith("[]"), path  # a route names sequence elements
            assert set(classes.values()) <= set(KEY_CLASSES)


def test_identity_keys_are_never_declared_non_semantic() -> None:
    """A key a producer glues entity identity into cannot leave the family
    projection — under either generation's rule.  Derived from both
    authorities; no key name is spelled here."""

    from codeclone.contracts.report_identity import (
        all_identity_keys,
        non_semantic_key_names,
    )
    from codeclone.report.document.integrity import _NON_SEMANTIC_PROJECTION_KEYS

    assert all_identity_keys()  # the rule must quantify over something
    for exclusions in (non_semantic_key_names(), _NON_SEMANTIC_PROJECTION_KEYS):
        conflicts = all_identity_keys() & exclusions
        assert conflicts == frozenset(), (
            "identity-bearing keys declared non-semantic; a glued location is "
            f"identity, not provenance: {sorted(conflicts)}"
        )


def test_line_glued_identity_key_moves_identity() -> None:
    """The F1 collision the glued key exists to prevent: two pairs whose
    members share qualnames and differ only in source position must not
    share a run identity.  Member spans are stripped by the projection, so
    ``pair_key`` is the only surviving distinguisher — exactly what the
    surviving mutation removed."""

    def _pair_at(beta_line: int) -> NearMissPair:
        return NearMissPair(
            pair_key=(
                "pkg/module.py:pkg.module:alpha:1"
                f"|pkg/module.py:pkg.module:beta:{beta_line}"
            ),
            members=(
                NearMissMember(
                    qualname="pkg.module:alpha",
                    filepath="pkg/module.py",
                    start_line=1,
                    end_line=12,
                    differing_start_line=6,
                    differing_end_line=6,
                ),
                NearMissMember(
                    qualname="pkg.module:beta",
                    filepath="pkg/module.py",
                    start_line=beta_line,
                    end_line=beta_line + 11,
                    differing_start_line=beta_line + 5,
                    differing_end_line=beta_line + 5,
                ),
            ),
            edit_statements=1,
            edit_kind="replace",
        )

    first_site = _document(near_miss_pairs=[_pair_at(15)])
    second_site = _document(near_miss_pairs=[_pair_at(40)])
    assert report_run_identity(first_site) != report_run_identity(second_site)


# ---------------------------------------------------------------------------
# Identity-key census: the declaration is provable against measured behavior
# in BOTH directions (controller mutation c04, 2026-08-31: removing the
# near_miss declaration survived — the intersection rule quantified over a
# population nothing held).
#
# Each census row is a measurement: perturbing that key through the REAL
# projection owner moves the family digest, so excluding the key reddens its
# row.  The census-equality pin binds the measured population to the
# registry declaration, so removing a declaration (c04) or declaring a key
# nothing measures reddens the equality.  No key name below restates the
# registry — every row carries its own executable evidence.
# ---------------------------------------------------------------------------

_IDENTITY_KEY_CENSUS: tuple[tuple[str, str], ...] = (
    ("authority", "id"),
    ("clones", "fingerprint"),
    ("clones", "group_key"),
    ("clones", "id"),
    ("dead_code", "id"),
    ("near_miss", "pair_key"),
    ("renamed_structure", "fingerprint"),
    ("renamed_structure", "group_key"),
    ("structural", "id"),
)


@pytest.mark.parametrize(("family", "key"), _IDENTITY_KEY_CENSUS)
def test_identity_key_perturbation_moves_family_digest(family: str, key: str) -> None:
    """Perturbing a declared identity key must move its family digest: the
    projection may never erase it."""

    from codeclone.report.document.family_projection import (
        analysis_semantic_projection,
    )
    from codeclone.report.document.integrity import (
        _CURRENT_GENERATION,
        _family_digest_value,
    )

    def _digest(container: Mapping[str, object]) -> str:
        projection = analysis_semantic_projection(
            family, findings={"groups": {family: container}}, metrics={}
        )
        return _family_digest_value(family, projection, generation=_CURRENT_GENERATION)

    base = {"anchor": "z", key: "entity-a"}
    perturbed = {"anchor": "z", key: "entity-b"}
    assert _digest(base) != _digest(perturbed), (
        f"projection erased identity key {key!r} of family {family!r}"
    )


def test_identity_key_census_matches_registry_declaration() -> None:
    """Measured census == registry declaration, per family, both directions:
    an undeclared measured key and an unmeasured declared key both refuse."""

    from codeclone.contracts.report_identity import (
        REPORT_SEMANTIC_PRODUCERS,
        spec_family,
        spec_identity_keys,
    )

    declared = {
        spec_family(spec): frozenset(spec_identity_keys(spec))
        for spec in REPORT_SEMANTIC_PRODUCERS
        if spec_identity_keys(spec)
    }
    measured: dict[str, set[str]] = {}
    for family, key in _IDENTITY_KEY_CENSUS:
        measured.setdefault(family, set()).add(key)
    assert {family: frozenset(keys) for family, keys in measured.items()} == declared, (
        "identity-key declaration and measured census diverge; a declared "
        "key needs its perturbation measurement, a measured key needs its "
        "declaration"
    )


# ---------------------------------------------------------------------------
# Identity v3 landing: the widened quantification domain.  Measured
# 2026-09-05 with the identity coverage map over a real document sealed by
# the pre-landing engine (every key pattern perturbed once, resealed through
# the production owner): five whole metric families differed on the wire
# while every tier and the run id stayed the same — api_surface (25 key
# patterns), coverage_adoption (29), overloaded_modules (39),
# security_surfaces (28) and the semantic_authority container (52).  Each now
# has one registered owner, and each probe below is paired with the boundary
# it must not cross.
# ---------------------------------------------------------------------------


def _member(document: Mapping[str, object], path: str) -> dict[str, object]:
    """The mutable mapping at a dotted path whose segments may index lists."""

    current: object = document
    for segment in path.split("."):
        if isinstance(current, list):
            current = current[int(segment)]
        else:
            assert isinstance(current, dict), path
            current = current[segment]
    assert isinstance(current, dict), path
    return current


def _row(
    document: Mapping[str, object], path: str, **match: object
) -> dict[str, object]:
    """The first row of the list at ``path`` matching every ``match`` key:
    rows are addressed by what they say, never by the sort order the
    document normalizer happens to give them."""

    rows = _member(document, path.rsplit(".", 1)[0])[path.rsplit(".", 1)[1]]
    assert isinstance(rows, list), path
    for row in rows:
        if isinstance(row, dict) and all(
            row.get(key) == value for key, value in match.items()
        ):
            return row
    raise AssertionError(f"no row at {path} matches {match}")


def _moved_by(family: str) -> tuple[str, ...]:
    return (f"family.analysis.{family}", "analysis_facts", "run_id")


def _with(
    document: Mapping[str, object], path: str, **fields: object
) -> dict[str, object]:
    """A deep copy of ``document`` with ``fields`` set on the mapping at ``path``."""

    changed = copy.deepcopy(dict(document))
    _member(changed, path).update(fields)
    return changed


def _held_at_every_tier(
    document: dict[str, object], changed: dict[str, object], *, family: str
) -> None:
    """The other boundary of every movement probe: resealed, ``changed`` must
    hold the family digest, the analysis and comparison tiers and the run id."""

    _assert_moved(
        document,
        _resealed(changed),
        moved=(),
        held=(f"family.analysis.{family}", "analysis_facts", "comparison", "run_id"),
    )


@pytest.mark.parametrize(
    ("family", "path", "key", "value"),
    [
        pytest.param(
            "security_surfaces",
            "metrics.families.security_surfaces.items.0",
            "capability",
            "subprocess_popen",
            id="security-surface-capability",
        ),
        pytest.param(
            "security_surfaces",
            "metrics.families.security_surfaces.summary",
            "production",
            2,
            id="security-surface-summary-count",
        ),
        pytest.param(
            "overloaded_modules",
            "metrics.families.overloaded_modules.items.0",
            "candidate_status",
            "candidate",
            id="overloaded-candidate-status",
        ),
        pytest.param(
            "overloaded_modules",
            "metrics.families.overloaded_modules.items.0",
            "fan_in",
            7,
            id="overloaded-fan-in",
        ),
        pytest.param(
            "coverage_join",
            "metrics.families.coverage_join.items.0",
            "covered_lines",
            9,
            id="coverage-join-covered-lines",
        ),
        pytest.param(
            "coverage_join",
            "metrics.families.coverage_join.summary",
            "status",
            "invalid",
            id="coverage-join-status",
        ),
        pytest.param(
            "coverage_adoption",
            "metrics.families.coverage_adoption.items.0",
            "params_annotated",
            2,
            id="adoption-params-annotated",
        ),
        pytest.param(
            "coverage_adoption",
            "metrics.families.coverage_adoption.summary",
            "docstring_permille",
            999,
            id="adoption-summary-permille",
        ),
        pytest.param(
            "authority",
            "metrics.families.semantic_authority.summary",
            "active_violations",
            0,
            id="authority-summary-active-violations",
        ),
    ],
)
def test_v3_metrics_only_statement_moves_its_registered_owner(
    family: str, path: str, key: str, value: object
) -> None:
    """Each of these statements left every tier SAME under the findings-only
    domain (identity coverage map, 2026-09-05).  Owned, it moves its own
    family digest, ``analysis_facts`` and the run id."""

    document = _maximal_document()
    _assert_complete(document, family)
    changed = copy.deepcopy(document)
    container = _member(changed, path)
    assert container[key] != value, (path, key)
    container[key] = value
    changed = _resealed(changed)
    assert _verify(changed) is None
    _assert_moved(document, changed, moved=_moved_by(family))


def test_v3_api_symbol_row_moves_the_analysis_tier() -> None:
    document = _maximal_document()
    _assert_complete(document, "api_surface")
    changed = copy.deepcopy(document)
    _row(changed, "metrics.families.api_surface.items", record_kind="symbol")[
        "symbol_kind"
    ] = "class"
    changed = _resealed(changed)
    _assert_moved(document, changed, moved=_moved_by("api_surface"))


def test_v3_authority_candidate_level_moves_the_analysis_tier() -> None:
    """The candidate level and score are document-layer conclusions no
    observation lane stores (``tests/_projection_equivalence``: rebuilt, not
    stored) — the statements ``source_facts.semantic`` never carried."""

    document = _maximal_document()
    changed = copy.deepcopy(document)
    _row(changed, "metrics.families.semantic_authority.items", item_kind="candidate")[
        "level"
    ] = "divergent_projection"
    changed = _resealed(changed)
    _assert_moved(document, changed, moved=_moved_by("authority"))


@pytest.mark.parametrize(
    ("family", "path", "key", "value"),
    [
        pytest.param(
            "api_surface",
            "metrics.families.api_surface.summary",
            "breaking",
            7,
            id="api-summary-breaking",
        ),
        pytest.param(
            "coverage_adoption",
            "metrics.families.coverage_adoption.summary",
            "param_delta",
            -40,
            id="adoption-param-delta",
        ),
    ],
)
def test_v3_baseline_derived_statement_moves_only_the_comparison_tier(
    family: str, path: str, key: str, value: object
) -> None:
    """The reverse boundary: a statement the metrics diff wrote is routed to
    the family's comparison-tier digest, and the analysis tier — the fixed
    point of the hierarchy — does not move on it."""

    document = _maximal_document()
    changed = copy.deepcopy(document)
    _member(changed, path)[key] = value
    changed = _resealed(changed)
    _assert_moved(
        document,
        changed,
        moved=(f"family.comparison.{family}", "comparison", "run_id"),
        held=(f"family.analysis.{family}", "analysis_facts"),
    )


def test_v3_api_breaking_change_row_is_a_comparison_statement_whole() -> None:
    """``core.metrics_payload`` interleaves one ``breaking_change`` row per
    new breaking change with the symbol rows.  The row is routed whole:
    editing it, or dropping it, moves the comparison tier and never the
    analysis tier."""

    document = _maximal_document()
    edited = copy.deepcopy(document)
    _row(edited, "metrics.families.api_surface.items", record_kind="breaking_change")[
        "detail"
    ] = "signature changed"
    edited = _resealed(edited)
    _assert_moved(
        document,
        edited,
        moved=("family.comparison.api_surface", "comparison", "run_id"),
        held=("family.analysis.api_surface", "analysis_facts"),
    )
    dropped = copy.deepcopy(document)
    container = _member(dropped, "metrics.families.api_surface")
    rows = container["items"]
    assert isinstance(rows, list)
    container["items"] = [
        row
        for row in rows
        if not (isinstance(row, dict) and row.get("record_kind") == "breaking_change")
    ]
    dropped = _resealed(dropped)
    _assert_moved(
        document,
        dropped,
        moved=("family.comparison.api_surface", "comparison", "run_id"),
        held=("family.analysis.api_surface", "analysis_facts"),
    )


def test_v3_coverage_join_row_moves_its_own_owner_not_design() -> None:
    """Until the landing the ``coverage_join`` container rode ``design``,
    which the registry did not see.  A joined coverage fact now moves the
    ``coverage_join`` family digest; the design digest holds — the design
    findings drawn from the container are owned by design, the container is
    not."""

    base = _document(metrics=_design_metrics())
    other = _document(metrics=_design_metrics(coverage_permille=900))
    _assert_complete(base, "coverage_join", "design")
    assert section(base, "findings") == section(other, "findings")
    _assert_moved(
        base, other, moved=_moved_by("coverage_join"), held=("family.analysis.design",)
    )


def test_v3_coverage_gate_policy_outputs_stay_outside_analysis() -> None:
    """``hotspot_threshold_percent`` is ``MetricGateConfig.coverage_min`` —
    the ``--coverage-min`` GATE — echoed into the join, and the four hotspot
    verdicts and counts are decided by it with the risk bands.  Their natural
    tier is evaluation: a gate change moves the evaluation tier through the
    gate request, never the assertion about program structure."""

    document = _maximal_document()
    _assert_complete(document, "coverage_join")
    policy = _with(
        document,
        "metrics.families.coverage_join.summary",
        hotspot_threshold_percent=80,
        coverage_hotspots=1,
        scope_gap_hotspots=1,
    )
    row = _member(policy, "metrics.families.coverage_join.items.0")
    row["coverage_hotspot"] = not row["coverage_hotspot"]
    row["scope_gap_hotspot"] = True
    assert section(policy, "metrics.families") != section(document, "metrics.families")
    _held_at_every_tier(document, policy, family="coverage_join")
    gated = _resealed(_with(document, "evaluation.request", coverage_min=80))
    _assert_moved(
        document, gated, moved=("evaluation", "run_id"), held=("analysis_facts",)
    )


def test_v3_coverage_source_path_stays_outside_every_tier() -> None:
    document = _maximal_document()
    elsewhere = _with(
        document, "metrics.families.coverage_join.summary", source="elsewhere.xml"
    )
    _held_at_every_tier(document, elsewhere, family="coverage_join")


def test_v3_physical_line_count_stays_outside_every_tier() -> None:
    """``overloaded_modules.items[].loc`` is ``len(source_lines)`` — comment
    lines included — so a comment-only edit moves it.  Measured 2026-09-05:
    with it semantic, the four MCP analyzer-invariant probes went red
    (``tests/test_mcp_service.py``: the run id moved on a comment edit).  A
    text extent is navigation provenance; the structural counts beside it are
    not, and the sibling probe above shows one of them moving the owner."""

    document = _maximal_document()
    _assert_complete(document, "overloaded_modules")
    row_path = "metrics.families.overloaded_modules.items.0"
    longer = _with(
        document, row_path, loc=int(str(_member(document, row_path)["loc"])) + 1
    )
    _held_at_every_tier(document, longer, family="overloaded_modules")


def test_v3_health_digest_is_the_owner_projection_whole() -> None:
    """The evaluation family digest is now built by the one projection owner
    from ``metrics.families.health`` whole: ``items_truncated`` was outside
    every tier under the summary-only digest (coverage map, 2026-09-05)."""

    document = _maximal_document()
    changed = copy.deepcopy(document)
    _member(changed, "metrics.families.health")["items_truncated"] = True
    changed = _resealed(changed)
    _assert_moved(
        document,
        changed,
        moved=("family.evaluation.health", "evaluation", "run_id"),
        held=("analysis_facts", "comparison"),
    )


def test_v3_an_evaluation_family_refuses_a_comparison_routed_statement() -> None:
    """An evaluation family has no comparison-tier digest, so a statement the
    classification routes there would leave the only digest that carries
    it: a typed refusal at the seal, never a silent drop."""

    from codeclone.contracts.report_identity import ReportIdentityRegistryError

    grown = copy.deepcopy(_maximal_document())
    _member(grown, "metrics.families.health")["novelty"] = "new"
    with pytest.raises(ReportIdentityRegistryError, match="evaluation family 'health'"):
        _resealed(grown)


def test_v3_overloaded_modules_realized_contract_is_the_uttered_detection() -> None:
    """No constant owns the producer's revision: the container utters it, and
    realized beats registered — the ``detection`` block is the realized
    contract, cross-checked at verification like the near-miss budget."""

    document = _maximal_document()
    entry = section(
        document, "integrity.semantic.realized_contracts.analysis.overloaded_modules"
    )
    assert entry["algorithm_revisions"] == {"overloaded_modules_detection": "1"}
    params = entry["params"]
    assert isinstance(params, dict)
    assert params["strategy"] == "project_relative_composite"
    assert params["minimum_population"] == 20
    assert "version" not in params
    tampered = _tampered(document)
    _member(
        tampered,
        "integrity.semantic.realized_contracts.analysis.overloaded_modules"
        ".algorithm_revisions",
    )["overloaded_modules_detection"] = "9"
    assert _verify(tampered) == (
        "report overloaded_modules realized revision disagrees with its container"
    )


def test_v3_metrics_only_families_witness_their_activation() -> None:
    """``coverage_join`` and ``api_surface`` are complete only when the run
    declared them computed; a default document utters both disabled and
    seals no digest for them (absence of execution is population state)."""

    plain = _document()
    producers = section(plain, "integrity.semantic.population.producers")
    assert producers["coverage_join"] == "disabled"
    assert producers["api_surface"] == "disabled"
    assert producers["security_surfaces"] == "complete"
    assert producers["overloaded_modules"] == "complete"
    assert producers["coverage_adoption"] == "complete"
    digests = section(plain, "integrity.semantic.family_digests.analysis")
    assert "coverage_join" not in digests and "api_surface" not in digests
    assert {"security_surfaces", "overloaded_modules", "coverage_adoption"} <= set(
        digests
    )


def test_metrics_summary_is_a_copy_of_the_family_summaries() -> None:
    """``metrics.summary`` stays outside every tier (coverage map: SAME): it
    is the builder's index over the family summaries — one fact spelled
    twice — pinned here as an exact copy so the SAME is by construction."""

    document = _maximal_document()
    families = section(document, "metrics.families")
    assert section(document, "metrics.summary") == {
        name: section(families, name)["summary"] for name in families
    }


# ---------------------------------------------------------------------------
# The grown-field test against the widened domain: a producer that grows a
# new user-visible member of a metrics-only family enters the identity by
# construction and the census names it — the pin reddens with its name.
# ---------------------------------------------------------------------------


def test_v3_a_grown_member_of_a_metrics_only_family_is_surfaced() -> None:
    from codeclone.report.document.family_projection import semantic_member_census

    document = _maximal_document()
    grown = copy.deepcopy(document)
    _row(
        grown, "metrics.families.security_surfaces.items", category="process_boundary"
    )["taint_sink"] = "os.system"
    grown = _resealed(grown)
    assert _verify(grown) is None
    _assert_moved(document, grown, moved=_moved_by("security_surfaces"))
    census = semantic_member_census(
        "security_surfaces",
        findings=section(grown, "findings"),
        metrics=section(grown, "metrics"),
    )
    assert set(census) - set(_SEMANTIC_MEMBER_CENSUS_V3["security_surfaces"]) == {
        "metrics.families.security_surfaces/items[].taint_sink"
    }


# ---------------------------------------------------------------------------
# The cfg causal check (maintainer's prescription): change ONLY
# cfg_cyclomatic_complexity, findings and every other semantic fact
# unchanged.  If the analysis identity moved anyway through the realized
# contract, the field would be a contract echo and would need a NAMED
# contract-provenance class; it does not, so it stays SEMANTIC.  The positive
# control is a genuine contract echo on the dead_code lane.
# ---------------------------------------------------------------------------

_CFG_DECLARATION = ("metrics.families.complexity", "items[].cfg_cyclomatic_complexity")


def _with_hypothetical_exclusions(
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    *paths: tuple[str, str],
) -> None:
    """Classify the given paths OUT of the analysis projection for one probe,
    so the probe can ask what ELSE in the preimage carries the value."""

    import codeclone.report.document.family_projection as family_projection
    from codeclone.contracts.report_identity import (
        KEY_CLASS_PRESENTATION,
        SCOPED_KEY_CLASSES,
    )

    hypothetical = {
        **SCOPED_KEY_CLASSES,
        family: {
            **SCOPED_KEY_CLASSES.get(family, {}),
            **dict.fromkeys(paths, KEY_CLASS_PRESENTATION),
        },
    }
    monkeypatch.setattr(family_projection, "SCOPED_KEY_CLASSES", hypothetical)


def test_v3_cfg_cyclomatic_complexity_is_not_a_contract_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E-N+2P over the complete CFG (``metrics.complexity``) is computed from
    the graph, not echoed from configuration.  Measured here: the field
    changes alone (findings identical, realized contracts identical), the
    identity moves only through the design projection, and with the field
    hypothetically classified out nothing else in the preimage moves — so
    the value is a semantic member, not a contract echo."""

    base = _document(metrics=_design_metrics(cfg=5))
    cfg_only = _document(metrics=_design_metrics(cfg=6))
    _assert_complete(base, "design")
    assert section(base, "findings") == section(cfg_only, "findings")
    assert section(base, "integrity.semantic.realized_contracts") == section(
        cfg_only, "integrity.semantic.realized_contracts"
    )
    _assert_moved(base, cfg_only, moved=_moved_by("design"))

    _with_hypothetical_exclusions(monkeypatch, "design", _CFG_DECLARATION)
    _assert_moved(
        _resealed(base),
        _resealed(cfg_only),
        moved=(),
        held=("family.analysis.design", "analysis_facts", "comparison", "run_id"),
    )


def test_v3_contract_echo_control_moves_through_the_realized_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive control for the check above.  ``world_contract`` IS a contract
    echo — a realized dead_code parameter — so with the same hypothetical
    exclusion of every copy in the container, changing it alone still moves
    ``analysis_facts`` through ``realized_contracts`` while the family digest
    holds: this is what "moves anyway through the realized contract" looks
    like, and it is what cfg does not do."""

    base = _document(metrics=_dead_code_metrics(world="open"))
    closed = _document(metrics=_dead_code_metrics(world="closed"))
    _with_hypothetical_exclusions(
        monkeypatch,
        "dead_code",
        ("metrics.families.dead_code", "summary.world_contract"),
        ("metrics.families.dead_code", "unresolved[].world_contract"),
    )
    left, right = _resealed(base), _resealed(closed)
    assert section(
        left, "integrity.semantic.realized_contracts.analysis.dead_code"
    ) != section(right, "integrity.semantic.realized_contracts.analysis.dead_code")
    _assert_moved(
        left,
        right,
        moved=("analysis_facts", "run_id"),
        held=("family.analysis.dead_code",),
    )


# ---------------------------------------------------------------------------
# Identity v3: the analysis population state is an ANALYSIS fact.
#
# Measured 2026-09-06, before the ``observed`` statement landed: three runs
# stating ``complete_nonempty``, ``partial`` and ``unmeasured`` — every
# analysis-digested counter held equal by construction — shared one
# ``analysis_facts``, ``e3e51652b428c75c...``.  The analysis layer asserted
# that a complete and a partial analysis of one tree are the same facts.  The
# word moved only the EVALUATION tier, because the health family was its only
# carrier and health is evaluation-domain: a fact wearing a policy output's
# clothes.  ``summary.population`` is decided by two discovery counters and no
# policy at all — that is what makes it a fact, and why its owner belongs on
# the analysis tier.
# ---------------------------------------------------------------------------

#: The three states the collision was measured over, and the counters that
#: produce each.  ``total_found`` is constant and ``skipped`` /
#: ``unsupported_construct_skipped`` are 0 in every row: the three counters the
#: analysis population block copies are held equal BY CONSTRUCTION, so a
#: difference between two arms can only be the state itself.
_POPULATION_ARMS: tuple[tuple[str, int, int], ...] = (
    ("complete_nonempty", 10, 0),
    ("partial", 4, 0),
    ("unmeasured", 0, 0),
)


def _population_document(
    *,
    analyzed: int,
    cached: int = 0,
    total_found: int = 10,
    metrics: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """One run that found ``total_found`` files and observed ``analyzed +
    cached`` of them, stated consistently by the inventory and by health."""

    return _document(
        inventory={
            "files": {
                "total_found": total_found,
                "analyzed": analyzed,
                "cached": cached,
                "skipped": 0,
                "source_io_skipped": 0,
                "unsupported_construct_skipped": 0,
                "unsupported_constructs": [],
            },
            "code": {
                "parsed_lines": 100,
                "functions": 4,
                "methods": 0,
                "classes": 1,
            },
            "file_list": [f"pkg/m{index}.py" for index in range(total_found)],
        },
        metrics={
            **_health_metrics(
                dead_code_items=0,
                files_found=total_found,
                files_analyzed_or_cached=analyzed + cached,
            ),
            **(metrics or {}),
        },
    )


def _population_counters(document: Mapping[str, object]) -> tuple[tuple[str, int], ...]:
    """The counters the analysis population block copies — the ones a probe
    must show held equal before reading anything into a digest difference."""

    files = section(document, "integrity.semantic.population.files")
    counters: list[tuple[str, int]] = []
    for name, value in files.items():
        assert isinstance(value, int), (name, value)
        counters.append((str(name), value))
    return tuple(sorted(counters))


def _stated_population(document: Mapping[str, object]) -> str:
    return str(section(document, "integrity.semantic.population").get("observed"))


def _displayed_population(document: Mapping[str, object]) -> object:
    return section(document, "metrics.families.health.summary")["population"]


def _leaf_strings(value: object) -> set[str]:
    """Every string a projection carries, at any depth: the population words
    cannot hide inside a nested container."""

    if isinstance(value, str):
        return {value}
    if isinstance(value, Mapping):
        return set().union(*(_leaf_strings(item) for item in value.values()), set())
    if isinstance(value, (list, tuple)):
        return set().union(*(_leaf_strings(item) for item in value), set())
    return set()


def test_v3_population_state_is_carried_by_the_analysis_tier() -> None:
    """Condition 2, and the accounting behind it: three states, every other
    analysis observation identical, three distinct ``analysis_facts``.

    The equality assertions come FIRST.  A difference in the tier digests
    means nothing until the counters the tier copies are shown to be the same
    in every arm — otherwise the probe would be measuring the counters.
    """

    documents = {
        state: _population_document(analyzed=analyzed, cached=cached)
        for state, analyzed, cached in _POPULATION_ARMS
    }
    expected = {state: state for state, _analyzed, _cached in _POPULATION_ARMS}

    counters = {state: _population_counters(doc) for state, doc in documents.items()}
    assert len(set(counters.values())) == 1, counters
    assert {name for name, _value in counters["partial"]} == {
        "total_found",
        "skipped",
        "unsupported_construct_skipped",
    }

    # The states are real: stated by the owner, and by health's consumed copy.
    assert {state: _stated_population(doc) for state, doc in documents.items()} == (
        expected
    )
    assert {state: _displayed_population(doc) for state, doc in documents.items()} == (
        expected
    )

    for name in ("analysis_facts", "comparison", "evaluation", "run_id"):
        values = {_tiers(doc)[name] for doc in documents.values()}
        assert len(values) == len(documents), f"{name} collided: {len(values)} values"


def test_v3_complete_to_partial_moves_the_analysis_facts() -> None:
    """The first named pair: same source, same scope, same config, complete ->
    partial.  ``analysis_facts`` MUST move.  Verbatim-equal before the
    ``observed`` statement landed."""

    complete = _population_document(analyzed=10)
    partial = _population_document(analyzed=4)
    assert _population_counters(complete) == _population_counters(partial)
    assert (_stated_population(complete), _stated_population(partial)) == (
        "complete_nonempty",
        "partial",
    )
    _assert_moved(complete, partial, moved=("analysis_facts", "comparison", "run_id"))


def test_v3_evaluation_policy_does_not_move_the_population_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second named pair: one partial population, risk thresholds A -> B.
    ``analysis_facts`` MUST NOT move.

    The negative is readable only because the same perturbation is shown to
    bind on the tier that owns the policy: the recalibration moves
    ``evaluation`` and the run id.  The design family is above its threshold
    so the band word is actually uttered, and both arms are the SAME partial
    population — a policy change measured over a complete population would not
    touch the statement under test at all.
    """

    import codeclone.contracts as contracts

    metrics = _design_metrics(cbo=15)
    before = _population_document(analyzed=4, metrics=metrics)
    assert _stated_population(before) == "partial"
    assert section(before, "findings.groups.design")["groups"]  # the band is uttered

    monkeypatch.setattr(
        contracts, "COUPLING_RISK_LOW_MAX", contracts.COUPLING_RISK_LOW_MAX + 1
    )
    recalibrated = _population_document(analyzed=4, metrics=metrics)

    assert _stated_population(recalibrated) == "partial"
    assert section(before, "integrity.semantic.population") == section(
        recalibrated, "integrity.semantic.population"
    )
    _assert_moved(
        before,
        recalibrated,
        moved=("evaluation", "run_id"),
        held=("analysis_facts", "comparison"),
    )


def test_v3_population_has_exactly_one_identity_bearing_owner() -> None:
    """Condition 5, over the maximal document: the four-state word enters
    exactly one identity-bearing projection, and it is not a family's.

    The census names health's copy as consumed, and no family projection of
    any tier carries the word.  That the owner and health's displayed copy
    agree is measured where a document is COHERENT — over the three states
    above, and end to end over a cold and a warm run in
    ``test_report_honest_population`` — not here: ``_maximal_document`` sets
    its inventory and its health family independently, so the fixture states
    a health population its own counters contradict.  Asserting agreement on
    it would be asserting a property of the fixture.
    """

    from typing import get_args

    from codeclone.contracts import ObservedPopulation
    from codeclone.report.document.family_projection import (
        analysis_semantic_projection,
        comparison_semantic_projection,
        semantic_member_census,
    )

    document = _maximal_document()
    findings = section(document, "findings")
    metrics = section(document, "metrics")
    states = frozenset(get_args(ObservedPopulation))
    assert len(states) == 4

    assert (
        "metrics.families.health/summary.population => consumed_analysis_fact"
    ) in semantic_member_census("health", findings=findings, metrics=metrics)

    carriers: list[str] = []
    for family in _projected_families():
        projected = analysis_semantic_projection(
            family, findings=findings, metrics=metrics
        )
        if states.intersection(_leaf_strings(projected)):
            carriers.append(f"family.{family}")
        routed = comparison_semantic_projection(
            family, findings=findings, metrics=metrics
        )
        if routed is not None and states.intersection(_leaf_strings(routed)):
            carriers.append(f"family.comparison.{family}")
    assert carriers == [], carriers

    assert _stated_population(document) in states


def test_v3_health_population_is_a_representation_not_an_owner() -> None:
    """Conditions 4 and 7, causally.  Editing the word health displays moves
    no identity; editing the counter its OWNER reads moves the analysis tier.

    The positive control perturbs the same causal path the negative claims to
    measure — the analysis population block — through the same builder.
    """

    document = _population_document(analyzed=10)
    assert _stated_population(document) == "complete_nonempty"

    displayed = copy.deepcopy(document)
    _mutable(displayed, "metrics.families.health.summary")["population"] = "partial"
    displayed = _resealed(displayed)
    assert _verify(displayed) is None
    assert _displayed_population(displayed) == "partial"
    _assert_moved(
        document,
        displayed,
        moved=(),
        held=("analysis_facts", "comparison", "evaluation", "run_id"),
    )

    observed = _population_document(analyzed=4)
    _assert_moved(document, observed, moved=("analysis_facts", "run_id"))


def test_v3_warm_and_cold_runs_state_one_population() -> None:
    """The split of the observed counters is provenance; their sum is the
    fact.  A warm run moves every file from ``analyzed`` to ``cached`` and must
    land on the identical ``analysis_facts`` — the cache-trust invariant.  The
    control on the same path: reading fewer files does move it."""

    cold = _population_document(analyzed=10, cached=0)
    warm = _population_document(analyzed=0, cached=10)
    assert _stated_population(cold) == _stated_population(warm) == "complete_nonempty"
    _assert_moved(cold, warm, moved=(), held=("analysis_facts", "comparison", "run_id"))

    truncated = _population_document(analyzed=6, cached=0)
    _assert_moved(cold, truncated, moved=("analysis_facts", "run_id"))


def test_v3_population_mutant_restores_the_measured_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Condition 6, the causal mutant.  Remove the population statement from
    the analysis projection — the generation-2 population block, verbatim —
    and the proven collision returns: three states, one ``analysis_facts``.

    This is what makes the probes above evidence rather than decoration, and
    it is the pin that reddens if a later edit drops ``observed`` from the
    generation-3 row.
    """

    from codeclone.report.document import integrity

    monkeypatch.setitem(
        integrity._GENERATION_THREE,
        "population_statements",
        integrity._GENERATION_TWO["population_statements"],
    )
    documents = [
        _population_document(analyzed=analyzed, cached=cached)
        for _state, analyzed, cached in _POPULATION_ARMS
    ]

    assert {_displayed_population(doc) for doc in documents} == {
        state for state, _analyzed, _cached in _POPULATION_ARMS
    }
    assert len({_tiers(doc)["analysis_facts"] for doc in documents}) == 1
    assert len({_tiers(doc)["comparison"] for doc in documents}) == 1
    assert len({_tiers(doc)["run_id"] for doc in documents}) == len(documents)


# ---------------------------------------------------------------------------
# Identity v3: the fixture probes above, answered by a real run.
# ---------------------------------------------------------------------------


def _population_evidence(
    root: Path,
    cache_path: Path,
    *,
    warm: bool,
    expect_cache_hits: int | None = None,
) -> tuple[Cache, str, str, dict[str, object]]:
    """One real run: what the analysis identity states, what health displays,
    and the file counters both were derived from.

    Built through the production report body, so the inventory under test is
    the one a released report carries — not a hand-typed mapping.
    """

    from codeclone.core.reporting import build_report_body_for_analysis
    from codeclone.report.document.integrity import _observed_population
    from tests._pipeline_fixtures import analysis_boot, run_pipeline_once

    boot = analysis_boot(root, min_loc=1, min_stmt=1, skip_metrics=False)
    cache, run = run_pipeline_once(
        boot,
        cache_path,
        root=root,
        warm=warm,
        expect_cache_hits=expect_cache_hits,
    )
    body = build_report_body_for_analysis(
        discovery=run.discovery,
        processing=run.processing,
        analysis=run.result,
        report_meta={},
        new_func=None,
        new_block=None,
    )
    files = section(body, "inventory.files")
    payload = run.result.metrics_payload
    assert payload is not None, "metrics payload missing; the run skipped metrics"
    displayed = section(payload, "health")["population"]
    return cache, _observed_population(files), str(displayed), dict(files)


def test_the_analysis_tier_and_health_state_one_population_on_a_real_run(
    tmp_path: Path,
) -> None:
    """The two producers consult one owner over one run's counters.

    Health is fed ``processing.files_analyzed + discovery.cache_hits``
    (``core.pipeline``) and the report inventory carries those same two
    numbers as ``analyzed`` and ``cached`` (``core.reporting``), so the
    identity statement and the displayed word are the same fact twice, never
    two facts. Measured on a cold run and on the warm run of the same tree:
    the split moves, the state does not.
    """

    root = tmp_path / "src"
    root.mkdir()
    for index in range(3):
        (root / f"mod{index}.py").write_text(
            f"def f{index}() -> int:\n    return {index}\n", "utf-8"
        )
    cache_path = tmp_path / "cache.json"

    cold_cache, stated, displayed, cold_files = _population_evidence(
        root, cache_path, warm=False
    )
    cold_cache.save()
    assert stated == displayed == "complete_nonempty"
    assert cold_files["analyzed"] == 3
    assert cold_files["cached"] == 0

    _warm_cache, warm_stated, warm_displayed, warm_files = _population_evidence(
        root, cache_path, warm=True, expect_cache_hits=3
    )
    assert warm_stated == warm_displayed == "complete_nonempty"
    # The split is provenance and it really did move; the fact did not.
    assert warm_files["analyzed"] == 0
    assert warm_files["cached"] == 3
    assert warm_files["total_found"] == cold_files["total_found"] == 3
