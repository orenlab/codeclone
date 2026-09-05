# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Serving one fact family out of a run must not read the whole run.

``RunStore.read_run`` reconstructs a complete :class:`CanonicalModel` to
answer any question about a published run.  Measured on the serving corpus,
isolated processes, two runs each: 1.999 / 1.959 s at +354.8 MB peak RSS to
deliver the same 22 609 rows a per-family read delivers in 0.107 / 0.109 s
at +16.8 MB, and 245.72 MB of materialized model to serve a 31.76 MB slice --
more than the whole write.  :meth:`RunStore.read_family` is the bounded
primitive that closes that gap, and the three properties below are its
contract rather than its implementation notes.

Each property is pinned twice where it can be: once on the OBSERVABLE answer
(a wrong run's rows, a store that came into existence) and once on the
MECHANISM (no whole model constructed, no store constructed).  An answer-only
pin cannot tell a bounded read from a whole-model read that happens to return
the same rows -- which is precisely the regression that costs 21x the memory
and stays green.

``does not create the store``
    Inherited law, not a new one: a read of an absent store refuses typed
    (``run_store_absent``) and leaves the filesystem byte-identical, because
    ``RunStore(path, create=False)`` is refused before any ``mkdir`` or
    ``connect``.  The bounded read is reached THROUGH that constructor and
    constructs nothing of its own -- pinned structurally with the classifier
    that owns the question (``tests/test_run_store_construction_intent``),
    not with a second one written here.

``does not read an implicit latest``
    A head is a mutable pointer; a ``run_id`` is a content address.  A
    serving path that falls back to the head silently answers about a
    different run than the caller meant, and every later question inherits
    that substitution.  Pinned with two runs published in one store, the head
    standing on the SECOND: a read of the first must answer the first.

``does not materialize the whole model``
    The point of the change.  Pinned by counting what the read builds -- zero
    ``CanonicalModel`` and zero ``AnalysisFacts`` objects -- and by counting
    the stored members it decodes, which must be the family's row count and
    not the run's.  A count is not a ratio: it does not need a threshold
    nobody can defend, and it dies the moment the read falls back.
"""

from __future__ import annotations

import inspect
import sqlite3
import textwrap
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Final, cast

import pytest

from codeclone.canonical import store as store_module
from codeclone.canonical.errors import StoreIntegrityError, UnknownRunError
from codeclone.canonical.model import (
    AnalysisFacts,
    CanonicalFacts,
    CanonicalModel,
    UnitSpanRow,
)
from codeclone.canonical.store import (
    FAMILY_COUPLED_SET,
    FAMILY_UNIT_SPAN,
    RunStore,
    StoredFamily,
)
from tests.test_canonical_roundtrip import fixture_model
from tests.test_run_store_construction_intent import run_store_constructions

_NS: Final = "bounded-read"
_TARGET: Final = "worktree"

#: The module the construction classifier must believe it is reading, so that
#: the defining-module binding of ``RunStore`` applies exactly as it does over
#: the real tree.
_STORE_PATH: Final = "codeclone/canonical/store.py"


def _read_any_family(
    store: RunStore, run_id: str, entry: store_module._FamilyEntry
) -> tuple[object, ...]:
    """The bounded read, driven over the registry rather than over a token.

    Enumerating the registry is erased by construction -- its members have
    twenty-four different row types, so the tuple that holds them can only be
    typed by the face they share.  The contract itself is NOT erased: a caller
    that names one family passes its token and gets that family's row type
    back, which is what every other call in this module does.  The cast is the
    honest spelling of the enumeration, kept in one place so no test grows a
    private opinion about it.
    """

    return store.read_family(run_id, cast("StoredFamily[object]", entry))


def _publish(store: RunStore, model: CanonicalModel, *, generation: int = 0) -> str:
    return store.write_full_run(
        model, namespace=_NS, target=_TARGET, expected_generation=generation
    ).run_id


def _neighbour_model() -> CanonicalModel:
    """A second state: every object of the fixture, plus one coupled set.

    The families the two runs disagree about are exactly one, which is what
    makes it usable as the head/run distinguisher below -- a neighbour that
    differed everywhere could not tell "answered the wrong run" from
    "answered nothing".
    """
    model = fixture_model()
    return replace(
        model, coupled_sets=frozenset({*model.coupled_sets, frozenset({"OnlySecond"})})
    )


# ---------------------------------------------------------------------------
# The opposite boundary: an honest bounded read must be answered
# ---------------------------------------------------------------------------


def test_a_bounded_read_answers_the_family_it_was_asked_for(tmp_path: Path) -> None:
    """The positive control for every refusal pinned below.

    A surface that refuses, empties, or drops the legitimate read would make
    every "did not do the wrong thing" pin here vacuously green.  This one
    fails on any of those, so the others measure a read that happens.
    """

    model = fixture_model()
    with RunStore(tmp_path / "runs.sqlite") as store:
        run_id = _publish(store, model)
        rows = store.read_family(run_id, FAMILY_UNIT_SPAN)
    assert rows, "the bounded read returned nothing for a non-empty family"
    assert frozenset(rows) == model.facts.analysis.unit_spans
    assert all(isinstance(row, FAMILY_UNIT_SPAN.row_type) for row in rows)


def test_every_declared_family_is_readable_and_equals_the_whole_model_path(
    tmp_path: Path,
) -> None:
    """Equivalence, over the whole registry rather than one family.

    The accessor table below is hand-written, so it is held equal to the
    registry in BOTH directions: a family declared and never compared would
    leave the equivalence claim smaller than it sounds, and an accessor for a
    family that no longer exists would keep a dead comparison green.
    """

    accessors = _MODEL_ACCESSORS
    declared = {entry.family for entry in store_module._FAMILIES}
    assert set(accessors) == declared, (
        "the equivalence table and the family registry disagree: "
        f"table-only={sorted(set(accessors) - declared)} "
        f"registry-only={sorted(declared - set(accessors))}"
    )

    with RunStore(tmp_path / "runs.sqlite") as store:
        run_id = _publish(store, fixture_model())
        whole = store.read_run(run_id)
        for entry in store_module._FAMILIES:
            bounded = _read_any_family(store, run_id, entry)
            expected = accessors[entry.family](whole)
            assert frozenset(bounded) == expected, entry.family
            assert len(bounded) == len(expected), (
                f"{entry.family}: the bounded read returned a duplicate row"
            )
            assert bounded, f"{entry.family}: empty in the distinguishing fixture"


def _one_span_model(span: UnitSpanRow) -> CanonicalModel:
    """The fixture reduced to ONE unit span, and otherwise unchanged.

    Published before the full fixture it puts that span at a low rowid, which
    is how a family whose storage order and whose content-address order
    disagree is built at all.
    """

    model = fixture_model()
    return replace(
        model,
        facts=CanonicalFacts(
            analysis=replace(model.facts.analysis, unit_spans=frozenset({span}))
        ),
    )


def _storage_order(store: RunStore, run_id: str, family: str) -> list[str]:
    """One run's members of one family, in the order the STORE laid them
    down -- the order a bounded read must not inherit."""

    return [
        str(row[0])
        for row in store._connection.execute(
            "SELECT o.object_id FROM run_members m "
            "JOIN objects o ON o.object_pk = m.object_pk "
            "JOIN runs r ON r.run_pk = m.run_pk "
            "WHERE r.run_id = ? AND o.family = ? ORDER BY o.object_pk",
            (run_id, family),
        )
    ]


def test_the_bounded_read_order_is_content_derived_not_insertion_derived(
    tmp_path: Path,
) -> None:
    """Rows come back in the store's total order over immutable objects.

    One state, two stores, and in the second a prior run has already laid one
    of its objects down at a low rowid.  A read that returned rows in storage
    order would answer two different sequences for ONE run -- which is what a
    caller diffing two workspaces would see as a change that never happened.

    **Why the distinguishing case is SEARCHED for and then asserted.**
    Measured first, and it is the whole reason this test is shaped like this:
    over every store the obvious constructions build -- one model, the
    reverse-insertion twin, a superset published first -- storage order and
    content-address order agree in all 24 families, so an order pin driven by
    any of them stays green for a rowid-ordered read.  The case needs a prior
    run holding a STRICT subset that is not content-address-minimal, and WHICH
    span that is depends on the namespace the addresses are computed in, not
    on anything visible in the model.  So every candidate is tried, the ones
    that shift the order are counted, and a population that offers none fails
    here instead of passing blind.
    """

    candidates = sorted(
        fixture_model().facts.analysis.unit_spans,
        key=lambda row: (row.symbol.file.path, row.symbol.qualname, row.start_line),
    )
    shifting: list[int] = []
    with RunStore(tmp_path / "plain.sqlite") as plain:
        run_id = _publish(plain, fixture_model())
        plain_storage = _storage_order(plain, run_id, "unit_span")
        assert plain_storage == sorted(plain_storage), (
            "a store holding only this run already lays it down out of "
            "content-address order; the construction below is not the probe"
        )
        for index, span in enumerate(candidates):
            with RunStore(tmp_path / f"shifted-{index}.sqlite") as shifted:
                _publish(shifted, _one_span_model(span))
                again = _publish(shifted, fixture_model(), generation=1)
                assert run_id == again, "the two stores do not hold the same run"
                storage = _storage_order(shifted, again, "unit_span")
                if storage == plain_storage:
                    continue
                shifting.append(index)
                assert storage != sorted(storage)
                for entry in store_module._FAMILIES:
                    assert _read_any_family(plain, run_id, entry) == _read_any_family(
                        shifted, again, entry
                    ), entry.family

    assert shifting, (
        f"none of the {len(candidates)} candidate spans shifted the storage "
        "order, so this test cannot tell a content-ordered read from a "
        "rowid-ordered one"
    )

    # The reverse-insertion twin is kept as the second, weaker construction:
    # it proves the read is insensitive to the order the MODEL was built in.
    with (
        RunStore(tmp_path / "forward.sqlite") as forward,
        RunStore(tmp_path / "reverse.sqlite") as reverse,
    ):
        first = _publish(forward, fixture_model())
        second = _publish(reverse, fixture_model(reverse_insertion=True))
        assert first == second, "the two loads are not the same run"
        for entry in store_module._FAMILIES:
            assert _read_any_family(forward, first, entry) == _read_any_family(
                reverse, second, entry
            ), entry.family


# ---------------------------------------------------------------------------
# Property 1 -- does not create the store
# ---------------------------------------------------------------------------


def test_a_bounded_read_of_an_absent_store_creates_nothing(tmp_path: Path) -> None:
    """The reader flow refuses before the store can be brought into being.

    The bounded read inherits this rather than restating it: it is reached
    through ``RunStore(path, create=False)``, which refuses before ``mkdir``
    and before ``connect``.  The pin is here as well as on ``read_run``
    because inheritance that nothing exercises is a claim, not a property --
    remove the guard and this reds with the new surface named in the failure.
    """

    path = tmp_path / "no-store-here" / "runs.sqlite"
    with (
        pytest.raises(UnknownRunError) as refusal,
        RunStore(path, create=False) as store,
    ):
        store.read_family("0" * 64, FAMILY_UNIT_SPAN)
    assert refusal.value.reason == "run_store_absent"
    assert refusal.value.next_step
    assert not path.exists(), "the bounded read created the store it refused to read"
    assert not path.parent.exists(), "the bounded read created the store's directory"


def test_the_bounded_read_constructs_no_run_store(tmp_path: Path) -> None:
    """The mechanism half: nothing on this path can construct a store.

    The filesystem pin above is satisfied by a refusal that happens EARLY; it
    would stay green for a read that constructs a store on some later branch
    -- an unknown run, a corrupt row -- because that branch never runs in it.
    So the source of the read is classified by the owner of the question,
    ``run_store_constructions``, and must contain no construction at all.

    The classifier is driven on the read's own source rather than on the
    module, so this stays a statement about THIS surface: the tree-wide
    inventory is that ratchet's own subject.
    """

    source = textwrap.dedent(inspect.getsource(RunStore.read_family))
    found = run_store_constructions(source, path=_STORE_PATH)
    assert found == (), (
        "the bounded read constructs a run store: "
        f"{[(site.qualname, site.intent) for site in found]}"
    )
    # The classifier can see a construction in this shape: without a positive
    # control, an empty answer proves only that the probe ran.
    control = run_store_constructions(
        source + "\n    RunStore(self._path)\n", path=_STORE_PATH
    )
    assert len(control) == 1 and control[0].intent == "implicit-create"


# ---------------------------------------------------------------------------
# Property 2 -- does not read an implicit latest
# ---------------------------------------------------------------------------


def test_a_bounded_read_answers_the_run_it_was_given_not_the_head(
    tmp_path: Path,
) -> None:
    """Two runs, the head on the second, a read of the first.

    A read that resolved -- or fell back to -- the head would answer the
    second run's rows here while every digest, every count and every other
    family still matched, because the two states differ in exactly one
    family.  That is the shape of the defect: not a crash, a substitution.
    """

    first_model = fixture_model()
    second_model = _neighbour_model()
    with RunStore(tmp_path / "runs.sqlite") as store:
        first = _publish(store, first_model)
        second = _publish(store, second_model, generation=1)
        assert first != second
        head = store.head(namespace=_NS, target=_TARGET)
        assert head is not None and head.run_id == second, "the head is not the second"

        assert frozenset(store.read_family(first, FAMILY_COUPLED_SET)) == (
            first_model.coupled_sets
        )
        # ... and the neighbour is genuinely distinguishable, so the pin above
        # is not comparing a state to itself.
        assert frozenset(store.read_family(second, FAMILY_COUPLED_SET)) == (
            second_model.coupled_sets
        )
        assert first_model.coupled_sets != second_model.coupled_sets


def test_a_bounded_read_never_reads_the_head_table(tmp_path: Path) -> None:
    """The mechanism half: no statement of the read touches ``heads``.

    The substitution pin above catches a read that answers the head's run.
    It cannot catch a read that CONSULTS the head and then, on this corpus,
    happens to agree -- an implicit-latest path that is wrong only when two
    runs are live. Statement tracing sees the consultation itself.
    """

    with RunStore(tmp_path / "runs.sqlite") as store:
        run_id = _publish(store, fixture_model())
        statements: list[str] = []
        store._connection.set_trace_callback(statements.append)
        try:
            store.read_family(run_id, FAMILY_UNIT_SPAN)
        finally:
            store._connection.set_trace_callback(None)

    assert statements, "no statement was traced; the probe saw nothing"
    offending = [text for text in statements if "heads" in text.lower()]
    assert offending == [], f"the bounded read consulted the head: {offending}"
    # Positive control: the tracer does see a head lookup when one happens.
    with RunStore(tmp_path / "runs.sqlite", create=False) as store:
        control: list[str] = []
        store._connection.set_trace_callback(control.append)
        try:
            store.head(namespace=_NS, target=_TARGET)
        finally:
            store._connection.set_trace_callback(None)
    assert any("heads" in text.lower() for text in control), (
        "the tracer cannot see a head lookup, so its silence proves nothing"
    )


def test_a_bounded_read_of_an_unpublished_run_is_a_typed_refusal(
    tmp_path: Path,
) -> None:
    """An unknown run refuses; it is never softened into an empty family.

    "This run has no rows of that family" and "there is no such run" are
    different answers, and a serving path that conflates them reports an
    absent run as a measured-empty one.
    """

    with RunStore(tmp_path / "runs.sqlite") as store:
        _publish(store, fixture_model())
        with pytest.raises(UnknownRunError) as refusal:
            store.read_family("0" * 64, FAMILY_UNIT_SPAN)
    assert refusal.value.reason == "run_not_published"
    assert refusal.value.next_step


# ---------------------------------------------------------------------------
# Property 3 -- does not materialize the whole model
# ---------------------------------------------------------------------------


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, int]]:
    """Count what the store CONSTRUCTS and what it DECODES.

    Both are needed and neither is enough.  Constructing no model does not by
    itself mean the read was bounded -- a read could decode every member of
    the run and discard all but one family, paying the whole I/O and decode
    cost.  Decoding few rows does not by itself mean no model was built.
    """

    tally = {"model": 0, "facts": 0, "decoded": 0}
    real_model = CanonicalModel
    real_facts = AnalysisFacts
    real_decode = store_module._decode_member_object

    def counting_model(*args: object, **kwargs: object) -> CanonicalModel:
        tally["model"] += 1
        return real_model(*args, **kwargs)  # type: ignore[arg-type]

    def counting_facts(*args: object, **kwargs: object) -> AnalysisFacts:
        tally["facts"] += 1
        return real_facts(*args, **kwargs)  # type: ignore[arg-type]

    def counting_decode(*args: object, **kwargs: object) -> None:
        tally["decoded"] += 1
        real_decode(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(store_module, "CanonicalModel", counting_model)
    monkeypatch.setattr(store_module, "AnalysisFacts", counting_facts)
    monkeypatch.setattr(store_module, "_decode_member_object", counting_decode)
    yield tally


def test_a_bounded_read_builds_no_model_and_decodes_only_its_family(
    tmp_path: Path, counted: dict[str, int]
) -> None:
    """The load-bearing pin: the whole-model materialization does not happen.

    ``read_run`` is measured beside it in the same process and the same
    counters, so this is a contrast and not an absolute -- the counters are
    shown able to move, which is what makes the bounded read's zeros mean
    something (a probe that could not count would report zero for both).
    """

    model = fixture_model()
    family_rows = len(model.facts.analysis.unit_spans)
    with RunStore(tmp_path / "runs.sqlite") as store:
        run_id = _publish(store, model)
        counted.update(model=0, facts=0, decoded=0)
        rows = store.read_family(run_id, FAMILY_UNIT_SPAN)
        bounded = dict(counted)

        counted.update(model=0, facts=0, decoded=0)
        store.read_run(run_id)
        whole = dict(counted)

    assert len(rows) == family_rows
    assert bounded["model"] == 0, "the bounded read materialized a canonical model"
    assert bounded["facts"] == 0, "the bounded read materialized a fact house"
    assert bounded["decoded"] == family_rows, (
        "the bounded read decoded members outside its family: "
        f"{bounded['decoded']} decoded for {family_rows} rows"
    )
    # The counters are alive: the materializing path moves every one of them,
    # and decodes the whole run to answer the same question.
    assert whole["model"] >= 1
    assert whole["facts"] >= 1
    assert whole["decoded"] > bounded["decoded"]


def test_the_bounded_read_cost_does_not_grow_with_the_families_it_ignores(
    tmp_path: Path, counted: dict[str, int]
) -> None:
    """Boundedness as a shape, not as a single measurement.

    One run holds the fixture; the other holds the fixture plus a second
    coupled set, so the RUN grows while the ``unit_span`` family does not.
    A read whose decode count follows the run rather than the family is a
    whole-run read wearing a family's name -- and it survives every
    single-corpus count, which is why the second corpus is here.
    """

    with RunStore(tmp_path / "runs.sqlite") as store:
        small = _publish(store, fixture_model())
        large = _publish(store, _neighbour_model(), generation=1)

        counted.update(decoded=0)
        store.read_family(small, FAMILY_UNIT_SPAN)
        small_cost = counted["decoded"]

        counted.update(decoded=0)
        store.read_family(large, FAMILY_UNIT_SPAN)
        large_cost = counted["decoded"]

        counted.update(decoded=0)
        store.read_run(small)
        whole_small = counted["decoded"]
        counted.update(decoded=0)
        store.read_run(large)
        whole_large = counted["decoded"]

    assert small_cost == large_cost, (
        f"the bounded read cost followed the run: {small_cost} -> {large_cost}"
    )
    # The control: the run really did grow, and the whole-model path pays for it.
    assert whole_large > whole_small


# ---------------------------------------------------------------------------
# What the bounded read is NOT
# ---------------------------------------------------------------------------


def test_the_bounded_read_still_proves_every_row_against_its_content_address(
    tmp_path: Path,
) -> None:
    """Boundedness costs the RUN proof, never the ROW proof.

    A corrupted payload is the same typed refusal on this path as on the
    materializing one, because both members go through one decoder.  The
    membership digest, the scope receipt and the model-assembly laws are what
    a bounded read does not buy -- and that trade is only honest if the half
    it does buy is executable.
    """

    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        run_id = _publish(store, fixture_model())

    with sqlite3.connect(path) as raw:
        raw.execute(
            "UPDATE objects SET payload = ? WHERE family = 'unit_span' "
            "AND object_pk = (SELECT MIN(object_pk) FROM objects "
            "WHERE family = 'unit_span')",
            (b'{"tampered": true}',),
        )
    raw.close()

    with (
        RunStore(path, create=False) as store,
        pytest.raises(StoreIntegrityError, match="content address"),
    ):
        store.read_family(run_id, FAMILY_UNIT_SPAN)


#: Every family, and where the whole-model path states the same rows.  Two
#: families are singletons on the model (``None`` is the absent record, never
#: an all-zero fake), so they are lifted to a set of at most one -- the
#: bounded read speaks rows for every family, including those.
_MODEL_ACCESSORS: Final[dict[str, Callable[[CanonicalModel], frozenset[object]]]] = {
    "adoption_count": lambda m: m.facts.analysis.adoption_counts,
    "analysis_population": lambda m: _optional(m.facts.analysis.analysis_population),
    "analyzed_file": lambda m: m.analyzed_files,
    "api_symbol": lambda m: m.facts.analysis.api_symbols,
    "candidate": lambda m: m.facts.analysis.candidates,
    "clone_group": lambda m: m.facts.analysis.clone_groups,
    "contract": lambda m: m.facts.analysis.contracts,
    "coupled_set": lambda m: m.coupled_sets,
    "coupling_cohesion_observation": (
        lambda m: m.facts.analysis.coupling_cohesion_observations
    ),
    "dead_code_observation": lambda m: m.facts.analysis.dead_code_observations,
    "dependency_cycle": lambda m: m.facts.analysis.dependency_cycles,
    "dependency_occurrence": lambda m: m.facts.analysis.dependency_occurrences,
    "dependency_relation": lambda m: m.facts.analysis.dependency_relations,
    "file": lambda m: m.files,
    "file_module": lambda m: m.file_modules,
    "graph_node": lambda m: m.facts.analysis.graph_nodes,
    "module": lambda m: m.modules,
    "risk_observation": lambda m: m.facts.analysis.risk_observations,
    "run_scalar": lambda m: _optional(m.facts.analysis.run_scalars),
    "security_surface": lambda m: m.facts.analysis.security_surfaces,
    "semantic_edge": lambda m: m.facts.analysis.semantic_edges,
    "sink_role": lambda m: m.facts.analysis.sink_roles,
    "unit_span": lambda m: m.facts.analysis.unit_spans,
    "violation": lambda m: m.facts.analysis.violations,
}


def _optional(record: object | None) -> frozenset[object]:
    """A record family as rows: the absent record is no row, never a fake."""
    return frozenset() if record is None else frozenset({record})


def test_the_family_token_is_the_only_way_to_name_a_family() -> None:
    """An unknown family is unspellable rather than typed-refused.

    Keyed by a token from the registry, a family that does not exist cannot
    be passed at all, and the row type comes from the same declaration the
    decoder binds.  A string-keyed read would need a refusal for a name that
    does not exist AND would hand back rows of an erased type; the vocabulary
    is therefore never a second list beside the registry -- it IS the
    registry, which this holds in both directions.
    """

    exported = {
        name
        for name in store_module.__all__
        if isinstance(getattr(store_module, name), StoredFamily)
    }
    declared = {entry.family for entry in store_module._FAMILIES}
    assert {getattr(store_module, name).family for name in exported} == declared, (
        "the exported family tokens and the registry disagree"
    )
