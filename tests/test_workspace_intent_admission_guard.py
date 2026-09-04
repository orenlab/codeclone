# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Unknown scope is not absent conflict.

Two laws, pinned together because the second is only expressible once the
first holds.

**One owner for the read outcome.** Reading one stored registry payload has
more than one non-record answer, so the answer is a declared, tagged type with
one owner -- :class:`codeclone.workspace_intent.contract.WorkspaceDocumentRead`
-- and not a record-or-sentinel union discriminated by ``isinstance``. The
owner is the module that already owns both discriminated things: the record
and the ``integrity.payload_sha256`` witness that decides between damage and
unfamiliarity.

**Fail closed on write authority.** An integrity-valid persisted intent that
this build cannot interpret must never become indistinguishable from no
intent. The row is positive evidence that another writer holds coordination
state here; its scope is unknown, and unknown scope is not absent conflict.
Granting or widening write authority over such a registry is refused. Reading
it, listing it, and releasing authority already held are not.

Both backends are exercised. The library default is ``file`` and this
repository is configured ``sqlite``; a guard proved against one is blind to
the half the other runs.
"""

from __future__ import annotations

import ast
import json
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest

from codeclone.surfaces.mcp.messages import intent as intent_msgs
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests.test_mcp_service import _PID_ALIVE, _patch_contract_run_record
from tests.test_workspace_intent_unreadable_records import (
    _newer_build_payload,
    _seed_raw_payload,
    _stored_intent_ids,
    registry_root,  # noqa: F401  (fixture: both registry backends)
)
from tests.test_workspace_intents import _record

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CODECLONE = _REPO_ROOT / "codeclone"
_CONTRACT_MODULE = _CODECLONE / "workspace_intent" / "contract.py"
_MODELS_MODULE = _CODECLONE / "workspace_intent" / "models.py"
_STORE_MODULE = _CODECLONE / "surfaces" / "mcp" / "_workspace_intent_store.py"
_MIXIN_MODULE = _CODECLONE / "surfaces" / "mcp" / "_session_intent_mixin.py"

#: The one function whose answer distributes write authority over a registry.
#: Every caller of it must first ask whether this build may speak for the
#: registry at all.
_AUTHORITY_ORACLE = "detect_conflicts"

#: The name of that question. Pinned so the reconciliation below cannot be
#: satisfied by a differently-named lookalike.
_ADMISSION_GUARD = "workspace_admission_refusal"

_FOREIGN_PID = 99999
_FOREIGN_START_EPOCH = 1000000
_FOREIGN_INTENT_ID = "intent-foreign-001"
_RUN_ID = "admission1234567"


# ── harness ─────────────────────────────────────────────────────────────────


def _service_with_run(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> CodeCloneMCPService:
    monkeypatch.setattr(_PID_ALIVE, lambda pid: True)
    service = CodeCloneMCPService(history_limit=4)
    service._runs.register(
        _patch_contract_run_record(
            root,
            run_id=_RUN_ID,
            digest="admission-digest",
            include_regression=False,
            complexity=6,
            health=90,
        )
    )
    return service


def _seed_foreign_unreadable_row(root: Path) -> None:
    """A row another build wrote whole, signed, and this build cannot model."""

    record = _record(
        intent_id=_FOREIGN_INTENT_ID,
        pid=_FOREIGN_PID,
        start_epoch=_FOREIGN_START_EPOCH,
    )
    _seed_raw_payload(root, record=record, payload=_newer_build_payload(record))


def _remove_stored_rows(root: Path) -> None:
    """Delete the planted row the way an operator would, outside the reader."""

    from codeclone.surfaces.mcp._workspace_intent_paths import registry_dir
    from codeclone.surfaces.mcp._workspace_intent_store import (
        FileWorkspaceIntentStore,
        get_workspace_intent_store,
    )

    store = get_workspace_intent_store(root)
    if isinstance(store, FileWorkspaceIntentStore):
        for path in registry_dir(root).glob("*.json"):
            path.unlink()
        return
    store._conn.execute("DELETE FROM workspace_intents")
    store._conn.commit()


def _declare(service: CodeCloneMCPService, root: Path) -> dict[str, object]:
    return service.manage_change_intent(
        action="declare",
        run_id=_RUN_ID,
        root=str(root),
        scope={"allowed_files": ["pkg/b.py"]},
        intent="edit pkg/b",
    )


def _module_functions(path: Path) -> dict[str, ast.AST]:
    tree = ast.parse(path.read_text("utf-8"))
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


# ══ law one: the read outcome is a declared type with one owner ═════════════


def test_the_read_outcome_type_has_exactly_one_owner() -> None:
    """One named definition, in the module the dependency graph chose.

    The rejected shape was ``WorkspaceIntentRecord | UnreadableReason`` -- an
    existing type plus an ad-hoc sentinel, discriminated by the structural
    coincidence that a record is never a string. A census, so a second owner
    or a re-introduced alias fails here rather than at the next reader.
    """

    definitions: list[str] = []
    aliases: list[str] = []
    for path in sorted(_CODECLONE.rglob("*.py")):
        tree = ast.parse(path.read_text("utf-8"))
        module = str(path.relative_to(_REPO_ROOT))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "WorkspaceDocumentRead":
                definitions.append(module)
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            aliases.extend(
                module
                for target in targets
                if isinstance(target, ast.Name) and target.id == "WorkspaceDocumentRead"
            )

    assert definitions == ["codeclone/workspace_intent/contract.py"]
    assert aliases == []


def test_the_read_outcome_carries_a_declared_tag() -> None:
    """Every arm answers ``kind`` from a closed vocabulary, not by its shape."""

    from codeclone.surfaces.mcp._workspace_intents import (
        WorkspaceDocumentRead,
        WorkspaceDocumentReadKind,
    )

    record = _record()
    arms = (
        WorkspaceDocumentRead.of_record(record),
        WorkspaceDocumentRead(WorkspaceDocumentReadKind.ABSENT),
        WorkspaceDocumentRead(WorkspaceDocumentReadKind.CORRUPT),
        WorkspaceDocumentRead(WorkspaceDocumentReadKind.INCOMPATIBLE),
    )

    assert {arm.kind for arm in arms} == set(WorkspaceDocumentReadKind)
    assert WorkspaceDocumentRead.of_record(record).record is record
    assert all(
        arm.record is None
        for arm in arms
        if arm.kind is not WorkspaceDocumentReadKind.RECORD
    )


def test_the_record_arm_has_one_constructor() -> None:
    """The one arm that can break the invariant has one place that builds it.

    Three arms carry no record and hold the invariant by construction; the
    fourth must pair a tag with a payload, so it goes through ``of_record``
    and no production module assembles it by hand.
    """

    handmade: list[str] = []
    for path in sorted(_CODECLONE.rglob("*.py")):
        handmade.extend(
            f"{path.relative_to(_REPO_ROOT)}:{node.lineno}"
            for node in ast.walk(ast.parse(path.read_text("utf-8")))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "WorkspaceDocumentRead"
            and "RECORD" in ast.unparse(node)
        )

    assert handmade == []


def test_no_reader_discriminates_the_read_outcome_by_structure() -> None:
    """``isinstance(read, WorkspaceIntentRecord)`` is the rejected model.

    A structural test rather than a behavioural one on purpose: the union
    behaved correctly on the day it was written. What it could not do was
    survive a fourth state, and that failure has no runtime symptom until the
    fourth state exists.
    """

    store_source = _STORE_MODULE.read_text("utf-8")
    offending = [
        ast.unparse(node)
        for node in ast.walk(ast.parse(store_source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isinstance"
        and "WorkspaceIntentRecord" in ast.unparse(node)
    ]
    assert offending == []
    # And the sentinel spellings are gone from the reader entirely.
    assert "UNREADABLE_BY_THIS_BUILD" not in store_source
    assert "UnreadableReason" not in _MODELS_MODULE.read_text("utf-8")


def test_the_scanned_row_is_a_named_structure_not_a_bare_tuple() -> None:
    """The same defect, second instance: ``_RegistryEntry = tuple[...]``.

    It never crosses a ring boundary, so its owner is trivially the module
    that produces and consumes it -- but it is still a domain state with
    fields, and positional unpacking is not a declaration.
    """

    source = _STORE_MODULE.read_text("utf-8")
    tree = ast.parse(source)
    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert "ScannedRegistryRow" in classes
    assert "_RegistryEntry" not in source


@pytest.mark.parametrize("kind_name", ["RECORD", "CORRUPT", "INCOMPATIBLE"])
def test_every_scannable_kind_reaches_a_removal_decision(kind_name: str) -> None:
    """The reader's dispatch is exhaustive over what a scan can hand it."""

    from codeclone.surfaces.mcp._workspace_intent_store import (
        ScannedRegistryRow,
        _lazy_close_from_entries,
    )
    from codeclone.surfaces.mcp._workspace_intents import (
        WorkspaceDocumentRead,
        WorkspaceDocumentReadKind,
    )

    kind = WorkspaceDocumentReadKind[kind_name]
    stale = _record(
        intent_id="intent-stale-001",
        expires_delta=-timedelta(hours=2),
        lease_renewed_delta=-timedelta(hours=2),
    )
    read = (
        WorkspaceDocumentRead.of_record(stale)
        if kind is WorkspaceDocumentReadKind.RECORD
        else WorkspaceDocumentRead(kind=kind, record=None)
    )

    result = _lazy_close_from_entries(
        (ScannedRegistryRow("key", "intent-x", read),),
        for_lazy_close=True,
        remove_corrupted=lambda key: True,
        close_active=lambda record, reason: True,
    )

    observed = {
        WorkspaceDocumentReadKind.RECORD: result.closed_ids,
        WorkspaceDocumentReadKind.CORRUPT: result.corrupted_removed,
        WorkspaceDocumentReadKind.INCOMPATIBLE: result.unreadable_retained,
    }
    expected = {
        WorkspaceDocumentReadKind.RECORD: (stale.intent_id,),
        WorkspaceDocumentReadKind.CORRUPT: ("key",),
        WorkspaceDocumentReadKind.INCOMPATIBLE: ("key",),
    }

    assert observed[kind] == expected[kind]
    # Exactly one lane fired: a dispatch that both removed and retained a row
    # would satisfy the line above and still be wrong.
    assert [lane for lane, value in observed.items() if value] == [kind]


