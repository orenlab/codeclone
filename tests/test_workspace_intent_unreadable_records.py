# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A registry row this build cannot parse is not a registry row to destroy.

``parse_workspace_document`` answers ``None`` for two situations that have
nothing in common: bytes no writer ever produced, and a document some *other*
writer produced whole and signed, carrying a field, a generation or a status
token this build has never heard of.  Removing the first is hygiene.  Removing
the second destroys live coordination state, and turns every
forward-compatibility mistake in this subsystem into silent, unrecoverable
data loss.

The discriminator is read off the persisted shape, not invented here: every
registry document carries ``integrity.payload_sha256`` over the canonical JSON
of itself minus that key, and :func:`verify_intent_integrity` recomputes it
from a raw mapping without consulting this build's model.  A document whose
digest verifies is one a writer produced whole; a document whose digest does
not verify is one no writer can be shown to have produced.

Both backends are exercised: the default is ``file``, and a guard proved only
against the default is blind to the half of the code sqlite runs.
"""

from __future__ import annotations

import ast
import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest

from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
from codeclone.surfaces.mcp._workspace_intent_contract import (
    WorkspaceIntentRecord,
    verify_intent_integrity,
)
from codeclone.surfaces.mcp._workspace_intent_models import parse_workspace_document
from codeclone.surfaces.mcp._workspace_intent_paths import (
    intent_filename,
    intent_path,
    registry_dir,
)
from codeclone.surfaces.mcp._workspace_intent_store import (
    FileWorkspaceIntentStore,
    SqliteWorkspaceIntentStore,
    clear_workspace_intent_store_cache,
    get_workspace_intent_store,
    lazy_close_eligible_records,
    lazy_close_eligible_records_unlocked,
    registry_transaction,
    write_workspace_intent_with_existing,
)
from codeclone.surfaces.mcp.messages import intent as intent_msgs
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests.test_workspace_intents import _record, _signed_payload_with

_STORE_MODULE = (
    Path(__file__).resolve().parent.parent
    / "codeclone"
    / "surfaces"
    / "mcp"
    / "_workspace_intent_store.py"
)

# Every lazy-close entry point in the store module. Pinned by name so a new
# reader that applies lazy close has to join the behavioural sweep below
# rather than quietly become a twelfth way to destroy a record.
_LAZY_CLOSE_ENTRY_POINTS = frozenset(
    {
        "_lazy_close_eligible_records_unlocked",
        "_gc_eligible_records_unlocked",
        "_close_eligible_records_unlocked",
    }
)


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(params=["file", "sqlite"])
def registry_root(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    monkeypatch.setenv("CODECLONE_INTENT_REGISTRY_BACKEND", str(request.param))
    monkeypatch.delenv("CODECLONE_INTENT_REGISTRY_PATH", raising=False)
    clear_workspace_intent_store_cache()
    try:
        yield tmp_path
    finally:
        clear_workspace_intent_store_cache()


# ── seeding and probing, straight at the storage layer ──────────────────────


def _seed_raw_payload(
    root: Path,
    *,
    record: WorkspaceIntentRecord,
    payload: dict[str, object],
) -> None:
    """Write ``payload`` as this record's stored bytes, bypassing the writer.

    The writer cannot express these documents -- that is the whole point -- so
    the row is planted the way another build would have left it.
    """

    store = get_workspace_intent_store(root)
    if isinstance(store, FileWorkspaceIntentStore):
        path = intent_path(
            root=root,
            pid=record.agent_pid,
            start_epoch=record.agent_start_epoch,
            intent_id=record.intent_id,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        return
    store._conn.execute(
        """
        INSERT INTO workspace_intents(
            agent_pid, agent_start_epoch, intent_id,
            declared_at_utc, payload_json, closed_at_utc, updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.agent_pid,
            record.agent_start_epoch,
            record.intent_id,
            record.declared_at_utc,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            None,
            record.declared_at_utc,
        ),
    )
    store._conn.commit()


