# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Phase 34 — durable post-clear patch-trail retrieval (get_patch_trail).

These tests write a patch_trail.computed event to the audit trail and read it
back through a FRESH service with no session knowledge of the run, proving the
full forensic trail is durable and post-clear: it reads stored evidence exactly
as persisted (forensic-retention), never re-derives or summarizes it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest

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
from codeclone.surfaces.mcp._session_shared import MCPServiceContractError
from codeclone.surfaces.mcp.service import CodeCloneMCPService


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

    assert out["status"] == "ok"
    assert out["format"] == "structured"
    assert out["source"] == "audit_event"
    assert out["durable"] is True
    assert out["patch_trail_digest"] == "abc123"
    trail = cast("dict[str, object]", out["patch_trail"])
    assert trail["declared_files"] == ["a.py"]
    assert trail["verification_status"] == "accepted"
    governance = cast("dict[str, object]", out["context_governance"])
    response = cast("dict[str, object]", governance["response"])
    assert response["tool"] == "get_patch_trail"


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
