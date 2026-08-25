# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Wave-2 run-store laws: L8, atomic publish, CAS head, fencing, walls.

The model fixture is the wave-1 distinguishing fixture (§6.2): every family
non-empty, separator-collision neighbours present, an empty root set next
to non-empty ones — so a store that loses or invents one row cannot produce
the same canonical bytes.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.canonical import (
    CanonicalModel,
    PublishReceipt,
    RunStore,
    StoreCompatibilityError,
    StoreFenceError,
    StoreIntegrityError,
    UnknownRunError,
    analysis_scope_digest,
    decode_canonical_json,
    encode_canonical_json,
)
from tests.test_canonical_roundtrip import fixture_model

_NS = "lineage-alpha"
_TARGET = "worktree-a"


def _store(tmp_path: Path, name: str = "runs.sqlite") -> RunStore:
    return RunStore(tmp_path / name)


def _publish(
    store: RunStore, model: CanonicalModel, *, expected_generation: int = 0
) -> PublishReceipt:
    return store.write_full_run(
        model,
        namespace=_NS,
        target=_TARGET,
        expected_generation=expected_generation,
    )


def _second_model() -> CanonicalModel:
    """A neighbour state: shares every object with the fixture, adds one."""
    model = fixture_model()
    coupled = set(model.coupled_sets)
    coupled.add(frozenset({"OnlyInSecond"}))
    return replace(model, coupled_sets=frozenset(coupled))


# -- L8 and the equivalence square -----------------------------------------


def test_l8_store_projection_equals_model_projection_bytewise(tmp_path: Path) -> None:
    model = fixture_model()
    with _store(tmp_path) as store:
        receipt = _publish(store, model)
        assert store.project_run(receipt.run_id) == encode_canonical_json(model)


def test_square_decode_of_store_projection_is_the_model(tmp_path: Path) -> None:
    model = fixture_model().normalize()
    with _store(tmp_path) as store:
        receipt = _publish(store, model)
        assert decode_canonical_json(store.project_run(receipt.run_id)) == model
        assert store.read_run(receipt.run_id) == model


def test_run_identity_is_content_derived_and_deterministic(tmp_path: Path) -> None:
    """Law 6 (cross-process convergence) in miniature: two stores, one
    model, byte-identical projection and identical run identity."""
    model = fixture_model()
    with _store(tmp_path, "a.sqlite") as first, _store(tmp_path, "b.sqlite") as second:
        receipt_a = _publish(first, model)
        receipt_b = _publish(second, fixture_model(reverse_insertion=True))
        assert receipt_a.run_id == receipt_b.run_id
        assert first.project_run(receipt_a.run_id) == second.project_run(
            receipt_b.run_id
        )


# -- Wall 3: SQLite id is never canonical id --------------------------------


def test_rowid_shift_does_not_move_run_identity_or_bytes(tmp_path: Path) -> None:
    """The same model published into a store whose rowids are already taken
    must produce the same run_id and the same canonical bytes as a fresh
    store — physical keys never escape (brief §14)."""
    model = fixture_model()
    with _store(tmp_path, "fresh.sqlite") as fresh:
        fresh_receipt = _publish(fresh, model)
        fresh_bytes = fresh.project_run(fresh_receipt.run_id)
    with _store(tmp_path, "shifted.sqlite") as shifted:
        _publish(shifted, _second_model())  # occupies low rowids first
        receipt = _publish(shifted, model, expected_generation=1)
        assert receipt.run_id == fresh_receipt.run_id
        assert shifted.project_run(receipt.run_id) == fresh_bytes


