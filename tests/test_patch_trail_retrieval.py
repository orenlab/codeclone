# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Durable post-clear patch-trail retrieval (get_patch_trail).

These tests write a patch_trail.computed event to the audit trail and read it
back through a FRESH service with no session knowledge of the run, proving the
full forensic trail is durable and post-clear: it reads stored evidence exactly
as persisted (forensic-retention), never re-derives or summarizes it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest

import codeclone.memory.sqlite_store as memory_sqlite_store
from codeclone.audit import (
    DEFAULT_AUDIT_PATH,
    EVENT_PATCH_TRAIL_COMPUTED,
    AuditEvent,
    resolve_audit_path,
)
from codeclone.audit.reader import (
    PatchTrailLookup,
    StoredPatchTrail,
    lookup_patch_trail,
)
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.contracts import PATCH_TRAIL_SCHEMA_VERSION
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.memory.trajectory import store as trajectory_store
from codeclone.memory.trajectory.models import Trajectory
from codeclone.surfaces.mcp._session_shared import MCPServiceContractError
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.utils.json_io import json_text

from .memory_fixtures import memory_project_db_paths


def _patch_trail_payload(
    *, digest: str = "abc123", scope: str = "clean", verify: str = "accepted"
) -> dict[str, object]:
    return {
        "schema_version": PATCH_TRAIL_SCHEMA_VERSION,
        "intent_id": "intent-30b56d21-001",
        "intent_description": "demo patch trail",
        "declared_files": ["a.py"],
        "changed_files": ["a.py"],
        "untouched_in_declared": [],
        "unexpected_files": [],
        "forbidden_touched": [],
        "scope_check_status": scope,
        "verification_status": verify,
        "workspace_hygiene": {"blocks_finish": False},
        "evidence": {"report_digest": "reportdigest"},
        "truncation": {"declared_files": False},
        "patch_trail_digest": digest,
    }


def _emit_patch_trail(
    db_path: Path,
    *,
    run_id: str,
    payload: dict[str, object],
    payloads: str = "compact",
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    writer = SqliteAuditWriter(
        db_path=db_path, payloads=cast("Any", payloads), retention_days=30
    )
    writer.emit(
        AuditEvent(
            event_type=EVENT_PATCH_TRAIL_COMPUTED,
            severity="info",
            repo_root_digest="rootdigest0000",
            agent_pid=1,
            agent_start_epoch=1,
            agent_label="test",
            run_id=run_id,
            intent_id=None,
            report_digest="reportdigest",
            status=str(payload.get("scope_check_status", "")),
            payload=payload,
        )
    )
    writer.close()


def _audit_db(root: Path) -> Path:
    return resolve_audit_path(root_path=root, value=DEFAULT_AUDIT_PATH)


def _ok_trail(lookup: PatchTrailLookup) -> StoredPatchTrail:
    assert lookup.status == "ok"
    assert lookup.patch_trail is not None
    return lookup.patch_trail


def _assert_structured_patch_trail_response(
    out: Mapping[str, object],
    *,
    source: str,
) -> dict[str, object]:
    assert out["status"] == "ok"
    assert out["format"] == "structured"
    assert out["source"] == source
    assert out["durable"] is True
    assert out["patch_trail_digest"] == "abc123"
    trail = cast("dict[str, object]", out["patch_trail"])
    assert trail["declared_files"] == ["a.py"]
    return trail


def _assert_patch_trail_retrieval_governance(out: Mapping[str, object]) -> None:
    governance = cast("dict[str, object]", out["context_governance"])
    response = cast("dict[str, object]", governance["response"])
    assert response["tool"] == "get_patch_trail"
    assert response["evidence_policy"] == "observe_only_no_omission"
    assert governance["mode"] == "observe"
    assert governance["enforcement"] == {
        "response_budget": False,
        "nested_budget": False,
        "omission": False,
    }
    assert governance["truncated"] is False


def test_lookup_patch_trail_compact_mode_preserves_full_forensic_trail(
    tmp_path: Path,
) -> None:
    # The whole point of the forensic-retention exemption: even the default
    # compact audit mode keeps the complete trail durably retrievable, matched
    # exactly by run id and digest.
    db_path = tmp_path / "audit.sqlite3"
    _emit_patch_trail(
        db_path, run_id="30b56d21", payload=_patch_trail_payload(), payloads="compact"
    )

    trail = _ok_trail(
        lookup_patch_trail(db_path, run_id="30b56d21", patch_trail_digest="abc123")
    )

    assert trail.scope_check_status == "clean"
    assert trail.verification_status == "accepted"
    assert trail.schema_version == PATCH_TRAIL_SCHEMA_VERSION
    # Full forensic detail survives compaction, not just the bounded summary.
    assert trail.payload["declared_files"] == ["a.py"]
    assert trail.payload["workspace_hygiene"] == {"blocks_finish": False}


def test_lookup_patch_trail_fail_closed_statuses(tmp_path: Path) -> None:
    missing = tmp_path / "absent.sqlite3"
    assert lookup_patch_trail(missing, run_id="30b56d21").status == "not_found"

    db_path = tmp_path / "audit.sqlite3"
    _emit_patch_trail(
        db_path, run_id="30b56d21", payload=_patch_trail_payload(digest="aaa")
    )
    _emit_patch_trail(
        db_path, run_id="30b56d21", payload=_patch_trail_payload(digest="bbb")
    )

    assert lookup_patch_trail(db_path, run_id="ffffffff").status == "not_found"
    # Two trails on one run cannot be disambiguated by run id alone.
    assert lookup_patch_trail(db_path, run_id="30b56d21").status == "ambiguous"
    pinned = _ok_trail(
        lookup_patch_trail(db_path, run_id="30b56d21", patch_trail_digest="bbb")
    )
    assert pinned.patch_trail_digest == "bbb"
    mismatch = lookup_patch_trail(db_path, run_id="30b56d21", patch_trail_digest="zzz")
    assert mismatch.status == "digest_mismatch"


def test_lookup_patch_trail_malformed_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    _emit_patch_trail(db_path, run_id="30b56d21", payload=_patch_trail_payload())
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE controller_events SET payload_json='{not valid json' "
        "WHERE event_type=?",
        (EVENT_PATCH_TRAIL_COMPUTED,),
    )
    conn.commit()
    conn.close()

    assert (
        lookup_patch_trail(db_path, run_id="30b56d21").status
        == "malformed_stored_patch_trail"
    )