def test_the_removal_decision_refuses_a_kind_it_has_no_rule_for() -> None:
    """Probe validity: the fallback is reachable, not decoration.

    ``ABSENT`` is real in the vocabulary and is produced by the lookup, never
    by a storage scan. Feeding it here proves the branch that would catch a
    future fifth state actually fires, instead of the whole guarantee resting
    on a case nothing can enter.
    """

    from codeclone.surfaces.mcp._workspace_intent_store import (
        ScannedRegistryRow,
        _lazy_close_from_entries,
    )
    from codeclone.surfaces.mcp._workspace_intents import (
        WorkspaceDocumentRead,
        WorkspaceDocumentReadKind,
    )

    with pytest.raises(ValueError, match="read kind"):
        _lazy_close_from_entries(
            (
                ScannedRegistryRow(
                    "key",
                    "intent-x",
                    WorkspaceDocumentRead(WorkspaceDocumentReadKind.ABSENT),
                ),
            ),
            for_lazy_close=True,
            remove_corrupted=lambda key: True,
            close_active=lambda record, reason: True,
        )


def test_the_lookup_answers_all_three_of_its_states(
    registry_root: Path,  # noqa: F811
) -> None:
    """Absent, unreadable and found are three answers from one typed call."""

    from codeclone.surfaces.mcp._workspace_intents import (
        WorkspaceDocumentReadKind,
        read_workspace_intent,
        write_workspace_intent,
    )

    absent = read_workspace_intent(root=registry_root, intent_id="intent-nothing")
    assert absent.kind is WorkspaceDocumentReadKind.ABSENT

    _seed_foreign_unreadable_row(registry_root)
    unreadable = read_workspace_intent(root=registry_root, intent_id=_FOREIGN_INTENT_ID)
    assert unreadable.kind is WorkspaceDocumentReadKind.INCOMPATIBLE

    own = _record(intent_id="intent-own-001")
    write_workspace_intent(root=registry_root, record=own)
    found = read_workspace_intent(root=registry_root, intent_id="intent-own-001")
    assert found.kind is WorkspaceDocumentReadKind.RECORD
    assert found.record is not None
    assert found.record.intent_id == "intent-own-001"


