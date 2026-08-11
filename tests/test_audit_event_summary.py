# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from codeclone.audit.events import (
    EVENT_BASELINE_ABUSE,
    EVENT_CLAIM_VIOLATED,
    EVENT_INTENT_DECLARED,
    EVENT_PATCH_VERIFIED,
    EVENT_PATCH_VIOLATED,
    EVENT_RECEIPT_CREATED,
    EVENT_WORKSPACE_CONFLICT,
    _compact_analysis_completed_payload,
    event_summary,
)


def test_intent_declared_summary_unchanged() -> None:
    summary = event_summary(
        EVENT_INTENT_DECLARED, {"intent_description": "recover after restart"}
    )
    assert summary == "recover after restart"


def test_patch_violated_summary() -> None:
    summary = event_summary(
        EVENT_PATCH_VIOLATED,
        {
            "status": "violated",
            "structural_delta": {"regressions": [{"id": "x"}, {"id": "y"}]},
            "contract_violations": ["structural_regressions", "gate_failures"],
        },
    )
    assert summary == (
        "patch contract violated: 2 regression(s); "
        "structural_regressions, gate_failures"
    )


def test_workspace_conflict_summary() -> None:
    summary = event_summary(
        EVENT_WORKSPACE_CONFLICT, {"concurrent_intents": [{"id": "a"}, {"id": "b"}]}
    )
    assert summary == "workspace conflict: 2 concurrent intent(s)"


def test_baseline_abuse_summary() -> None:
    summary = event_summary(
        EVENT_BASELINE_ABUSE,
        {"baseline_abuse": {"detected": True, "triggers": ["suppressed_finding"]}},
    )
    assert summary == "baseline abuse detected: suppressed_finding"


def test_claim_violated_summary() -> None:
    summary = event_summary(
        EVENT_CLAIM_VIOLATED, {"valid": False, "violations": [{"c": 1}]}
    )
    assert summary == "claim validation failed: 1 violation(s)"


def test_receipt_created_summary() -> None:
    summary = event_summary(
        EVENT_RECEIPT_CREATED, {"format": "markdown", "receipt": {"verdict": "clean"}}
    )
    assert summary == "review receipt: clean"


def test_non_incident_event_has_no_summary() -> None:
    # patch_contract.verified is not an indexed incident -> no embeddable text.
    assert event_summary(EVENT_PATCH_VERIFIED, {"status": "accepted"}) is None


def test_none_payload_returns_none() -> None:
    assert event_summary(EVENT_PATCH_VIOLATED, None) is None


def test_compact_analysis_completed_does_not_stringify_a_missing_grade() -> None:
    """An unread run has no grade, and ``str(None)`` is not an absence.

    A run that opened no source file now reports ``score: null`` and
    ``grade: null``; the compaction used to write the four-character string
    "None" into the audit row, which reads like a value.
    """

    compact = _compact_analysis_completed_payload(
        {
            "source": "cli",
            "mode": "full",
            "focus": "repository",
            "health": {"score": None, "grade": None, "population": "unmeasured"},
            "findings": {"total": 0, "new": 0},
            "inventory": {"files": 0},
        }
    )

    assert compact["health_score"] is None
    assert compact["health_grade"] == ""


def test_compact_analysis_completed_keeps_a_measured_grade() -> None:
    """The reverse skew: a measured grade still reaches the audit row."""

    compact = _compact_analysis_completed_payload(
        {
            "source": "cli",
            "mode": "full",
            "focus": "repository",
            "health": {"score": 91, "grade": "A", "population": "complete_nonempty"},
            "findings": {"total": 0, "new": 0},
            "inventory": {"files": 12},
        }
    )

    assert compact["health_score"] == 91
    assert compact["health_grade"] == "A"
