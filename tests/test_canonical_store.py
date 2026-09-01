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

import ast
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, replace
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
from codeclone.canonical.identity import FileId, ModuleId
from codeclone.canonical.model import (
    AdoptionCountRow,
    AnalysisPopulation,
    ApiSymbolRow,
    CandidateRow,
    CloneGroupRow,
    ContractRow,
    CouplingCohesionRow,
    DeadCodeObservationRow,
    DependencyCycleRow,
    DependencyOccurrenceRow,
    DependencyRelationRow,
    FileModuleRelation,
    GraphNodeRow,
    RiskObservationRow,
    RunScalars,
    SecuritySurfaceRow,
    SemanticEdge,
    SinkRoleRow,
    ViolationRow,
)
from codeclone.canonical.store import _payload_bytes
from codeclone.contracts import STORAGE_SCHEMA_REVISION
from tests.test_canonical_roundtrip import fixture_model

_NS = "lineage-alpha"
_TARGET = "worktree-a"
_REPO_ROOT = Path(__file__).resolve().parents[1]


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
    model, byte-identical projection and identical run identity.

    "In miniature" is literal: both models are built in ONE interpreter, so
    both spell the same ``frozenset``s into the same hash-table layout.
    That makes this pin blind to every owner that turns a set into an
    ordered payload — see the hash-seed pin below, which is not.
    """
    model = fixture_model()
    with _store(tmp_path, "a.sqlite") as first, _store(tmp_path, "b.sqlite") as second:
        receipt_a = _publish(first, model)
        receipt_b = _publish(second, fixture_model(reverse_insertion=True))
        assert receipt_a.run_id == receipt_b.run_id
        assert first.project_run(receipt_a.run_id) == second.project_run(
            receipt_b.run_id
        )


_CONVERGENCE_CHILD = """
import hashlib, io, pathlib, sys, tempfile
from codeclone.canonical import RunStore, export_run
from tests.test_canonical_roundtrip import fixture_model

model = fixture_model()
with tempfile.TemporaryDirectory() as directory:
    with RunStore(pathlib.Path(directory) / "runs.sqlite") as store:
        receipt = store.write_full_run(
            model, namespace="conv", target="head", expected_generation=0
        )
        wire = store.project_run(receipt.run_id)
        sink = io.BytesIO()
        envelope = export_run(store, receipt.run_id, sink)
print(receipt.run_id, receipt.analysis_scope_digest,
      hashlib.sha256(wire).hexdigest(), envelope.artifact_digest)
"""


def test_law6_identity_and_bytes_are_hash_seed_independent() -> None:
    """Law 6 across PROCESSES — the axis the in-process pin cannot reach.

    Set-to-payload owners (``analysis_scope_digest``'s path sort,
    ``_sorted_symbols`` / ``_sorted_roots``, the inner label sort of
    ``_identity_rows``) only show themselves when a FRESH interpreter
    re-lays the same ``frozenset`` out under a different string hash seed.
    Dropping any one of them was measured green under some seeds and red
    under others, so the known-answer literals catch them by luck, not by
    construction; these three seeds are the measured triple that separates
    all three owners.

    Deliberately an invariance pin, not a value pin: run identity, scope
    receipt, projected bytes and the export artifact digest each get their
    frozen value elsewhere.  Here they only have to agree with themselves.
    """
    observed: list[str] = []
    for seed in ("1", "2", "3"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            (sys.executable, "-c", _CONVERGENCE_CHILD),
            cwd=_REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        observed.append(completed.stdout.strip())
    assert len(observed) == 3
    assert len(set(observed)) == 1, observed


# ---------------------------------------------------------------------------
# The two independent contracts (RULING-2026-09-01).  Storage physics answers
# "can this process open and migrate this SQLite container"; the canonical
# object identity answers "by which semantic preimage is an object addressed".
# They are pinned by two SEPARATE tests below, one per direction, because a
# single test that asserted both would stay green if the two contracts were
# re-merged under one constant.
#
# Both children bump a contracts constant AT THE SOURCE -- the module
# attribute, before ``codeclone.canonical.store`` is first imported -- so the
# substitution reaches every use site the production module has, including the
# module-level separator glue that a ``monkeypatch.setattr`` on an already-
# imported ``Final`` cannot touch.
# ---------------------------------------------------------------------------

#: The separator rule, spelled here independently of the production constant
#: so a pin can check the live spelling before substituting anything.
_STORE_DOMAINS: tuple[tuple[str, bytes], ...] = (
    ("_DOMAIN_PREFIX", b""),
    ("_DOMAIN_OBJECT", b"object\x00"),
    ("_DOMAIN_RUN", b"run\x00"),
    ("_DOMAIN_SCOPE", b"scope\x00"),
    ("_DOMAIN_MEMBERSHIP", b"membership\x00"),
    ("_DOMAIN_CONTRACT_EPOCH", b"contract-epoch\x00"),
)

#: The separator spelling of the generation that salted every content address
#: with ``STORAGE_SCHEMA_REVISION``.  Kept as history: no live code may
#: produce it, and the migration pin below is the only thing that still does.
_PRIOR_GENERATION_PREFIX = b"cc-run-store:1\x00"

_GENERATION_CHILD = """
import json, pathlib, sqlite3, sys, tempfile

