# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from codeclone.surfaces.mcp import _workspace_intent_models as workspace_intent_models
from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
from codeclone.surfaces.mcp._workspace_intent_models import (
    IntentIntegrityModel,
    IntentScopeModel,
    WorkspaceIntentRowModel,
    document_to_record_fields,
    parse_workspace_document,
    parse_workspace_document_json,
    record_from_document,
    signed_payload_dict_from_record,
    signed_payload_json_from_record,
)


def test_intent_scope_model_normalizes_paths() -> None:
    scope = IntentScopeModel.model_validate(
        {
            "allowed_files": ["pkg/a.py", "pkg/a.py", "./pkg/b.py"],
            "allowed_related": [],
            "forbidden": [".codeclone/**"],
        }
    )
    assert scope.allowed_files == ["./pkg/b.py", "pkg/a.py"]


def test_intent_scope_model_rejects_traversal() -> None:
    with pytest.raises(ValidationError):
        IntentScopeModel.model_validate(
            {"allowed_files": ["../outside.py"], "allowed_related": [], "forbidden": []}
        )


def test_intent_scope_model_rejects_empty_allowed_files() -> None:
    with pytest.raises(ValidationError, match="allowed_files must not be empty"):
        IntentScopeModel.model_validate(
            {"allowed_files": ["", "   "], "allowed_related": [], "forbidden": []}
        )


def test_intent_scope_model_skips_blank_entries() -> None:
    scope = IntentScopeModel.model_validate(
        {
            "allowed_files": ["pkg/a.py", "", "  "],
            "allowed_related": [],
            "forbidden": [],
        }
    )
    assert scope.allowed_files == ["pkg/a.py"]


def test_intent_integrity_model_rejects_invalid_digest() -> None:
    with pytest.raises(ValidationError, match="64-char hex digest"):
        IntentIntegrityModel.model_validate({"payload_sha256": "not-a-digest"})


def test_parse_workspace_document_json_rejects_invalid_payload() -> None:
    assert parse_workspace_document_json("{not-json") is None
    assert parse_workspace_document_json('{"registry_version":"2"}') is None


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
            "forbidden": [".codeclone/**"],
        },
        scope_digest=workspace_intents.compute_scope_digest(
            {
                "allowed_files": ["pkg/a.py"],
                "allowed_related": [],
                "forbidden": [".codeclone/**"],
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


def test_workspace_intent_document_rejects_naive_timestamp() -> None:
    from tests.test_workspace_intents import _record

    record = _record()
    payload = signed_payload_dict_from_record(record)
    payload["declared_at_utc"] = "2026-05-29T20:00:00"
    assert parse_workspace_document(payload) is None


def test_workspace_intent_document_rejects_invalid_dirty_snapshot() -> None:
    from tests.test_workspace_intents import _record

    record = replace(
        _record(),
        dirty_snapshot={
            "git_available": True,
            "captured_at_utc": "2026-05-29T20:00:00Z",
            "entries": {
                "../outside.py": {
                    "status_xy": " M",
                    "digest": "a" * 64,
                    "digest_status": "ok",
                }
            },
        },
    )
    assert parse_workspace_document(signed_payload_dict_from_record(record)) is None


@pytest.mark.parametrize(
    "dirty_snapshot",
    (
        (
            {
                "git_available": "yes",
                "captured_at_utc": "2026-05-29T20:00:00Z",
                "entries": {},
            }
        ),
        (
            {
                "git_available": True,
                "captured_at_utc": "not-utc",
                "entries": {},
            }
        ),
        (
            {
                "git_available": True,
                "captured_at_utc": "2026-05-29T20:00:00Z",
                "entries": {"pkg/a.py": {"status_xy": "M", "digest_status": "ok"}},
            }
        ),
        (
            {
                "git_available": True,
                "captured_at_utc": "2026-05-29T20:00:00Z",
                "entries": {"pkg/a.py": {"status_xy": " M", "digest_status": "ok"}},
            }
        ),
        (
            {
                "git_available": True,
                "captured_at_utc": "2026-05-29T20:00:00Z",
                "entries": {
                    "pkg/a.py": {
                        "status_xy": " M",
                        "digest": "a" * 64,
                        "digest_status": "bad",
                    }
                },
            }
        ),
    ),
)
def test_workspace_intent_document_dirty_snapshot_validation_messages(
    dirty_snapshot: dict[str, object],
) -> None:
    from tests.test_workspace_intents import _record

    record = replace(_record(), dirty_snapshot=dirty_snapshot)
    assert parse_workspace_document(signed_payload_dict_from_record(record)) is None


def test_signed_payload_json_roundtrip_via_pydantic() -> None:
    from tests.test_workspace_intents import _record

    record = replace(
        _record(),
        dirty_snapshot={
            "git_available": True,
            "captured_at_utc": "2026-05-29T20:00:00Z",
            "entries": {
                "pkg/a.py": {
                    "status_xy": " M",
                    "digest": "a" * 64,
                    "digest_status": "ok",
                }
            },
        },
    )
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


def test_workspace_intent_row_model_rejects_unsafe_intent_id() -> None:
    from tests.test_workspace_intents import _record

    record = _record()
    with pytest.raises(ValidationError):
        WorkspaceIntentRowModel.from_record_fields(
            agent_pid=record.agent_pid,
            agent_start_epoch=record.agent_start_epoch,
            intent_id="../evil",
            declared_at_utc=record.declared_at_utc,
            payload_json=signed_payload_json_from_record(record),
            updated_at_utc=record.declared_at_utc,
        )


def test_workspace_intent_document_to_record_fields_includes_lease_values() -> None:
    from tests.test_workspace_intents import _record

    payload = signed_payload_dict_from_record(_record())
    document = parse_workspace_document(payload)
    assert document is not None
    fields = document_to_record_fields(document)
    assert fields["lease_renewed_at_utc"] == document.lease_renewed_at_utc
    assert fields["lease_seconds"] == document.lease_seconds
    assert fields["report_digest"] == document.report_digest


def test_validate_dirty_snapshot_payload_private_edges() -> None:
    validate = workspace_intent_models._validate_dirty_snapshot_payload

    assert validate(None) is None
    with pytest.raises(ValueError, match=r"dirty_snapshot\.entries must be an object"):
        validate(
            {
                "git_available": True,
                "captured_at_utc": "2026-05-29T20:00:00Z",
                "entries": [],
            }
        )
    with pytest.raises(ValueError, match="entry path must be a non-empty string"):
        validate(
            {
                "git_available": True,
                "captured_at_utc": "2026-05-29T20:00:00Z",
                "entries": {"": {"status_xy": " M", "digest_status": "unavailable"}},
            }
        )
    with pytest.raises(ValueError, match="entry must be an object"):
        validate(
            {
                "git_available": True,
                "captured_at_utc": "2026-05-29T20:00:00Z",
                "entries": {"pkg/a.py": "bad"},
            }
        )
