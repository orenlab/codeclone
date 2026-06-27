# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Phase 34.4 — durable post-clear review receipt retrieval (get_review_receipt).

These tests write a review_receipt.created event to the audit trail and then read
it back through a FRESH service that has no session knowledge of the run, proving
retrieval is durable and post-clear: it reads stored evidence, never re-derives.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from codeclone.audit import (
    DEFAULT_AUDIT_PATH,
    EVENT_RECEIPT_CREATED,
    AuditEvent,
    resolve_audit_path,
)
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.surfaces.mcp._session_shared import MCPServiceContractError
from codeclone.surfaces.mcp.service import CodeCloneMCPService


def _receipt_payload(
    *, verdict: str = "clean", digest: str = "abc123"
) -> dict[str, object]:
    return {
        "run_id": "30b56d21",
        "format": "markdown",
        "receipt_version": "1",
        "verdict": verdict,
        "receipt_digest": {
            "kind": "receipt_v1",
            "algorithm": "sha256",
            "digest_version": "1",
            "value": digest,
        },
        "content": "## CodeClone Agent Review Receipt\nverdict: " + verdict,
        "receipt": {"receipt_version": "1", "verdict": verdict, "provenance": {}},
    }


def _emit_receipt(root: Path, *, run_id: str, payload: dict[str, object]) -> None:
    db_path = resolve_audit_path(root_path=root, value=DEFAULT_AUDIT_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    writer = SqliteAuditWriter(db_path=db_path, payloads="compact", retention_days=30)
    writer.emit(
        AuditEvent(
            event_type=EVENT_RECEIPT_CREATED,
            severity="info",
            repo_root_digest="rootdigest0000",
            agent_pid=1,
            agent_start_epoch=1,
            agent_label="test",
            run_id=run_id,
            intent_id=None,
            report_digest="reportdigest",
            status=str(payload.get("verdict", "")),
            payload=payload,
        )
    )
    writer.close()


def test_get_review_receipt_structured_post_clear(tmp_path: Path) -> None:
    _emit_receipt(tmp_path, run_id="30b56d21", payload=_receipt_payload())
    # Fresh service: no in-memory run/intent for this run id (i.e. post-clear).
    service = CodeCloneMCPService(history_limit=4)

    out = service.get_review_receipt(
        root=str(tmp_path), run_id="30b56d21", receipt_digest="abc123"
    )

    assert out["status"] == "ok"
    assert out["format"] == "structured"
    assert out["source"] == "audit_event"
    assert out["durable"] is True
    assert out["receipt_digest"] == "abc123"
    structured = cast("dict[str, object]", out["structured_receipt"])
    assert structured["verdict"] == "clean"
    governance = cast("dict[str, object]", out["context_governance"])
    response = cast("dict[str, object]", governance["response"])
    assert response["tool"] == "get_review_receipt"


def test_get_review_receipt_markdown(tmp_path: Path) -> None:
    _emit_receipt(tmp_path, run_id="30b56d21", payload=_receipt_payload())
    service = CodeCloneMCPService(history_limit=4)

    out = service.get_review_receipt(
        root=str(tmp_path), run_id="30b56d21", format="markdown"
    )

    assert out["status"] == "ok"
    assert out["format"] == "markdown"
    assert "CodeClone Agent Review Receipt" in str(out["content"])


def test_get_review_receipt_unsupported_format(tmp_path: Path) -> None:
    service = CodeCloneMCPService(history_limit=4)
    out = service.get_review_receipt(
        root=str(tmp_path), run_id="30b56d21", format="json"
    )
    assert out["status"] == "unsupported_format"
    assert out["requested_format"] == "json"
    assert out["supported_formats"] == ["markdown", "structured"]


def test_get_review_receipt_requires_a_lookup_key(tmp_path: Path) -> None:
    service = CodeCloneMCPService(history_limit=4)
    with pytest.raises(MCPServiceContractError, match="run_id or receipt_digest"):
        service.get_review_receipt(root=str(tmp_path))


def test_get_review_receipt_not_found(tmp_path: Path) -> None:
    service = CodeCloneMCPService(history_limit=4)
    out = service.get_review_receipt(root=str(tmp_path), run_id="deadbeef")
    assert out["status"] == "not_found"
    assert out["durable"] is True


def test_get_review_receipt_digest_mismatch(tmp_path: Path) -> None:
    _emit_receipt(tmp_path, run_id="30b56d21", payload=_receipt_payload(digest="aaa"))
    service = CodeCloneMCPService(history_limit=4)
    out = service.get_review_receipt(
        root=str(tmp_path), run_id="30b56d21", receipt_digest="zzz"
    )
    assert out["status"] == "digest_mismatch"
