# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical epoch E2 (2026-09-26): the comparison families' laws, their
store rows, and the absence of any comparison byte on the wire.

Every law is pinned on the mechanism it names, both boundaries where it
classifies: the row refuses what the producer cannot publish and admits what
it does, the model binds the families to ONE baseline and partitions the
lanes into the four availability states, the store reads each family back
under its own name with DDL 0 — and the wire of this revision carries none of
it (the negative contract of the 2026-09-26 ruling).
"""

from __future__ import annotations

import dataclasses
import io
import json
import sqlite3
import typing
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.baseline import BaselineStatus, MetricsBaselineStatus
from codeclone.canonical import (
    CanonicalModelError,
    RunStore,
    StoreIntegrityError,
    WireDecodeError,
    comparison_rows,
    decode_canonical_json,
    encode_canonical_json,
    export_run,
)
from codeclone.canonical.comparison_rows import (
    BaselineWitnessRecord,
    ComparisonAvailabilityRow,
    DisabledCapabilityRow,
    FindingNoveltyRow,
    LaneTrustRow,
    MetricDeltaRow,
    MetricsBaselineWitnessRecord,
    comparison_availability_state,
)
from codeclone.canonical.model import ComparisonFacts
from codeclone.canonical.store import (
    FAMILY_ADOPTION_DELTA,
    FAMILY_API_SURFACE_DELTA,
    FAMILY_BASELINE_WITNESS,
    FAMILY_CLONE_NOVELTY,
    FAMILY_COMPARISON_AVAILABILITY,
    FAMILY_COMPLEXITY_NOVELTY,
    FAMILY_COUPLING_NOVELTY,
    FAMILY_DEAD_SYMBOL_NOVELTY,
    FAMILY_DEPENDENCY_CYCLE_NOVELTY,
    FAMILY_DISABLED_CAPABILITY,
    FAMILY_LANE_TRUST,
    FAMILY_METRICS_BASELINE_WITNESS,
    StoredFamily,
    _collected_model,
)
from codeclone.contracts import (
    BASELINE_FINGERPRINT_VERSION,
    BASELINE_SCHEMA_VERSION,
    CANONICAL_MODEL_REVISION,
    CANONICAL_WIRE_REVISION,
    COMPLEXITY_ALGORITHM_REVISION,
    DESIGN_METRICS_ALGORITHM_REVISION,
    LIVENESS_POLICY_VERSION,
    METRICS_BASELINE_SCHEMA_VERSION,
    STORAGE_SCHEMA_REVISION,
)
from codeclone.models import LaneTrustReason, ObservationLaneName
from tests.test_canonical_roundtrip import (
    FIXTURE_BASELINE_SCOPE_ID,
    FIXTURE_ROOT_DIGEST,
    comparison_fixture_facts,
    comparison_fixture_model,
    fixture_model,
)

_IDENTITY = {
    "baseline_scope_id": FIXTURE_BASELINE_SCOPE_ID,
    "root_digest": FIXTURE_ROOT_DIGEST,
}
_NO_CONTAINER: dict[str, str | None] = {"baseline_scope_id": None, "root_digest": None}

#: Every comparison storage family, spelled by hand.
_COMPARISON_FAMILIES: tuple[StoredFamily[typing.Any], ...] = (
    FAMILY_BASELINE_WITNESS,
    FAMILY_METRICS_BASELINE_WITNESS,
    FAMILY_LANE_TRUST,
    FAMILY_COMPARISON_AVAILABILITY,
    FAMILY_DISABLED_CAPABILITY,
    FAMILY_CLONE_NOVELTY,
    FAMILY_COMPLEXITY_NOVELTY,
    FAMILY_COUPLING_NOVELTY,
    FAMILY_DEAD_SYMBOL_NOVELTY,
    FAMILY_DEPENDENCY_CYCLE_NOVELTY,
    FAMILY_ADOPTION_DELTA,
    FAMILY_API_SURFACE_DELTA,
)


def _publish(store: RunStore, model: object, target: str = "head") -> str:
    return store.write_full_run(
        model,  # type: ignore[arg-type]
        namespace="e2",
        target=target,
        expected_generation=0,
    ).run_id


def _witness(**overrides: object) -> BaselineWitnessRecord:
    fields: dict[str, object] = {
        **_IDENTITY,
        "state": "trusted",
        "loaded": True,
        "status": "ok",
        "fingerprint_version": "3",
        "schema_version": "3.0",
        "python_tag": "cp314",
        "payload_sha256": FIXTURE_ROOT_DIGEST,
    }
    fields.update(overrides)
    return BaselineWitnessRecord(**fields)  # type: ignore[arg-type]


def _novelty(**overrides: object) -> FindingNoveltyRow:
    fields: dict[str, object] = {
        **_IDENTITY,
        "finding_id": "clone:function:aa11|0-19",
        "novelty": "new",
        "novelty_reason": None,
    }
    fields.update(overrides)
    return FindingNoveltyRow(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Vocabularies: mirrors pinned against their producers.
# ---------------------------------------------------------------------------


def test_the_mirrored_vocabularies_equal_their_producers() -> None:
    assert (
        tuple(sorted(status.value for status in BaselineStatus))
        == comparison_rows.BASELINE_STATUSES
    )
    assert (
        tuple(sorted(status.value for status in MetricsBaselineStatus))
        == comparison_rows.METRICS_BASELINE_STATUSES
    )
    assert (
        tuple(sorted(typing.get_args(ObservationLaneName)))
        == comparison_rows.OBSERVATION_LANES
    )
    assert (
        tuple(
            sorted(
                {
                    *typing.get_args(LaneTrustReason),
                    "baseline_missing",
                    "root_unverified",
                }
            )
        )
        == comparison_rows.LANE_TRUST_REASONS
    )
    assert set(comparison_rows.COMPARED_LANES) == set(
        comparison_rows.OBSERVATION_LANES
    ) - {"module_identity", "semantic_authority"}


def test_the_availability_owner_speaks_three_words_for_three_cases() -> None:
    assert comparison_availability_state(compared=True, lane_trusted=True) == (
        "compared"
    )
    assert comparison_availability_state(compared=True, lane_trusted=False) == (
        "compared"
    )
    assert comparison_availability_state(compared=False, lane_trusted=True) == (
        "not_compared"
    )
    assert comparison_availability_state(compared=False, lane_trusted=False) == (
        "unavailable"
    )


def test_a_comparison_row_requires_every_field() -> None:
    """The container/row rule of the composition pin, on the E2 row types:
    no row lets a caller omit a field, the house is the only container."""
    rows = (
        MetricDeltaRow,
        BaselineWitnessRecord,
        ComparisonAvailabilityRow,
        DisabledCapabilityRow,
        FindingNoveltyRow,
        LaneTrustRow,
        MetricsBaselineWitnessRecord,
    )
    for row in rows:
        defaulted = [
            field.name
            for field in dataclasses.fields(row)
            if field.default is not dataclasses.MISSING
            or field.default_factory is not dataclasses.MISSING
        ]
        assert defaulted == [], (row.__name__, defaulted)


# ---------------------------------------------------------------------------
# Row laws: refuse what the producer cannot publish, admit what it does.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (lambda: _witness(root_digest=None), "half a baseline identity"),
        (lambda: _witness(baseline_scope_id=None), "half a baseline identity"),
        (lambda: _witness(state="missing"), "contradicts its container"),
        (lambda: _witness(**_NO_CONTAINER), "contradicts its container"),
        (lambda: _witness(state="stale"), "unknown baseline witness state"),
        (lambda: _witness(status="updated"), "unknown baseline witness status"),
        (lambda: _witness(loaded=True, status="missing"), "loaded under the failure"),
        (lambda: _witness(python_tag=""), "python_tag must be a non-empty"),
        (lambda: _witness(loaded=1), "loaded must be a bool"),
        (
            lambda: MetricsBaselineWitnessRecord(
                **_IDENTITY,
                loaded=True,
                status="mismatch_scope_id",
                schema_version=None,
                payload_sha256=None,
            ),
            "loaded under the failure",
        ),
        (
            lambda: LaneTrustRow(
                **_IDENTITY, lane="dead_code", status="trusted", reason="payload_schema"
            ),
            "contradicts reason",
        ),
        (
            lambda: LaneTrustRow(
                **_IDENTITY,
                lane="dead_code",
                status="unavailable",
                reason="compatible",
            ),
            "contradicts reason",
        ),
        (
            lambda: LaneTrustRow(
                **_IDENTITY,
                lane="dead_code",
                status="unavailable",
                reason="baseline_missing",
            ),
            "contradicts the container identity",
        ),
        (
            lambda: LaneTrustRow(
                **_NO_CONTAINER,
                lane="dead_code",
                status="unavailable",
                reason="root_unverified",
            ),
            "contradicts the container identity",
        ),
        (
            lambda: LaneTrustRow(
                **_IDENTITY,
                lane="clones.segments",
                status="trusted",
                reason="compatible",
            ),
            "unknown lane trust lane",
        ),
        (
            lambda: ComparisonAvailabilityRow(
                **_IDENTITY, lane="module_identity", availability="compared"
            ),
            "unknown comparison availability lane",
        ),
        (
            lambda: ComparisonAvailabilityRow(
                **_IDENTITY, lane="dead_code", availability="disabled"
            ),
            "unknown comparison availability word",
        ),
        (
            lambda: ComparisonAvailabilityRow(
                **_NO_CONTAINER, lane="dead_code", availability="not_compared"
            ),
            "without a container",
        ),
        (lambda: _novelty(novelty="old"), "word"),
        (lambda: _novelty(novelty_reason="lane_unavailable"), "carries a reason"),
        (lambda: _novelty(novelty="known", **_NO_CONTAINER), "against no baseline"),
        (
            lambda: _novelty(novelty="unavailable", novelty_reason=None),
            "reason",
        ),
        (
            lambda: _novelty(
                novelty="unavailable", novelty_reason="not_baseline_governed"
            ),
            "reason",
        ),
        (lambda: _novelty(finding_id=""), "finding id must be"),
        (
            lambda: MetricDeltaRow(
                **_NO_CONTAINER, delta="typing_param_permille_delta", value=0
            ),
            "against no baseline",
        ),
        (
            lambda: MetricDeltaRow(
                **_IDENTITY, delta="typing_param_permille_delta", value=True
            ),
            "must be an int",
        ),
        (
            # ``health_delta`` joined the closed term set with canonical epoch
            # E3 (the delta annotation of ``health_result``); the term set
            # stays closed.
            lambda: MetricDeltaRow(**_IDENTITY, delta="score_delta", value=1),
            "unknown delta term",
        ),
        (
            lambda: MetricDeltaRow(**_IDENTITY, delta="api_breaking_changes", value=-1),
            "at least 0",
        ),
    ],
)
def test_rows_refuse_what_the_producer_cannot_publish(
    build: typing.Callable[[], object], match: str
) -> None:
    with pytest.raises(CanonicalModelError, match=match):
        build()


def test_rows_admit_the_boundaries_the_producer_publishes() -> None:
    # No container: the witness says ``missing``, a lane says why, an
    # availability says ``unavailable``, a governed finding is unavailable.
    assert _witness(**_NO_CONTAINER, state="missing", loaded=False, status="missing")
    assert LaneTrustRow(
        **_NO_CONTAINER,
        lane="dead_code",
        status="unavailable",
        reason="baseline_missing",
    )
    assert ComparisonAvailabilityRow(
        **_NO_CONTAINER, lane="dead_code", availability="unavailable"
    )
    assert _novelty(
        **_NO_CONTAINER, novelty="unavailable", novelty_reason="lane_unavailable"
    )
    # A container that did not load: status says why, loaded is false.
    assert _witness(state="untrusted", loaded=False, status="mismatch_scope_id")
    assert LaneTrustRow(
        **_IDENTITY, lane="dead_code", status="unavailable", reason="root_unverified"
    )
    # A negative permille delta is a measured delta; a zero count is too.
    assert MetricDeltaRow(**_IDENTITY, delta="typing_param_permille_delta", value=-40)
    assert MetricDeltaRow(**_IDENTITY, delta="api_breaking_changes", value=0)


# ---------------------------------------------------------------------------
# Model laws: one baseline, four states, a result iff its comparison ran.
# ---------------------------------------------------------------------------


def _normalize_with(**overrides: object) -> None:
    model = comparison_fixture_model()
    comparison = replace(model.facts.comparison, **overrides)  # type: ignore[arg-type]
    replace(model, facts=replace(model.facts, comparison=comparison)).normalize()


def test_the_comparison_fixture_is_admitted_and_distinguishing() -> None:
    comparison = comparison_fixture_model().normalize().facts.comparison
    words = {row.availability for row in comparison.comparison_availability}
    assert words == {"compared", "not_compared", "unavailable"}
    assert {row.lane for row in comparison.disabled_capabilities} == {
        "semantic_authority"
    }
    novelty = {
        row.novelty
        for rows in (
            comparison.clone_novelty,
            comparison.dead_symbol_novelty,
            comparison.complexity_novelty,
        )
        for row in rows
    }
    assert novelty == {"new", "known", "unavailable"}


def test_a_comparison_row_without_the_witness_is_refused() -> None:
    with pytest.raises(CanonicalModelError, match="without the baseline witness"):
        _normalize_with(baseline_witness=None)


def test_a_witnessed_run_witnesses_the_metrics_baseline_too() -> None:
    with pytest.raises(CanonicalModelError, match="not the metrics baseline"):
        _normalize_with(metrics_baseline_witness=None)


def test_a_row_naming_another_container_is_refused() -> None:
    """m-baseline-identity: one run is compared against ONE baseline."""
    fixture = comparison_fixture_facts()
    foreign = {
        replace(row, root_digest="f" * 64) if row.lane == "dead_code" else row
        for row in fixture.lane_trust
    }
    with pytest.raises(CanonicalModelError, match="one run is compared against one"):
        _normalize_with(lane_trust=frozenset(foreign))


def test_the_empty_house_is_the_unwitnessed_run() -> None:
    """The decoded-from-wire state: no witness, no rows — admitted."""
    model = fixture_model()
    assert model.normalize().facts.comparison == ComparisonFacts()


def test_a_lane_both_assessed_and_disabled_is_refused() -> None:
    fixture = comparison_fixture_facts()
    with pytest.raises(CanonicalModelError, match="both trust-assessed and disabled"):
        _normalize_with(
            disabled_capabilities=fixture.disabled_capabilities
            | {DisabledCapabilityRow(**_IDENTITY, lane="module_identity")}
        )


def test_a_lane_neither_assessed_nor_disabled_is_refused() -> None:
    with pytest.raises(CanonicalModelError, match="neither trust-assessed nor"):
        _normalize_with(disabled_capabilities=frozenset())


def test_a_compared_lane_without_availability_is_refused() -> None:
    """The four states partition: a comparable lane with no word at all is
    the fifth state the law forbids."""
    fixture = comparison_fixture_facts()
    with pytest.raises(CanonicalModelError, match="exactly one of an availability"):
        _normalize_with(
            comparison_availability=frozenset(
                row
                for row in fixture.comparison_availability
                if row.lane != "dependencies"
            )
        )


def test_a_disabled_lane_with_an_availability_word_is_refused() -> None:
    """m-availability: the fourth state folded into a word is refused."""
    fixture = comparison_fixture_facts()
    lanes = frozenset(row for row in fixture.lane_trust if row.lane != "api_surface")
    with pytest.raises(CanonicalModelError, match="exactly one of an availability"):
        _normalize_with(
            lane_trust=lanes,
            disabled_capabilities=fixture.disabled_capabilities
            | {DisabledCapabilityRow(**_IDENTITY, lane="api_surface")},
        )


@pytest.mark.parametrize(
    ("lane", "family"),
    [("adoption_counts", "adoption_delta"), ("api_surface", "api_surface_delta")],
)
def test_a_delta_exists_exactly_when_its_comparison_ran(lane: str, family: str) -> None:
    fixture = comparison_fixture_facts()
    not_compared = frozenset(
        replace(row, availability="not_compared") if row.lane == lane else row
        for row in fixture.comparison_availability
    )
    with pytest.raises(CanonicalModelError, match="delta is present while"):
        _normalize_with(comparison_availability=not_compared)
    with pytest.raises(CanonicalModelError, match="delta is absent while"):
        _normalize_with(**{family: frozenset()})
    _normalize_with(comparison_availability=not_compared, **{family: frozenset()})


def test_a_delta_family_is_admitted_whole_and_only_with_its_own_terms() -> None:
    fixture = comparison_fixture_facts()
    partial = frozenset(
        row for row in fixture.adoption_delta if row.delta != "docstring_permille_delta"
    )
    with pytest.raises(CanonicalModelError, match="not exactly its terms"):
        _normalize_with(adoption_delta=partial)
    foreign = partial | {MetricDeltaRow(**_IDENTITY, delta="new_api_symbols", value=1)}
    with pytest.raises(CanonicalModelError, match="not exactly its terms"):
        _normalize_with(adoption_delta=foreign)


def test_a_clone_verdict_requires_its_lane_compared() -> None:
    fixture = comparison_fixture_facts()
    not_compared = frozenset(
        replace(row, availability="not_compared")
        if row.lane == "clones.functions"
        else row
        for row in fixture.comparison_availability
    )
    with pytest.raises(CanonicalModelError, match=r"is 'new' while clones\.functions"):
        _normalize_with(comparison_availability=not_compared)
    # The block lane stays compared, so its ``known`` verdict stands alone.
    _normalize_with(
        comparison_availability=not_compared,
        clone_novelty=frozenset(
            row
            for row in fixture.clone_novelty
            if row.finding_id.startswith("clone:block:")
        ),
    )


def test_a_novelty_filed_under_another_subject_is_refused() -> None:
    with pytest.raises(CanonicalModelError, match="not a finding of its subject"):
        _normalize_with(
            complexity_novelty=frozenset({_novelty(finding_id="clone:function:x")})
        )
    with pytest.raises(CanonicalModelError, match="not a finding of its subject"):
        _normalize_with(
            clone_novelty=frozenset(
                {_novelty(finding_id="clone:segment:aa11|0-19", novelty="known")}
            )
        )
    with pytest.raises(CanonicalModelError, match="not a finding of its subject"):
        _normalize_with(clone_novelty=frozenset({_novelty(finding_id="clone:block:")}))


def test_two_novelties_of_one_finding_are_refused() -> None:
    with pytest.raises(CanonicalModelError, match=r"clone_novelty\.id"):
        _normalize_with(
            clone_novelty=frozenset(
                {
                    _novelty(finding_id="clone:block:k", novelty="known"),
                    _novelty(
                        finding_id="clone:block:k",
                        novelty="unavailable",
                        novelty_reason="lane_unavailable",
                    ),
                }
            )
        )


# ---------------------------------------------------------------------------
# The store: rows in ``objects``, read back by name, DDL 0.
# ---------------------------------------------------------------------------


def test_the_comparison_is_a_member_of_the_store_run(tmp_path: Path) -> None:
    """Decision D-10 (2026-09-28), the comparison half: the rows of the
    comparison house are MEMBERS of the store run, never a key beside it.
    One analysis, published once unwitnessed and once compared against a
    container, is two store runs over ONE scope receipt."""
    compared = comparison_fixture_model()
    with RunStore(tmp_path / "runs.sqlite3") as store:
        unwitnessed = store.write_full_run(
            fixture_model(), namespace="e2", target="a", expected_generation=0
        )
        witnessed = store.write_full_run(
            compared, namespace="e2", target="b", expected_generation=0
        )
    assert (
        compared.normalize().facts.analysis
        == fixture_model().normalize().facts.analysis
    )
    assert witnessed.analysis_scope_digest == unwitnessed.analysis_scope_digest
    assert witnessed.run_id != unwitnessed.run_id
    assert witnessed.object_count > unwitnessed.object_count


def test_each_comparison_family_is_read_back_under_its_own_name(
    tmp_path: Path,
) -> None:
    model = comparison_fixture_model()
    expected = model.normalize().facts.comparison
    with RunStore(tmp_path / "runs.sqlite3") as store:
        run_id = _publish(store, model)
        whole = store.read_run(run_id).facts.comparison
        read = {
            entry.family: store.read_family(run_id, entry)
            for entry in _COMPARISON_FAMILIES
        }
    assert whole == expected
    assert read["baseline_witness"] == (expected.baseline_witness,)
    assert read["metrics_baseline_witness"] == (expected.metrics_baseline_witness,)
    assert frozenset(read["adoption_delta"]) == expected.adoption_delta
    assert frozenset(read["api_surface_delta"]) == expected.api_surface_delta
    assert frozenset(read["lane_trust"]) == expected.lane_trust
    assert frozenset(read["comparison_availability"]) == (
        expected.comparison_availability
    )
    assert frozenset(read["disabled_capability"]) == expected.disabled_capabilities
    assert frozenset(read["clone_novelty"]) == expected.clone_novelty
    assert frozenset(read["complexity_novelty"]) == expected.complexity_novelty
    assert frozenset(read["coupling_novelty"]) == expected.coupling_novelty
    assert frozenset(read["dead_symbol_novelty"]) == expected.dead_symbol_novelty
    assert frozenset(read["dependency_cycle_novelty"]) == (
        expected.dependency_cycle_novelty
    )


def test_the_comparison_families_take_no_ddl(tmp_path: Path) -> None:
    """Rows in ``objects(object_id, family, payload)`` under the storage
    revision the tree already has: no table, no index names a family."""
    assert STORAGE_SCHEMA_REVISION == "1"
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        _publish(store, comparison_fixture_model())
    connection = sqlite3.connect(path)
    try:
        schema = {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
            )
        }
        families = {
            family
            for (family,) in connection.execute(
                "SELECT DISTINCT f.family FROM objects o "
                "JOIN families f ON f.family_pk = o.family_pk"
            )
        }
    finally:
        connection.close()
    names = {entry.family for entry in _COMPARISON_FAMILIES}
    assert names <= families
    assert not any(any(name in item for name in names) for item in schema)


def test_each_comparison_family_takes_the_namespace_of_its_contracts() -> None:
    baseline = f"baseline_schema:{BASELINE_SCHEMA_VERSION}"
    metrics = f"{baseline}:metrics_baseline_schema:{METRICS_BASELINE_SCHEMA_VERSION}"
    expected = {
        "baseline_witness": baseline,
        "lane_trust": baseline,
        "comparison_availability": baseline,
        "disabled_capability": baseline,
        "metrics_baseline_witness": metrics,
        "adoption_delta": metrics,
        "api_surface_delta": metrics,
        "clone_novelty": f"clone_fingerprint:{BASELINE_FINGERPRINT_VERSION}:{baseline}",
        "complexity_novelty": (
            f"complexity_metrics:{COMPLEXITY_ALGORITHM_REVISION}:{baseline}"
        ),
        "coupling_novelty": (
            f"design_metrics:{DESIGN_METRICS_ALGORITHM_REVISION}:{baseline}"
        ),
        "dead_symbol_novelty": f"liveness:{LIVENESS_POLICY_VERSION}:{baseline}",
        "dependency_cycle_novelty": (
            f"canonical_model:{CANONICAL_MODEL_REVISION}:{baseline}"
        ),
    }
    assert {entry.family: entry.namespace for entry in _COMPARISON_FAMILIES} == expected


@pytest.mark.parametrize(
    ("family", "record"),
    [
        ("baseline_witness", "baseline_witness"),
        ("metrics_baseline_witness", "metrics_baseline_witness"),
    ],
)
def test_two_stored_comparison_records_of_one_run_are_a_writer_defect(
    family: str, record: str
) -> None:
    value = getattr(comparison_fixture_facts(), record)
    with pytest.raises(StoreIntegrityError, match=f"more than one {family}"):
        _collected_model({family: [value, value]})


def test_the_comparison_house_enters_the_store_run_and_not_the_wire(
    tmp_path: Path,
) -> None:
    """The comparison facts are MEMBERS of the run — its identity names the
    comparison it made — while the artifact the run exports is the
    analysis-only wire, byte for byte: until the wire-revision bump the
    export carries no comparison section."""
    analysis_only = fixture_model()
    compared = comparison_fixture_model()
    with RunStore(tmp_path / "runs.sqlite3") as store:
        plain = _publish(store, analysis_only, target="plain")
        full = _publish(store, compared, target="full")
        plain_bytes, full_bytes = io.BytesIO(), io.BytesIO()
        plain_envelope = export_run(store, plain, plain_bytes)
        full_envelope = export_run(store, full, full_bytes)
        assert store.project_run(full) == encode_canonical_json(analysis_only)
    assert plain != full
    assert full_bytes.getvalue() == plain_bytes.getvalue()
    assert full_envelope.artifact_digest == plain_envelope.artifact_digest
    assert full_envelope.wire_revision == CANONICAL_WIRE_REVISION


# ---------------------------------------------------------------------------
# The negative contract: no comparison byte on the wire of this revision.
# ---------------------------------------------------------------------------


def test_the_wire_carries_no_comparison_section() -> None:
    """Byte for byte AND semantically: the encoding of a model compared
    against a baseline is the encoding of the same analysis uncompared, no
    member of it names a comparison family, and a decode answers the house
    empty — "not witnessed by this artifact", never "compared, nothing"."""
    compared = comparison_fixture_model()
    data = encode_canonical_json(compared)
    assert data == encode_canonical_json(fixture_model())
    document = json.loads(data)
    assert "comparison" not in document
    assert not set(document["facts"]) & set(ComparisonFacts.__annotations__)
    for family in (entry.family for entry in _COMPARISON_FAMILIES):
        assert f'"{family}"'.encode() not in data
    decoded = decode_canonical_json(data)
    assert decoded.facts.comparison == ComparisonFacts()
    assert decoded == replace(
        compared.normalize(),
        facts=replace(compared.normalize().facts, comparison=ComparisonFacts()),
    )


def test_a_revision_one_document_carrying_a_comparison_section_is_refused() -> None:
    """The reader's half of the fence: a comparison member under wire
    revision 1 is not a document this revision reads."""
    document = json.loads(encode_canonical_json(fixture_model()))
    integrity = document.pop("integrity")
    document["comparison"] = {}
    document["integrity"] = integrity
    with pytest.raises(WireDecodeError) as refusal:
        decode_canonical_json(json.dumps(document, separators=(",", ":")).encode())
    assert refusal.value.code == "W01"
