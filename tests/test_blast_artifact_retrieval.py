# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Durable start-time blast artifact retrieval (get_blast_artifact)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest

from codeclone.audit import (
    DEFAULT_AUDIT_PATH,
    EVENT_BLAST_ARTIFACT_CREATED,
    AuditEvent,
    resolve_audit_path,
)
from codeclone.audit.reader import (
    BlastArtifactLookup,
    StoredBlastArtifact,
    lookup_blast_artifact,
)
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.surfaces.mcp._blast_radius import (
    BLAST_ARTIFACT_DETAIL_CONTRACT_VERSION,
    blast_radius_artifact_payload,
    blast_radius_summary_payload,
)
from codeclone.surfaces.mcp._session_shared import MCPServiceContractError
from codeclone.surfaces.mcp.service import CodeCloneMCPService


def _blast_payload(*, direct: str = "pkg/b.py") -> dict[str, object]:
    return {
        "run_id": "30b56d21",
        "origin": ["pkg/a.py"],
        "depth": "direct",
        "radius_level": "medium",
        "direct_dependents": [direct],
        "transitive_dependents": [],
        "clone_cohort_members": ["pkg/c.py"],
        "in_dependency_cycle": [],
        "structural_risk": {"low_coverage_in_blast_zone": ["pkg/b.py"]},
        "do_not_touch": [{"path": "codeclone.baseline.json", "severity": "hard"}],
        "do_not_touch_summary": {"total": 1, "shown": 1, "truncated": False},
        "review_context": [{"path": "pkg/d.py", "severity": "context"}],
        "review_context_summary": {"total": 1, "shown": 1, "truncated": False},
        "guardrails": ["review direct dependents before editing public behavior"],
    }


def _emit_blast_artifact(
    db_path: Path,
    *,
    run_id: str,
    blast_payload: dict[str, object],
    payloads: str = "compact",
) -> dict[str, object]:
    artifact = blast_radius_artifact_payload(
        blast_payload,
        source_tool="start_controlled_change",
    )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    writer = SqliteAuditWriter(
        db_path=db_path,
        payloads=cast("Any", payloads),
        retention_days=30,
    )
    writer.emit(
        AuditEvent(
            event_type=EVENT_BLAST_ARTIFACT_CREATED,
            severity="info",
            repo_root_digest="rootdigest0000",
            agent_pid=1,
            agent_start_epoch=1,
            agent_label="test",
            run_id=run_id,
            report_digest="reportdigest",
            status="medium",
            payload=artifact,
        )
    )
    writer.close()
    return artifact


def _artifact_id(artifact: dict[str, object]) -> str:
    return str(artifact["blast_artifact_id"])


def _projection_digest(artifact: dict[str, object]) -> str:
    digest = cast("dict[str, object]", artifact["projection_digest"])
    return str(digest["value"])


def _audit_db(root: Path) -> Path:
    return resolve_audit_path(root_path=root, value=DEFAULT_AUDIT_PATH)


def _ok_artifact(lookup: BlastArtifactLookup) -> StoredBlastArtifact:
    assert lookup.status == "ok"
    assert lookup.blast_artifact is not None
    return lookup.blast_artifact


def test_blast_radius_summary_omits_zero_lanes_from_omitted_evidence() -> None:
    empty_payload = {
        "run_id": "30b56d21",
        "origin": ["pkg/a.py"],
        "depth": "direct",
        "radius_level": "low",
        "direct_dependents": [],
        "transitive_dependents": [],
        "clone_cohort_members": [],
        "in_dependency_cycle": [],
        "structural_risk": {},
        "do_not_touch": [],
        "do_not_touch_summary": {"total": 0, "shown": 0, "truncated": False},
        "review_context": [],
        "review_context_summary": {"total": 0, "shown": 0, "truncated": False},
        "guardrails": [],
    }
    artifact = blast_radius_artifact_payload(
        empty_payload,
        source_tool="start_controlled_change",
    )
    summary = blast_radius_summary_payload(empty_payload, artifact=artifact)

    assert summary["omitted_evidence"] == {}
    assert "blast_artifact" in summary


def test_blast_radius_summary_omitted_evidence_uses_compact_retrieval() -> None:
    blast_payload = _blast_payload()
    artifact = blast_radius_artifact_payload(
        blast_payload,
        source_tool="start_controlled_change",
    )
    summary = blast_radius_summary_payload(blast_payload, artifact=artifact)
    omitted = cast("dict[str, object]", summary["omitted_evidence"])

    assert set(omitted) == {
        "direct_dependents",
        "clone_cohort_members",
        "review_context",
        "structural_risk",
    }
    direct = cast("dict[str, object]", omitted["direct_dependents"])
    retrieval = cast("dict[str, object]", direct["retrieval"])
    assert retrieval == {
        "blast_artifact_id": artifact["blast_artifact_id"],
        "run_id": artifact["run_id"],
        "retrieval_tool": "get_blast_artifact",
        "route": "get_blast_artifact(root=..., run_id=..., blast_artifact_id=...)",
    }
    assert "projection_digest" not in retrieval


