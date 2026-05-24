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
    lease_renewed_delta: timedelta = timedelta(),
    lease_seconds: int = workspace_intents.DEFAULT_LEASE_SECONDS,
    report_digest: str = "digest-a",
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
        lease_renewed_at_utc=workspace_intents.format_utc(
            declared_at + lease_renewed_delta
        ),
        lease_seconds=lease_seconds,
        report_digest=report_digest,
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


def test_workspace_intent_lease_expiry_is_recoverable_not_gc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(
        intent_id="intent-lease-expired-001",
        lease_renewed_delta=timedelta(minutes=-10),
        lease_seconds=workspace_intents.MIN_LEASE_SECONDS,
    )
    assert workspace_intents.write_workspace_intent(root=tmp_path, record=record)
    monkeypatch.setattr(workspace_intents, "_is_pid_alive", lambda pid: True)

    assert workspace_intents.stale_reason(record) == "lease_expired"
    assert workspace_intents.list_workspace_intents(root=tmp_path) == ()
    assert workspace_intents.list_workspace_intents(
        root=tmp_path,
        exclude_stale=False,
    ) == (record,)

    gc_payload = workspace_intents.gc_workspace(root=tmp_path)
    assert gc_payload["removed"] == 0
    assert workspace_intents.list_workspace_intents(
        root=tmp_path,
        exclude_stale=False,
    ) == (record,)


def test_workspace_intent_ownership_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = workspace_intents.utc_now()
    own = _record(pid=111, start_epoch=100)
    own_stale = _record(
        pid=111,
        start_epoch=100,
        lease_renewed_delta=timedelta(minutes=-10),
        lease_seconds=workspace_intents.MIN_LEASE_SECONDS,
    )
    foreign = _record(pid=222, start_epoch=200)
    expired = _record(expires_delta=timedelta(seconds=-1))

    monkeypatch.setattr(workspace_intents, "_is_pid_alive", lambda pid: pid != 333)

    assert (
        workspace_intents.classify_intent_ownership(
            own,
            own_pid=111,
            own_start_epoch=100,
            now=now,
        )
        == workspace_intents.IntentOwnership.OWN_ACTIVE
    )
    assert (
        workspace_intents.classify_intent_ownership(
            own_stale,
            own_pid=111,
            own_start_epoch=100,
            now=now,
        )
        == workspace_intents.IntentOwnership.OWN_STALE
    )
    assert (
        workspace_intents.classify_intent_ownership(
            foreign,
            own_pid=111,
            own_start_epoch=100,
            now=now,
        )
        == workspace_intents.IntentOwnership.FOREIGN_ACTIVE
    )
    dead_pid = _record(pid=333, start_epoch=300)
    assert (
        workspace_intents.classify_intent_ownership(
            dead_pid,
            own_pid=111,
            own_start_epoch=100,
            now=now,
        )
        == workspace_intents.IntentOwnership.RECOVERABLE
    )
    assert (
        workspace_intents.classify_intent_ownership(
            expired,
            own_pid=expired.agent_pid,
            own_start_epoch=expired.agent_start_epoch,
            now=now,
        )
        == workspace_intents.IntentOwnership.EXPIRED
    )


def test_workspace_intent_renew_lease_updates_timestamp(tmp_path: Path) -> None:
    record = _record(
        lease_renewed_delta=timedelta(minutes=-2),
        lease_seconds=workspace_intents.DEFAULT_LEASE_SECONDS,
    )
    assert workspace_intents.write_workspace_intent(root=tmp_path, record=record)

    assert workspace_intents.renew_workspace_intent_lease(
        root=tmp_path,
        pid=record.agent_pid,
        start_epoch=record.agent_start_epoch,
        intent_id=record.intent_id,
    )
    updated = workspace_intents.list_workspace_intents(root=tmp_path)[0]
    assert updated.lease_renewed_at_utc != record.lease_renewed_at_utc
    assert workspace_intents.verify_intent_integrity(updated.signed_payload())


def test_workspace_intent_renew_lease_rejects_foreign_owner(tmp_path: Path) -> None:
    record = _record()
    assert workspace_intents.write_workspace_intent(root=tmp_path, record=record)

    assert (
        workspace_intents.renew_workspace_intent_lease(
            root=tmp_path,
            pid=record.agent_pid + 1,
            start_epoch=record.agent_start_epoch,
            intent_id=record.intent_id,
        )
        is False
    )
    assert workspace_intents.list_workspace_intents(root=tmp_path)[0] == record


def test_workspace_intent_v1_record_defaults_lease_fields() -> None:
    record = _record()
    payload = {
        "registry_version": workspace_intents.LEGACY_REGISTRY_VERSION,
        "intent_id": record.intent_id,
        "agent_pid": record.agent_pid,
        "agent_start_epoch": record.agent_start_epoch,
        "agent_label": record.agent_label,
        "run_id": record.run_id,
        "declared_at_utc": record.declared_at_utc,
        "expires_at_utc": record.expires_at_utc,
        "ttl_seconds": record.ttl_seconds,
        "status": record.status,
        "intent": record.intent,
        "scope": record.scope,
        "scope_digest": record.scope_digest,
        "blast_radius_summary": record.blast_radius_summary,
    }
    payload["integrity"] = {
        "payload_sha256": workspace_intents.compute_intent_digest(payload)
    }

    validated = workspace_intents.validate_workspace_record(payload)

    assert validated is not None
    assert validated.lease_renewed_at_utc == record.declared_at_utc
    assert validated.lease_seconds == workspace_intents.DEFAULT_LEASE_SECONDS
    assert validated.report_digest == ""


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
        own_start_epoch=999,
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
        own_start_epoch=999,
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
            own_start_epoch=existing.agent_start_epoch,
        )
        == []
    )
