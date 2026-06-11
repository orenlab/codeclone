# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json

from codeclone.audit.events import (
    EVENT_ANALYSIS_COMPLETED,
    EVENT_INTENT_CLEARED,
    EVENT_INTENT_QUEUE_BLOCKED,
    EVENT_PATCH_TRAIL_COMPUTED,
    EVENT_RECEIPT_CREATED,
    EVENT_WORKSPACE_GC,
    AuditEvent,
    compact_payload_for_event,
    event_core_for_event,
    event_summary,
    projection_supplement_facts_from_payload,
)


def _facts(core: dict[str, object]) -> dict[str, object]:
    value = core["facts"]
    assert isinstance(value, dict)
    return value


def _event(event_type: str, **payload: object) -> AuditEvent:
    return AuditEvent(
        event_type=event_type,
        severity="info",
        repo_root_digest="digest",
        agent_pid=1,
        agent_label="agent",
        status="ok",
        payload=payload,
    )


def test_compact_payload_for_patch_trail_and_receipt() -> None:
    patch_trail = compact_payload_for_event(
        event_type=EVENT_PATCH_TRAIL_COMPUTED,
        payload={
            "patch_trail_digest": "abc",
            "scope_check_status": "clean",
            "verification_status": "accepted",
            "declared_files": ["a.py"],
            "changed_files": ["a.py"],
            "untouched_in_declared": [],
            "unexpected_files": [],
            "forbidden_touched": [],
            "truncation": {"declared_files": True},
        },
    )
    assert patch_trail["declared"] == 1
    assert patch_trail["truncation"] is True

    receipt = compact_payload_for_event(
        event_type=EVENT_RECEIPT_CREATED,
        payload={
            "format": "markdown",
            "receipt": {"verdict": "clean", "human_decision_points": [{"id": "x"}]},
        },
    )
    assert receipt["verdict"] == "clean"
    assert receipt["human_decisions"] == 1


def test_event_core_for_workspace_and_queue_events() -> None:
    queue = event_core_for_event(
        _event(
            EVENT_INTENT_QUEUE_BLOCKED,
            intent_id="intent-q",
            blocking_count=2,
        )
    )
    assert _facts(queue)["blocking_count"] == 2

    cleared = event_core_for_event(
        _event(EVENT_INTENT_CLEARED, cleared=1, workspace_cleared=True)
    )
    assert _facts(cleared)["cleared"] == 1
    assert _facts(cleared)["workspace_cleared"] is True

    gc = event_core_for_event(
        _event(EVENT_WORKSPACE_GC, removed=3, stale_count=1, orphaned_count=2)
    )
    assert _facts(gc)["removed"] == 3
    assert _facts(gc)["orphaned_count"] == 2


def test_event_core_for_receipt_and_check_paths() -> None:
    receipt_core = event_core_for_event(
        _event(
            EVENT_RECEIPT_CREATED,
            format="json",
            receipt={"verdict": "needs_attention", "human_decision_points": [1, 2]},
        )
    )
    facts = _facts(receipt_core)
    assert facts["format"] == "json"
    assert facts["human_decisions"] == 2

    check_core = event_core_for_event(
        _event(
            "intent.checked",
            status="clean",
            declared_scope=["pkg/a.py", "pkg/b.py"],
            actual_changed_files=["pkg/a.py"],
            unexpected_files=["extra.py"],
            forbidden_touched=["codeclone.baseline.json"],
        )
    )
    check_facts = _facts(check_core)
    assert check_facts["unexpected_files_list"] == ["extra.py"]
    assert check_facts["forbidden_touched_list"] == ["codeclone.baseline.json"]


def test_analysis_completed_summary_and_projection_supplement() -> None:
    summary = event_summary(
        EVENT_ANALYSIS_COMPLETED,
        {"source": "mcp", "health": {"score": 91}},
    )
    assert summary == "analysis completed (mcp): health=91"

    payload = json.dumps(
        {
            "scope": {"allowed_files": ["pkg/a.py"]},
            "intent_description": "test",
        }
    )
    supplement = projection_supplement_facts_from_payload(
        "intent.declared",
        payload,
    )
    assert supplement.get("scope_paths") == ["pkg/a.py"]
    assert projection_supplement_facts_from_payload("intent.declared", "{bad") == {}
    assert projection_supplement_facts_from_payload("intent.declared", None) == {}

    intent_cleared = event_core_for_event(
        _event("intent.cleared", cleared=2, workspace_cleared=False)
    )
    assert _facts(intent_cleared)["cleared"] == 2

    workspace_conflict = compact_payload_for_event(
        event_type="workspace.conflict_detected",
        payload={"concurrent_intents": [{"id": "a"}]},
    )
    assert workspace_conflict["concurrent_intents"] == 1

    analysis = compact_payload_for_event(
        event_type=EVENT_ANALYSIS_COMPLETED,
        payload={
            "source": "cli",
            "mode": "full",
            "health": {"score": 88, "grade": "B"},
            "findings": {"total": 3, "new": 1},
            "inventory": {"files": 10},
        },
    )
    assert analysis["health_score"] == 88
    assert analysis["findings_total"] == 3

    cleared_core = event_core_for_event(
        _event(EVENT_INTENT_CLEARED, cleared=1, workspace_cleared=True)
    )
    assert _facts(cleared_core)["workspace_cleared"] is True

    patch_trail_core = event_core_for_event(
        _event(
            EVENT_PATCH_TRAIL_COMPUTED,
            counts={"declared": 2, "changed": 1},
            scope_check_status="clean",
            verification_status="accepted",
            patch_trail_digest="digest",
            truncation={},
        )
    )
    assert _facts(patch_trail_core)["declared"] == 2

    many_citations = [
        {"kind": "finding", "cited_id": f"f-{index}", "valid": True}
        for index in range(40)
    ]
    claim_payload = event_core_for_event(
        _event(
            "claim_validation.completed",
            valid=True,
            citations_found=40,
            validated_citations=[
                *many_citations,
                {"kind": "", "cited_id": "", "valid": False},
            ],
        )
    )
    claim_facts = claim_payload["facts"]
    assert isinstance(claim_facts, dict)
    assert claim_facts.get("citations_truncated") is True
    assert len(claim_facts.get("citations", [])) == 32

    supplement = projection_supplement_facts_from_payload(
        "intent.declared",
        json.dumps(["not", "mapping"]),
    )
    assert supplement == {}
