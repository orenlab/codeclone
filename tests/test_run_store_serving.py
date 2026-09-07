# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The served projection and its door: the store's answer, or a typed reason.

``codeclone.canonical.serving`` is the one owner of the producer's serving
dialect over the store's families; ``codeclone.api.run_store_serving`` is
the R3 door through which the MCP surface asks for it.  The pins here drive
both by fixture where the serving corpus cannot — the nullary target
variant of an import, a repeated relationship record, a module-less
source, the absent-able columns — and pin the door's every reason, so that
a fallback the surface counts is a fallback that was reached.

The two producer orders the projection restates (the module docstring of
``codeclone.canonical.serving`` says why they are restated at all) are held
equal to the producers' own functions here, order-sensitively, over inputs
that include ties.
"""

from __future__ import annotations

import json
import random
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.analysis._module_walk import _relationship_record_sort_key
from codeclone.api.run_store_serving import (
    MEMORY_BY_DESIGN_REASONS,
    SERVING_REASON_INCOMPATIBLE_GENERATION,
    SERVING_REASON_NOT_PUBLISHED,
    SERVING_REASON_RUN_NOT_PUBLISHED,
    SERVING_REASON_SERVED,
    SERVING_REASON_STORE_ABSENT,
    SERVING_REASON_STORE_DISABLED,
    SERVING_REASONS,
    SERVING_SOURCE_MEMORY,
    SERVING_SOURCE_RUN_STORE,
    RunStoreServingOutcome,
    read_run_store_slices,
)
from codeclone.canonical import (
    STORE_GENERATION_NEXT_STEP,
    CanonicalModel,
    IdentityIndex,
    RunStore,
    module_dep_order_key,
    read_served_run_slices,
    relationship_record_order_key,
)
from codeclone.core._types import _module_dep_sort_key
from codeclone.models import (
    RUN_SNAPSHOT_LINK_LINKED,
    RUN_SNAPSHOT_LINK_UNPUBLISHED,
    RUN_SNAPSHOT_PUBLICATION_DISABLED,
    RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
    ModuleDep,
    RelationshipKind,
    RelationshipOriginLane,
    RelationshipRecord,
    RelationshipResolutionStatus,
    RunSnapshotLink,
)
from tests.test_canonical_roundtrip import fixture_model

_NS = "serving-lineage"
_TARGET = "worktree"
_GENERATION_1 = Path(__file__).parent / "fixtures" / "run_store_generation_1"
_SERVING_ROOT = Path("/srv/checkout")


def _publish(store: RunStore, model: CanonicalModel) -> str:
    return store.write_full_run(
        model, namespace=_NS, target=_TARGET, expected_generation=0
    ).run_id


@pytest.fixture
def published(tmp_path: Path) -> tuple[Path, str]:
    """The distinguishing fixture, published once into a fresh store."""
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        run_id = _publish(store, fixture_model())
    return path, run_id


# -- the projection ---------------------------------------------------------


def test_served_units_glue_the_producers_head(published: tuple[Path, str]) -> None:
    """A mapped file is headed by its module, any other file by its own
    path — the producer's rule verbatim, total over the store's rows."""
    path, run_id = published
    with RunStore(path, create=False) as store:
        slices = read_served_run_slices(store, run_id, root=Path("/root"))
    units = [
        (u.qualname, u.path, u.start_line, u.end_line) for u in slices.unit_inventory
    ]
    assert units == [
        ("pkg.a:A.run", "pkg/a.py", 10, 24),
        ("pkg.a:A.run", "pkg/a.py", 40, 40),
        ("pkg/a.py.d:run", "pkg/a.py.d", 1, 1),
    ]


def test_served_imports_spell_every_target_variant(published: tuple[Path, str]) -> None:
    """MODULE -> its name, opaque head -> its text, the nullary variant ->
    the empty string the producer writes; a FILE source -> its path; every
    payload column back verbatim, absent ``requested_module`` included."""
    path, run_id = published
    with RunStore(path, create=False) as store:
        slices = read_served_run_slices(store, run_id, root=Path("/root"))
    deps = slices.module_imports
    assert [(d.source, d.target, d.import_type, d.line) for d in deps] == [
        ("pkg.a", "os.path", "from_import", 6),
        ("pkg.a", "pkg.sibling", "from_import", 7),
        ("pkg.a", "tools.helper", "import", 4),
        ("tools/b.py", "", "import", 0),
    ]
    by_target = {d.target: d for d in deps}
    external = by_target["os.path"]
    assert external.resolution == "external"
    assert external.is_lazy and external.binding == "type_checking"
    assert external.requested_names == ("join", "split")
    relative = by_target["pkg.sibling"]
    assert relative.level == 1 and relative.requested_module is None
    assert relative.inventory_expansion
    unresolved = by_target[""]
    assert unresolved.resolution == "unresolved_dynamic"
    assert unresolved.mechanism == "dynamic" and unresolved.candidate_targets == ()
    assert list(deps) == sorted(deps, key=_module_dep_sort_key)


@pytest.fixture
def served_relationships(
    published: tuple[Path, str],
) -> dict[str, tuple[RelationshipRecord, ...]]:
    """The served relationship slice of the distinguishing fixture, by source,
    read through the production projection under ``_SERVING_ROOT``."""
    path, run_id = published
    with RunStore(path, create=False) as store:
        slices = read_served_run_slices(store, run_id, root=_SERVING_ROOT)
    by_source = {
        facts.source_qualname: facts.relationships
        for facts in slices.relationship_facts
    }
    assert list(by_source) == ["pkg.a:A.run", "pkg/a.py.d:run", "tools/b.py:helper"]
    return by_source


def test_served_relationships_expand_multiplicity(
    served_relationships: dict[str, tuple[RelationshipRecord, ...]],
) -> None:
    """A row counted three times comes back as three identical records; an
    opaque target rides verbatim; the path is the source file under the
    serving root."""
    run = served_relationships["pkg.a:A.run"]
    assert [r.target_qualname for r in run] == [
        "pkg.a:A.stop",
        "typing:cast",
        "typing:cast",
        "typing:cast",
    ]
    assert run[1] == run[2] == run[3]
    assert run[1].resolution_rule == "imported_symbol" and run[1].expression == "cast"
    assert {r.resolution_status for r in run} == {"resolved"}
    assert {r.path for r in run} == {str(_SERVING_ROOT / "pkg/a.py")}


def test_served_relationships_derive_status_from_the_target_variant(
    served_relationships: dict[str, tuple[RelationshipRecord, ...]],
) -> None:
    """The status is the target variant's: the nullary one is ``None`` and
    unresolved, a SYMBOL one is resolved; the absent-able columns come back
    absent, not spelled."""
    helper = served_relationships["tools/b.py:helper"]
    assert [
        (r.relation_kind, r.resolution_status, r.target_qualname) for r in helper
    ] == [
        ("call", "unresolved", None),
        ("reference", "resolved", "pkg.a:A.run"),
    ]
    assert helper[0].expression == "dynamic()"
    assert helper[0].resolution_rule == "unresolved_dynamic"
    assert helper[1].expression is None and helper[1].resolution_rule is None
    assert {r.origin_lane for r in helper} == {"test"}


def test_served_relationships_glue_symbol_targets_in_the_producers_order(
    served_relationships: dict[str, tuple[RelationshipRecord, ...]],
) -> None:
    """A SYMBOL target is glued under its file's head, and every source's
    records come back in the producer's own order."""
    render = served_relationships["pkg/a.py.d:run"]
    assert [r.target_qualname for r in render] == ["tools/b.py:Widget.render"] * 2
    for records in served_relationships.values():
        assert list(records) == sorted(records, key=_relationship_record_sort_key)


