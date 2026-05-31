# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from codeclone.memory.identity import make_identity_key
from codeclone.memory.models import (
    MemoryRecord,
    generate_memory_id,
)
from codeclone.memory.project import compute_project_id
from codeclone.report.meta import current_report_timestamp_utc


def test_make_identity_key_encodes_unsafe_segments() -> None:
    key = make_identity_key(
        type="risk_note",
        subject_kind="path",
        subject_key="codeclone/core/worker.py",
        discriminator="high:complexity",
    )
    assert key.startswith("risk_note:path:")
    assert ":" in key
    assert key.count(":") >= 3


def test_compute_project_id_is_deterministic(tmp_path: Path) -> None:
    first = compute_project_id(tmp_path)
    second = compute_project_id(tmp_path)
    assert first == second
    assert first.startswith("proj-")


def test_memory_record_frozen_fields() -> None:
    now = current_report_timestamp_utc()
    record = MemoryRecord(
        id=generate_memory_id(),
        project_id="proj-deadbeef",
        identity_key="module_role:module:codeclone:inventory",
        type="module_role",
        status="active",
        confidence="supported",
        origin="system",
        ingest_source="analysis",
        statement="test",
        summary=None,
        payload={"module_path": "codeclone"},
        created_at_utc=now,
        updated_at_utc=now,
        last_verified_at_utc=now,
        expires_at_utc=None,
        created_by="test",
        verified_by=None,
        approved_by=None,
        approved_at_utc=None,
        report_digest=None,
        code_fingerprint=None,
        stale_reason=None,
        created_on_branch=None,
        created_at_commit=None,
        verified_on_branch=None,
        verified_at_commit=None,
    )
    with pytest.raises(FrozenInstanceError):
        record.statement = "changed"  # type: ignore[misc]
