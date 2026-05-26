from __future__ import annotations

import os
from dataclasses import replace
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


def _signed_payload_with(
    record: WorkspaceIntentRecord,
    **updates: object,
) -> dict[str, object]:
    payload = record.unsigned_payload()
    payload.update(updates)
    payload["integrity"] = {
        "payload_sha256": workspace_intents.compute_intent_digest(payload)
    }
    return payload


def _signed_payload_without(
    record: WorkspaceIntentRecord,
    *keys: str,
) -> dict[str, object]:
    payload = record.unsigned_payload()
    for key in keys:
        payload.pop(key, None)
    payload["integrity"] = {
        "payload_sha256": workspace_intents.compute_intent_digest(payload)
    }
    return payload


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


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {1: "not-a-string-key"},
        {"integrity": {"payload_sha256": "0" * 64}},
        _signed_payload_with(_record(), registry_version="9"),
        _signed_payload_without(_record(), "intent_id"),
        _signed_payload_with(_record(), agent_pid=True),
        _signed_payload_with(_record(), agent_start_epoch=0),
        _signed_payload_with(_record(), status="finished"),
        _signed_payload_with(_record(), scope_digest="not-a-digest"),
        _signed_payload_with(_record(), declared_at_utc="not-a-date"),
        _signed_payload_with(_record(), lease_renewed_at_utc="not-a-date"),
        _signed_payload_without(_record(), "lease_renewed_at_utc"),
        _signed_payload_with(_record(), lease_seconds=1),
        _signed_payload_with(_record(), lease_seconds=True),
        _signed_payload_without(_record(), "report_digest"),
        _signed_payload_with(_record(), blast_radius_summary=[]),
        _signed_payload_with(_record(), scope=[]),
        _signed_payload_with(_record(), scope={"allowed_files": []}),
        _signed_payload_with(
            _record(),
            scope={"allowed_files": ["pkg/a.py"], "allowed_related": "tests/a.py"},
        ),
        _signed_payload_with(
            _record(),
            scope={"allowed_files": ["pkg/a.py"], "forbidden": [1]},
        ),
    ],
)
def test_workspace_intent_validation_rejects_malformed_payloads(
    payload: object,
) -> None:
    assert workspace_intents.validate_workspace_record(payload) is None


def test_workspace_intent_validation_rejects_scope_digest_mismatch() -> None:
    payload = _signed_payload_with(_record(), scope_digest="0" * 64)

    assert workspace_intents.validate_workspace_record(payload) is None


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


def test_workspace_intent_io_failure_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record()

    assert (
        workspace_intents.find_workspace_intent(
            root=tmp_path,
            intent_id=record.intent_id,
        )
        is None
    )
    assert (
        workspace_intents.update_workspace_intent_status(
            root=tmp_path,
            pid=record.agent_pid,
            start_epoch=record.agent_start_epoch,
            intent_id=record.intent_id,
            new_status="clean",
        )
        is False
    )
    assert (
        workspace_intents.renew_workspace_intent_lease(
            root=tmp_path,
            pid=record.agent_pid,
            start_epoch=record.agent_start_epoch,
            intent_id=record.intent_id,
        )
        is False
    )

    assert workspace_intents.write_workspace_intent(root=tmp_path, record=record)
    assert (
        workspace_intents.update_workspace_intent_status(
            root=tmp_path,
            pid=record.agent_pid + 1,
            start_epoch=record.agent_start_epoch,
            intent_id=record.intent_id,
            new_status="clean",
        )
        is False
    )

    expired = _record(
        intent_id="intent-expired-lease",
        expires_delta=timedelta(days=-1),
    )
    assert workspace_intents.write_workspace_intent(root=tmp_path, record=expired)
    assert (
        workspace_intents.renew_workspace_intent_lease(
            root=tmp_path,
            pid=expired.agent_pid,
            start_epoch=expired.agent_start_epoch,
            intent_id=expired.intent_id,
        )
        is False
    )

    def raise_oserror(*args: object, **kwargs: object) -> None:
        raise OSError("boom")

    monkeypatch.setattr(
        workspace_intents,
        "write_json_document_atomically",
        raise_oserror,
    )
    assert (
        workspace_intents.write_workspace_intent(root=tmp_path, record=_record())
        is False
    )
    assert (
        workspace_intents.update_workspace_intent_status(
            root=tmp_path,
            pid=record.agent_pid,
            start_epoch=record.agent_start_epoch,
            intent_id=record.intent_id,
            new_status="violated",
        )
        is False
    )
    assert (
        workspace_intents.renew_workspace_intent_lease(
            root=tmp_path,
            pid=record.agent_pid,
            start_epoch=record.agent_start_epoch,
            intent_id=record.intent_id,
        )
        is False
    )

    monkeypatch.setattr(Path, "unlink", raise_oserror)
    assert (
        workspace_intents.remove_workspace_intent(
            root=tmp_path,
            pid=record.agent_pid,
            start_epoch=record.agent_start_epoch,
            intent_id=record.intent_id,
        )
        is False
    )