def _record(
    kind: RelationshipKind,
    lane: RelationshipOriginLane,
    target: str | None,
    line: int,
    expression: str | None,
    rule: str | None,
) -> RelationshipRecord:
    status: RelationshipResolutionStatus = "resolved" if target else "unresolved"
    return RelationshipRecord(
        relation_kind=kind,
        resolution_status=status,
        origin_lane=lane,
        source_qualname="m:f",
        target_qualname=target,
        path="/r/m.py",
        line=line,
        expression=expression,
        resolution_rule=rule,
    )


def test_the_served_orders_are_the_producers_orders() -> None:
    """The two restated sort keys equal the producers' own, including on
    ties — a component dropped or reordered on either side reddens here."""
    deps = [
        ModuleDep(source="b", target="x", import_type="import", line=3),
        ModuleDep(source="a", target="y", import_type="from_import", line=9),
        ModuleDep(source="a", target="y", import_type="import", line=9),
        ModuleDep(source="a", target="y", import_type="import", line=2),
        ModuleDep(source="a", target="", import_type="import", line=2),
    ]
    for dep in deps:
        assert module_dep_order_key(dep) == _module_dep_sort_key(dep)
    kinds: list[RelationshipKind] = ["reference", "call"]
    lanes: list[RelationshipOriginLane] = ["test", "production"]
    payloads: list[tuple[str | None, str | None]] = [
        ("g()", "same_module_function"),
        (None, None),
        ("g", "imported_symbol"),
    ]
    records = [
        _record(kind, lane, target, line, expression, rule)
        for kind in kinds
        for lane in lanes
        for target in ("m:g", None, "m:a")
        for line in (7, 2)
        for expression, rule in payloads
    ]
    for record in records:
        assert relationship_record_order_key(record) == _relationship_record_sort_key(
            record
        )
    shuffled = list(records)
    random.Random(7).shuffle(shuffled)
    assert sorted(shuffled, key=relationship_record_order_key) == sorted(
        shuffled, key=_relationship_record_sort_key
    )


