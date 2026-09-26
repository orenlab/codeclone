# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A registry this process cannot read is unknown, never empty.

Three measured ways the workspace intent registry turned "I could not read
it" into "there is nothing there":

* **file backend (the default).** An intent file the process may not open --
  another user's ``0600`` file, ``EIO``, ``EMFILE`` -- was classified exactly
  like damaged bytes and unlinked by the next lazy close. A live agent's
  intent vanished and its scope stopped being protected.
* **sqlite backend.** Every read swallowed ``sqlite3.Error`` into ``()``. A
  damaged registry read as an empty one, conflict detection saw nobody, and
  ``start_controlled_change`` answered ``edit_allowed: true``.
* **configuration.** The documented ``CODECLONE_INTENT_REGISTRY_RETENTION_DAYS``
  override is text, and the resolver accepted only ``int`` -- so setting it
  disabled the whole registry, and change control with it.

Bytes that were read and are not a JSON object stay damaged bytes: that
policy is unchanged and pinned here as the opposite boundary.

The per-file classification is pinned in the ring that owns it
(``test_workspace_intent_registry_file_read``) and the env parse in
``test_intent_registry_retention_env``; this module pins what the store and
the MCP surface do with the answers.
"""

from __future__ import annotations

import errno
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from codeclone.surfaces.mcp import _workspace_intent_paths as intent_paths
from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
from codeclone.surfaces.mcp._workspace_intent_contract import WorkspaceIntentRecord
from codeclone.surfaces.mcp._workspace_intent_store import (
    FileWorkspaceIntentStore,
    clear_workspace_intent_store_cache,
    get_workspace_intent_store,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests.test_workspace_intent_admission_guard import _RUN_ID, _service_with_run
from tests.test_workspace_intents import _record

_FOREIGN_PID = 99999
_FOREIGN_START_EPOCH = 1000000
_REGISTRY_UNREADABLE = "registry_unreadable"
_RETENTION_ENV = "CODECLONE_INTENT_REGISTRY_RETENTION_DAYS"


def _running_as_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


_needs_permission_bits = pytest.mark.skipif(
    _running_as_root() or not hasattr(os, "chmod"),
    reason="permission bits do not deny reads to root",
)


# ── fixtures ────────────────────────────────────────────────────────────────


def _registry_root(
    backend: str,
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    monkeypatch.setenv("CODECLONE_INTENT_REGISTRY_BACKEND", backend)
    monkeypatch.delenv("CODECLONE_INTENT_REGISTRY_PATH", raising=False)
    monkeypatch.delenv(_RETENTION_ENV, raising=False)
    clear_workspace_intent_store_cache()
    try:
        yield root
    finally:
        clear_workspace_intent_store_cache()


@pytest.fixture
def file_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    yield from _registry_root("file", tmp_path, monkeypatch)


def _foreign_record(intent_id: str = "intent-foreign-001") -> WorkspaceIntentRecord:
    return _record(
        intent_id=intent_id,
        pid=_FOREIGN_PID,
        start_epoch=_FOREIGN_START_EPOCH,
    )


def _intent_file(root: Path, record: WorkspaceIntentRecord) -> Path:
    return intent_paths.intent_path(
        root=root,
        pid=record.agent_pid,
        start_epoch=record.agent_start_epoch,
        intent_id=record.intent_id,
    )


class _Unreadable:
    """chmod 0 on one registry file, undone however the test exits."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> Path:
        os.chmod(self.path, 0)
        return self.path

    def __exit__(self, *exc: object) -> None:
        if self.path.exists():
            os.chmod(self.path, 0o600)