def test_workspace_intent_payload_and_helper_edge_cases(tmp_path: Path) -> None:
    record = _record()
    now = workspace_intents.utc_now()

    own_payload = record.to_payload(
        own_pid=record.agent_pid,
        own_start_epoch=record.agent_start_epoch,
        now=now,
    )
    assert own_payload["ownership"] == "own_active"
    assert own_payload["is_own"] is True
    assert isinstance(own_payload["lease_expires_in_seconds"], int)

    invalid_lease = replace(record, lease_renewed_at_utc="not-a-date")
    invalid_payload = invalid_lease.to_payload(
        own_pid=record.agent_pid,
        own_start_epoch=record.agent_start_epoch,
        now=now,
    )
    assert invalid_payload["ownership"] == "own_stale"
    assert "lease_expires_in_seconds" not in invalid_payload

    assert workspace_intents.resolved_ttl_seconds(True) == (
        workspace_intents.DEFAULT_TTL_SECONDS
    )
    assert workspace_intents.resolved_ttl_seconds("bad") == (
        workspace_intents.DEFAULT_TTL_SECONDS
    )
    assert workspace_intents.resolved_ttl_seconds("1") == (
        workspace_intents.MIN_TTL_SECONDS
    )
    assert workspace_intents.resolved_ttl_seconds("999999") == (
        workspace_intents.MAX_TTL_SECONDS
    )
    assert workspace_intents.resolved_lease_seconds("1") == (
        workspace_intents.MIN_LEASE_SECONDS
    )
    assert workspace_intents.resolved_lease_seconds("999999") == (
        workspace_intents.MAX_LEASE_SECONDS
    )
    assert workspace_intents.verify_intent_integrity({}) is False
    assert (
        workspace_intents.safe_remove_own_intent(
            root=Path("relative"),
            pid=record.agent_pid,
            start_epoch=record.agent_start_epoch,
            intent_id=record.intent_id,
        )
        is False
    )

    assert workspace_intents.write_workspace_intent(root=tmp_path, record=record)
    assert workspace_intents.safe_remove_own_intent(
        root=tmp_path,
        pid=record.agent_pid,
        start_epoch=record.agent_start_epoch,
        intent_id=record.intent_id,
    )
    assert not workspace_intents.intent_path(
        root=tmp_path,
        pid=record.agent_pid,
        start_epoch=record.agent_start_epoch,
        intent_id=record.intent_id,
    ).exists()

    assert workspace_intents.write_workspace_intent(root=tmp_path, record=record)
    assert workspace_intents.remove_workspace_record(root=tmp_path, record=record)