def test_get_patch_trail_structured_post_clear(tmp_path: Path) -> None:
    _emit_patch_trail(
        _audit_db(tmp_path), run_id="30b56d21", payload=_patch_trail_payload()
    )
    # Fresh service: no in-memory run/intent for this run id (i.e. post-clear).
    service = CodeCloneMCPService(history_limit=4)

    out = service.get_patch_trail(
        root=str(tmp_path), run_id="30b56d21", patch_trail_digest="abc123"
    )

    trail = _assert_structured_patch_trail_response(out, source="audit_event")
    assert trail["verification_status"] == "accepted"
    _assert_patch_trail_retrieval_governance(out)


def test_get_patch_trail_falls_back_to_memory_trajectory_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project, db_path = memory_project_db_paths(root)
    store = SqliteEngineeringMemoryStore(db_path)
    now = "2026-01-01T00:00:00Z"
    trajectory = Trajectory(
        id="traj-patch-trail",
        project_id=project.id,
        repo_root_digest="rootdigest0000",
        workflow_id="intent:intent-30b56d21-001",
        intent_id="intent-30b56d21-001",
        primary_run_id="30b56d21",
        first_run_id="30b56d21",
        last_run_id="30b56d21",
        report_digest="reportdigest",
        outcome="accepted",
        quality_tier="verified",
        quality_score=95,
        labels=("patch_trail_recorded",),
        summary="accepted change with durable patch trail",
        trajectory_digest="t" * 64,
        source_event_stream_digest="s" * 64,
        projection_version="trajectory-v3",
        event_count=2,
        step_count=0,
        incident_count=0,
        started_at_utc=now,
        finished_at_utc=now,
        projected_at_utc=now,
        updated_at_utc=now,
        steps=(),
        subjects=(),
        evidence=(),
    )
    try:
        store.initialize(project)
        trajectory_store.upsert_trajectory(store.connection, trajectory)
        trajectory_store.upsert_trajectory_patch_trail(
            store.connection,
            trajectory_id=trajectory.id,
            patch_trail_json=json_text(_patch_trail_payload(), sort_keys=True),
            patch_trail_digest="abc123",
            schema_version=PATCH_TRAIL_SCHEMA_VERSION,
            projected_at_utc=now,
        )
        store.commit()
    finally:
        store.close()

    def fail_writable_open(_path: Path) -> sqlite3.Connection:
        raise AssertionError("patch-trail retrieval must use read-only memory access")

    monkeypatch.setattr(memory_sqlite_store, "open_memory_db", fail_writable_open)

    service = CodeCloneMCPService(history_limit=4)
    out = service.get_patch_trail(
        root=str(root),
        run_id="30b56d21",
        patch_trail_digest="abc123",
    )

    _assert_structured_patch_trail_response(
        out,
        source="memory_trajectory_patch_trail",
    )
    _assert_patch_trail_retrieval_governance(out)
    governance = cast("dict[str, object]", out["context_governance"])
    response = cast("dict[str, object]", governance["response"])
    assert response["retrieval"] == "durable_audit_event_or_memory_projection"


def test_get_patch_trail_fail_closed_paths(tmp_path: Path) -> None:
    service = CodeCloneMCPService(history_limit=4)

    with pytest.raises(MCPServiceContractError, match="run_id or patch_trail_digest"):
        service.get_patch_trail(root=str(tmp_path))

    unsupported = service.get_patch_trail(
        root=str(tmp_path), run_id="30b56d21", format="summary"
    )
    assert unsupported["status"] == "unsupported_format"
    assert unsupported["supported_formats"] == ["structured"]

    not_found = service.get_patch_trail(root=str(tmp_path), run_id="deadbeef")
    assert not_found["status"] == "not_found"
    assert not_found["durable"] is True