def _fail_open_for(
    monkeypatch: pytest.MonkeyPatch,
    target: Path,
    exc: OSError,
) -> None:
    """Make the real ``open`` of one registry file fail, and nothing else.

    Patched at ``Path.open`` -- the call the bounded reader actually makes --
    so the error rises through the production read chain rather than from a
    stand-in reader the store would never call.
    """

    real_open = Path.open

    def flaky_open(self: Path, *args: object, **kwargs: object) -> object:
        if self.name == target.name:
            raise exc
        return real_open(self, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(Path, "open", flaky_open)


def _declare(service: CodeCloneMCPService, root: Path) -> dict[str, object]:
    return service.manage_change_intent(
        action="declare",
        run_id=_RUN_ID,
        root=str(root),
        scope={"allowed_files": ["pkg/b.py"]},
        intent="edit pkg/b",
    )


def _start(service: CodeCloneMCPService, root: Path) -> dict[str, object]:
    return service.start_controlled_change(
        root=str(root),
        scope={"allowed_files": ["pkg/b.py"]},
        intent="edit pkg/b",
    )


def _seed_foreign_file(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[WorkspaceIntentRecord, Path, CodeCloneMCPService]:
    """A live foreign intent on ``pkg/a.py``, its file, and a service with a run."""

    foreign = _foreign_record()
    assert workspace_intents.write_workspace_intent(root=root, record=foreign)
    return foreign, _intent_file(root, foreign), _service_with_run(root, monkeypatch)


def _assert_registry_refusal(payload: dict[str, object]) -> None:
    """A refused grant over an unreadable registry, whichever door refused it."""

    assert payload["status"] == "blocked"
    assert payload["reason"] == _REGISTRY_UNREADABLE
    assert payload["edit_allowed"] is False
    assert payload["user_action_required"] is True
    assert payload["workspace_registered"] is False


# ══ INT-01 · an unreadable intent file is retained, never removed ═══════════


@_needs_permission_bits
def test_an_unreadable_live_intent_file_survives_every_read(file_root: Path) -> None:
    """The audit probe, pinned. Control first, in the same test.

    readable live intent  -> listed, file on disk
    same file, chmod 0    -> not listed, STILL on disk, reported as retained
    permissions restored  -> listed again: nothing was lost
    """

    store = FileWorkspaceIntentStore(root=file_root)
    live = _record(intent_id="intent-cccccccc-001")
    assert store.write(live)
    path = _intent_file(file_root, live)
    assert [r.intent_id for r in store.list_records_current()] == [live.intent_id]

    with _Unreadable(path):
        listed = store.list_records_current()
        found = store.find(live.intent_id)
        collected = store.gc()
        assert path.exists(), "an unreadable intent file was deleted"

    assert [r.intent_id for r in listed] == []
    assert found is None
    assert collected["corrupted_removed"] == 0
    assert collected["corrupted_filenames"] == []
    assert collected["inaccessible_retained"] == 1
    assert collected["inaccessible_retained_filenames"] == [path.name]

    assert [r.intent_id for r in store.list_records_current()] == [live.intent_id]


def test_damaged_bytes_are_still_removed(file_root: Path) -> None:
    """Opposite boundary on the same path: corrupt JSON keeps being hygiene."""

    store = FileWorkspaceIntentStore(root=file_root)
    bad = intent_paths.registry_dir(file_root) / "123-456-intent-bad-001.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{", encoding="utf-8")

    collected = store.gc()

    assert not bad.exists()
    assert collected["corrupted_filenames"] == [bad.name]
    assert collected["inaccessible_retained"] == 0


# ══ INT-01 · unknown blocks every grant of write authority ══════════════════


@_needs_permission_bits
def test_declare_refuses_over_an_unreadable_file_and_proceeds_once_readable(
    file_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The causal pair: the only variable is the file's readability.

    The foreign intent holds ``pkg/a.py``; the declare asks for ``pkg/b.py``.
    While the file cannot be read its scope is unknown, so the declare is
    refused even though, once readable, the two scopes do not overlap.
    """

    foreign, path, service = _seed_foreign_file(file_root, monkeypatch)

    with _Unreadable(path):
        refused = _declare(service, file_root)
        assert path.exists()
        assert sorted(p.name for p in path.parent.glob("*.json")) == [path.name]

    _assert_registry_refusal(refused)
    relative = f".codeclone/intents/{path.name}"
    assert refused["inaccessible_registry_entries"] == [
        {
            "path": relative,
            "intent_id": foreign.intent_id,
            "error": "PermissionError",
        }
    ]
    next_step = str(refused["next_step"])
    assert relative in next_step
    assert "permission" in next_step.lower()
    assert "owner" in next_step.lower()
    assert "scope" not in refused

    admitted = _declare(service, file_root)

    assert admitted["status"] == "active"
    assert admitted["edit_allowed"] is True
    assert admitted["concurrent_intents"] == []


@_needs_permission_bits
def test_start_controlled_change_refuses_over_an_unreadable_file(
    file_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _foreign, path, service = _seed_foreign_file(file_root, monkeypatch)

    with _Unreadable(path):
        refused = _start(service, file_root)
        assert path.exists()

    _assert_registry_refusal(refused)


def test_any_os_error_on_an_entry_refuses_admission(
    file_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not only permission bits: EIO answers the same, without root caveats."""

    foreign, path, service = _seed_foreign_file(file_root, monkeypatch)
    _fail_open_for(monkeypatch, path, OSError(errno.EIO, "Input/output error"))
    refused = _declare(service, file_root)
    listed = service.manage_change_intent(action="list_workspace", root=str(file_root))
    assert path.exists()

    _assert_registry_refusal(refused)
    assert refused["inaccessible_registry_entries"] == [
        {
            "path": f".codeclone/intents/{path.name}",
            "intent_id": foreign.intent_id,
            "error": "OSError",
        }
    ]
    # Listing stays available and names the entry instead of omitting it.
    assert listed["workspace_intents"] == []
    assert (
        listed["inaccessible_registry_entries"]
        == refused["inaccessible_registry_entries"]
    )


def test_promote_refuses_over_an_unreadable_entry(
    file_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocker = _record(
        intent_id="intent-blocker-001",
        pid=_FOREIGN_PID,
        start_epoch=_FOREIGN_START_EPOCH,
        scope={"allowed_files": ["pkg/b.py"], "allowed_related": [], "forbidden": []},
    )
    assert workspace_intents.write_workspace_intent(root=file_root, record=blocker)
    service = _service_with_run(file_root, monkeypatch)
    queued = service.manage_change_intent(
        action="declare",
        run_id=_RUN_ID,
        root=str(file_root),
        scope={"allowed_files": ["pkg/b.py"]},
        intent="edit pkg/b",
        on_conflict="queue",
    )
    assert queued["status"] == "queued"
    blocker_path = _intent_file(file_root, blocker)
    _fail_open_for(
        monkeypatch,
        blocker_path,
        PermissionError(errno.EACCES, "Permission denied"),
    )

    refused = service.manage_change_intent(
        action="promote",
        intent_id=str(queued["intent_id"]),
    )

    _assert_registry_refusal(refused)
    assert blocker_path.exists()


# ══ INT-03 · the documented override no longer takes change control down ══


def test_the_documented_retention_override_keeps_change_control_up(
    file_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: the registry resolves, lists and admits with the env set.

    ``7`` from the environment used to raise on every registry resolution,
    the default file backend's included.
    """

    monkeypatch.setenv(_RETENTION_ENV, "7")
    clear_workspace_intent_store_cache()
    assert get_workspace_intent_store(file_root).backend == "file"
    service = _service_with_run(file_root, monkeypatch)

    listed = service.manage_change_intent(action="list_workspace", root=str(file_root))
    admitted = _declare(service, file_root)

    assert listed["registry_retention_days"] == "7"
    assert admitted["status"] == "active"
    assert admitted["edit_allowed"] is True
