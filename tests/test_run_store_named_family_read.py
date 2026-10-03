# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A run read by its named families: only those, and nothing passes as empty.

``read_named_families`` is the bounded read a projection over several
families needs.  Measured on the self-repository (2026-10-03, isolated
processes): the run summary served out of ``read_run`` decoded all 356 736
members of the run in 5.1-5.2 s at +700 MB peak RSS, to answer from a
handful of families.  The contract pinned here:

* the named families equal the whole read's, row for row, every one proven
  against its content address by the same member decoder;
* every family NOT named is a typed absence -- each use refuses with
  ``UnreadFamilyError`` naming it -- because "not read" is not "measured,
  empty" (the four-state law);
* the read decodes the named families' members and no others, issues the
  one family scan per family and no whole-run scan, answers the run it was
  given, and refuses a store of another generation before reading anything.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Final

import pytest

from codeclone.canonical import store as store_module
from codeclone.canonical.errors import (
    CanonicalModelError,
    StoreCompatibilityError,
    StoreIntegrityError,
    UnknownRunError,
)
from codeclone.canonical.model import AnalysisFacts, CanonicalModel
from codeclone.canonical.store import (
    FAMILY_CLONE_GROUP,
    FAMILY_COVERAGE_JOIN,
    FAMILY_GATE_OUTCOME,
    FAMILY_RUN_SCALAR,
    FAMILY_UNIT_SPAN,
    RunStore,
    UnreadFamilyError,
    read_named_families,
)
from tests.test_canonical_roundtrip import evaluated_fixture_model, fixture_model
from tests.test_run_store_bounded_family_read import _MODEL_ACCESSORS

_NS: Final = "named-family-read"
_GENERATION_1: Final = Path(__file__).parent / "fixtures" / "run_store_generation_1"


@pytest.fixture
def published(tmp_path: Path) -> tuple[Path, str]:
    """The evaluated fixture -- every family of the three tiers non-empty --
    published once into a fresh store."""
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        run_id = store.write_full_run(
            evaluated_fixture_model(), namespace=_NS, target="t", expected_generation=0
        ).run_id
    return path, run_id


def _refused_family(read: Callable[[], object]) -> str:
    with pytest.raises(UnreadFamilyError) as refusal:
        read()
    return refusal.value.family


def _used(
    accessor: Callable[[CanonicalModel], frozenset[object]], model: CanonicalModel
) -> frozenset[object]:
    """One family of ``model``, actually used (an accessor alone hands back
    the stand-in untouched)."""
    return frozenset(accessor(model))


@pytest.mark.parametrize(
    "entry", store_module._FAMILIES, ids=lambda entry: entry.family
)
def test_a_named_family_equals_the_whole_read_and_every_other_one_refuses(
    published: tuple[Path, str], entry: store_module._FamilyEntry
) -> None:
    """Over the whole registry, one family named at a time: that family is
    the whole read's, row for row and non-empty; every other family of the
    model refuses, naming itself -- so the accessor table is also proven to
    reach every family exactly once."""
    path, run_id = published
    with RunStore(path, create=False) as store:
        whole = store.read_run(run_id)
        bounded = read_named_families(store, run_id, [entry])
    assert set(_MODEL_ACCESSORS) == {item.family for item in store_module._FAMILIES}
    named = _MODEL_ACCESSORS[entry.family]
    assert named(bounded) == named(whole)
    assert named(whole), f"{entry.family}: empty in the distinguishing fixture"
    for family, accessor in _MODEL_ACCESSORS.items():
        if family != entry.family:
            assert _refused_family(partial(_used, accessor, bounded)) == family


#: The ways a projection reaches past the attribute: every one refuses,
#: because the refusal is the attribute itself -- no consumer can hold an
#: unread family's value to ask it anything.
_REACHES: Final[dict[str, Callable[[CanonicalModel], object]]] = {
    "set_family": lambda model: model.facts.analysis.clone_groups,
    "record_family": lambda model: model.facts.analysis.coverage_join,
    "record_is_none": lambda model: model.facts.evaluation.gate_outcome is None,
    "model_root_family": lambda model: model.file_modules,
    "house_replace": lambda model: replace(model.facts.comparison),
    "normalize": lambda model: model.normalize(),
}