# -- the door ---------------------------------------------------------------


def _enable(monkeypatch: pytest.MonkeyPatch, store: Path) -> None:
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(store))


def _disable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODECLONE_RUN_STORE_ENABLED", raising=False)
    monkeypatch.delenv("CODECLONE_RUN_STORE_FORCE", raising=False)
    monkeypatch.delenv("CODECLONE_RUN_STORE_PATH", raising=False)


def _linked(run_id: str) -> RunSnapshotLink:
    return RunSnapshotLink(
        state=RUN_SNAPSHOT_LINK_LINKED,
        outcome=RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
        store_run_id=run_id,
        analysis_scope_digest="0" * 64,
        report_run_identity="1" * 64,
    )


def test_the_door_serves_a_published_run_out_of_the_store(
    published: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, run_id = published
    _enable(monkeypatch, path)
    slices, outcome = read_run_store_slices(root=tmp_path, link=_linked(run_id))
    assert outcome == RunStoreServingOutcome(
        source=SERVING_SOURCE_RUN_STORE,
        reason=SERVING_REASON_SERVED,
        store_run_id=run_id,
    )
    assert slices is not None
    with RunStore(path, create=False) as store:
        assert slices == read_served_run_slices(store, run_id, root=tmp_path)
    assert outcome.as_payload() == {
        "source": "run_store",
        "reason": "served",
        "store_run_id": run_id,
    }


def test_the_door_answers_memory_by_design_when_nothing_was_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch, tmp_path / "runs.sqlite3")
    slices, outcome = read_run_store_slices(root=tmp_path, link=None)
    assert slices is None
    assert (outcome.source, outcome.reason) == (
        SERVING_SOURCE_MEMORY,
        SERVING_REASON_NOT_PUBLISHED,
    )
    unpublished = RunSnapshotLink(
        state=RUN_SNAPSHOT_LINK_UNPUBLISHED,
        outcome=RUN_SNAPSHOT_PUBLICATION_DISABLED,
        report_run_identity="1" * 64,
    )
    _slices, outcome = read_run_store_slices(root=tmp_path, link=unpublished)
    assert outcome.reason == SERVING_REASON_NOT_PUBLISHED
    assert outcome.detail == RUN_SNAPSHOT_PUBLICATION_DISABLED
    assert SERVING_REASON_NOT_PUBLISHED in MEMORY_BY_DESIGN_REASONS
    assert not (tmp_path / "runs.sqlite3").exists()