# ══ law two: unknown scope is not absent conflict ═══════════════════════════


def test_declare_refuses_and_then_proceeds_when_the_row_is_gone(
    registry_root: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The causal positive-control pair, in one test so it cannot drift apart.

    signed foreign/unknown intent on disk  ->  an ordinary start MUST refuse
    remove that row                        ->  the same start MAY proceed

    Same service, same run, same scope, same call. The only variable is the
    row, which is what makes this evidence about the admission guard rather
    than about some neighbouring refusal.
    """

    _seed_foreign_unreadable_row(registry_root)
    service = _service_with_run(registry_root, monkeypatch)

    refused = _declare(service, registry_root)

    assert refused["status"] == "blocked"
    assert refused["reason"] == intent_msgs.WORKSPACE_INTENT_INCOMPATIBLE
    assert refused["edit_allowed"] is False
    assert refused["unreadable_workspace_intent_ids"] == [_FOREIGN_INTENT_ID]
    assert "manage_change_intent" in str(refused["next_step"])
    # Refusing must not invent scope semantics for a document it cannot read.
    assert "scope" not in refused
    # And it must not have written an intent on the way to refusing.
    assert _stored_intent_ids(registry_root) == (_FOREIGN_INTENT_ID,)

    _remove_stored_rows(registry_root)

    admitted = _declare(service, registry_root)

    assert admitted["status"] == "active"
    assert admitted["edit_allowed"] is True


def test_start_controlled_change_refuses_over_an_unreadable_row(
    registry_root: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The headline case, through the workflow tool an agent actually calls.

    ``start_controlled_change`` reaches declare through a different door than
    ``manage_change_intent(action='declare')`` and owns its own response
    shaping, so proving the refusal on one says nothing about the other.
    """

    _seed_foreign_unreadable_row(registry_root)
    service = _service_with_run(registry_root, monkeypatch)

    refused = service.start_controlled_change(
        root=str(registry_root),
        scope={"allowed_files": ["pkg/b.py"]},
        intent="edit pkg/b",
    )

    assert refused["status"] == "blocked"
    assert refused["reason"] == intent_msgs.WORKSPACE_INTENT_INCOMPATIBLE
    assert refused["edit_allowed"] is False
    assert refused["unreadable_workspace_intent_ids"] == [_FOREIGN_INTENT_ID]
    assert _stored_intent_ids(registry_root) == (_FOREIGN_INTENT_ID,)


def test_promote_refuses_while_an_unreadable_row_is_stored(
    registry_root: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Promotion grants edit authority too, so it asks the same question."""

    service = _service_with_run(registry_root, monkeypatch)
    blocker = _record(
        intent_id="intent-blocker-001",
        pid=_FOREIGN_PID,
        start_epoch=_FOREIGN_START_EPOCH,
        scope={"allowed_files": ["pkg/b.py"], "allowed_related": [], "forbidden": []},
    )
    from codeclone.surfaces.mcp._workspace_intents import write_workspace_intent

    write_workspace_intent(root=registry_root, record=blocker)
    queued = service.manage_change_intent(
        action="declare",
        run_id=_RUN_ID,
        root=str(registry_root),
        scope={"allowed_files": ["pkg/b.py"]},
        intent="edit pkg/b",
        on_conflict="queue",
    )
    assert queued["status"] == "queued"
    _remove_stored_rows(registry_root)
    _seed_foreign_unreadable_row(registry_root)

    refused = service.manage_change_intent(
        action="promote",
        intent_id=str(queued["intent_id"]),
    )

    assert refused["reason"] == intent_msgs.WORKSPACE_INTENT_INCOMPATIBLE
    assert refused["edit_allowed"] is False


def test_the_admission_reason_table_is_closed() -> None:
    """Subscript, never ``.get``: an invented reason fails at the raise."""

    reason = intent_msgs.WORKSPACE_INTENT_INCOMPATIBLE
    assert intent_msgs.workspace_admission_message(reason)
    assert intent_msgs.workspace_admission_next_step(reason)

    with pytest.raises(KeyError):
        intent_msgs.workspace_admission_message("not_a_real_reason")
    with pytest.raises(KeyError):
        intent_msgs.workspace_admission_next_step("not_a_real_reason")


def test_listing_names_the_unreadable_row(
    registry_root: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registry must not become a brick: inspection still answers."""

    _seed_foreign_unreadable_row(registry_root)
    service = _service_with_run(registry_root, monkeypatch)

    listed = service.manage_change_intent(
        action="list_workspace",
        root=str(registry_root),
    )

    assert listed["unreadable_workspace_intent_ids"] == [_FOREIGN_INTENT_ID]
    assert listed["workspace_intents"] == []


def test_reading_and_releasing_own_authority_stay_allowed(
    registry_root: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opposite boundary: a guard that blocks these is over-reaching.

    Authority already held may be inspected and released; a registry with an
    unreadable row must not strand the agent that is trying to leave it.
    """

    service = _service_with_run(registry_root, monkeypatch)
    declared = _declare(service, registry_root)
    assert declared["status"] == "active"
    intent_id = str(declared["intent_id"])

    _seed_foreign_unreadable_row(registry_root)

    got = service.manage_change_intent(action="get", intent_id=intent_id)
    assert got["intent_id"] == intent_id

    checked = service.manage_change_intent(
        action="check",
        intent_id=intent_id,
        changed_files=["pkg/b.py"],
    )
    assert checked["intent_id"] == intent_id

    listed = service.manage_change_intent(
        action="list_workspace", root=str(registry_root)
    )
    assert listed["unreadable_workspace_intent_ids"] == [_FOREIGN_INTENT_ID]

    collected = service.manage_change_intent(
        action="gc_workspace", root=str(registry_root)
    )
    assert collected["unreadable_retained"] == 1

    cleared = service.manage_change_intent(action="clear", intent_id=intent_id)
    assert cleared["cleared_intent_ids"] == [intent_id]
    # Releasing must not have taken the foreign row with it.
    assert _FOREIGN_INTENT_ID in _stored_intent_ids(registry_root)


def test_every_write_authority_entry_point_consults_the_admission_guard() -> None:
    """Coverage, reconciled against an AST inventory rather than asserted.

    ``detect_conflicts`` is the single oracle whose answer decides whether an
    agent may edit. Its callers are the complete population of places this
    build grants or widens write authority, so every one of them must first
    ask whether this build may speak for the registry at all.
    """

    functions = _module_functions(_MIXIN_MODULE)
    granting = sorted(
        name
        for name, node in functions.items()
        if _AUTHORITY_ORACLE in _called_names(node)
    )

    assert granting == ["_declare_change_intent", "_promote_queued_intent"]
    unguarded = [
        name
        for name in granting
        if _ADMISSION_GUARD not in _called_names(functions[name])
    ]
    assert unguarded == []

    # The oracle has no other production caller anywhere, so the two above are
    # the whole population and not merely the ones this module happens to hold.
    callers = sorted(
        str(path.relative_to(_REPO_ROOT))
        for path in _CODECLONE.rglob("*.py")
        if _AUTHORITY_ORACLE in _called_names(ast.parse(path.read_text("utf-8")))
    )
    assert callers == ["codeclone/surfaces/mcp/_session_intent_mixin.py"]


def test_the_guard_reads_the_registry_it_is_asked_about(
    registry_root: Path,  # noqa: F811
) -> None:
    """Population check: the planted row really is integrity-valid here.

    Without it a refusal could come from bytes no writer signed -- the
    corruption path -- and the evidence would be about the wrong mechanism.
    """

    from codeclone.surfaces.mcp._workspace_intent_contract import (
        verify_intent_integrity,
    )
    from codeclone.surfaces.mcp._workspace_intent_models import (
        parse_workspace_document,
    )

    record = _record(
        intent_id=_FOREIGN_INTENT_ID,
        pid=_FOREIGN_PID,
        start_epoch=_FOREIGN_START_EPOCH,
    )
    payload = cast(
        "dict[str, object]",
        json.loads(json.dumps(_newer_build_payload(record), sort_keys=True)),
    )

    assert verify_intent_integrity(payload) is True
    assert parse_workspace_document(payload) is None