import codeclone.contracts as contracts

for name, value in json.loads(sys.argv[1]).items():
    if not hasattr(contracts, name):
        raise SystemExit("unknown contract constant: " + name)
    setattr(contracts, name, value)

assert "codeclone.canonical.store" not in sys.modules, "store imported too early"

from codeclone.canonical import RunStore
from tests.test_canonical_roundtrip import fixture_model

with tempfile.TemporaryDirectory() as directory:
    path = pathlib.Path(directory) / "runs.sqlite"
    with RunStore(path) as store:
        receipt = store.write_full_run(
            fixture_model(), namespace="gen", target="head", expected_generation=0
        )
    with sqlite3.connect(path) as connection:
        objects = [
            str(row[0])
            for row in connection.execute(
                "SELECT object_id FROM objects ORDER BY object_id"
            )
        ]
        membership = str(
            connection.execute("SELECT membership_digest FROM runs").fetchone()[0]
        )
        meta = connection.execute(
            "SELECT storage_schema_revision, contract_epoch FROM store_meta"
        ).fetchone()

print(json.dumps({
    "run_id": receipt.run_id,
    "scope": receipt.analysis_scope_digest,
    "membership": membership,
    "objects": objects,
    "storage_revision": str(meta[0]),
    "contract_epoch": str(meta[1]),
}))
"""


@dataclass(frozen=True, slots=True)
class _Generation:
    """One published fixture, read back through the store's own tables."""

    run_id: str
    scope: str
    membership: str
    objects: tuple[str, ...]
    storage_revision: str
    contract_epoch: str