def test_the_door_honours_the_kill_switch(
    published: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A store the rollout no longer names is never read, even when the
    execution published into it."""
    _path, run_id = published
    _disable(monkeypatch)
    slices, outcome = read_run_store_slices(root=tmp_path, link=_linked(run_id))
    assert slices is None
    assert (outcome.source, outcome.reason) == (
        SERVING_SOURCE_MEMORY,
        SERVING_REASON_STORE_DISABLED,
    )
    assert outcome.store_run_id == run_id
    assert SERVING_REASON_STORE_DISABLED in MEMORY_BY_DESIGN_REASONS


def test_the_door_never_creates_the_store_it_could_not_find(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    absent = tmp_path / "nowhere" / "runs.sqlite3"
    _enable(monkeypatch, absent)
    slices, outcome = read_run_store_slices(root=tmp_path, link=_linked("0" * 64))
    assert slices is None
    assert outcome.reason == SERVING_REASON_STORE_ABSENT
    assert outcome.reason not in MEMORY_BY_DESIGN_REASONS, (
        "an absent store is a fallback"
    )
    assert not absent.exists() and not absent.parent.exists()


def test_the_door_reports_a_run_the_store_does_not_hold(
    published: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _run_id = published
    _enable(monkeypatch, path)
    slices, outcome = read_run_store_slices(root=tmp_path, link=_linked("f" * 64))
    assert slices is None
    assert outcome.reason == SERVING_REASON_RUN_NOT_PUBLISHED
    assert "run_not_published" in outcome.detail


def test_the_door_falls_back_typed_on_a_generation_one_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The REAL generation-1 artifact (produced by the revision-1 build at
    f117a8ad, see its provenance file) is refused at open and the surface
    falls back to memory with the refusal's own words, migration path
    included — never a silent reinterpretation."""
    provenance = json.loads((_GENERATION_1 / "provenance.json").read_text("utf-8"))
    store = tmp_path / "generation-1.sqlite3"
    shutil.copy(_GENERATION_1 / "runs.sqlite3", store)
    _enable(monkeypatch, store)
    slices, outcome = read_run_store_slices(
        root=tmp_path, link=_linked(str(provenance["run_id"]))
    )
    assert slices is None
    assert (outcome.source, outcome.reason) == (
        SERVING_SOURCE_MEMORY,
        SERVING_REASON_INCOMPATIBLE_GENERATION,
    )
    assert "canonical_model stored '1' declared '2'" in outcome.detail
    assert "canonical_wire stored '0' declared '1'" in outcome.detail
    assert STORE_GENERATION_NEXT_STEP in outcome.detail


def test_the_outcome_vocabulary_is_closed_and_the_source_follows_the_reason() -> None:
    assert SERVING_REASON_SERVED in SERVING_REASONS
    with pytest.raises(ValueError, match="store-backed answer is served"):
        RunStoreServingOutcome(
            source=SERVING_SOURCE_RUN_STORE, reason=SERVING_REASON_STORE_ABSENT
        )
    with pytest.raises(ValueError, match="store-backed answer is served"):
        RunStoreServingOutcome(
            source=SERVING_SOURCE_MEMORY, reason=SERVING_REASON_SERVED
        )
    with pytest.raises(ValueError, match="unknown serving reason"):
        RunStoreServingOutcome(source=SERVING_SOURCE_MEMORY, reason="because")
    with pytest.raises(ValueError, match="unknown serving source"):
        RunStoreServingOutcome(source="cache", reason=SERVING_REASON_STORE_ABSENT)
    memory = RunStoreServingOutcome(
        source=SERVING_SOURCE_MEMORY, reason=SERVING_REASON_NOT_PUBLISHED
    )
    assert memory.as_payload() == {"source": "memory", "reason": "not_published"}
    assert replace(memory, detail="why").as_payload()["detail"] == "why"


# -- the producer edge: the two tagged targets, every variant reached -----


def _index() -> IdentityIndex:
    from codeclone.canonical.semantic_grammar import build_identity_index

    return build_identity_index(
        [("pkg/a.py", "pkg.a"), ("pkg/engine.py", "pkg.engine")],
        analyzed_paths=frozenset({"pkg/a.py", "pkg/engine.py", "tools/b.py"}),
    )


def test_the_import_target_is_decided_by_the_producer_and_checked_by_the_registry() -> (
    None
):
    """Every variant of the tagged import target has an input that reaches
    it, and both refusals fire: an ``analyzed`` import the registry does not
    carry, and a contradiction between the classification and the target."""
    from codeclone.canonical import (
        FileId,
        ModuleId,
        OpaqueDottedHead,
        SemanticGrammarError,
        UnresolvedTarget,
    )
    from codeclone.core.canonical_snapshot import _import_target

    index = _index()

    def dep(resolution: str, target: str, mechanism: str = "static") -> ModuleDep:
        return ModuleDep(
            source="pkg.a",
            target=target,
            import_type="import",
            line=1,
            resolution=resolution,  # type: ignore[arg-type]
            mechanism=mechanism,  # type: ignore[arg-type]
        )

    assert _import_target(dep("analyzed", "pkg.engine"), index) == ModuleId(
        "pkg.engine"
    )
    assert _import_target(dep("analyzed", "tools/b.py"), index) == FileId("tools/b.py")
    assert _import_target(dep("external", "os.path"), index) == OpaqueDottedHead(
        "os.path"
    )
    assert _import_target(dep("known_internal_not_analyzed", "pkg.x"), index) == (
        OpaqueDottedHead("pkg.x")
    )
    assert _import_target(dep("unresolved_dynamic", "", "dynamic"), index) == (
        UnresolvedTarget()
    )
    with pytest.raises(SemanticGrammarError, match="neither a registry module"):
        _import_target(dep("analyzed", "os.path"), index)
    with pytest.raises(SemanticGrammarError, match="names a target"):
        _import_target(dep("unresolved_relative", "pkg.x"), index)
    with pytest.raises(SemanticGrammarError, match="names no target"):
        _import_target(dep("external", ""), index)


def test_the_relationship_target_resolves_through_the_registry_or_rides_opaque() -> (
    None
):
    from codeclone.canonical import (
        FileId,
        OpaqueEntity,
        SemanticGrammarError,
        SymbolId,
        UnresolvedTarget,
    )
    from codeclone.core.canonical_snapshot import _relationship_target

    index = _index()
    assert _relationship_target("pkg.engine:Engine.run", index) == SymbolId(
        FileId("pkg/engine.py"), "Engine.run"
    )
    assert _relationship_target("tools/b.py:helper", index) == SymbolId(
        FileId("tools/b.py"), "helper"
    )
    assert _relationship_target("typing:cast", index) == OpaqueEntity("typing", "cast")
    assert _relationship_target(None, index) == UnresolvedTarget()
    for malformed in ("nocolon", ":local", "head:", "a:b:c"):
        with pytest.raises(SemanticGrammarError, match="not a head:local"):
            _relationship_target(malformed, index)
