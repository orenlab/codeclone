from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest

from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
from codeclone.surfaces.mcp._workspace_intents import WorkspaceIntentRecord
from codeclone.utils.json_io import read_json_object, write_json_document_atomically


def _record(
    *,
    intent_id: str = "intent-abcdef12-001",
    pid: int | None = None,
    start_epoch: int = 100,
    status: str = "active",
    scope: dict[str, object] | None = None,
    expires_delta: timedelta = timedelta(hours=1),
) -> WorkspaceIntentRecord:
    declared_at = workspace_intents.utc_now()
    scope_payload = scope or {
        "allowed_files": ["pkg/a.py"],
        "allowed_related": ["tests/test_a.py"],
        "forbidden": [".cache/codeclone/**", "codeclone.baseline.json"],
    }
    return WorkspaceIntentRecord(
        intent_id=intent_id,
        agent_pid=pid or os.getpid(),
        agent_start_epoch=start_epoch,
        agent_label="agent-a",
        run_id="abcdef1234567890",
        declared_at_utc=workspace_intents.format_utc(declared_at),
        expires_at_utc=workspace_intents.format_utc(declared_at + expires_delta),
        ttl_seconds=3600,
        status=status,
        intent="edit pkg.a",
        scope=scope_payload,
        scope_digest=workspace_intents.compute_scope_digest(scope_payload),
        blast_radius_summary={"radius_level": "medium"},
    )


def test_workspace_intent_write_validate_update_and_remove(tmp_path: Path) -> None:
    record = _record()

    assert workspace_intents.write_workspace_intent(root=tmp_path, record=record)
    records = workspace_intents.list_workspace_intents(root=tmp_path)
    assert records == (record,)
    assert workspace_intents.find_workspace_intent(
        root=tmp_path,
        intent_id=record.intent_id,
    ) == (
        workspace_intents.intent_path(
            root=tmp_path,
            pid=record.agent_pid,
            start_epoch=record.agent_start_epoch,
            intent_id=record.intent_id,
        ),
        record,
    )

    assert workspace_intents.update_workspace_intent_status(
        root=tmp_path,
        pid=record.agent_pid,
        start_epoch=record.agent_start_epoch,
        intent_id=record.intent_id,
        new_status="clean",
    )
    updated = workspace_intents.list_workspace_intents(root=tmp_path)[0]
    assert updated.status == "clean"
    assert workspace_intents.verify_intent_integrity(updated.signed_payload())

    assert workspace_intents.remove_workspace_intent(
        root=tmp_path,
        pid=record.agent_pid,
        start_epoch=record.agent_start_epoch,
        intent_id=record.intent_id,
    )
    assert workspace_intents.list_workspace_intents(root=tmp_path) == ()


def test_workspace_intent_validation_rejects_tampered_and_invalid_paths(
    tmp_path: Path,
) -> None:
    record = _record()
    assert workspace_intents.write_workspace_intent(root=tmp_path, record=record)
    path = workspace_intents.intent_path(
        root=tmp_path,
        pid=record.agent_pid,
        start_epoch=record.agent_start_epoch,
        intent_id=record.intent_id,
    )
    payload = read_json_object(path)
    payload["intent"] = "tampered"
    write_json_document_atomically(path, payload, sort_keys=True)

    assert workspace_intents.list_workspace_intents(root=tmp_path) == ()
    gc_payload = workspace_intents.gc_workspace(root=tmp_path)
    assert gc_payload["corrupted_removed"] == 1
    assert gc_payload["corrupted_filenames"] == [path.name]

    invalid_scope: dict[str, object] = {
        "allowed_files": [str(tmp_path / "abs.py")],
        "allowed_related": [],
        "forbidden": [],
    }
    invalid = _record(scope=invalid_scope)
    signed = invalid.signed_payload()
    assert workspace_intents.validate_workspace_record(signed) is None

    traversal_scope: dict[str, object] = {
        "allowed_files": ["../outside.py"],
        "allowed_related": [],
        "forbidden": [],
    }
    traversal = _record(scope=traversal_scope)
    assert (
        workspace_intents.validate_workspace_record(traversal.signed_payload()) is None
    )


def test_workspace_intent_stale_orphan_and_gc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired = _record(
        intent_id="intent-expired-001",
        expires_delta=timedelta(seconds=-1),
    )
    orphaned = _record(
        intent_id="intent-orphaned-001",
        pid=999999,
        start_epoch=101,
    )
    active = _record(intent_id="intent-active-001", start_epoch=102)
    for record in (expired, orphaned, active):
        assert workspace_intents.write_workspace_intent(root=tmp_path, record=record)

    monkeypatch.setattr(
        workspace_intents,
        "_is_pid_alive",
        lambda pid: pid != orphaned.agent_pid,
    )

    assert workspace_intents.stale_reason(expired) == "expired"
    assert workspace_intents.stale_reason(orphaned) == "orphaned"
    assert workspace_intents.list_workspace_intents(root=tmp_path) == (active,)

    gc_payload = workspace_intents.gc_workspace(root=tmp_path)
    assert gc_payload["removed"] == 2
    assert gc_payload["removed_reasons"] == {
        expired.intent_id: "expired",
        orphaned.intent_id: "orphaned",
    }
    assert workspace_intents.list_workspace_intents(root=tmp_path) == (active,)


def test_workspace_intent_conflict_detection() -> None:
    existing = _record()

    hard = workspace_intents.detect_conflicts(
        new_scope={
            "allowed_files": ["pkg/a.py"],
            "allowed_related": [],
            "forbidden": [],
        },
        existing=(existing,),
        own_pid=123456,
    )
    assert hard[0]["overlap_type"] == "hard"
    assert hard[0]["hard_overlap"] == ["pkg/a.py"]

    soft = workspace_intents.detect_conflicts(
        new_scope={
            "allowed_files": ["tests/test_a.py"],
            "allowed_related": [],
            "forbidden": [],
        },
        existing=(existing,),
        own_pid=123456,
    )
    assert soft[0]["overlap_type"] == "soft"
    assert soft[0]["soft_overlap"] == ["tests/test_a.py"]

    assert (
        workspace_intents.detect_conflicts(
            new_scope={
                "allowed_files": ["pkg/a.py"],
                "allowed_related": [],
                "forbidden": [],
            },
            existing=(existing,),
            own_pid=existing.agent_pid,
        )
        == []
    )