def _generation(**overrides: str) -> _Generation:
    """Publish the fixture in a fresh interpreter under bumped constants."""
    completed = subprocess.run(
        (sys.executable, "-c", _GENERATION_CHILD, json.dumps(overrides)),
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    return _Generation(
        run_id=str(payload["run_id"]),
        scope=str(payload["scope"]),
        membership=str(payload["membership"]),
        objects=tuple(str(value) for value in payload["objects"]),
        storage_revision=str(payload["storage_revision"]),
        contract_epoch=str(payload["contract_epoch"]),
    )


def test_a_storage_schema_bump_moves_the_container_and_no_content_address() -> None:
    """Container side: DDL generation moves, semantic addresses do not.

    ``STORAGE_SCHEMA_REVISION`` answers one question -- may this process open
    this SQLite file -- and a bridge table, an index or a layout change is a
    legitimate reason to move it.  Measured 2026-09-01 on the first bump the
    constant ever took ("0" -> "1", the persisted identity bridge): it was
    spelled into ``_DOMAIN_PREFIX``, so a pure container change reset every
    object id, the scope receipt, the membership digest and the run identity
    -- the analysis semantics moved without a single fact changing.

    The reachability half is load-bearing in its own right: the bump is
    proven to have REACHED the container (the stored revision and the fenced
    contract epoch both move), so the invariance below is the measured
    silence of a guard that fired, not the silence of an input that never
    arrived.
    """
    baseline = _generation()
    bumped = _generation(STORAGE_SCHEMA_REVISION="99")

    # Reachable input: the bump really is a container-generation change.
    assert baseline.storage_revision == STORAGE_SCHEMA_REVISION
    assert bumped.storage_revision == "99"
    assert bumped.contract_epoch != baseline.contract_epoch

    # ... and it reaches no semantic address.
    assert baseline.objects
    assert bumped.objects == baseline.objects
    assert bumped.scope == baseline.scope
    assert bumped.membership == baseline.membership
    assert bumped.run_id == baseline.run_id


def test_a_canonical_object_identity_bump_moves_every_content_address() -> None:
    """Identity side: the semantic preimage generation owns the addresses.

    ``CANONICAL_OBJECT_IDENTITY_VERSION`` answers the other question -- by
    which preimage is an object addressed -- and it is what the logical key,
    the family namespace, the witnesses and the canonical payload move with.
    Every store content address must move with it, and the container
    generation must not.

    The live separators are re-derived from the rule BEFORE anything is
    substituted.  A pin that hand-feeds its own separators measures its own
    substitution: that is exactly how the previous wave's pin was found
    hollow (mutant m11, 2026-09-01) -- dropping the constant out of
    ``_DOMAIN_PREFIX`` altogether left it green.
    """
    import codeclone.canonical.store as store_module
    from codeclone.contracts import CANONICAL_OBJECT_IDENTITY_VERSION

    live = f"cc-object-identity:{CANONICAL_OBJECT_IDENTITY_VERSION}\x00".encode()
    for name, suffix in _STORE_DOMAINS:
        assert getattr(store_module, name) == live + suffix, name

    baseline = _generation()
    bumped = _generation(CANONICAL_OBJECT_IDENTITY_VERSION="99")

    # Every single address moved -- not merely the set as a whole.
    assert baseline.objects
    assert frozenset(bumped.objects).isdisjoint(frozenset(baseline.objects))
    assert bumped.scope != baseline.scope
    assert bumped.membership != baseline.membership
    assert bumped.run_id != baseline.run_id

    # The container generation is not dragged along by a semantic bump.
    assert bumped.storage_revision == baseline.storage_revision


def test_the_contract_epoch_separator_is_owned_by_the_identity_prefix() -> None:
    """Which contract owns the FENCE separator — measured, not assumed.

    ``_DOMAIN_CONTRACT_EPOCH`` is the one domain here that addresses nothing:
    no object, no run and no receipt is named by it.  It separates the store's
    generation fence, whose preimage already joins EVERY witness layer.  Its
    separator nevertheless descends from ``_DOMAIN_PREFIX``, so the identity
    contract owns it today: an identity bump reaches the epoch twice (through
    the separator AND through the layer list) while a storage bump reaches it
    once, through the list alone.

    This pin is the derivation, not a verdict.  Whether a container fence
    should carry a semantic generation at all is the layer owner's decision
    and is deliberately left open.  What may not happen again is that the
    relation lives only in a comment: that is exactly how the storage revision
    got inside every content address and stayed there for a whole generation.
    """
    import codeclone.canonical.store as store_module
    from codeclone.contracts import CANONICAL_OBJECT_IDENTITY_VERSION

    identity_rule = f"cc-object-identity:{CANONICAL_OBJECT_IDENTITY_VERSION}\x00"
    storage_rule = f"cc-run-store:{STORAGE_SCHEMA_REVISION}\x00"
    suffix = b"contract-epoch\x00"

    # Owned by the identity prefix, and provably not by the storage rule --
    # the second half is what reds if the split is reverted wholesale.
    epoch = store_module._DOMAIN_CONTRACT_EPOCH
    assert epoch == identity_rule.encode() + suffix
    assert epoch != storage_rule.encode() + suffix
    assert epoch == store_module._DOMAIN_PREFIX + suffix

    # Reachable input for BOTH owners: neither bump is silent on the fence.
    baseline = _generation()
    assert _generation(CANONICAL_OBJECT_IDENTITY_VERSION="99").contract_epoch != (
        baseline.contract_epoch
    )
    assert _generation(STORAGE_SCHEMA_REVISION="99").contract_epoch != (
        baseline.contract_epoch
    )


def test_a_prior_generation_store_file_is_refused_not_reopened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The migration rule: a file whose addresses carry the storage revision
    inside them may not be reopened as if its addresses were compatible.

    Admissible outcomes are a typed regeneration, a typed refusal, or the
    next storage generation.  What is forbidden is a silent open.  The
    refusal here is structural rather than advisory: the identity version is
    a witness layer, so a file written before the split simply does not
    declare it, and law 7 refuses the stored generation at open -- before a
    single address is read back.

    The first half measures WHY that matters, and doubles as this pin's
    mutation guard: the prior generation's addresses are disjoint from the
    ones this process computes for the same model.  Put the storage revision
    back into the separator and the two sets coincide, which reds here.
    """
    import codeclone.canonical.store as store_module

    for name, suffix in _STORE_DOMAINS:
        monkeypatch.setattr(store_module, name, _PRIOR_GENERATION_PREFIX + suffix)
    monkeypatch.setattr(
        store_module,
        "_WITNESS_LAYERS",
        tuple(
            layer
            for layer in store_module._WITNESS_LAYERS
            if layer[0] != "canonical_object_identity"
        ),
    )
    path = tmp_path / "prior.sqlite"
    with _store(tmp_path, "prior.sqlite") as store:
        _publish(store, fixture_model())
    monkeypatch.undo()

    with sqlite3.connect(path) as connection:
        prior_addresses = frozenset(
            str(row[0]) for row in connection.execute("SELECT object_id FROM objects")
        )
    with _store(tmp_path, "current.sqlite") as store:
        _publish(store, fixture_model())
    with sqlite3.connect(tmp_path / "current.sqlite") as connection:
        current_addresses = frozenset(
            str(row[0]) for row in connection.execute("SELECT object_id FROM objects")
        )
    assert prior_addresses and current_addresses
    assert prior_addresses.isdisjoint(current_addresses)

    with pytest.raises(StoreCompatibilityError, match="canonical_object_identity"):
        RunStore(path)


def test_storage_payload_bytes_ignore_mapping_key_order() -> None:
    """``_payload_bytes`` owns the byte form the content address hashes.

    Every family ``_model_rows`` yields happens to spell its row dict in
    alphabetical key order today, so ``sort_keys=True`` is a guard NO
    production input reaches — measured: flipping it to ``False`` survives
    the whole suite.  This pin supplies the input that does reach it, so
    the guard cannot decay into decoration while the families drift.
    """
    ascending = {"alpha": 1, "beta": [2, 3], "gamma": "x"}
    descending = {"gamma": "x", "beta": [2, 3], "alpha": 1}
    assert list(descending) != list(ascending)  # the input really is disordered
    assert _payload_bytes(descending) == _payload_bytes(ascending)
    assert _payload_bytes(descending) == b'{"alpha":1,"beta":[2,3],"gamma":"x"}'


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
        # F2, zero numerator: the store's shape guard admits the int, the
        # MODEL law (the floor's one owner) refuses, and the store wraps it.
        (
            "coupling_cohesion_observation",
            b'{"dimension":"cbo","numerator":0,"symbol":["pkg/a.py","A.run"]}',
            "numerator",
        ),
        # F2, non-int numerator: the store's own shape guard refuses.
        (
            "coupling_cohesion_observation",
            b'{"dimension":"cbo","numerator":"3","symbol":["pkg/a.py","A.run"]}',
            "numerator",
        ),
        # F5 sub-guards, one probe each (masked-sibling law: a passing set
        # exercising two guards must isolate each).
        (
            "api_symbol",
            b'{"parameters":7,"returns_digest":null,"symbol":["pkg/a.py","A"],'
            b'"symbol_kind":"class","visibility":"all"}',
            "'parameters' is not an array",
        ),
        (
            "api_symbol",
            b'{"parameters":[["value","pos_or_kw"]],"returns_digest":null,'
            b'"symbol":["pkg/a.py","A"],"symbol_kind":"class","visibility":"all"}',
            "stored api parameter is not a",
        ),
        (
            "api_symbol",
            b'{"parameters":[[7,"pos_or_kw",false,null]],"returns_digest":null,'
            b'"symbol":["pkg/a.py","A"],"symbol_kind":"class","visibility":"all"}',
            "api parameter names are not strings",
        ),
        (
            "api_symbol",
            b'{"parameters":[["value","pos_or_kw","no",null]],'
            b'"returns_digest":null,"symbol":["pkg/a.py","A"],'
            b'"symbol_kind":"class","visibility":"all"}',
            "default marker is not a boolean",
        ),
        (
            "api_symbol",
            b'{"parameters":[["value","pos_or_kw",false,7]],"returns_digest":null,'
            b'"symbol":["pkg/a.py","A"],"symbol_kind":"class","visibility":"all"}',
            "annotation is not a string",
        ),
        (
            "api_symbol",
            b'{"parameters":[],"returns_digest":7,"symbol":["pkg/a.py","A"],'
            b'"symbol_kind":"class","visibility":"all"}',
            "'returns_digest' is not a string",
        ),
        # model law through the store wrapper: unknown symbol kind
        (
            "api_symbol",
            b'{"parameters":[],"returns_digest":null,"symbol":["pkg/a.py","A"],'
            b'"symbol_kind":"banana","visibility":"all"}',
            "unknown api symbol kind",
        ),
        # F7 shape guard: a non-string module member is refused by the store
        (
            "dependency_cycle",
            b'{"kind":"import_cycle","modules":["pkg.a",7]}',
            "carries a non-string",
        ),
        # F7 model law through the store wrapper: unknown cycle kind
        (
            "dependency_cycle",
            b'{"kind":"banana","modules":["pkg.a","pkg.b"]}',
            "cycle kind",
        ),
        # F7 model law through the store wrapper: the two-module floor
        (
            "dependency_cycle",
            b'{"kind":"import_cycle","modules":["pkg.a"]}',
            "at least two",
        ),
        # F8 shape guard: an item that is not a [path, qualname, start, end]
        # quad is refused by the store
        (
            "clone_group",
            b'{"clone_kind":"function","group_key":"k1",'
            b'"items":[["pkg/a.py","A.run",1]]}',
            "clone item is not a",
        ),
        # F8 model law through the store wrapper: unknown clone kind
        (
            "clone_group",
            b'{"clone_kind":"banana","group_key":"k1",'
            b'"items":[["pkg/a.py","A.run",1,5],["pkg/a.py","A.run",9,13]]}',
            "clone kind",
        ),
        # F8 model law through the store wrapper: the two-item floor
        (
            "clone_group",
            b'{"clone_kind":"function","group_key":"k1",'
            b'"items":[["pkg/a.py","A.run",1,5]]}',
            "at least two",
        ),
        # F4 shape guard: an entity that is not a tagged triple
        (
            "dead_code_observation",
            b'{"abstained":false,"candidate_kind":"function",'
            b'"entity":["module","pkg.m"],"live_root_reason":null,'
            b'"observation_kind":"symbol","reachable":false,'
            b'"reference_count":0,"runtime_marker_count":0,"source_markers":[]}',
            "tag, head, qualname",
        ),
        # F4 shape guard: an unknown entity tag
        (
            "dead_code_observation",
            b'{"abstained":false,"candidate_kind":"function",'
            b'"entity":["banana","pkg.m","f"],"live_root_reason":null,'
            b'"observation_kind":"symbol","reachable":false,'
            b'"reference_count":0,"runtime_marker_count":0,"source_markers":[]}',
            "unknown dead-code entity tag",
        ),
        # F4 model law through the store wrapper: abstention with a root
        (
            "dead_code_observation",
            b'{"abstained":true,"candidate_kind":"function",'
            b'"entity":["module","pkg.m","f"],"live_root_reason":"export_root",'
            b'"observation_kind":"symbol","reachable":false,'
            b'"reference_count":0,"runtime_marker_count":0,"source_markers":[]}',
            "mutually exclusive",
        ),
        # F3 shape guard: a non-int count is refused by the store
        (
            "adoption_count",
            b'{"denominator":"4","feature":"typing.parameters",'
            b'"numerator":3,"scope":["module","pkg.a"]}',
            "'denominator' is not an int",
        ),
        # F3 shape guard: an unknown scope tag is refused by the store
        (
            "adoption_count",
            b'{"denominator":4,"feature":"typing.parameters",'
            b'"numerator":3,"scope":["banana","pkg.a"]}',
            "unknown endpoint tag",
        ),
        # F3 model law through the store wrapper: the denominator floor
        (
            "adoption_count",
            b'{"denominator":0,"feature":"typing.parameters",'
            b'"numerator":0,"scope":["module","pkg.a"]}',
            "denominator",
        ),
        # F3 model law through the store wrapper: numerator above denominator
        (
            "adoption_count",
            b'{"denominator":2,"feature":"typing.parameters",'
            b'"numerator":3,"scope":["module","pkg.a"]}',
            "exceed",
        ),
        # F10 shape guard: a non-int span member is refused by the store
        (
            "security_surface",
            b'{"capability":"subprocess_run","category":"process_boundary",'
            b'"classification_mode":"exact_call","end_line":"7",'
            b'"evidence_kind":"call","evidence_symbol":"subprocess.run",'
            b'"file":"pkg/a.py","location_scope":"callable","qualname":"go",'
            b'"source_kind":"production","start_line":5}',
            "'end_line' is not an int",
        ),
        # F10 model law through the store wrapper: unknown source kind
        (
            "security_surface",
            b'{"capability":"subprocess_run","category":"process_boundary",'
            b'"classification_mode":"exact_call","end_line":7,'
            b'"evidence_kind":"call","evidence_symbol":"subprocess.run",'
            b'"file":"pkg/a.py","location_scope":"callable","qualname":"go",'
            b'"source_kind":"banana","start_line":5}',
            "source kind",
        ),
        # F10 model law through the store wrapper: module scope with a name
        (
            "security_surface",
            b'{"capability":"subprocess_run","category":"process_boundary",'
            b'"classification_mode":"exact_call","end_line":7,'
            b'"evidence_kind":"call","evidence_symbol":"subprocess.run",'
            b'"file":"pkg/a.py","location_scope":"module","qualname":"go",'
            b'"source_kind":"production","start_line":5}',
            "module-scope",
        ),
        # F9 shape guard: a non-int scalar is refused by the store
        (
            "run_scalar",
            b'{"classes":"7","files_analyzed":2,"files_cached":1,'
            b'"files_found":3,"files_skipped":0,"functions":41,"methods":13,'
            b'"parsed_lines":905,"source_io_skipped":4,'
            b'"unsupported_construct_skipped":5}',
            "'classes' is not an int",
        ),
        # F9 model law through the store wrapper: a negative scalar
        (
            "run_scalar",
            b'{"classes":-7,"files_analyzed":2,"files_cached":1,'
            b'"files_found":3,"files_skipped":0,"functions":41,"methods":13,'
            b'"parsed_lines":905,"source_io_skipped":4,'
            b'"unsupported_construct_skipped":5}',
            "run scalar classes",
        ),
        # Population shape guard: stored pairs must be a list
        (
            "analysis_population",
            b'{"analysis_mode":"full","analysis_profile":"min_loc",'
            b'"producer_states":[]}',
            "stored pairs are not a list",
        ),
        # Population shape guard: a pair must be a [name, value] list
        (
            "analysis_population",
            b'{"analysis_mode":"full","analysis_profile":[["min_loc",6,6]],'
            b'"producer_states":[]}',
            r"not a \[name, value\] list",
        ),
        # Population shape guard: profile value must be an int
        (
            "analysis_population",
            b'{"analysis_mode":"full","analysis_profile":[["min_loc","6"]],'
            b'"producer_states":[]}',
            "is not an int",
        ),
        # Population shape guard: a state must be a string
        (
            "analysis_population",
            b'{"analysis_mode":"full","analysis_profile":[],'
            b'"producer_states":[["complexity",7]]}',
            "is not a string",
        ),
        # Population model law through the store wrapper: unknown state
        (
            "analysis_population",
            b'{"analysis_mode":"full","analysis_profile":[],'
            b'"producer_states":[["complexity","paused"]]}',
            "ratified execution-state",
        ),
    ],
    ids=[
        "contract-not-a-pair",
        "contract-non-string-pair",
        "coupling-zero-numerator-model-law",
        "coupling-non-int-numerator-shape-guard",
        "api-parameters-not-array",
        "api-parameter-not-a-quad",
        "api-parameter-non-string-names",
        "api-default-marker-not-bool",
        "api-annotation-not-string",
        "api-returns-not-string",
        "api-unknown-kind-model-law",
        "cycle-non-string-module-shape-guard",
        "cycle-unknown-kind-model-law",
        "cycle-single-module-model-law",
        "clone-item-not-a-quad-shape-guard",
        "clone-unknown-kind-model-law",
        "clone-single-item-model-law",
        "dead-entity-not-a-triple-shape-guard",
        "dead-entity-unknown-tag-shape-guard",
        "dead-abstained-with-root-model-law",
        "adoption-non-int-count-shape-guard",
        "adoption-unknown-scope-tag-shape-guard",
        "adoption-zero-denominator-model-law",
        "adoption-numerator-above-denominator-model-law",
        "surface-non-int-span-shape-guard",
        "surface-unknown-source-kind-model-law",
        "surface-module-scope-with-name-model-law",
        "run-scalar-non-int-shape-guard",
        "run-scalar-negative-model-law",
        "population-pairs-not-list-shape-guard",
        "population-pair-not-a-pair-shape-guard",
        "population-profile-non-int-shape-guard",
        "population-state-non-string-shape-guard",
        "population-unknown-state-model-law",
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


def test_two_run_scalar_records_in_one_run_are_refused(tmp_path: Path) -> None:
    """F9 law at the storage face: ONE record per analysis snapshot.

    The forgery is SELF-CONSISTENT (membership and run identity are refit
    through the store's own formulas), so every digest check passes and the
    one-record guard is the only wall left — without it the reader would
    silently pick one of the two records.
    """
    from codeclone.canonical.store import (
        _membership_digest,
        _object_id,
        _payload_bytes,
        _run_id,
    )

    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        _publish(store, fixture_model())
    second = _payload_bytes(
        {
            "classes": 8,
            "files_analyzed": 2,
            "files_cached": 1,
            "files_found": 3,
            "files_skipped": 0,
            "functions": 41,
            "methods": 13,
            "parsed_lines": 905,
            "source_io_skipped": 4,
            "unsupported_construct_skipped": 5,
        }
    )
    with sqlite3.connect(path) as connection:
        run_pk, namespace_pk = connection.execute(
            "SELECT run_pk, namespace_pk FROM runs"
        ).fetchone()
        cursor = connection.execute(
            "INSERT INTO objects (namespace_pk, object_id, family, payload) "
            "VALUES (?, ?, ?, ?)",
            (namespace_pk, _object_id(_NS, "run_scalar", second), "run_scalar", second),
        )
        connection.execute(
            "INSERT INTO run_members (run_pk, object_pk) VALUES (?, ?)",
            (run_pk, cursor.lastrowid),
        )
        object_ids = [
            str(row[0])
            for row in connection.execute(
                "SELECT o.object_id FROM run_members m "
                "JOIN objects o ON o.object_pk = m.object_pk WHERE m.run_pk = ?",
                (run_pk,),
            )
        ]
        scope_digest = str(
            connection.execute(
                "SELECT analysis_scope_digest FROM runs WHERE run_pk = ?", (run_pk,)
            ).fetchone()[0]
        )
        membership = _membership_digest(object_ids)
        forged = _run_id(_NS, scope_digest, membership)
        connection.execute(
            "UPDATE runs SET membership_digest = ?, run_id = ? WHERE run_pk = ?",
            (membership, forged, run_pk),
        )
        connection.commit()
    with (
        RunStore(path) as store,
        pytest.raises(StoreIntegrityError, match="one record per analysis snapshot"),
    ):
        store.read_run(forged)


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


def test_receipt_counts_the_slice4_families(tmp_path: Path) -> None:
    """The wave-4 slice families ride the same receipt accounting."""
    model = fixture_model().normalize()
    with _store(tmp_path) as store:
        counts = _publish(store, model).family_counts
        assert counts["dependency_cycle"] == len(model.facts.analysis.dependency_cycles)
        assert counts["clone_group"] == len(model.facts.analysis.clone_groups)
        assert counts["dead_code_observation"] == len(
            model.facts.analysis.dead_code_observations
        )


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
        assert counts["dependency_relation"] == len(
            model.facts.analysis.dependency_relations
        )
        assert counts["dependency_occurrence"] == len(
            model.facts.analysis.dependency_occurrences
        )

        assert counts["violation"] == len(model.facts.analysis.violations)
        assert counts["coupling_cohesion_observation"] == len(
            model.facts.analysis.coupling_cohesion_observations
        )
        assert counts["api_symbol"] == len(model.facts.analysis.api_symbols)
        assert counts["run_scalar"] == 1  # F9: ONE record per snapshot
        assert counts["file"] == len(model.files)
        assert counts["module"] == len(model.modules)
        assert counts["analyzed_file"] == len(model.analyzed_files)
        assert counts["file_module"] == len(model.file_modules)
        assert counts["coupled_set"] == len(model.coupled_sets)
        assert receipt.object_count == sum(counts.values())


def test_two_analysis_population_records_in_one_run_are_refused(
    tmp_path: Path,
) -> None:
    """RULING-2026-08-31 §3 at the storage face: the execution-population
    record is a SINGLETON authority.  Same self-consistent forgery as the
    F9 twin — membership and run identity refit through the store's own
    formulas — so the one-record guard is the only wall left, and the
    refusal message must name THIS family, never its sibling."""
    from codeclone.canonical.store import (
        _membership_digest,
        _object_id,
        _payload_bytes,
        _run_id,
    )

    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        _publish(store, fixture_model())
    second = _payload_bytes(
        {
            "analysis_mode": "clones_only",
            "analysis_profile": [["min_loc", 6]],
            "producer_states": [["complexity", "not_executed"]],
        }
    )
    with sqlite3.connect(path) as connection:
        run_pk, namespace_pk = connection.execute(
            "SELECT run_pk, namespace_pk FROM runs"
        ).fetchone()
        cursor = connection.execute(
            "INSERT INTO objects (namespace_pk, object_id, family, payload) "
            "VALUES (?, ?, ?, ?)",
            (
                namespace_pk,
                _object_id(_NS, "analysis_population", second),
                "analysis_population",
                second,
            ),
        )
        connection.execute(
            "INSERT INTO run_members (run_pk, object_pk) VALUES (?, ?)",
            (run_pk, cursor.lastrowid),
        )
        object_ids = [
            str(row[0])
            for row in connection.execute(
                "SELECT o.object_id FROM run_members m "
                "JOIN objects o ON o.object_pk = m.object_pk WHERE m.run_pk = ?",
                (run_pk,),
            )
        ]
        scope_digest = str(
            connection.execute(
                "SELECT analysis_scope_digest FROM runs WHERE run_pk = ?", (run_pk,)
            ).fetchone()[0]
        )
        membership = _membership_digest(object_ids)
        forged = _run_id(_NS, scope_digest, membership)
        connection.execute(
            "UPDATE runs SET membership_digest = ?, run_id = ? WHERE run_pk = ?",
            (membership, forged, run_pk),
        )
        connection.commit()
    with (
        RunStore(path) as store,
        pytest.raises(
            StoreIntegrityError,
            match="more than one analysis_population record",
        ),
    ):
        store.read_run(forged)


# -- The typed family registry ----------------------------------------------

# Independent literal fixture (the ``test_canonical_grammar`` precedent):
# what each storage family's decoded row IS, spelled here by hand and never
# read back from the production registry.  A production entry that starts
# producing a different row type must red here; a family added to the
# registry without landing here must red here too.
_EXPECTED_ROW_TYPES: dict[str, type[object]] = {
    "adoption_count": AdoptionCountRow,
    "analysis_population": AnalysisPopulation,
    "analyzed_file": FileId,
    "api_symbol": ApiSymbolRow,
    "candidate": CandidateRow,
    "clone_group": CloneGroupRow,
    "contract": ContractRow,
    "coupled_set": frozenset,
    "coupling_cohesion_observation": CouplingCohesionRow,
    "dead_code_observation": DeadCodeObservationRow,
    "dependency_cycle": DependencyCycleRow,
    "dependency_occurrence": DependencyOccurrenceRow,
    "dependency_relation": DependencyRelationRow,
    "file": FileId,
    "file_module": FileModuleRelation,
    "graph_node": GraphNodeRow,
    "module": ModuleId,
    "risk_observation": RiskObservationRow,
    "run_scalar": RunScalars,
    "security_surface": SecuritySurfaceRow,
    "semantic_edge": SemanticEdge,
    "sink_role": SinkRoleRow,
    "violation": ViolationRow,
}

_STORE_SOURCE = _REPO_ROOT / "codeclone" / "canonical" / "store.py"


def _store_module_ast() -> ast.Module:
    return ast.parse(_STORE_SOURCE.read_text(encoding="utf-8"), filename="store.py")


def _named_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone from store.py")


def test_store_recovers_no_row_type_by_cast() -> None:
    """``cast`` is not a type: it is the project's declaration that our
    own annotation is weaker than the truth.  The row reader states each
    family's row type ONCE, in the registry entry, so nothing downstream
    has a type left to recover."""
    calls = sorted(
        node.lineno
        for node in ast.walk(_store_module_ast())
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "cast")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "cast")
        )
    )
    assert calls == [], f"store.py recovers row types by cast at lines {calls}"


def test_model_assembly_does_not_restate_the_family_table() -> None:
    """One place for ``family -> row type``: the assembler reads typed
    buckets and must not spell a storage family name at all.  A family
    name here is the second statement whose drift nothing catches."""
    assembler = _named_function(_store_module_ast(), "_collected_model")
    spelled = sorted(
        {
            node.value
            for node in ast.walk(assembler)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in _EXPECTED_ROW_TYPES
        }
    )
    assert spelled == [], f"_collected_model restates families {spelled}"


def test_every_family_decodes_to_its_declared_row_type() -> None:
    """The registry's two halves are one declaration: real fixture
    payloads go through the production reader, and what each family files
    must be the row type this test spells by hand."""
    from codeclone.canonical.store import _collect_row, _model_rows

    collected: dict[str, list[object]] = {}
    for family, row in _model_rows(fixture_model().normalize()):
        _collect_row(family, row, f"{family} object", collected)
    for family, expected in _EXPECTED_ROW_TYPES.items():
        rows = collected.get(family, [])
        assert rows, f"the distinguishing fixture produced no {family} row"
        assert {type(row) for row in rows} == {expected}, (
            f"family {family!r} decoded to the wrong row type"
        )


def test_family_dispatch_is_total_over_the_declared_families() -> None:
    """The family set is stated ONCE in production: the reader dispatch
    and the contract namespace map are both derived from the same
    declarations, so a family cannot exist for one and be missing for the
    other."""
    from codeclone.canonical.store import (
        _FAMILIES,
        _FAMILY_NAMESPACE,
        _FAMILY_READER,
    )

    assert {entry.family for entry in _FAMILIES} == set(_EXPECTED_ROW_TYPES)
    assert set(_FAMILY_READER) == set(_EXPECTED_ROW_TYPES)
    assert set(_FAMILY_NAMESPACE) == set(_EXPECTED_ROW_TYPES)


def test_unknown_stored_family_is_a_typed_refusal() -> None:
    """Totality is a refusal, never a silent skip — and the refusal has a
    reachable input: a stored family the registry does not know."""
    from codeclone.canonical.store import _collect_row

    with pytest.raises(StoreIntegrityError, match="unknown stored family"):
        _collect_row("not_a_family", {}, "probe", {})


def test_a_row_filed_under_the_wrong_family_is_refused() -> None:
    """What replaced the cast is a CHECK, not a second assertion: decoded
    rows wait in an untyped per-family mapping, and a caller that files a
    row under the wrong family gets a typed refusal instead of a silently
    wrong model."""
    from codeclone.canonical.store import _collected_model

    node = next(iter(fixture_model().normalize().facts.analysis.graph_nodes))
    with pytest.raises(StoreIntegrityError, match="carries a GraphNodeRow"):
        _collected_model({"contract": [node]})