def test_api_identifiers_are_content_digests_not_rowids(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        receipt = _publish(store, fixture_model())
        assert len(receipt.run_id) == 64
        assert set(receipt.run_id) <= set("0123456789abcdef")
        head = store.head(namespace=_NS, target=_TARGET)
        assert head is not None and head.run_id == receipt.run_id


# -- Immutable content-addressed sharing (brief §3) -------------------------


def test_neighbour_runs_share_immutable_objects(tmp_path: Path) -> None:
    model = fixture_model()
    neighbour = _second_model()
    with _store(tmp_path) as store:
        first = _publish(store, model)
        second = _publish(store, neighbour, expected_generation=1)
        assert first.run_id != second.run_id
        assert second.shared_objects == first.object_count
        assert second.new_objects == 1  # exactly the added coupled set
        # Neighbour independence: both stay readable, byte-exact.
        assert store.project_run(first.run_id) == encode_canonical_json(model)
        assert store.project_run(second.run_id) == encode_canonical_json(neighbour)


def test_republishing_the_same_state_reuses_the_run(tmp_path: Path) -> None:
    model = fixture_model()
    with _store(tmp_path) as store:
        first = _publish(store, model)
        again = _publish(store, model, expected_generation=1)
        assert again.run_id == first.run_id
        assert again.new_objects == 0
        assert again.head_advanced


# -- Head: CAS and monotonicity (brief §6) ----------------------------------


def test_stale_publisher_cannot_move_the_head_back(tmp_path: Path) -> None:
    """The §6.1 race verbatim: A and B both derive from generation 1; B
    lands first; A must keep its run but must NOT advance the head."""
    base = fixture_model()
    with _store(tmp_path) as store:
        _publish(store, base)  # generation 1
        b = _publish(store, _second_model(), expected_generation=1)
        assert b.head_advanced and b.generation == 2
        stale = _publish(
            store, fixture_model(reverse_insertion=True), expected_generation=1
        )
        assert not stale.head_advanced
        assert stale.generation == 2  # the head after the call: B's, untouched
        assert stale.head_run_id == b.run_id
        head = store.head(namespace=_NS, target=_TARGET)
        assert head is not None
        assert head.generation == 2 and head.run_id == b.run_id
        # The stale run is still a valid immutable run (brief §6.1).
        assert store.read_run(stale.run_id) == fixture_model().normalize()


def test_head_advances_only_from_its_own_generation(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        first = _publish(store, fixture_model())
        assert first.head_advanced and first.generation == 1
        second = _publish(store, _second_model(), expected_generation=1)
        assert second.head_advanced and second.generation == 2
        # A publisher expecting a future generation is stale too.
        eager = _publish(store, fixture_model(), expected_generation=7)
        assert not eager.head_advanced


def test_first_publish_expects_the_empty_generation(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        wrong = _publish(store, fixture_model(), expected_generation=3)
        assert not wrong.head_advanced
        assert store.head(namespace=_NS, target=_TARGET) is None
        right = _publish(store, fixture_model())
        assert right.head_advanced and right.generation == 1


def test_targets_are_independent_operational_namespaces(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        a = store.write_full_run(
            fixture_model(), namespace=_NS, target="worktree-a", expected_generation=0
        )
        b = store.write_full_run(
            _second_model(), namespace=_NS, target="ci-checkout", expected_generation=0
        )
        assert a.head_advanced and b.head_advanced
        head_a = store.head(namespace=_NS, target="worktree-a")
        head_b = store.head(namespace=_NS, target="ci-checkout")
        assert head_a is not None and head_a.run_id == a.run_id
        assert head_b is not None and head_b.run_id == b.run_id


# -- Fencing on every mutation (brief §4.2) ---------------------------------


def test_write_is_refused_after_the_store_generation_moved(tmp_path: Path) -> None:
    """An open handle whose store epoch moved under it must refuse the next
    mutation — compatibility at open() alone is the stale-process P0."""
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as held, RunStore(path) as migrator:
        migrator.bump_store_epoch()
        with pytest.raises(StoreFenceError, match="write refused"):
            _publish(held, fixture_model())
        # The refused write left nothing behind and the store stays usable
        # through a fresh handle that sees the new generation.
    with RunStore(path) as fresh:
        assert fresh.head(namespace=_NS, target=_TARGET) is None
        receipt = _publish(fresh, fixture_model())
        assert receipt.head_advanced


def test_stale_handle_cannot_bump_the_epoch_either(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as held, RunStore(path) as migrator:
        migrator.bump_store_epoch()
        with pytest.raises(StoreFenceError):
            held.bump_store_epoch()


def test_open_refuses_an_incompatible_witness(tmp_path: Path) -> None:
    """Law 7: a store written by a different contract generation is refused
    at open, never reinterpreted."""
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        _publish(store, fixture_model())
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE witness SET revision = '99' WHERE layer = 'canonical_model'"
        )
        connection.commit()
    with pytest.raises(StoreCompatibilityError, match="canonical_model"):
        RunStore(path)


# -- Atomic publish (brief §10) ---------------------------------------------


def test_crash_before_publish_leaves_the_previous_generation_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = fixture_model()
    neighbour = _second_model()
    # The identity the crashed run would have had, from an unrelated store.
    with _store(tmp_path, "oracle.sqlite") as oracle:
        staged_run_id = _publish(oracle, neighbour).run_id
    with _store(tmp_path) as store:
        first = _publish(store, model)

        def _die() -> None:
            raise RuntimeError("injected crash between staging and publish")

        monkeypatch.setattr(store, "_before_publish", _die)
        with pytest.raises(RuntimeError, match="injected crash"):
            _publish(store, neighbour, expected_generation=1)
        monkeypatch.undo()

        # Previous head is still true; the crashed run never became visible.
        head = store.head(namespace=_NS, target=_TARGET)
        assert head is not None
        assert head.generation == 1 and head.run_id == first.run_id
        with pytest.raises(UnknownRunError):
            store.read_run(staged_run_id)
        # Recovery is a plain re-publish, not a repair.
        retried = _publish(store, neighbour, expected_generation=1)
        assert retried.run_id == staged_run_id and retried.head_advanced
        assert store.read_run(staged_run_id) == neighbour.normalize()


def test_publish_verifies_staged_bytes_before_the_flip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reachability of the pre-publish verification (§10): a staged member
    whose bytes are corrupted after staging and before the flip — injected
    through the ``_before_publish`` seam on the same connection, inside the
    open transaction — is a typed refusal.  The head keeps its generation
    and the run never publishes; a dropped verification call would seal a
    published-but-unreadable run, which law 5 forbids."""
    model = fixture_model()
    neighbour = _second_model()
    with _store(tmp_path, "oracle.sqlite") as oracle:
        staged_run_id = _publish(oracle, neighbour).run_id
    with _store(tmp_path) as store:
        first = _publish(store, model)

        def _corrupt_one_staged_member() -> None:
            store._connection.execute(
                "UPDATE objects SET payload = ? WHERE object_pk = "
                "(SELECT MIN(object_pk) FROM objects)",
                (b"{}",),
            )

        monkeypatch.setattr(store, "_before_publish", _corrupt_one_staged_member)
        with pytest.raises(StoreIntegrityError, match="publish refused"):
            _publish(store, neighbour, expected_generation=1)
        monkeypatch.undo()

        head = store.head(namespace=_NS, target=_TARGET)
        assert head is not None
        assert head.generation == 1 and head.run_id == first.run_id
        with pytest.raises(UnknownRunError):
            store.read_run(staged_run_id)
        # The refused transaction rolled the corruption back with it.
        assert store.read_run(first.run_id) == model.normalize()


def test_unpublished_staging_rows_are_invisible_to_readers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even when staging rows survive a crash (a future multi-transaction
    staging), a reader must never see the run: publication is the flip."""
    model = fixture_model()
    with _store(tmp_path) as store:
        # Compute the identity the staged run would get.
        run_id = _publish(store, model).run_id
    path = tmp_path / "runs.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE runs SET published = 0 WHERE run_id = ?", (run_id,))
        connection.commit()
    with RunStore(path) as store, pytest.raises(UnknownRunError):
        store.read_run(run_id)


# -- Integrity: corruption is loud (E8 row 4) -------------------------------


def test_corrupted_payload_byte_is_a_typed_refusal(tmp_path: Path) -> None:
    model = fixture_model()
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        run_id = _publish(store, model).run_id
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT object_pk, payload FROM objects ORDER BY object_pk LIMIT 1"
        ).fetchone()
        payload = bytearray(row[1])
        payload[-2] ^= 0x01  # flip one bit inside the payload
        connection.execute(
            "UPDATE objects SET payload = ? WHERE object_pk = ?",
            (bytes(payload), row[0]),
        )
        connection.commit()
    with (
        RunStore(path) as store,
        pytest.raises(StoreIntegrityError, match="content address"),
    ):
        store.read_run(run_id)


@pytest.mark.parametrize(
    ("family", "malformed", "match"),
    [
        # Not a pair at all: reaches the list-shape guard.
        (
            "contract",
            b'{"effect_signature":"x","function":"not-a-pair","root_set":[]}',
            "stored symbol",
        ),
        # A pair of non-strings: reaches the element-type guard behind it.
        (
            "contract",
            b'{"effect_signature":"x","function":[1,2],"root_set":[]}',
            "stored symbol",
        ),
    ],
    ids=[
        "contract-not-a-pair",
        "contract-non-string-pair",
    ],
)
def test_well_addressed_malformed_payload_is_refused(
    tmp_path: Path, family: str, malformed: bytes, match: str
) -> None:
    """Depth guard reachability: a payload that hashes to its content
    address but decodes to the wrong shape or violates a family law (a
    writer-drift class, not bit rot) is still a typed refusal, never a
    silently different model.  One input per sub-guard: a sibling guard
    catching the probe would otherwise mask a dropped one."""
    from codeclone.canonical.store import _object_id

    model = fixture_model()
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        run_id = _publish(store, model).run_id
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT object_pk FROM objects WHERE family = ? ORDER BY object_id LIMIT 1",
            (family,),
        ).fetchone()
        connection.execute(
            "UPDATE objects SET payload = ?, object_id = ? WHERE object_pk = ?",
            (malformed, _object_id(_NS, family, malformed), row[0]),
        )
        connection.commit()
    with (
        RunStore(path) as store,
        pytest.raises(StoreIntegrityError, match=match),
    ):
        store.read_run(run_id)


def test_intact_store_raises_no_integrity_refusal(tmp_path: Path) -> None:
    """The opposite boundary: verification must not refuse honest bytes."""
    model = fixture_model()
    with _store(tmp_path) as store:
        run_id = _publish(store, model).run_id
        assert store.read_run(run_id) == model.normalize()


def test_unknown_run_is_a_typed_refusal(tmp_path: Path) -> None:
    with _store(tmp_path) as store, pytest.raises(UnknownRunError):
        store.read_run("0" * 64)


# -- Scope receipt (brief §7.1, wave-2 minimal) -----------------------------


def test_scope_receipt_rides_the_run_and_recomputes(tmp_path: Path) -> None:
    model = fixture_model()
    with _store(tmp_path) as store:
        receipt = _publish(store, model)
        assert receipt.analysis_scope_digest == analysis_scope_digest(
            model.normalize().analyzed_files
        )
        assert store.run_scope_digest(receipt.run_id) == receipt.analysis_scope_digest


def test_scope_digest_separates_scope_from_facts(tmp_path: Path) -> None:
    """Both boundaries: same facts under a different analyzed universe is a
    different scope AND a different run; same scope with different facts
    keeps the receipt and moves only the run."""
    model = fixture_model().normalize()
    unanalyzed = sorted(
        model.files - model.analyzed_files, key=lambda file_id: file_id.path
    )
    assert unanalyzed, "fixture must carry a file outside the analyzed scope"
    widened = replace(
        model, analyzed_files=frozenset(model.analyzed_files | {unanalyzed[0]})
    )
    other_facts = _second_model()
    with _store(tmp_path) as store:
        base = _publish(store, model)
        scope_moved = store.write_full_run(
            widened, namespace=_NS, target="scope-probe", expected_generation=0
        )
        facts_moved = store.write_full_run(
            other_facts, namespace=_NS, target="facts-probe", expected_generation=0
        )
        assert scope_moved.analysis_scope_digest != base.analysis_scope_digest
        assert scope_moved.run_id != base.run_id
        assert facts_moved.analysis_scope_digest == base.analysis_scope_digest
        assert facts_moved.run_id != base.run_id


# -- W1 + the ratified PRAGMA convention (ruling 2026-08-24 §5) -------------


def test_w1_run_store_path_is_a_workspace_constant() -> None:
    """W1 verbatim: the run-store lives at ``.codeclone/db/runs.sqlite3``.

    The value is a ratified normative decision (ruling 2026-08-24 §5: W2 and
    W3 rejected), pinned literally on purpose — moving the store is a
    decision for the maintainer, not a refactor.
    """
    from codeclone.paths.workspace import REL_RUN_STORE_DB_PATH

    assert REL_RUN_STORE_DB_PATH == ".codeclone/db/runs.sqlite3"


def _connection_pragmas(store: RunStore) -> tuple[str, int, int, int]:
    connection = store._connection
    return (
        str(connection.execute("PRAGMA journal_mode").fetchone()[0]),
        int(connection.execute("PRAGMA busy_timeout").fetchone()[0]),
        int(connection.execute("PRAGMA synchronous").fetchone()[0]),
        int(connection.execute("PRAGMA foreign_keys").fetchone()[0]),
    )


def test_store_connection_carries_the_ratified_pragmas(tmp_path: Path) -> None:
    """WAL + busy_timeout=5000 + synchronous=FULL(2) + foreign keys ON.

    The convention arrives through the one shared connection owner
    (``codeclone.utils.sqlite_store``); FULL is this store's own override —
    the durability of a published immutable run is not weakened to NORMAL
    as a side effect of unification (ruling 2026-08-24 §5).
    """
    with _store(tmp_path) as store:
        journal, busy_timeout, synchronous, foreign_keys = _connection_pragmas(store)
    assert journal == "wal"
    assert busy_timeout == 5000
    assert synchronous == 2  # FULL — never NORMAL(1) by unification default
    assert foreign_keys == 1


def test_ratified_pragmas_hold_on_reopen_of_an_existing_store(tmp_path: Path) -> None:
    """journal_mode persists in the file, but busy_timeout and synchronous
    are per-connection state: a reopen path that bypasses the shared owner
    loses them silently, so the pin observes a second handle."""
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        _publish(store, fixture_model())
    with RunStore(path) as reopened:
        journal, busy_timeout, synchronous, foreign_keys = _connection_pragmas(reopened)
    assert (journal, busy_timeout, synchronous, foreign_keys) == ("wal", 5000, 2, 1)


# -- Receipt counts ---------------------------------------------------------


def test_receipt_counts_every_family_of_the_fixture(tmp_path: Path) -> None:
    model = fixture_model().normalize()
    with _store(tmp_path) as store:
        receipt = _publish(store, model)
        counts = receipt.family_counts
        assert counts["contract"] == len(model.facts.analysis.contracts)
        assert counts["graph_node"] == len(model.facts.analysis.graph_nodes)
        assert counts["sink_role"] == len(model.facts.analysis.sink_roles)
        assert counts["candidate"] == len(model.facts.analysis.candidates)
        assert counts["semantic_edge"] == len(model.facts.analysis.semantic_edges)
        assert counts["dependency_edge"] == len(model.facts.analysis.dependency_edges)
        assert counts["violation"] == len(model.facts.analysis.violations)
        assert counts["file"] == len(model.files)
        assert counts["module"] == len(model.modules)
        assert counts["analyzed_file"] == len(model.analyzed_files)
        assert counts["file_module"] == len(model.file_modules)
        assert counts["coupled_set"] == len(model.coupled_sets)
        assert receipt.object_count == sum(counts.values())