def _stored_intent_ids(root: Path) -> tuple[str, ...]:
    """Intent ids physically present in storage, read from the storage key.

    Never from the document: a document this build cannot parse would answer
    nothing, and "the row is gone" would be indistinguishable from "the row is
    unreadable" -- which is exactly the conflation under test.
    """

    store = get_workspace_intent_store(root)
    if isinstance(store, FileWorkspaceIntentStore):
        return tuple(
            sorted(
                path.name.removesuffix(".json").split("-", 2)[2]
                for path in registry_dir(root).glob("*.json")
            )
        )
    return tuple(sorted(row[2] for row in store.iter_rows()))


def _newer_build_payload(record: WorkspaceIntentRecord) -> dict[str, object]:
    """What a build one generation ahead of this one leaves behind.

    An unknown key, signed over.  ``extra="forbid"`` refuses the document and
    the integrity witness still proves a writer produced exactly these bytes.
    """

    return _signed_payload_with(record, queue_lane="fast")


def _corrupt_payload(record: WorkspaceIntentRecord) -> dict[str, object]:
    """Bytes attributable to no writer: a value edited under a stale digest."""

    payload = dict(_signed_payload_with(record))
    payload["intent"] = "edited after signing"
    return payload


# ── the persisted shape actually separates the two situations ───────────────


def test_the_unreadable_vocabulary_has_one_spelling() -> None:
    """One closed enum, and every table that reports it is keyed off it.

    The vocabulary used to be a ``Literal`` alias plus two module constants
    that had to agree by hand.  It is now one owned enum -- but the message
    tables live in a leaf module that may not import the ring the enum lives
    in, so their keys are literal strings.  That is the drift this pins: a
    renamed member has to break here, not in an operator's next_step.
    """

    kinds = workspace_intents.WorkspaceDocumentReadKind
    assert {kind.value for kind in kinds} == {
        "record",
        "absent",
        "registry_record_corrupt",
        "registry_record_unreadable_by_this_build",
    }
    assert set(intent_msgs.UNREADABLE_REGISTRY_RECORD_MESSAGES) == {
        kinds.INCOMPATIBLE.value
    }
    assert set(intent_msgs.UNREADABLE_REGISTRY_RECORD_NEXT_STEPS) == {
        kinds.INCOMPATIBLE.value
    }


def test_the_persisted_integrity_witness_separates_the_two_situations() -> None:
    record = _record()
    newer = _newer_build_payload(record)
    corrupt = _corrupt_payload(record)

    # Neither is modellable by this build...
    assert parse_workspace_document(newer) is None
    assert parse_workspace_document(corrupt) is None
    # ...and the persisted witness tells them apart anyway.
    assert verify_intent_integrity(newer) is True
    assert verify_intent_integrity(corrupt) is False


# ── half one: the reader must not destroy what it cannot read ───────────────


def test_authentic_record_from_a_newer_build_survives_a_read(
    registry_root: Path,
) -> None:
    record = _record(intent_id="intent-newer-001")
    _seed_raw_payload(
        registry_root,
        record=record,
        payload=_newer_build_payload(record),
    )
    assert _stored_intent_ids(registry_root) == ("intent-newer-001",)

    workspace_intents.list_workspace_intents(root=registry_root)

    assert _stored_intent_ids(registry_root) == ("intent-newer-001",)


def test_corrupt_record_is_still_removed_by_a_read(registry_root: Path) -> None:
    """The opposite boundary: a reader that never cleans up is not the fix."""

    record = _record(intent_id="intent-corrupt-001")
    _seed_raw_payload(
        registry_root,
        record=record,
        payload=_corrupt_payload(record),
    )
    assert _stored_intent_ids(registry_root) == ("intent-corrupt-001",)

    workspace_intents.list_workspace_intents(root=registry_root)

    assert _stored_intent_ids(registry_root) == ()


# ── coverage: every reader that applies lazy close, not just the one ────────


