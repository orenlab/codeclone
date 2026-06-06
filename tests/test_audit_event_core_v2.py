# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from codeclone.audit.events import (
    AUDIT_EVENT_CORE_VERSION,
    EVENT_INTENT_CHECKED,
    AuditEvent,
    event_core_for_event,
)


def _event(tmp_path: Path, **payload: object) -> AuditEvent:
    return AuditEvent(
        event_type=EVENT_INTENT_CHECKED,
        severity="info",
        repo_root_digest="digest",
        agent_pid=1,
        agent_label="agent",
        intent_id="intent-test",
        status="clean",
        payload=payload,
    )


def test_check_event_core_v2_includes_bounded_path_lists(tmp_path: Path) -> None:
    core = event_core_for_event(
        _event(
            tmp_path,
            status="clean",
            declared_scope=["pkg/a.py", "pkg/b.py"],
            actual_changed_files=["pkg/a.py"],
            unexpected_files=[],
            forbidden_touched=[],
        )
    )

    assert core["core_schema_version"] == AUDIT_EVENT_CORE_VERSION
    facts = core["facts"]
    assert isinstance(facts, dict)
    assert facts["changed_files"] == ["pkg/a.py"]
    assert facts["declared_scope_paths"] == ["pkg/a.py", "pkg/b.py"]
    assert facts["untouched_in_declared"] == ["pkg/b.py"]


def test_check_event_core_compact_payload_stays_count_only() -> None:
    from codeclone.audit.events import compact_payload_for_event

    compact = compact_payload_for_event(
        event_type=EVENT_INTENT_CHECKED,
        payload={
            "status": "clean",
            "declared_scope": ["pkg/a.py"],
            "actual_changed_files": ["pkg/a.py"],
            "unexpected_files": ["x.py"],
            "forbidden_touched": [],
        },
    )
    assert compact["unexpected_files"] == 1
    assert "changed_files" not in compact


def test_patch_trail_event_core_uses_counts() -> None:
    from codeclone.audit.events import (
        EVENT_PATCH_TRAIL_COMPUTED,
        event_core_for_event,
    )

    core = event_core_for_event(
        AuditEvent(
            event_type=EVENT_PATCH_TRAIL_COMPUTED,
            severity="info",
            repo_root_digest="digest",
            agent_pid=1,
            agent_label="agent",
            status="clean",
            payload={
                "schema_version": "1",
                "scope_check_status": "clean",
                "verification_status": "accepted",
                "declared_files": ["a.py", "b.py"],
                "changed_files": ["a.py"],
                "untouched_in_declared": ["b.py"],
                "unexpected_files": [],
                "forbidden_touched": [],
                "truncation": {},
                "patch_trail_digest": "abc",
            },
        )
    )
    facts = core["facts"]
    assert isinstance(facts, dict)
    assert facts["untouched_in_declared"] == 1
    assert facts["patch_trail_digest"] == "abc"