def test_workspace_intent_private_edge_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired_status = _record(
        status=workspace_intents.WorkspaceIntentStatus.EXPIRED.value
    )
    orphaned_status = _record(
        status=workspace_intents.WorkspaceIntentStatus.ORPHANED.value
    )

    assert workspace_intents.is_stale(expired_status)
    assert workspace_intents.stale_reason(expired_status) == "expired"
    assert workspace_intents.stale_reason(orphaned_status) == "orphaned"
    assert workspace_intents._is_pid_alive(0) is False
    assert workspace_intents._dict_payload({1: "bad"}) is None
    assert workspace_intents._valid_path_list(
        ["", "pkg/a.py"],
        required=True,
    ) == ["pkg/a.py"]
    assert workspace_intents._string_value(123) == ""
    assert workspace_intents._required_string("  ") is None
    assert workspace_intents._required_string("value") == "value"
    assert workspace_intents._positive_int(True) is None
    assert workspace_intents._positive_int(0) is None
    assert workspace_intents._positive_int(5) == 5
    assert (
        workspace_intents._valid_lease_seconds(workspace_intents.MIN_LEASE_SECONDS - 1)
        is None
    )
    assert (
        workspace_intents._valid_lease_seconds(workspace_intents.MAX_LEASE_SECONDS + 1)
        is None
    )
    assert (
        workspace_intents._valid_lease_seconds(workspace_intents.MIN_LEASE_SECONDS)
        == workspace_intents.MIN_LEASE_SECONDS
    )
    assert workspace_intents._is_hex_digest(123) is False
    assert workspace_intents._is_hex_digest("0" * 63) is False
    assert workspace_intents._is_hex_digest("g" * 64) is False
    assert workspace_intents._is_hex_digest("A" * 64) is True
    assert workspace_intents._valid_status_values() == frozenset(
        status.value for status in workspace_intents.WorkspaceIntentStatus
    )
    assert workspace_intents._valid_scope([]) is None
    assert workspace_intents._valid_scope({1: ["pkg/a.py"]}) is None
    assert workspace_intents._valid_scope({"allowed_files": []}) is None
    assert (
        workspace_intents._valid_scope(
            {"allowed_files": ["pkg/a.py"], "allowed_related": "tests/a.py"}
        )
        is None
    )
    assert (
        workspace_intents._valid_scope(
            {"allowed_files": ["pkg/a.py"], "forbidden": [1]}
        )
        is None
    )
    assert workspace_intents._valid_path_list("pkg/a.py", required=True) is None
    assert workspace_intents._valid_path_list([1], required=True) is None
    assert workspace_intents._valid_path_list(["/abs.py"], required=True) is None
    assert workspace_intents._valid_path_list(["../abs.py"], required=True) is None
    assert workspace_intents._valid_path_list(["pkg/a.py/"], required=True) == [
        "pkg/a.py"
    ]
    assert workspace_intents._scope_all_sets({"allowed_files": "pkg/a.py"}) == (
        set(),
        set(),
        (),
    )
    assert workspace_intents._parse_utc("2026-01-01T00:00:00") is None
    assert workspace_intents._sort_agent_pid(True) == 0
    assert workspace_intents._sort_agent_pid("123") == 0
    assert workspace_intents._sort_agent_pid(123) == 123
    assert workspace_intents._overlap_type(hard=False, soft=True) == "soft"

    def raise_permission_error(pid: int, signal: int) -> None:
        raise PermissionError

    def raise_oserror(pid: int, signal: int) -> None:
        raise OSError

    def raise_process_lookup(pid: int, signal: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(os, "kill", raise_permission_error)
    assert workspace_intents._is_pid_alive(123) is True
    monkeypatch.setattr(os, "kill", raise_oserror)
    assert workspace_intents._is_pid_alive(123) is True
    monkeypatch.setattr(os, "kill", raise_process_lookup)
    assert workspace_intents._is_pid_alive(123) is False

    path = tmp_path / "intent.json"
    path.write_text("{}", "utf-8")

    def raise_unlink_oserror(self: Path, missing_ok: bool = False) -> None:
        raise OSError("unlink failed")

    monkeypatch.setattr(Path, "unlink", raise_unlink_oserror)
    assert workspace_intents._unlink(path) is False

    def raise_resolve_oserror(self: Path, strict: bool = False) -> Path:
        raise OSError("resolve failed")

    monkeypatch.setattr(Path, "resolve", raise_resolve_oserror)
    assert (
        workspace_intents._is_safe_intent_path(
            tmp_path / "intent.json",
            workspace_intents.registry_dir(tmp_path),
        )
        is False
    )


def test_workspace_intent_safe_path_edge_helpers(tmp_path: Path) -> None:
    registry = workspace_intents.registry_dir(tmp_path)
    registry.mkdir(parents=True)
    good = registry / "123-456-intent-good.json"
    good.write_text("{}", encoding="utf-8")

    assert workspace_intents._is_safe_intent_path(good, registry)
    assert (
        workspace_intents._is_safe_intent_path(Path("relative.json"), registry) is False
    )
    assert (
        workspace_intents._is_safe_intent_path(tmp_path / "outside.json", registry)
        is False
    )
    assert (
        workspace_intents._is_safe_intent_path(registry / "bad.json", registry) is False
    )

    directory_target = registry / "123-456-intent-dir.json"
    directory_target.mkdir()
    assert workspace_intents._is_safe_intent_path(directory_target, registry) is False

    non_normalized = registry / ".." / "123-456-intent-other.json"
    assert workspace_intents._is_safe_intent_path(non_normalized, registry) is False


def test_workspace_intent_registry_defensive_failure_edges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(
        intent_id="intent-expired-cleanup", expires_delta=timedelta(days=-1)
    )
    assert workspace_intents.write_workspace_intent(root=tmp_path, record=record)
    path = workspace_intents.intent_path(
        root=tmp_path,
        pid=record.agent_pid,
        start_epoch=record.agent_start_epoch,
        intent_id=record.intent_id,
    )

    corrupted = workspace_intents.registry_dir(tmp_path) / "123-456-intent-bad.json"
    corrupted.write_text("{", encoding="utf-8")
    cleanup = workspace_intents.gc_workspace(root=tmp_path)
    assert cleanup["corrupted_filenames"] == ["123-456-intent-bad.json"]

    monkeypatch.setattr(workspace_intents, "_unlink", lambda item: False)
    assert workspace_intents.gc_workspace(root=tmp_path)["removed"] == 0

    def raise_read_error(item: Path) -> dict[str, object]:
        raise ValueError("bad json")

    monkeypatch.setattr(workspace_intents, "read_json_object", raise_read_error)
    assert workspace_intents._read_payload(path) is None

    def raise_glob_error(self: Path, pattern: str) -> tuple[Path, ...]:
        raise OSError("glob failed")

    monkeypatch.setattr(Path, "glob", raise_glob_error)
    assert workspace_intents.list_workspace_intents(root=tmp_path) == ()
    assert workspace_intents._valid_scope({1: ["pkg/a.py"]}) is None

    def raise_safety_error(expected: Path, registry: Path) -> bool:
        raise RuntimeError("safety check failed")

    monkeypatch.setattr(workspace_intents, "_is_safe_intent_path", raise_safety_error)
    assert (
        workspace_intents.safe_remove_own_intent(
            root=tmp_path,
            pid=record.agent_pid,
            start_epoch=record.agent_start_epoch,
            intent_id=record.intent_id,
        )
        is False
    )


def test_workspace_intent_foreign_stale_conflict_and_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = _record(intent_id="intent-active-001", pid=111, start_epoch=100)
    foreign_stale = _record(
        intent_id="intent-stale-001",
        pid=222,
        start_epoch=200,
        lease_renewed_delta=timedelta(minutes=-10),
        lease_seconds=workspace_intents.MIN_LEASE_SECONDS,
    )
    orphaned = _record(intent_id="intent-orphaned-001", pid=333, start_epoch=300)
    for record in (active, foreign_stale, orphaned):
        assert workspace_intents.write_workspace_intent(root=tmp_path, record=record)

    monkeypatch.setattr(workspace_intents, "_is_pid_alive", lambda pid: pid != 333)

    counts = workspace_intents.workspace_status_counts(root=tmp_path)
    assert counts == {"stale_count": 2, "orphaned_count": 1, "total_agents": 3}

    payload = foreign_stale.to_payload(
        own_pid=111,
        own_start_epoch=100,
        now=workspace_intents.utc_now(),
    )
    assert payload["ownership"] == workspace_intents.IntentOwnership.FOREIGN_STALE.value
    assert "owner may still be working" in str(payload["escalation_hint"])
    assert workspace_intents._gc_removal_reason(foreign_stale) is None

    conflicts = workspace_intents.detect_conflicts(
        new_scope={
            "allowed_files": ["pkg/a.py"],
            "allowed_related": [],
            "forbidden": [],
        },
        existing=(foreign_stale,),
        own_pid=111,
        own_start_epoch=100,
    )
    assert conflicts == [
        {
            "intent_id": foreign_stale.intent_id,
            "agent_pid": 222,
            "agent_start_epoch": 200,
            "agent_label": "agent-a",
            "intent": "edit pkg.a",
            "ownership": workspace_intents.IntentOwnership.FOREIGN_STALE.value,
            "severity": "stale",
            "recommended_action": "coordinate_or_recover",
            "overlap_type": "hard",
            "hard_overlap": ["pkg/a.py"],
            "soft_overlap": [],
            "declared_at_utc": foreign_stale.declared_at_utc,
            "expires_at_utc": foreign_stale.expires_at_utc,
        }
    ]

    assert (
        workspace_intents.detect_conflicts(
            new_scope={
                "allowed_files": ["pkg/other.py"],
                "allowed_related": [],
                "forbidden": [],
            },
            existing=(foreign_stale,),
            own_pid=111,
            own_start_epoch=100,
        )
        == []
    )


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
    foreign_stale = _record(
        pid=222,
        start_epoch=200,
        lease_renewed_delta=timedelta(minutes=-10),
        lease_seconds=workspace_intents.MIN_LEASE_SECONDS,
    )
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
    assert (
        workspace_intents.classify_intent_ownership(
            foreign_stale,
            own_pid=111,
            own_start_epoch=100,
            now=now,
        )
        == workspace_intents.IntentOwnership.FOREIGN_STALE
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


def test_workspace_intent_update_status_can_extend_ttl(tmp_path: Path) -> None:
    record = _record(lease_renewed_delta=timedelta(minutes=-2))
    assert workspace_intents.write_workspace_intent(root=tmp_path, record=record)

    assert workspace_intents.update_workspace_intent_status(
        root=tmp_path,
        pid=record.agent_pid,
        start_epoch=record.agent_start_epoch,
        intent_id=record.intent_id,
        new_status="active",
        ttl_seconds=workspace_intents.MIN_TTL_SECONDS,
    )

    updated = workspace_intents.list_workspace_intents(root=tmp_path)[0]
    assert updated.ttl_seconds == workspace_intents.MIN_TTL_SECONDS
    assert updated.lease_renewed_at_utc != record.lease_renewed_at_utc
    assert updated.lease_renewed_at_utc == updated.declared_at_utc


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

    both = workspace_intents.detect_conflicts(
        new_scope={
            "allowed_files": ["pkg/a.py"],
            "allowed_related": ["pkg/a.py"],
            "forbidden": [],
        },
        existing=(existing,),
        own_pid=123456,
        own_start_epoch=999,
    )
    assert both[0]["overlap_type"] == "both"


def test_workspace_intent_workspace_relations_forbidden_patterns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workspace_intents, "_is_pid_alive", lambda pid: True)
    foreign = _record(
        intent_id="intent-foreign-docs",
        pid=111,
        start_epoch=100,
        scope={
            "allowed_files": ["pkg/a.py"],
            "allowed_related": [],
            "forbidden": ["docs/**"],
        },
    )

    relations = workspace_intents.detect_workspace_relations(
        new_scope={
            "allowed_files": ["docs/readme.md"],
            "allowed_related": [],
            "forbidden": [],
        },
        existing=(foreign,),
        own_pid=222,
        own_start_epoch=200,
    )

    assert (
        workspace_intents.detect_conflicts(
            new_scope={
                "allowed_files": ["docs/readme.md"],
                "allowed_related": [],
                "forbidden": [],
            },
            existing=(foreign,),
            own_pid=222,
            own_start_epoch=200,
        )
        == []
    )
    assert relations == [
        {
            "intent_id": "intent-foreign-docs",
            "agent_pid": 111,
            "agent_start_epoch": 100,
            "agent_label": "agent-a",
            "intent": "edit pkg.a",
            "ownership": "foreign_active",
            "relation": "foreign_excludes_target",
            "severity": "info",
            "matching_patterns": ["docs/**"],
            "message": "Foreign agent explicitly excludes files in current scope.",
            "declared_at_utc": foreign.declared_at_utc,
            "expires_at_utc": foreign.expires_at_utc,
        }
    ]


def test_workspace_intent_workspace_relations_target_excludes_foreign(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workspace_intents, "_is_pid_alive", lambda pid: True)
    foreign = _record(
        intent_id="intent-foreign-docs",
        pid=111,
        start_epoch=100,
        scope={
            "allowed_files": ["docs/readme.md"],
            "allowed_related": [],
            "forbidden": [],
        },
    )

    relations = workspace_intents.detect_workspace_relations(
        new_scope={
            "allowed_files": ["pkg/a.py"],
            "allowed_related": [],
            "forbidden": ["docs/**"],
        },
        existing=(foreign,),
        own_pid=222,
        own_start_epoch=200,
    )

    assert (
        workspace_intents.detect_conflicts(
            new_scope={
                "allowed_files": ["pkg/a.py"],
                "allowed_related": [],
                "forbidden": ["docs/**"],
            },
            existing=(foreign,),
            own_pid=222,
            own_start_epoch=200,
        )
        == []
    )
    assert relations[0]["relation"] == "target_excludes_foreign"
    assert relations[0]["matching_patterns"] == ["docs/**"]


def test_workspace_intent_workspace_relations_include_edit_overlap() -> None:
    existing = _record()

    relations = workspace_intents.detect_workspace_relations(
        new_scope={
            "allowed_files": ["pkg/a.py"],
            "allowed_related": [],
            "forbidden": [],
        },
        existing=(existing,),
        own_pid=123456,
        own_start_epoch=999,
    )

    assert relations[0]["relation"] == "edit_overlap"
    assert relations[0]["hard_overlap"] == ["pkg/a.py"]


def test_workspace_intent_workspace_relations_omit_disjoint_scope() -> None:
    existing = _record()

    assert (
        workspace_intents.detect_workspace_relations(
            new_scope={
                "allowed_files": ["pkg/other.py"],
                "allowed_related": [],
                "forbidden": [],
            },
            existing=(existing,),
            own_pid=123456,
            own_start_epoch=999,
        )
        == []
    )


def test_workspace_intent_regression_stale_lease_silent_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: expired lease + alive PID must produce conflict, not silence.

    Timeline from real incident:
      T0:       PID A declares intent over files X, lease=300s
      T0+301s:  PID A lease expires, PID A still alive
      T0+352s:  PID B declares intent over same files X
      Expected: PID B sees concurrent_intents with ownership=foreign_stale
    """
    agent_a = _record(
        intent_id="intent-a-001",
        pid=1000,
        start_epoch=100,
        scope={
            "allowed_files": ["src/shared.py"],
            "allowed_related": [],
            "forbidden": [],
        },
        lease_renewed_delta=timedelta(minutes=-6),
        lease_seconds=workspace_intents.DEFAULT_LEASE_SECONDS,
    )
    monkeypatch.setattr(workspace_intents, "_is_pid_alive", lambda pid: True)

    conflicts = workspace_intents.detect_conflicts(
        new_scope={
            "allowed_files": ["src/shared.py"],
            "allowed_related": [],
            "forbidden": [],
        },
        existing=(agent_a,),
        own_pid=2000,
        own_start_epoch=200,
    )

    conflict = conflicts[0]
    assert len(conflicts) == 1
    for key, expected in (
        ("ownership", "foreign_stale"),
        ("severity", "stale"),
        ("recommended_action", "coordinate_or_recover"),
        ("hard_overlap", ["src/shared.py"]),
    ):
        assert conflict[key] == expected, f"{key}: {conflict[key]!r} != {expected!r}"


def test_workspace_intent_renew_lease_with_custom_seconds(tmp_path: Path) -> None:
    """Explicit lease_seconds on renew updates the workspace record."""
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
        lease_seconds=workspace_intents.MAX_LEASE_SECONDS,
    )
    updated = workspace_intents.list_workspace_intents(root=tmp_path)[0]
    assert updated.lease_seconds == workspace_intents.MAX_LEASE_SECONDS
    assert updated.lease_renewed_at_utc != record.lease_renewed_at_utc


def test_workspace_intent_max_lease_seconds_ceiling() -> None:
    """MAX_LEASE_SECONDS is 600 (10 minutes), not 3600."""
    assert workspace_intents.MAX_LEASE_SECONDS == 600
    assert workspace_intents.resolved_lease_seconds(9999) == 600
    assert workspace_intents.resolved_lease_seconds(60) == 60