def _lazy_close_readers() -> dict[str, Callable[[Path], object]]:
    """One callable per store-module function that applies lazy close."""

    def _store_call(name: str) -> Callable[[Path], object]:
        def run(root: Path) -> object:
            store = get_workspace_intent_store(root)
            return getattr(store, name)()

        return run

    def _find(root: Path) -> object:
        return get_workspace_intent_store(root).find("intent-newer-001")

    def _find_current_unlocked(root: Path) -> object:
        store = get_workspace_intent_store(root)
        with registry_transaction(store):
            return store.find_current_unlocked("intent-newer-001")

    def _write_with_existing(root: Path) -> object:
        return write_workspace_intent_with_existing(
            root=root,
            record=_record(intent_id="intent-other-002"),
        )

    def _lazy_close_public(root: Path) -> object:
        return lazy_close_eligible_records(get_workspace_intent_store(root))

    def _lazy_close_public_unlocked(root: Path) -> object:
        store = get_workspace_intent_store(root)
        with registry_transaction(store):
            return lazy_close_eligible_records_unlocked(store)

    return {
        "list_records": _store_call("list_records"),
        "list_records_current": _store_call("list_records_current"),
        "find": _find,
        "find_current_unlocked": _find_current_unlocked,
        "gc": _store_call("gc"),
        "write_workspace_intent_with_existing": _write_with_existing,
        "lazy_close_eligible_records": _lazy_close_public,
        "lazy_close_eligible_records_unlocked": _lazy_close_public_unlocked,
    }


@pytest.mark.parametrize("reader_name", sorted(_lazy_close_readers()))
def test_every_lazy_close_reader_leaves_the_unreadable_record_alone(
    registry_root: Path,
    reader_name: str,
) -> None:
    record = _record(intent_id="intent-newer-001")
    _seed_raw_payload(
        registry_root,
        record=record,
        payload=_newer_build_payload(record),
    )

    _lazy_close_readers()[reader_name](registry_root)

    assert "intent-newer-001" in _stored_intent_ids(registry_root)


@pytest.mark.parametrize("reader_name", sorted(_lazy_close_readers()))
def test_every_lazy_close_reader_still_removes_the_corrupt_record(
    registry_root: Path,
    reader_name: str,
) -> None:
    record = _record(intent_id="intent-corrupt-001")
    _seed_raw_payload(
        registry_root,
        record=record,
        payload=_corrupt_payload(record),
    )

    _lazy_close_readers()[reader_name](registry_root)

    assert "intent-corrupt-001" not in _stored_intent_ids(registry_root)


def test_the_behavioural_sweep_accounts_for_every_lazy_close_call_site() -> None:
    """Reconcile the sweep against the module, not against memory.

    A guard proved at one call site is blind by construction.  This counts the
    functions in the store module that reach a lazy-close entry point and
    fails when one of them is not represented above.
    """

    tree = ast.parse(_STORE_MODULE.read_text(encoding="utf-8"))
    callers: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id in _LAZY_CLOSE_ENTRY_POINTS
            ):
                callers.add(node.name)

    # The two dispatchers are the funnel itself, not readers of it.
    dispatchers = {
        "_lazy_close_eligible_records_unlocked",
        "_gc_eligible_records_unlocked",
    }
    assert callers >= dispatchers
    exercised = set(_lazy_close_readers())
    unaccounted = callers - dispatchers - exercised
    assert unaccounted == set(), (
        f"lazy-close readers with no survival probe: {sorted(unaccounted)}"
    )


def test_the_removal_decision_has_exactly_one_owner() -> None:
    """``remove_corrupted`` is invoked from one place, so one guard suffices."""

    tree = ast.parse(_STORE_MODULE.read_text(encoding="utf-8"))
    invokers = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for inner in ast.walk(node)
        if isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Name)
        and inner.func.id == "remove_corrupted"
    }
    assert invokers == {"_lazy_close_from_entries"}


def test_the_storage_key_inverse_round_trips_and_refuses() -> None:
    """Every branch of the key inverse, including the ones that say no."""

    for intent_id in ("intent-e5-006", "a", "x-y-z"):
        name = intent_filename(pid=123, start_epoch=456, intent_id=intent_id)
        assert workspace_intents.intent_id_from_filename(name) == intent_id

    # Not a registry filename at all: without this guard the split below would
    # happily read an id out of a name that never was one.
    assert workspace_intents.intent_id_from_filename("123-456-intent") is None
    # A key whose first two fields are not the integers the writer puts there.
    assert workspace_intents.intent_id_from_filename("a-b-c.json") is None
    assert workspace_intents.intent_id_from_filename("nope.json") is None
    # A traversal spelling never becomes an id.
    assert workspace_intents.intent_id_from_filename("1-2-../escape.json") is None


