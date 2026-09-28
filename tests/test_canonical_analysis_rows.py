# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical epoch E1 (2026-09-25): the eleven published-population families.

Every law here is pinned on the mechanism it names, both boundaries where
a fix corrects a classification: the row refuses what the producer cannot
publish, the model keys each family on its natural key, the closure
admits a symbol or a file on a family's word alone, the wire refuses a
malformed member with a typed code, the store reads each family back
under its own name, and the ingest oracle reads each family from the
container the document builder writes — and keeps the suppressed clone
population OUT of the emitted one (A1), and the absent coverage join OUT
of the empty one (A5).
"""

from __future__ import annotations

import copy
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from codeclone.canonical import (
    AnalysisFacts,
    CanonicalModel,
    CanonicalModelError,
    CloneItemRow,
    FileId,
    RunStore,
    StoreIntegrityError,
    SymbolId,
    WireDecodeError,
    decode_canonical_json,
    encode_canonical_json,
)
from codeclone.canonical.analysis_rows import (
    CohesionHotspotRow,
    ComplexityHotspotRow,
    CouplingHotspotRow,
    CoverageJoinRecord,
    CoverageUnitRow,
    DeadCodeSummaryRecord,
    DeadSymbolGroupRow,
    OverloadedModuleRow,
    StructuralGroupRow,
    SuppressedCloneGroupRow,
    UnreachableStatementRow,
)
from codeclone.canonical.errors import LegacyIngestError
from codeclone.canonical.ingest import canonical_model_from_legacy_document
from codeclone.canonical.store import (
    FAMILY_COHESION_HOTSPOT,
    FAMILY_COMPLEXITY_HOTSPOT,
    FAMILY_COUPLING_HOTSPOT,
    FAMILY_COVERAGE_JOIN,
    FAMILY_COVERAGE_UNIT,
    FAMILY_DEAD_CODE_SUMMARY,
    FAMILY_DEAD_SYMBOL_GROUP,
    FAMILY_OVERLOADED_MODULE,
    FAMILY_STRUCTURAL_GROUP,
    FAMILY_SUPPRESSED_CLONE_GROUP,
    FAMILY_UNREACHABLE_STATEMENT_GROUP,
    _collected_model,
)
from codeclone.contracts import (
    BASELINE_FINGERPRINT_VERSION,
    CANONICAL_MODEL_REVISION,
    COMPLEXITY_ALGORITHM_REVISION,
    DESIGN_METRICS_ALGORITHM_REVISION,
    LIVENESS_POLICY_VERSION,
    SOURCE_KIND_POLICY_VERSION,
    STATEMENT_REACHABILITY_POLICY_VERSION,
    STORAGE_SCHEMA_REVISION,
    STRUCTURAL_FINDINGS_CATALOG_VERSION,
)
from tests._served_run import ServedRunStoreProjection
from tests.conftest import RunStoreCorpusRunner
from tests.test_canonical_ingest import legacy_document
from tests.test_canonical_roundtrip import analysis_facts, fixture_model

_FA = FileId("pkg/a.py")
_FB = FileId("tools/b.py")
_SA = SymbolId(_FA, "A.run")
_SB = SymbolId(_FB, "helper")


def _overloaded(file: FileId = _FA, **overrides: object) -> OverloadedModuleRow:
    values: dict[str, object] = {
        "file": file,
        "source_kind": "production",
        "callable_count": 1,
        "classes": 0,
        "complexity_max": 3,
        "complexity_total": 3,
        "fan_in": 0,
        "fan_out": 1,
        "functions": 1,
        "import_edges": 1,
        "loc": 10,
        "methods": 0,
        "reimport_edges": 0,
        "reimport_ratio": 0.0,
        "total_deps": 1,
        "dependency_score": 0.25,
        "hub_balance": 0.5,
        "instability": 1.0,
        "score": 0.1234,
        "shape_score": 0.0,
        "size_score": 0.0001,
        "candidate_status": "non_candidate",
        "candidate_reasons": (),
    }
    values.update(overrides)
    return OverloadedModuleRow(**values)  # type: ignore[arg-type]


def _dead(**overrides: object) -> DeadSymbolGroupRow:
    values: dict[str, object] = {
        "symbol": _SA,
        "start_line": 10,
        "end_line": 24,
        "candidate_kind": "method",
        "confidence": "high",
        "reason": "unreferenced",
        "test_reference_sources": (),
    }
    values.update(overrides)
    return DeadSymbolGroupRow(**values)  # type: ignore[arg-type]


def _unit(**overrides: object) -> CoverageUnitRow:
    values: dict[str, object] = {
        "symbol": _SA,
        "start_line": 10,
        "end_line": 24,
        "executable_lines": 12,
        "covered_lines": 9,
        "coverage_status": "measured",
    }
    values.update(overrides)
    return CoverageUnitRow(**values)  # type: ignore[arg-type]


def _join(**overrides: object) -> CoverageJoinRecord:
    values: dict[str, object] = {
        "status": "ok",
        "source": "coverage.xml",
        "files": 2,
        "hotspot_threshold_percent": 50,
        "invalid_reason": None,
    }
    values.update(overrides)
    return CoverageJoinRecord(**values)  # type: ignore[arg-type]


def _suppressed(**overrides: object) -> SuppressedCloneGroupRow:
    values: dict[str, object] = {
        "clone_kind": "function",
        "group_key": "ffff|20-39",
        "items": frozenset({CloneItemRow(_SA, 30, 45), CloneItemRow(_SB, 3, 18)}),
        "suppression_rule": "golden_fixture",
        "suppression_source": "project_config",
        "matched_patterns": ("tests/fixtures/golden_*",),
    }
    values.update(overrides)
    return SuppressedCloneGroupRow(**values)  # type: ignore[arg-type]


def _structural(**overrides: object) -> StructuralGroupRow:
    values: dict[str, object] = {
        "finding_kind": "duplicated_branches",
        "finding_key": "k1",
        "signature": (("calls", "2"), ("stmt_seq", "Continue")),
        "occurrences": frozenset({CloneItemRow(_SA, 5, 9)}),
    }
    values.update(overrides)
    return StructuralGroupRow(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Row laws: what the producer cannot publish, the row refuses.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (lambda: _suppressed(clone_kind="banana"), "unknown clone kind"),
        (lambda: _suppressed(group_key=""), "group key"),
        (
            lambda: _suppressed(items=frozenset({CloneItemRow(_SA, 30, 45)})),
            "at least two items",
        ),
        (lambda: _suppressed(suppression_rule=""), "suppression rule"),
        (lambda: _suppressed(suppression_source=""), "suppression source"),
        (lambda: _suppressed(matched_patterns=()), "at least one matched pattern"),
        (lambda: _suppressed(matched_patterns=("a", "")), "matched patterns member"),
        (lambda: _structural(finding_kind="banana"), "unknown finding kind"),
        (lambda: _structural(finding_key=""), "finding key"),
        (lambda: _structural(occurrences=frozenset()), "at least one occurrence"),
        (
            lambda: _structural(signature=(("b", "1"), ("a", "2"))),
            "sorted and unique",
        ),
        (
            lambda: _structural(signature=(("a", "1"), ("a", "2"))),
            "sorted and unique",
        ),
        (lambda: _dead(candidate_kind="banana"), "candidate kind"),
        (lambda: _dead(confidence="certain"), "dead-symbol confidence"),
        (lambda: _dead(reason="banana"), "dead-symbol reason"),
        (lambda: _dead(start_line=0), "start line"),
        (lambda: _dead(end_line=9), "end line must not precede"),
        (
            lambda: _dead(test_reference_sources=("b", "a")),
            "sorted and unique",
        ),
        # Both boundaries of the reason/evidence contract.
        (
            lambda: _dead(reason="test_only_reference"),
            "non-empty exactly when",
        ),
        (
            lambda: _dead(test_reference_sources=("tests.t:test_a",)),
            "non-empty exactly when",
        ),
        (
            lambda: UnreachableStatementRow(
                symbol=_SA, start_line=1, end_line=1, reason="banana", statement_count=1
            ),
            "unreachable reason",
        ),
        (
            lambda: UnreachableStatementRow(
                symbol=_SA,
                start_line=1,
                end_line=1,
                reason="after_terminator",
                statement_count=0,
            ),
            "statement count",
        ),
        (
            lambda: ComplexityHotspotRow(
                symbol=_SA,
                start_line=1,
                end_line=1,
                cyclomatic_complexity=0,
                nesting_depth=0,
            ),
            "cyclomatic complexity",
        ),
        (
            lambda: ComplexityHotspotRow(
                symbol=_SA,
                start_line=1,
                end_line=1,
                cyclomatic_complexity=3,
                nesting_depth=-1,
            ),
            "nesting depth",
        ),
        (
            lambda: CouplingHotspotRow(
                symbol=_SA, start_line=1, end_line=1, cbo=2, coupled_classes=("B", "A")
            ),
            "sorted and unique",
        ),
        (
            lambda: CouplingHotspotRow(
                symbol=_SA, start_line=1, end_line=1, cbo=True, coupled_classes=()
            ),
            "cbo",
        ),
        (
            lambda: CohesionHotspotRow(
                symbol=_SA,
                start_line=1,
                end_line=1,
                lcom4=1,
                method_count=1,
                instance_var_count=-1,
            ),
            "instance variable count",
        ),
        (lambda: _overloaded(source_kind="banana"), "unknown source kind"),
        (lambda: _overloaded(loc=-1), "overloaded module loc"),
        (lambda: _overloaded(score=0.12345), "more than 4 decimals"),
        (lambda: _overloaded(score=-0.5), "finite non-negative"),
        (lambda: _overloaded(score=float("nan")), "finite non-negative"),
        (lambda: _overloaded(score=1), "must be a float"),
        (lambda: _overloaded(candidate_status="maybe"), "candidate status"),
        (lambda: _overloaded(candidate_reasons=("",)), "candidate reasons member"),
        (lambda: _unit(coverage_status="banana"), "coverage status"),
        (lambda: _unit(covered_lines=13), "cannot exceed executable"),
        # Both boundaries of the status/executable-lines contract.
        (lambda: _unit(executable_lines=0, covered_lines=0), "measured exactly when"),
        (
            lambda: _unit(coverage_status="missing_from_report"),
            "measured exactly when",
        ),
        (lambda: _join(status="pending"), "coverage join status"),
        (lambda: _join(source=""), "coverage join source"),
        # Both boundaries of the status/reason contract.
        (lambda: _join(status="invalid"), "exactly when its status is invalid"),
        (lambda: _join(invalid_reason="bad xml"), "exactly when its status is invalid"),
        (
            lambda: _join(status="invalid", invalid_reason="bad xml", files=1),
            "mapped no file",
        ),
        (
            lambda: DeadCodeSummaryRecord(
                suppressed=0,
                unresolved=0,
                unresolved_internal=0,
                unresolved_external_override=0,
                candidates=0,
                nested_candidates=0,
                live_roots=0,
                world_contract="flat",
            ),
            "world contract",
        ),
        (
            lambda: DeadCodeSummaryRecord(
                suppressed=0,
                unresolved=-1,
                unresolved_internal=0,
                unresolved_external_override=0,
                candidates=0,
                nested_candidates=0,
                live_roots=0,
                world_contract="open",
            ),
            "dead-code summary unresolved",
        ),
    ],
)
def test_rows_refuse_what_the_producer_cannot_publish(
    build: Callable[[], object], match: str
) -> None:
    with pytest.raises(CanonicalModelError, match=match):
        build()


def test_rows_admit_the_boundaries_the_producer_publishes() -> None:
    """The admitted side of every refused boundary above."""
    assert _dead(reason="test_only_reference", test_reference_sources=("t:x",))
    assert _unit(
        executable_lines=0, covered_lines=0, coverage_status="no_executable_lines"
    )
    assert _unit(
        executable_lines=0, covered_lines=0, coverage_status="missing_from_report"
    )
    assert _join(status="invalid", invalid_reason="bad xml", files=0)
    assert _overloaded(score=0.1234, size_score=1.0)
    assert _structural(signature=())
    assert _dead(start_line=7, end_line=7)


# ---------------------------------------------------------------------------
# Model laws: keys, the coverage-join binding, and the closure.
# ---------------------------------------------------------------------------


def _model(**families: object) -> CanonicalModel:
    return CanonicalModel(facts=analysis_facts(**families))


@pytest.mark.parametrize(
    ("family", "rows", "key"),
    [
        (
            "suppressed_clone_groups",
            [_suppressed(), _suppressed(suppression_rule="other")],
            "suppressed_clone_groups.key",
        ),
        (
            "structural_groups",
            [_structural(), _structural(signature=())],
            "structural_groups.key",
        ),
        ("dead_symbol_groups", [_dead(), _dead(confidence="medium")], "dead_symbol"),
        (
            "unreachable_statement_groups",
            [
                UnreachableStatementRow(
                    symbol=_SA,
                    start_line=1,
                    end_line=2,
                    reason="after_terminator",
                    statement_count=1,
                ),
                UnreachableStatementRow(
                    symbol=_SA,
                    start_line=1,
                    end_line=3,
                    reason="after_terminator",
                    statement_count=2,
                ),
            ],
            "unreachable_statement_groups.key",
        ),
        (
            "complexity_hotspots",
            [
                ComplexityHotspotRow(
                    symbol=_SA,
                    start_line=1,
                    end_line=9,
                    cyclomatic_complexity=21,
                    nesting_depth=1,
                ),
                ComplexityHotspotRow(
                    symbol=_SA,
                    start_line=1,
                    end_line=9,
                    cyclomatic_complexity=22,
                    nesting_depth=1,
                ),
            ],
            "complexity_hotspots.key",
        ),
        (
            "coupling_hotspots",
            [
                CouplingHotspotRow(
                    symbol=_SA, start_line=1, end_line=9, cbo=11, coupled_classes=()
                ),
                CouplingHotspotRow(
                    symbol=_SA, start_line=1, end_line=9, cbo=12, coupled_classes=()
                ),
            ],
            "coupling_hotspots.key",
        ),
        (
            "cohesion_hotspots",
            [
                CohesionHotspotRow(
                    symbol=_SA,
                    start_line=1,
                    end_line=9,
                    lcom4=4,
                    method_count=4,
                    instance_var_count=0,
                ),
                CohesionHotspotRow(
                    symbol=_SA,
                    start_line=1,
                    end_line=9,
                    lcom4=5,
                    method_count=4,
                    instance_var_count=0,
                ),
            ],
            "cohesion_hotspots.key",
        ),
        (
            "overloaded_modules",
            [_overloaded(), _overloaded(loc=11)],
            "overloaded_modules.file",
        ),
    ],
)
def test_model_refuses_two_facts_under_one_natural_key(
    family: str, rows: list[object], key: str
) -> None:
    with pytest.raises(CanonicalModelError, match=key):
        _model(**{family: frozenset(rows)}).normalize()


def test_model_refuses_two_coverage_units_under_one_site() -> None:
    model = _model(
        coverage_units=frozenset({_unit(), _unit(covered_lines=8)}),
        coverage_join=_join(),
    )
    with pytest.raises(CanonicalModelError, match=r"coverage_units\.key"):
        model.normalize()


def test_rows_differing_in_a_key_component_coexist() -> None:
    """The other side of every key: a second site of one symbol, a second
    kind under one key string, a second file — all legitimate rows."""
    model = _model(
        suppressed_clone_groups=frozenset(
            {_suppressed(), _suppressed(clone_kind="block")}
        ),
        structural_groups=frozenset(
            {_structural(), _structural(finding_kind="clone_cohort_drift")}
        ),
        dead_symbol_groups=frozenset({_dead(), _dead(start_line=40, end_line=41)}),
        overloaded_modules=frozenset({_overloaded(), _overloaded(file=_FB)}),
    ).normalize()
    assert len(model.facts.analysis.suppressed_clone_groups) == 2
    assert len(model.facts.analysis.structural_groups) == 2
    assert len(model.facts.analysis.dead_symbol_groups) == 2
    assert len(model.facts.analysis.overloaded_modules) == 2


def test_coverage_units_are_bound_to_a_readable_join() -> None:
    """A5, both boundaries: units without the record are refused, units
    under an invalid join are refused, and a readable join that mapped no
    unit is admitted."""
    with pytest.raises(CanonicalModelError, match="without a coverage join record"):
        _model(coverage_units=frozenset({_unit()})).normalize()
    invalid = _join(status="invalid", invalid_reason="bad xml", files=0)
    with pytest.raises(CanonicalModelError, match="invalid coverage join"):
        _model(coverage_units=frozenset({_unit()}), coverage_join=invalid).normalize()
    admitted = _model(coverage_join=_join()).normalize()
    assert admitted.facts.analysis.coverage_join == _join()
    assert admitted.facts.analysis.coverage_units == frozenset()


def test_the_closure_admits_identities_on_an_e1_family_alone() -> None:
    """A symbol referenced by the cohesion family alone, a file referenced
    by the overloaded family alone: both enter their domains."""
    lone_class = SymbolId(FileId("zz/lone.py"), "Lone")
    lone_file = FileId("zz/only.py")
    model = _model(
        cohesion_hotspots=frozenset(
            {
                CohesionHotspotRow(
                    symbol=lone_class,
                    start_line=1,
                    end_line=2,
                    lcom4=4,
                    method_count=4,
                    instance_var_count=0,
                )
            }
        ),
        overloaded_modules=frozenset({_overloaded(file=lone_file)}),
    ).normalize()
    assert lone_class.file in model.files
    assert lone_file in model.files


# ---------------------------------------------------------------------------
# The wire: every E1 member survives the round trip, and refuses typed.
# ---------------------------------------------------------------------------


def test_the_e1_families_survive_the_round_trip() -> None:
    model = fixture_model().normalize()
    decoded = decode_canonical_json(encode_canonical_json(model))
    for family in (
        "suppressed_clone_groups",
        "structural_groups",
        "dead_symbol_groups",
        "unreachable_statement_groups",
        "complexity_hotspots",
        "coupling_hotspots",
        "cohesion_hotspots",
        "overloaded_modules",
        "coverage_units",
    ):
        rows = getattr(model.facts.analysis, family)
        assert rows, f"{family} is empty on the fixture; the comparison is hollow"
        assert getattr(decoded.facts.analysis, family) == rows, family
    assert decoded.facts.analysis.coverage_join == model.facts.analysis.coverage_join
    assert decoded.facts.analysis.dead_code_summary == (
        model.facts.analysis.dead_code_summary
    )


def test_absent_records_are_the_empty_member_and_decode_to_absence() -> None:
    """A5/A7: the absent record is ``{}`` on the wire, never a zero record,
    and reads back as ``None``."""
    payload = encode_canonical_json(_model())
    document = json.loads(payload)
    assert document["facts"]["coverage_join"] == {}
    assert document["facts"]["dead_code_summary"] == {}
    decoded = decode_canonical_json(payload)
    assert decoded.facts.analysis.coverage_join is None
    assert decoded.facts.analysis.dead_code_summary is None


def _replaced(data: bytes, needle: str, replacement: str) -> bytes:
    text = data.decode("utf-8")
    assert text.count(needle) == 1, f"needle not unique: {needle!r}"
    return text.replace(needle, replacement).encode("utf-8")


@pytest.mark.parametrize(
    ("code", "needle", "replacement"),
    [
        (
            "W08",
            '"finding_kind":["clone_cohort_drift","duplicated_branches"]',
            '"finding_kind":["banana","duplicated_branches"]',
        ),
        (
            "W12",
            '"finding_kind":["clone_cohort_drift","duplicated_branches"]',
            '"finding_kind":["duplicated_branches","clone_cohort_drift"]',
        ),
        (
            "W18",
            '"items":[[[1,30,45],[7,3,18]]]',
            '"items":[[[1,30,45]]]',
        ),
        (
            "W08",
            '"reason":["unreferenced","test_only_reference","unreferenced"]',
            '"reason":["banana","test_only_reference","unreferenced"]',
        ),
        # The model law reached through the decoder: a test-only reason
        # with no evidence is refused typed, never as a bare model error.
        (
            "W18",
            '"test_reference_sources":[[],["tests.test_a:test_x"],[]]',
            '"test_reference_sources":[[],[],[]]',
        ),
        (
            "W08",
            '"reason":["after_terminator","literal_condition"]',
            '"reason":["after_terminator","banana"]',
        ),
        # Site rows out of canonical order, and a duplicated site.
        (
            "W12",
            '"end_line":[22,30],"reason":["after_terminator","literal_condition"],'
            '"start_line":[20,30],"statement_count":[2,1]',
            '"end_line":[30,22],"reason":["literal_condition","after_terminator"],'
            '"start_line":[30,20],"statement_count":[1,2]',
        ),
        (
            "W13",
            '"start_line":[20,30],"statement_count":[2,1],"symbol":[7,7]',
            '"start_line":[20,20],"statement_count":[2,1],"symbol":[7,7]',
        ),
        ("W07", '"start_line":[20,30]', '"start_line":[0,30]'),
        ("W07", '"end_line":[22,30]', '"end_line":[19,30]'),
        (
            "W08",
            '"candidate_status":["candidate","non_candidate"]',
            '"candidate_status":["banana","non_candidate"]',
        ),
        ("W18", '"score":[0.9972,0.0]', '"score":[0.9972,0]'),
        ("W07", '"score":[0.9972,0.0]', '"score":[-0.9972,0.0]'),
        (
            "W08",
            '"source_kind":["production","tests"]',
            '"source_kind":["production","banana"]',
        ),
        ("W12", '"file":[0,2]', '"file":[2,0]'),
        (
            "W08",
            '"coverage_status":["measured","no_executable_lines","missing_from_report"]',
            '"coverage_status":["measured","banana","missing_from_report"]',
        ),
        (
            "W08",
            '"source":"coverage.xml","status":"ok"',
            '"source":"coverage.xml","status":"pending"',
        ),
        (
            "W01",
            '"files":2,"hotspot_threshold_percent":50,',
            '"files":2,',
        ),
        (
            "W02",
            '"files":2,"hotspot_threshold_percent":50,',
            '"hotspot_threshold_percent":50,"files":2,',
        ),
        ("W08", '"world_contract":"open"', '"world_contract":"flat"'),
        ("W18", '"invalid_reason":"",', '"invalid_reason":"bad xml",'),
    ],
)
def test_e1_wire_members_refuse_typed(code: str, needle: str, replacement: str) -> None:
    data = encode_canonical_json(fixture_model())
    with pytest.raises(WireDecodeError) as caught:
        decode_canonical_json(_replaced(data, needle, replacement))
    assert caught.value.code == code, str(caught.value)


# ---------------------------------------------------------------------------
# The store: each family read back under its own name.
# ---------------------------------------------------------------------------


def test_each_e1_family_is_read_back_under_its_own_name(tmp_path: Path) -> None:
    model = fixture_model().normalize()
    facts = model.facts.analysis
    with RunStore(tmp_path / "runs.sqlite3") as store:
        run_id = _publish(store, model)
        assert frozenset(store.read_family(run_id, FAMILY_SUPPRESSED_CLONE_GROUP)) == (
            facts.suppressed_clone_groups
        )
        assert frozenset(store.read_family(run_id, FAMILY_STRUCTURAL_GROUP)) == (
            facts.structural_groups
        )
        assert frozenset(store.read_family(run_id, FAMILY_DEAD_SYMBOL_GROUP)) == (
            facts.dead_symbol_groups
        )
        assert (
            frozenset(store.read_family(run_id, FAMILY_UNREACHABLE_STATEMENT_GROUP))
            == facts.unreachable_statement_groups
        )
        assert frozenset(store.read_family(run_id, FAMILY_COMPLEXITY_HOTSPOT)) == (
            facts.complexity_hotspots
        )
        assert frozenset(store.read_family(run_id, FAMILY_COUPLING_HOTSPOT)) == (
            facts.coupling_hotspots
        )
        assert frozenset(store.read_family(run_id, FAMILY_COHESION_HOTSPOT)) == (
            facts.cohesion_hotspots
        )
        assert frozenset(store.read_family(run_id, FAMILY_OVERLOADED_MODULE)) == (
            facts.overloaded_modules
        )
        assert frozenset(store.read_family(run_id, FAMILY_COVERAGE_UNIT)) == (
            facts.coverage_units
        )
        assert store.read_family(run_id, FAMILY_COVERAGE_JOIN) == (facts.coverage_join,)
        assert store.read_family(run_id, FAMILY_DEAD_CODE_SUMMARY) == (
            facts.dead_code_summary,
        )
        assert store.read_run(run_id) == model


def _publish(store: RunStore, model: CanonicalModel) -> str:
    return store.write_full_run(
        model, namespace="probe", target="head", expected_generation=0
    ).run_id


def test_the_e1_families_take_no_ddl(tmp_path: Path) -> None:
    """The brief's stop condition, measured rather than assumed: the store
    is object-based, so the eleven families ride ``objects(object_id,
    family_pk, payload)`` under the storage revision E1 inherited — no table,
    no index, no schema bump.  Pinned on the schema the store declares and
    on the rows a published run actually lands."""
    # "2" is the E4 container (32-byte ids, family table and index; see
    # ``test_the_container_moved_so_the_storage_revision_moved``), not
    # these families: they still add no table and no index of their own.
    assert STORAGE_SCHEMA_REVISION == "2"
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        _publish(store, fixture_model())
    connection = sqlite3.connect(path)
    try:
        objects = {
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
    e1_families = {
        FAMILY_SUPPRESSED_CLONE_GROUP.family,
        FAMILY_STRUCTURAL_GROUP.family,
        FAMILY_DEAD_SYMBOL_GROUP.family,
        FAMILY_UNREACHABLE_STATEMENT_GROUP.family,
        FAMILY_COMPLEXITY_HOTSPOT.family,
        FAMILY_COUPLING_HOTSPOT.family,
        FAMILY_COHESION_HOTSPOT.family,
        FAMILY_OVERLOADED_MODULE.family,
        FAMILY_COVERAGE_UNIT.family,
        FAMILY_COVERAGE_JOIN.family,
        FAMILY_DEAD_CODE_SUMMARY.family,
    }
    assert e1_families <= families
    assert not any(any(family in name for family in e1_families) for name in objects)


def test_each_e1_family_takes_the_namespace_of_the_contract_that_owns_it() -> None:
    """A fact's content address carries the revision of the contract that
    gives it meaning (F-3 §5.0.1); spelled here by hand so a family quietly
    moved under another generation reddens."""
    expected: dict[str, str] = {
        "suppressed_clone_group": f"clone_fingerprint:{BASELINE_FINGERPRINT_VERSION}",
        "structural_group": (
            f"structural_findings:{STRUCTURAL_FINDINGS_CATALOG_VERSION}"
        ),
        "dead_symbol_group": f"liveness:{LIVENESS_POLICY_VERSION}",
        "unreachable_statement_group": (
            f"statement_reachability:{STATEMENT_REACHABILITY_POLICY_VERSION}"
        ),
        "complexity_hotspot": f"complexity_metrics:{COMPLEXITY_ALGORITHM_REVISION}",
        "coupling_hotspot": f"design_metrics:{DESIGN_METRICS_ALGORITHM_REVISION}",
        "cohesion_hotspot": f"design_metrics:{DESIGN_METRICS_ALGORITHM_REVISION}",
        "overloaded_module": (
            f"canonical_model:{CANONICAL_MODEL_REVISION}"
            f":source_kind:{SOURCE_KIND_POLICY_VERSION}"
        ),
        "coverage_unit": f"canonical_model:{CANONICAL_MODEL_REVISION}",
        "coverage_join": f"canonical_model:{CANONICAL_MODEL_REVISION}",
        "dead_code_summary": f"liveness:{LIVENESS_POLICY_VERSION}",
    }
    declared = {
        entry.family: entry.namespace
        for entry in (
            FAMILY_SUPPRESSED_CLONE_GROUP,
            FAMILY_STRUCTURAL_GROUP,
            FAMILY_DEAD_SYMBOL_GROUP,
            FAMILY_UNREACHABLE_STATEMENT_GROUP,
            FAMILY_COMPLEXITY_HOTSPOT,
            FAMILY_COUPLING_HOTSPOT,
            FAMILY_COHESION_HOTSPOT,
            FAMILY_OVERLOADED_MODULE,
            FAMILY_COVERAGE_UNIT,
            FAMILY_COVERAGE_JOIN,
            FAMILY_DEAD_CODE_SUMMARY,
        )
    }
    assert declared == expected


def test_two_stored_records_of_one_run_are_a_writer_defect() -> None:
    """The F9 law on the two new record families, refused in-band."""
    record = fixture_model().facts.analysis.dead_code_summary
    assert record is not None
    with pytest.raises(StoreIntegrityError, match="more than one dead_code_summary"):
        _collected_model({"dead_code_summary": [record, record]})
    join = fixture_model().facts.analysis.coverage_join
    assert join is not None
    with pytest.raises(StoreIntegrityError, match="more than one coverage_join"):
        _collected_model({"coverage_join": [join, join]})


# ---------------------------------------------------------------------------
# The ingest oracle: each family from the container the document writes.
# ---------------------------------------------------------------------------


def _mutated(mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    document = copy.deepcopy(legacy_document())
    mutate(document)
    return document


_MAKE = SymbolId(FileId("pkg/mod.py"), "make")
_RUN = SymbolId(FileId("scripts/tool.py"), "run")
_HELPER_CLASS = SymbolId(FileId("pkg/other.py"), "Helper")


def _ingested_facts() -> AnalysisFacts:
    return canonical_model_from_legacy_document(legacy_document()).facts.analysis


def test_ingest_reads_the_clone_populations_apart() -> None:
    """A1: the suppressed group is read with its provenance, and never
    enters the emitted family."""
    facts = _ingested_facts()
    assert facts.suppressed_clone_groups == frozenset(
        {
            SuppressedCloneGroupRow(
                clone_kind="function",
                group_key="ffff|20-39",
                items=frozenset(
                    {
                        CloneItemRow(_MAKE, 70, 90),
                        CloneItemRow(
                            SymbolId(FileId("pkg/other.py"), "helper"), 70, 90
                        ),
                    }
                ),
                suppression_rule="golden_fixture",
                suppression_source="project_config",
                matched_patterns=("tests/fixtures/golden_*", "tests/fixtures/extra_*"),
            )
        }
    )
    assert {row.group_key for row in facts.clone_groups} == {
        "aa11|0-19",
        "bb22|bb22|bb22|bb22",
    }


def test_ingest_reads_the_structural_groups_off_their_identity() -> None:
    facts = _ingested_facts()
    by_kind = {row.finding_kind: row for row in facts.structural_groups}
    assert set(by_kind) == {"duplicated_branches", "clone_cohort_drift"}
    assert {row.finding_key for row in facts.structural_groups} == {"k1"}
    branches = by_kind["duplicated_branches"]
    assert branches.signature == (("calls", "2"), ("stmt_seq", "Continue"))
    assert branches.occurrences == frozenset(
        {CloneItemRow(_MAKE, 5, 9), CloneItemRow(_RUN, 7, 11)}
    )


def test_ingest_reads_the_dead_code_groups_by_kind() -> None:
    facts = _ingested_facts()
    assert facts.dead_symbol_groups == frozenset(
        {
            DeadSymbolGroupRow(
                symbol=_MAKE,
                start_line=10,
                end_line=24,
                candidate_kind="function",
                confidence="high",
                reason="unreferenced",
                test_reference_sources=(),
            ),
            DeadSymbolGroupRow(
                symbol=_MAKE,
                start_line=40,
                end_line=40,
                candidate_kind="function",
                confidence="medium",
                reason="test_only_reference",
                test_reference_sources=("tests.test_mod:test_make",),
            ),
        }
    )
    assert facts.unreachable_statement_groups == frozenset(
        {
            UnreachableStatementRow(
                symbol=_RUN,
                start_line=20,
                end_line=22,
                reason="after_terminator",
                statement_count=2,
            )
        }
    )
    assert facts.dead_code_summary == DeadCodeSummaryRecord(
        suppressed=2,
        unresolved=85,
        unresolved_internal=559,
        unresolved_external_override=16,
        candidates=18621,
        nested_candidates=1309,
        live_roots=37,
        world_contract="open",
    )


def test_ingest_reads_the_design_groups_by_category() -> None:
    facts = _ingested_facts()
    assert facts.complexity_hotspots == frozenset(
        {
            ComplexityHotspotRow(
                symbol=_MAKE,
                start_line=10,
                end_line=24,
                cyclomatic_complexity=41,
                nesting_depth=4,
            )
        }
    )
    assert facts.coupling_hotspots == frozenset(
        {
            CouplingHotspotRow(
                symbol=_HELPER_CLASS,
                start_line=30,
                end_line=60,
                cbo=6,
                coupled_classes=("Token", "Writer"),
            )
        }
    )
    assert facts.cohesion_hotspots == frozenset(
        {
            CohesionHotspotRow(
                symbol=_HELPER_CLASS,
                start_line=30,
                end_line=60,
                lcom4=3,
                method_count=4,
                instance_var_count=1,
            )
        }
    )


def test_ingest_reads_the_overloaded_modules_and_the_coverage_join() -> None:
    facts = _ingested_facts()
    by_file = {row.file.path: row for row in facts.overloaded_modules}
    assert set(by_file) == {"pkg/mod.py", "scripts/tool.py"}
    assert by_file["pkg/mod.py"].score == 0.9972
    assert by_file["pkg/mod.py"].candidate_reasons == (
        "size_pressure",
        "dependency_pressure",
    )
    assert by_file["scripts/tool.py"].candidate_status == "non_candidate"
    assert facts.coverage_join == CoverageJoinRecord(
        status="ok",
        source="coverage.xml",
        files=2,
        hotspot_threshold_percent=50,
        invalid_reason=None,
    )
    assert {row.coverage_status for row in facts.coverage_units} == {
        "measured",
        "no_executable_lines",
        "missing_from_report",
    }


def test_ingest_answers_the_absent_containers_honestly() -> None:
    """A1: no ``suppressed`` container is the measured empty population.
    A5: no ``coverage_join`` container is the typed ABSENCE of the record —
    never an empty join."""

    def drop(document: dict[str, Any]) -> None:
        del document["findings"]["groups"]["clones"]["suppressed"]
        del document["metrics"]["families"]["coverage_join"]

    facts = canonical_model_from_legacy_document(_mutated(drop)).facts.analysis
    assert facts.suppressed_clone_groups == frozenset()
    assert facts.coverage_join is None
    assert facts.coverage_units == frozenset()


def test_ingest_reads_an_invalid_join_as_a_record_without_units() -> None:
    def invalidate(document: dict[str, Any]) -> None:
        join = document["metrics"]["families"]["coverage_join"]
        join["summary"].update(
            {"status": "invalid", "files": 0, "invalid_reason": "not cobertura"}
        )
        join["items"] = []

    facts = canonical_model_from_legacy_document(_mutated(invalidate)).facts.analysis
    assert facts.coverage_join == CoverageJoinRecord(
        status="invalid",
        source="coverage.xml",
        files=0,
        hotspot_threshold_percent=50,
        invalid_reason="not cobertura",
    )
    assert facts.coverage_units == frozenset()


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda d: d["findings"]["groups"]["dead_code"]["groups"][0].update(
                kind="banana"
            ),
            "unknown kind",
        ),
        (
            lambda d: d["findings"]["groups"]["design"]["groups"][0].update(
                category="banana"
            ),
            "unknown category",
        ),
        (
            lambda d: d["findings"]["groups"]["structural"]["groups"][0].update(
                id="structural:other:k1"
            ),
            "not spelled from kind",
        ),
        (
            lambda d: d["findings"]["groups"]["dead_code"]["groups"][0]["items"].append(
                {}
            ),
            "not a singleton group",
        ),
        (
            lambda d: d["metrics"]["families"]["overloaded_modules"]["items"][0].update(
                relative_path="pkg/nowhere.py"
            ),
            "not an analyzed path",
        ),
        (
            lambda d: d["metrics"]["families"]["overloaded_modules"]["items"][0].update(
                score=1
            ),
            "score is not a float",
        ),
        (
            lambda d: d["metrics"]["families"]["dead_code"].pop("summary"),
            "missing 'summary'",
        ),
        (
            lambda d: d["findings"]["groups"]["clones"]["suppressed"]["functions"][
                0
            ].pop("matched_patterns"),
            "missing 'matched_patterns'",
        ),
        (
            lambda d: d["findings"]["groups"].pop("structural"),
            "missing 'structural'",
        ),
    ],
)
def test_ingest_refuses_a_document_the_oracle_cannot_read(
    mutate: Callable[[dict[str, Any]], None], match: str
) -> None:
    with pytest.raises(LegacyIngestError, match=match):
        canonical_model_from_legacy_document(_mutated(mutate))


def test_ingest_never_reads_the_projected_design_categories() -> None:
    """Dependency and coverage design groups are projections of other
    families: a malformed one is invisible to the oracle."""

    def poison(document: dict[str, Any]) -> None:
        groups = document["findings"]["groups"]["design"]["groups"]
        groups.append({"category": "coverage", "items": "not a list"})

    model = canonical_model_from_legacy_document(_mutated(poison))
    assert len(model.facts.analysis.complexity_hotspots) == 1


# ---------------------------------------------------------------------------
# An MCP-published run: the surface's own execution, not a document-built
# model (census-3, 2026-09-25: the population witness of a run published
# through the MCP surface carries states the rendered document cannot
# express, so a pin that only ever ingests a document never sees the run
# the surface serves).
# ---------------------------------------------------------------------------


def _copied_tree(source: Path, destination: Path) -> Path:
    for path in sorted(source.rglob("*")):
        if any(part in {".codeclone", ".cache"} for part in path.parts):
            continue
        if path.is_file() and path.suffix in {".py", ".toml", ".txt"}:
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
    return destination


def test_the_e1_families_of_an_mcp_published_run_agree_with_the_oracle(
    served_run_store_projection: ServedRunStoreProjection,
    run_store_cli: RunStoreCorpusRunner,
    tmp_path: Path,
) -> None:
    """The run the MCP surface published, read back family by family, against
    the oracle over a CLI-rendered document of the same tree (a copy, so the
    session fixture's tree is never written into).

    Measured 2026-09-25 on the serving corpus: 8 overloaded rows and the
    dead-code summary record agree; the nine families the corpus leaves
    empty agree empty on both sides.  The population witness is the one
    thing that differs, and the difference is stated exactly (determinism
    audit DET-03, 2026-09-25): the store pronounces ``coverage_join``
    ``not_executed`` for a family the run never requested, where the
    rendered document writes ``disabled`` — and the oracle, which reads
    ``meta.computed_metric_families`` alone, sees neither that entry nor the
    ``near_miss``/``renamed_structure`` states the document does carry.
    Asserted here as the witness that this comparison reached an MCP run
    and not a look-alike; the vocabulary divergence itself is an E2/E3
    boundary, recorded, never repaired from this side.
    """
    with RunStore(served_run_store_projection.store_path) as store:
        published = store.read_run(served_run_store_projection.store_run_id)
        overloaded = store.read_family(
            served_run_store_projection.store_run_id, FAMILY_OVERLOADED_MODULE
        )
        summary = store.read_family(
            served_run_store_projection.store_run_id, FAMILY_DEAD_CODE_SUMMARY
        )
    assert len(overloaded) == 8, "every module of the serving corpus is a row"
    assert len(summary) == 1
    root = _copied_tree(served_run_store_projection.root, tmp_path / "tree")
    report_path = tmp_path / "report.json"
    run_store_cli(root, "--json", str(report_path), store=None)
    oracle = canonical_model_from_legacy_document(
        json.loads(report_path.read_text("utf-8"))
    )
    produced = published.facts.analysis
    expected = oracle.facts.analysis
    for family in (
        "suppressed_clone_groups",
        "structural_groups",
        "dead_symbol_groups",
        "unreachable_statement_groups",
        "complexity_hotspots",
        "coupling_hotspots",
        "cohesion_hotspots",
        "overloaded_modules",
        "coverage_units",
    ):
        assert getattr(produced, family) == getattr(expected, family), family
    assert produced.overloaded_modules == frozenset(overloaded)
    assert produced.coverage_join is None
    assert expected.coverage_join is None
    assert produced.dead_code_summary == summary[0] == expected.dead_code_summary
    assert produced.analysis_population is not None
    assert expected.analysis_population is not None
    store_states = dict(produced.analysis_population.producer_states)
    oracle_states = dict(expected.analysis_population.producer_states)
    # DET-03, stated: an unrequested family is ``not_executed`` in the store.
    assert store_states["coverage_join"] == "not_executed"
    assert "coverage_join" not in oracle_states
    # The oracle's own limit, stated: it reads the declared families only.
    assert {"near_miss", "renamed_structure"} <= set(store_states)
    assert {"near_miss", "renamed_structure"}.isdisjoint(oracle_states)