_REACHED_FAMILY: Final[dict[str, str]] = {
    "set_family": "clone_group",
    "record_family": "coverage_join",
    "record_is_none": "gate_outcome",
    "model_root_family": "file_module",
    "house_replace": "baseline_witness",
    "normalize": "file",
}


@pytest.mark.parametrize("reach", list(_REACHES))
def test_no_reach_into_an_unread_family_answers_empty_or_absent(
    published: tuple[Path, str], reach: str
) -> None:
    """Set families, record families (``None`` is never handed out for an
    unread record), the model root's own families, and the operations that
    walk a whole house all refuse, naming the first unread family met."""
    path, run_id = published
    with RunStore(path, create=False) as store:
        bounded = read_named_families(store, run_id, [FAMILY_RUN_SCALAR])
    assert _refused_family(lambda: _REACHES[reach](bounded)) == _REACHED_FAMILY[reach]


def test_a_named_record_the_run_lacks_is_absent_not_refused(tmp_path: Path) -> None:
    """The four-state law from the other side: a record family that WAS read
    and that the run does not carry answers ``None`` -- measured, absent --
    while the same family unread refuses."""
    with RunStore(tmp_path / "runs.sqlite") as store:
        run_id = store.write_full_run(
            fixture_model(), namespace=_NS, target="t", expected_generation=0
        ).run_id
        read = read_named_families(store, run_id, [FAMILY_GATE_OUTCOME])
        unread = read_named_families(store, run_id, [FAMILY_RUN_SCALAR])
    assert fixture_model().facts.evaluation.gate_outcome is None
    assert read.facts.evaluation.gate_outcome is None
    assert (
        _refused_family(lambda: unread.facts.evaluation.gate_outcome) == "gate_outcome"
    )


def test_the_refusal_is_a_canonical_model_refusal_naming_the_family(
    published: tuple[Path, str],
) -> None:
    """Typed for the serving door: a projection that reaches an unread family
    is a stored answer the projection cannot express -- never a crash with
    an arbitrary exception, never a silent zero."""
    path, run_id = published
    with RunStore(path, create=False) as store:
        bounded = read_named_families(store, run_id, [FAMILY_RUN_SCALAR])
        second = read_named_families(store, run_id, [FAMILY_RUN_SCALAR])
    with pytest.raises(CanonicalModelError, match="'clone_group' was not read"):
        len(bounded.facts.analysis.clone_groups)
    # Two bounded houses cannot even be compared: equality walks the fields.
    equal = _refused_family(lambda: bounded.facts.analysis == second.facts.analysis)
    assert equal == "contract"
    assert isinstance(bounded, CanonicalModel)
    assert isinstance(bounded.facts.analysis, AnalysisFacts)