def test_a_row_whose_key_cannot_be_parsed_is_still_not_destroyed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reachability of the key-inverse refusal through the real read path.

    ``registry_files`` admits any ``*.json`` with two hyphens, so a name whose
    pid field is not numeric does reach the inverse and does get refused. The
    row is still kept -- it is signed -- it simply cannot be named.
    """

    monkeypatch.setenv("CODECLONE_INTENT_REGISTRY_BACKEND", "file")
    clear_workspace_intent_store_cache()
    record = _record(intent_id="intent-unkeyed-001")
    directory = registry_dir(tmp_path)
    directory.mkdir(parents=True, exist_ok=True)
    planted = directory / "a-b-intent-unkeyed-001.json"
    planted.write_text(
        json.dumps(_newer_build_payload(record), sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = lazy_close_eligible_records(get_workspace_intent_store(tmp_path))

    assert planted.exists()
    assert result.unreadable_retained == ("a-b-intent-unkeyed-001.json",)
    assert result.unreadable_retained_intent_ids == ()
    clear_workspace_intent_store_cache()


# ── half two: the refusal names the real cause ──────────────────────────────


def test_recover_names_the_unreadable_record_instead_of_not_found(
    registry_root: Path,
) -> None:
    record = _record(intent_id="intent-newer-001", pid=os.getpid())
    _seed_raw_payload(
        registry_root,
        record=record,
        payload=_newer_build_payload(record),
    )
    service = CodeCloneMCPService(history_limit=2)

    rejected = service.manage_change_intent(
        action="recover",
        root=str(registry_root),
        run_id="abcdef12",
        intent_id="intent-newer-001",
    )

    assert rejected["action_taken"] == "recovery_rejected"
    assert rejected["reason"] == "registry_record_unreadable_by_this_build"
    next_step = str(rejected["next_step"])
    assert next_step
    # In-band: the step names a call the operator can actually make.
    assert "manage_change_intent" in next_step
    # And it must not pretend the record was never there.
    assert "No workspace intent found" not in str(rejected["message"])


def test_recover_still_says_not_found_when_nothing_is_stored(
    registry_root: Path,
) -> None:
    """The positive control's opposite: absence must keep answering absence."""

    service = CodeCloneMCPService(history_limit=2)

    rejected = service.manage_change_intent(
        action="recover",
        root=str(registry_root),
        run_id="abcdef12",
        intent_id="intent-absent-001",
    )

    assert rejected["reason"] == "not_found"


def test_the_unreadable_reason_table_is_closed() -> None:
    """Subscript, never ``.get``: an invented reason fails at the raise."""

    reason = "registry_record_unreadable_by_this_build"
    assert intent_msgs.unreadable_registry_record_message(reason)
    assert intent_msgs.unreadable_registry_record_next_step(reason)

    with pytest.raises(KeyError):
        intent_msgs.unreadable_registry_record_next_step("not_a_real_reason")
    with pytest.raises(KeyError):
        intent_msgs.unreadable_registry_record_message("not_a_real_reason")


def test_the_gc_fragment_reports_what_it_retained(registry_root: Path) -> None:
    record = _record(intent_id="intent-newer-001")
    _seed_raw_payload(
        registry_root,
        record=record,
        payload=_newer_build_payload(record),
    )

    fragment = get_workspace_intent_store(registry_root).gc()

    assert fragment["corrupted_removed"] == 0
    assert fragment["unreadable_retained"] == 1
    retained = cast("list[str]", fragment["unreadable_retained_intent_ids"])
    assert retained == ["intent-newer-001"]


def test_sqlite_and_file_stores_are_both_reached_by_this_module(
    registry_root: Path,
) -> None:
    """Population check: the parametrisation really produces two backends."""

    store = get_workspace_intent_store(registry_root)
    assert isinstance(store, FileWorkspaceIntentStore | SqliteWorkspaceIntentStore)
