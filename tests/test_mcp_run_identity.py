# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""What the MCP run identity is allowed to depend on.

``_report_digest`` is the run id, the run-store key, the intent's report
digest and the receipt's provenance digest. Two properties make that identity
usable, and they pull in opposite directions:

* it must move whenever the answer moves -- otherwise two runs that disagree
  are stored under one key and the second silently replaces the first;
* it must hold still when only the clock moves -- otherwise every re-analysis
  is a new run by construction and ``after_run_not_new`` can never fire.

Exactly one digest tier satisfies both, and these two tests are the pair that
says so: the first refuses every tier below ``evaluation``, the second refuses
the envelope above it.
"""

from __future__ import annotations

from collections.abc import Mapping

from codeclone.surfaces.mcp import _session_helpers as _helpers
from codeclone.utils.mapping_paths import section

from ._report_fixtures import (
    GATE_POLICY_GENERATED_AT,
    build_gate_policy_report_document,
)

_GENERATED_AT_LATER = "2026-08-13T11:00:00Z"


def _digest(document: Mapping[str, object], tier: str) -> str:
    value = section(document, f"integrity.digests.{tier}").get("value")
    assert isinstance(value, str) and value
    return value


def _health_score(document: Mapping[str, object]) -> int:
    score = section(document, "metrics.families.health.summary").get("score")
    assert isinstance(score, int)
    return score


def _exit_code(document: Mapping[str, object]) -> int:
    exit_code = section(document, "evaluation.outcome").get("exit_code")
    assert isinstance(exit_code, int)
    return exit_code


def _gate_reasons(document: Mapping[str, object]) -> list[object]:
    reasons = section(document, "evaluation.outcome").get("reasons")
    assert isinstance(reasons, list)
    return reasons


def test_run_identity_moves_when_the_gate_verdict_moves() -> None:
    """Same tree, different thresholds, different verdicts -- different ids.

    The run store is keyed by ``(root, run_id)``, so two runs sharing an id
    are one record: the second registration replaces the first, and the
    evidence that the two disagreed is gone. Taking the id from the comparison
    tier -- facts and baseline, no policy -- produced exactly that, because
    the thresholds and the outcome live one tier above it.

    The fixture makes an accidental pass impossible: the two runs are asserted
    to share every tier below ``evaluation`` (same tree, same baseline) and to
    disagree on the verdict, with the strict run carrying a real gate reason
    rather than a silent refusal.
    """

    probe = build_gate_policy_report_document()
    score = _health_score(probe)
    assert 10 <= score <= 90, "fixture must leave room on both sides of the score"

    lenient = build_gate_policy_report_document(fail_health=score - 10)
    strict = build_gate_policy_report_document(fail_health=score + 10)

    assert _exit_code(lenient) == 0
    assert _exit_code(strict) != 0
    assert _gate_reasons(strict)

    for tier in ("observation", "analysis_facts", "comparison"):
        assert _digest(lenient, tier) == _digest(strict, tier), tier

    assert _helpers._report_digest(lenient) != _helpers._report_digest(strict)


def test_run_identity_holds_still_when_only_the_clock_moves() -> None:
    """Re-measuring an unchanged tree must not mint a new identity.

    ``meta.runtime.report_generated_at_utc`` is the document's only time-like
    field, and only the envelope tier seals it. An identity taken from the
    envelope would be new on every run, which reads as honest and is not: it
    would leave ``after_run_not_new`` permanently unable to fire, so a cycle
    that never re-analysed anything would verify as if it had.
    """

    first = build_gate_policy_report_document()
    second = build_gate_policy_report_document(
        report_generated_at_utc=_GENERATED_AT_LATER
    )

    assert (
        section(first, "meta.runtime").get("report_generated_at_utc")
        == GATE_POLICY_GENERATED_AT
    )
    assert (
        section(second, "meta.runtime").get("report_generated_at_utc")
        == _GENERATED_AT_LATER
    )
    assert _digest(first, "envelope") != _digest(second, "envelope")

    assert _helpers._report_digest(first) == _helpers._report_digest(second)