@pytest.fixture
def decoded(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Every member the store decodes, by family, in order."""
    seen: list[str] = []
    original = store_module._decode_member_object

    def _counting(
        namespace: str,
        object_id_value: str,
        family: str,
        payload: bytes,
        into: dict[str, list[object]],
    ) -> None:
        seen.append(family)
        original(namespace, object_id_value, family, payload, into)

    monkeypatch.setattr(store_module, "_decode_member_object", _counting)
    yield seen


def test_a_named_read_decodes_the_named_members_and_no_other(
    published: tuple[Path, str], decoded: list[str]
) -> None:
    """Boundedness as a count: the members decoded are exactly the named
    families' rows; the whole read, measured beside it, decodes the run."""
    path, run_id = published
    named = (FAMILY_UNIT_SPAN, FAMILY_RUN_SCALAR, FAMILY_CLONE_GROUP)
    with RunStore(path, create=False) as store:
        whole = store.read_run(run_id)
        whole_decoded = len(decoded)
        decoded.clear()
        read_named_families(store, run_id, [*named, FAMILY_UNIT_SPAN])
    expected = sum(len(_MODEL_ACCESSORS[entry.family](whole)) for entry in named)
    assert sorted(set(decoded)) == sorted(entry.family for entry in named)
    assert len(decoded) == expected
    assert whole_decoded > expected


def test_a_named_read_issues_one_family_scan_per_family_and_no_run_scan(
    published: tuple[Path, str],
) -> None:
    """The one SQL path: each family through the family scan of
    :meth:`RunStore.read_family` (``idx_objects_family``), never the
    whole-run member scan of :meth:`RunStore.read_run`."""
    path, run_id = published
    statements: list[str] = []
    with RunStore(path, create=False) as store:
        store._connection.set_trace_callback(statements.append)
        try:
            read_named_families(store, run_id, [FAMILY_UNIT_SPAN, FAMILY_COVERAGE_JOIN])
        finally:
            store._connection.set_trace_callback(None)
    scans = [sql for sql in statements if "run_members" in sql]
    assert len(scans) == 2, scans
    for scan, family in zip(scans, ("coverage_join", "unit_span"), strict=True):
        assert "CROSS JOIN objects o CROSS JOIN run_members m" in scan, scan
        assert f"'{family}'" in scan, scan
    assert not any("FROM run_members m" in sql for sql in statements), statements


def test_a_named_read_still_proves_every_row_against_its_content_address(
    published: tuple[Path, str],
) -> None:
    """Boundedness costs the RUN proof, never the ROW proof: a tampered member
    of a named family is the same typed refusal as on the whole read."""
    path, run_id = published
    _tamper(path, "unit_span")
    with (
        RunStore(path, create=False) as store,
        pytest.raises(StoreIntegrityError, match="content address"),
    ):
        read_named_families(store, run_id, [FAMILY_RUN_SCALAR, FAMILY_UNIT_SPAN])


def test_a_tampered_member_outside_the_named_families_is_never_read(
    published: tuple[Path, str],
) -> None:
    """The positive control of boundedness: the same tampered member, its
    family not named, is not read at all -- the named families come back
    whole -- while the whole read refuses the run."""
    path, run_id = published
    _tamper(path, "unit_span")
    with RunStore(path, create=False) as store:
        bounded = read_named_families(store, run_id, [FAMILY_RUN_SCALAR])
        assert bounded.facts.analysis.run_scalars is not None
        assert bounded.facts.analysis.run_scalars.files_found >= 0
        with pytest.raises(StoreIntegrityError, match="content address"):
            store.read_run(run_id)


def _tamper(path: Path, family: str) -> None:
    with sqlite3.connect(path) as raw:
        raw.execute(
            "UPDATE objects SET payload = ? WHERE object_pk = "
            "(SELECT MIN(o.object_pk) FROM objects o "
            "JOIN families f ON f.family_pk = o.family_pk WHERE f.family = ?)",
            (b'{"tampered": true}', family),
        )
    raw.close()


def test_a_named_read_answers_the_named_run_and_refuses_an_unknown_one(
    published: tuple[Path, str],
) -> None:
    path, run_id = published
    with RunStore(path, create=False) as store:
        with pytest.raises(UnknownRunError):
            read_named_families(store, "f" * 64, [FAMILY_RUN_SCALAR])
        model = read_named_families(store, run_id, [FAMILY_RUN_SCALAR])
    assert isinstance(model, CanonicalModel)
    assert (
        model.facts.analysis.run_scalars
        == evaluated_fixture_model().facts.analysis.run_scalars
    )


def test_a_named_read_refuses_a_store_of_another_generation(tmp_path: Path) -> None:
    """The REAL generation-1 artifact is refused at open, before any family
    is read -- the bounded read never meets a row of another generation."""
    provenance = json.loads((_GENERATION_1 / "provenance.json").read_text("utf-8"))
    store_path = tmp_path / "generation-1.sqlite3"
    shutil.copy(_GENERATION_1 / "runs.sqlite3", store_path)
    with (
        pytest.raises(StoreCompatibilityError, match="canonical_model stored '1'"),
        RunStore(store_path, create=False) as store,
    ):
        read_named_families(store, str(provenance["run_id"]), [FAMILY_RUN_SCALAR])
