# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Acceptance corpus for report semantic identity v2 (RULING-2026-08-31).

Six collision probes were measured on 2026-08-31 against the v1 identity
(`integrity.digests.evaluation`): five distinct (tree x config x engine)
states shared one ``run_id`` because findings, tier containers, policy
parameters and evaluation outputs were outside the hashed preimage.  Each
probe below pins the ratified law:

    Two runs share a ``run_id`` iff they utter the same canonical set of
    semantic statements under the same realized contract of their
    derivation.

The corpus is permanent (ruling: "все шесть collision probes как acceptance
corpus").  Every probe that asserts inequality was verbatim-equal before the
v2 preimage landed; the equality probes (determinism, provenance immunity,
the disabled-producer subtlety) guard the other boundary and must stay green
across the generation change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeclone.models import NearMissMember, NearMissPair
from codeclone.utils.mapping_paths import section
from codeclone.utils.run_identity import report_run_identity

from ._report_fixtures import build_test_report_document

_FIXTURES = Path(__file__).parent / "fixtures" / "report_identity"


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


def _health_metrics(*, dead_code_items: int) -> dict[str, object]:
    """A real health family from the score's own producer — no caller ever
    types a score, so a recalibration moves this fixture with the metric."""

    from codeclone.metrics.health import (
        HealthInputs,
        compute_health,
        health_report_fields,
    )

    family = health_report_fields(
        compute_health(
            HealthInputs(
                files_found=10,
                files_analyzed_or_cached=10,
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
# Generations: the old fixture stays honestly interpretable in its own one.
# ---------------------------------------------------------------------------


def test_v1_generation_document_still_verifies() -> None:
    """A document produced by the v1 builder (captured before the v2 preimage
    landed) must keep verifying under its own generation's rules."""

    from codeclone.report.document.integrity import verify_report_integrity

    document = json.loads(
        (_FIXTURES / "report_document_v1.json").read_text(encoding="utf-8")
    )
    assert verify_report_integrity(document) is None


def test_v2_document_declares_its_identity_generation() -> None:
    from codeclone.contracts import REPORT_SEMANTIC_IDENTITY_VERSION

    document = _document()
    integrity = document["integrity"]
    assert isinstance(integrity, dict)
    assert (
        integrity.get("semantic_identity_version") == REPORT_SEMANTIC_IDENTITY_VERSION
    )


# ---------------------------------------------------------------------------
# Producer registry: totality and the population law.
# ---------------------------------------------------------------------------


def test_every_findings_family_has_exactly_one_registered_owner() -> None:
    """Every canonical semantic family the report utters has exactly one
    registered owner (ruling: producer registry ratchet)."""

    from codeclone.contracts.report_identity import (
        REPORT_SEMANTIC_PRODUCERS,
        analysis_families,
        spec_family,
    )

    document = _document()
    findings = document["findings"]
    assert isinstance(findings, dict)
    groups = findings["groups"]
    assert isinstance(groups, dict)
    assert sorted(groups) == sorted(analysis_families())
    families = [spec_family(spec) for spec in REPORT_SEMANTIC_PRODUCERS]
    assert families == sorted(families)
    assert len(families) == len(set(families))


def test_family_digests_cover_only_executed_families() -> None:
    """A family that never executed is population state, never an empty
    measurement: no digest may exist for it (count=0 is only ever the result
    of an executed measurement)."""

    document = _document(near_miss_pairs=None)
    analysis_digests = section(document, "integrity.semantic.family_digests.analysis")
    producers = section(document, "integrity.semantic.population.producers")

    assert producers["near_miss"] == "disabled"
    assert "near_miss" not in analysis_digests
    for family, state in producers.items():
        if family in {"health", "gates"}:
            continue
        assert (family in analysis_digests) == (state == "complete"), family


# ---------------------------------------------------------------------------
# Verifier witnesses: every spelled-twice fact, tampered, names its refusal.
# Each pin is also a mutation witness — killing the corresponding check in
# the verifier turns exactly one of these red.
# ---------------------------------------------------------------------------


def _tampered(document: dict[str, object]) -> dict[str, object]:
    import copy

    return copy.deepcopy(document)


def _verify(document: dict[str, object]) -> str | None:
    from codeclone.report.document.integrity import verify_report_integrity

    return verify_report_integrity(document)


def _v1_document() -> dict[str, object]:
    loaded = json.loads(
        (_FIXTURES / "report_document_v1.json").read_text(encoding="utf-8")
    )
    assert isinstance(loaded, dict)
    return loaded


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
    document = _tampered(_v1_document())
    tamper(document)  # type: ignore[operator]
    assert _verify(document) == expected


def test_v1_verify_refuses_missing_observation_tier() -> None:
    document = _tampered(_v1_document())
    del _mutable(document, "integrity.digests")["observation"]
    assert _verify(document) == (
        "report digest set must contain exactly five named tiers"
    )


def _tamper_population(document: dict[str, object]) -> None:
    _mutable(document, "integrity.semantic.population.producers")["near_miss"] = (
        "complete"
    )


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


def _tamper_observation(document: dict[str, object]) -> None:
    _mutable(document, "integrity.digests.observation")["value"] = None


def _tamper_schema(document: dict[str, object]) -> None:
    document["report_schema_version"] = 5


def _tamper_semantic_block(document: dict[str, object]) -> None:
    _mutable(document, "integrity")["semantic"] = {}


@pytest.mark.parametrize(
    ("tamper", "expected"),
    [
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
    ],
)
def test_v2_verify_names_each_tamper(tamper: object, expected: str) -> None:
    document = _tampered(_document(near_miss_pairs=None))
    tamper(document)  # type: ignore[operator]
    assert _verify(document) == expected


def test_v2_verify_refuses_near_miss_container_disagreement() -> None:
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


def test_v2_verify_refuses_tampered_health_family_digest() -> None:
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
# Identity keys versus the projection: both directions of the boundary.
# m07 pins that provenance cannot enter the identity; these pin that
# identity cannot fall out of it (controller mutation 2026-08-31: adding
# "pair_key" to the exclusion list survived the corpus).
# ---------------------------------------------------------------------------


def test_identity_keys_are_never_declared_non_semantic() -> None:
    """A key a producer glues entity identity into cannot be excluded from
    the family-digest projection.  Derived from both authorities — no key
    name is spelled here."""

    from codeclone.contracts.report_identity import all_identity_keys
    from codeclone.report.document.integrity import (
        _NON_SEMANTIC_PROJECTION_KEYS,
    )

    conflicts = all_identity_keys() & _NON_SEMANTIC_PROJECTION_KEYS
    assert conflicts == frozenset(), (
        "identity-bearing keys declared non-semantic; a glued location is "
        f"identity, not provenance: {sorted(conflicts)}"
    )
    assert all_identity_keys()  # the rule must quantify over something


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
# projection moves the family digest, so excluding the key reddens its row.
# The census-equality pin binds the measured population to the registry
# declaration, so removing a declaration (c04) or declaring a key nothing
# measures reddens the equality.  No key name below restates the registry —
# every row carries its own executable evidence.
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

    from codeclone.report.document.integrity import _family_digest_value

    base = {"anchor": "z", key: "entity-a"}
    perturbed = {"anchor": "z", key: "entity-b"}
    assert _family_digest_value(family, base) != _family_digest_value(
        family, perturbed
    ), f"projection erased identity key {key!r} of family {family!r}"


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