def test_lookup_blast_artifact_compact_mode_preserves_full_projection(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "audit.sqlite3"
    artifact = _emit_blast_artifact(
        db_path,
        run_id="30b56d21",
        blast_payload=_blast_payload(),
        payloads="compact",
    )

    stored = _ok_artifact(
        lookup_blast_artifact(
            db_path,
            run_id="30b56d21",
            blast_artifact_id=_artifact_id(artifact),
        )
    )

    blast = cast("dict[str, object]", stored.payload["blast_radius"])
    assert stored.detail_contract_version == BLAST_ARTIFACT_DETAIL_CONTRACT_VERSION
    assert stored.projection_digest == _projection_digest(artifact)
    assert blast["direct_dependents"] == ["pkg/b.py"]
    assert blast["review_context"] == [{"path": "pkg/d.py", "severity": "context"}]


def test_lookup_blast_artifact_fail_closed_statuses(tmp_path: Path) -> None:
    missing = tmp_path / "absent.sqlite3"
    assert lookup_blast_artifact(missing, run_id="30b56d21").status == "not_found"

    db_path = tmp_path / "audit.sqlite3"
    first = _emit_blast_artifact(
        db_path,
        run_id="30b56d21",
        blast_payload=_blast_payload(direct="pkg/first.py"),
    )
    second = _emit_blast_artifact(
        db_path,
        run_id="30b56d21",
        blast_payload=_blast_payload(direct="pkg/second.py"),
    )

    assert lookup_blast_artifact(db_path, run_id="ffffffff").status == "not_found"
    assert lookup_blast_artifact(db_path, run_id="30b56d21").status == "ambiguous"
    pinned = _ok_artifact(
        lookup_blast_artifact(
            db_path,
            run_id="30b56d21",
            blast_artifact_id=_artifact_id(second),
        )
    )
    assert pinned.blast_artifact_id == _artifact_id(second)
    digest_mismatch = lookup_blast_artifact(
        db_path,
        run_id="30b56d21",
        projection_digest="0" * 64,
    )
    id_mismatch = lookup_blast_artifact(
        db_path,
        run_id="30b56d21",
        blast_artifact_id="blast-missing",
    )
    assert digest_mismatch.status == "digest_mismatch"
    assert id_mismatch.status == "artifact_id_mismatch"
    assert _artifact_id(first) != _artifact_id(second)


def test_lookup_blast_artifact_malformed_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    _emit_blast_artifact(
        db_path,
        run_id="30b56d21",
        blast_payload=_blast_payload(),
    )
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE controller_events SET payload_json='{not valid json' "
        "WHERE event_type=?",
        (EVENT_BLAST_ARTIFACT_CREATED,),
    )
    conn.commit()
    conn.close()

    assert (
        lookup_blast_artifact(db_path, run_id="30b56d21").status
        == "malformed_stored_blast_artifact"
    )


def test_get_blast_artifact_structured_post_clear(tmp_path: Path) -> None:
    artifact = _emit_blast_artifact(
        _audit_db(tmp_path),
        run_id="30b56d21",
        blast_payload=_blast_payload(),
    )
    service = CodeCloneMCPService(history_limit=4)

    out = service.get_blast_artifact(
        root=str(tmp_path),
        run_id="30b56d21",
        blast_artifact_id=_artifact_id(artifact),
    )

    assert {
        "status": out["status"],
        "format": out["format"],
        "source": out["source"],
        "durable": out["durable"],
        "blast_artifact_id": out["blast_artifact_id"],
    } == {
        "status": "ok",
        "format": "structured",
        "source": "audit_event",
        "durable": True,
        "blast_artifact_id": _artifact_id(artifact),
    }
    blast = cast("dict[str, object]", out["blast_radius"])
    assert blast["direct_dependents"] == ["pkg/b.py"]
    governance = cast("dict[str, object]", out["context_governance"])
    response = cast("dict[str, object]", governance["response"])
    assert response["tool"] == "get_blast_artifact"


def test_get_blast_artifact_fail_closed_paths(tmp_path: Path) -> None:
    service = CodeCloneMCPService(history_limit=4)

    with pytest.raises(MCPServiceContractError, match="run_id"):
        service.get_blast_artifact(root=str(tmp_path))

    unsupported = service.get_blast_artifact(
        root=str(tmp_path),
        run_id="30b56d21",
        format="summary",
    )
    not_found = service.get_blast_artifact(root=str(tmp_path), run_id="deadbeef")

    assert unsupported["status"] == "unsupported_format"
    assert unsupported["supported_formats"] == ["structured"]
    assert not_found["status"] == "not_found"
    assert not_found["durable"] is True
