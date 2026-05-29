# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
from codeclone.surfaces.mcp._workspace_intent_models import (
    IntentScopeModel,
    WorkspaceIntentRowModel,
    parse_workspace_document,
    record_from_document,
    signed_payload_dict_from_record,
    signed_payload_json_from_record,
)


def test_intent_scope_model_normalizes_paths() -> None:
    scope = IntentScopeModel.model_validate(
        {
            "allowed_files": ["pkg/a.py", "pkg/a.py", "./pkg/b.py"],
            "allowed_related": [],
            "forbidden": [".cache/codeclone/**"],
        }
    )
    assert scope.allowed_files == ["./pkg/b.py", "pkg/a.py"]


def test_intent_scope_model_rejects_traversal() -> None:
    with pytest.raises(ValidationError):
        IntentScopeModel.model_validate(
            {"allowed_files": ["../outside.py"], "allowed_related": [], "forbidden": []}
        )


def test_workspace_intent_document_rejects_tampered_integrity() -> None:
    record = workspace_intents.WorkspaceIntentRecord(
        intent_id="intent-abcdef12-001",
        agent_pid=1000,
        agent_start_epoch=100,
        agent_label="agent",
        run_id="run1234567890",
        declared_at_utc="2026-05-29T20:00:00Z",
        expires_at_utc="2026-05-29T21:00:00Z",
        ttl_seconds=3600,
        status="active",
        intent="edit pkg",
        scope={
            "allowed_files": ["pkg/a.py"],
            "allowed_related": [],
            "forbidden": [".cache/codeclone/**"],
        },
        scope_digest=workspace_intents.compute_scope_digest(
            {
                "allowed_files": ["pkg/a.py"],
                "allowed_related": [],
                "forbidden": [".cache/codeclone/**"],
            }
        ),
        blast_radius_summary={"radius_level": "medium"},
        lease_renewed_at_utc="2026-05-29T20:00:00Z",
        lease_seconds=workspace_intents.DEFAULT_LEASE_SECONDS,
        report_digest="digest-a",
    )
    payload = signed_payload_dict_from_record(record)
    payload["intent"] = "tampered"
    assert parse_workspace_document(payload) is None


def test_signed_payload_json_roundtrip_via_pydantic() -> None:
    from tests.test_workspace_intents import _record

    record = _record()
    payload_json = signed_payload_json_from_record(record)
    document = parse_workspace_document(json.loads(payload_json))
    assert document is not None
    roundtrip = record_from_document(document)
    assert roundtrip == record


def test_workspace_intent_row_model_validates_payload_json() -> None:
    from tests.test_workspace_intents import _record

    record = _record()
    row = WorkspaceIntentRowModel.from_record_fields(
        agent_pid=record.agent_pid,
        agent_start_epoch=record.agent_start_epoch,
        intent_id=record.intent_id,
        declared_at_utc=record.declared_at_utc,
        payload_json=signed_payload_json_from_record(record),
        updated_at_utc=record.declared_at_utc,
    )
    assert row.intent_id == record.intent_id

    with pytest.raises(ValidationError):
        WorkspaceIntentRowModel.from_record_fields(
            agent_pid=record.agent_pid,
            agent_start_epoch=record.agent_start_epoch,
            intent_id=record.intent_id,
            declared_at_utc=record.declared_at_utc,
            payload_json="{not-json",
            updated_at_utc=record.declared_at_utc,
        )
