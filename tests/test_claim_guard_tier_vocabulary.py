# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Claim Guard must know the advisory clone-tier vocabulary.

Sanction of 2026-08-26: *"claim guard должен знать тир-словарь; 'no
near-miss clones' не должен проходить без проверки"*.

The two advisory clone tiers, ``near_miss`` and ``renamed_structure``,
carry an execution witness in their container: ``state`` (T1,
2026-08-24). ``disabled`` means the producer was never invoked and the
container omits ``count`` entirely — there is no measurement to quote.
``complete`` means the producer ran, and ``count: 0`` is then a real,
empty result.

Before this pin the guard had no tier vocabulary at all: a review saying
"no near-miss clones were found" validated clean against a run in which
the near-miss producer had never been invoked. That is a lie of the
instrument — the absence was never measured — and it is the shape P-5
already rejects one lane over ("fix claimed, no post-patch run
available"): a claim whose evidence does not exist. The MCP surface is
where the class bites hardest, because the tier opt-ins are not exposed
through it at all: every run reaching an agent through MCP has both
tiers ``disabled``, which the first pin below asserts rather than
assumes.

The vocabulary is derived, never restated. These pins take it from a
**real analysis run through the MCP surface**, so a third tier container
is covered the day the producers emit it: the tests iterate whatever the
run actually carries. Reading it from the report producers directly would
be an r2 import from an r4 test — the boundary ratchet's ring law — and
the surface's own document is in any case the stronger derivation: it
proves the witness survives the whole wire into the record the guard
reads.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import codeclone.surfaces.mcp._session_claim_guard_mixin as mcp_claim_session_mod
from codeclone.contracts import TIER_STATE_COMPLETE, TIER_STATE_DISABLED
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest, MCPRunRecord
from codeclone.surfaces.mcp.service import CodeCloneMCPService

_COMPLETE_RUN_ID = "claimguardtiercomplete0001"

#: The tiers the producers ship today, as an INDEPENDENT witness of the
#: universe. Every other pin in this file derives its tier set from the
#: extractor, which makes the extractor's own output the universe of its
#: coverage: drop a tier there and it leaves the pins' universe together
#: with its coverage, so a silently halved vocabulary reads as green. A
#: literal floor is the honest anchor precisely because the derivation is
#: the thing under suspicion — the same shape as a born-empty composition
#: pin. It is a fact of today's producer set and moves only by a declared
#: tier transition, never to accommodate a mutation.
KNOWN_TIERS = frozenset({"near_miss", "renamed_structure"})


def _write_fixture(root: Path) -> None:
    package = root / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    package.joinpath("__init__.py").write_text("", "utf-8")
    package.joinpath("units.py").write_text(
        (
            "def alpha(value: int) -> int:\n"
            "    total = value + 1\n"
            "    total += 2\n"
            "    total += 3\n"
            "    total += 4\n"
            "    return total\n\n"
            "def beta(value: int) -> int:\n"
            "    total = value + 1\n"
            "    total += 2\n"
            "    total += 3\n"
            "    total += 4\n"
            "    return total\n"
        ),
        "utf-8",
    )


def _analyzed(root: Path) -> tuple[CodeCloneMCPService, MCPRunRecord]:
    """One real MCP analysis; its record is what the claim guard reads."""

    _write_fixture(root)
    service = CodeCloneMCPService(history_limit=4)
    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(root),
            respect_pyproject=False,
        )
    )
    record = service._runs.resolve_any_root(str(summary["run_id"]))
    return service, record


def _tier_states(record: MCPRunRecord) -> dict[str, str]:
    return dict(
        mcp_claim_session_mod._tier_states_from_report_document(record.report_document)
    )


def _with_completed_tiers(record: MCPRunRecord) -> MCPRunRecord:
    """The same run, rewritten so every tier reports a completed measurement.

    The two state words come from the contract that owns them, not from a
    literal retyped here, and the count is added because a completed tier
    must utter one.
    """

    document = copy.deepcopy(record.report_document)
    findings = cast("dict[str, object]", document["findings"])
    groups = cast("dict[str, object]", findings["groups"])
    for container in groups.values():
        if not isinstance(container, dict):
            continue
        if str(container.get("tier", "")).strip():
            container["state"] = TIER_STATE_COMPLETE
            container["count"] = 0
    return replace(record, run_id=_COMPLETE_RUN_ID, report_document=document)


def _validate(
    service: CodeCloneMCPService,
    record: MCPRunRecord,
    text: str,
) -> dict[str, object]:
    return service._validate_review_claims_for_record(
        record=record,
        text=text,
        require_citations=False,
    )


def _patterns(payload: dict[str, object]) -> set[str]:
    violations = cast("list[dict[str, object]]", payload["violations"])
    return {str(item["pattern"]) for item in violations}


def _cited_ids(payload: dict[str, object]) -> set[str]:
    violations = cast("list[dict[str, object]]", payload["violations"])
    return {str(item["cited_id"]) for item in violations}


def _reason_for(payload: dict[str, object], tier: str) -> str:
    violations = cast("list[dict[str, object]]", payload["violations"])
    reasons = [
        str(item["reason"]) for item in violations if str(item["cited_id"]) == tier
    ]
    assert reasons, f"no violation cited {tier!r}: {violations}"
    return reasons[0]


def _assert_reason_is_self_explaining(reason: str, *, tier: str) -> None:
    """A refusal must carry its own explanation, not a bare label.

    ``valid: False`` on its own tells an agent that something was rejected,
    not what or why, and leaves nothing in-band to act on. The assertions
    run against the RENDERED reason and deliberately NOT against the message
    template: comparing the output to the template it was rendered from
    passes even when the template has stopped interpolating the tier
    entirely, which is the hollow shape this pin exists to avoid.
    """

    assert tier in reason, f"the rejection does not name the tier: {reason!r}"
    assert TIER_STATE_DISABLED in reason, (
        f"the rejection does not name the state it read: {reason!r}"
    )


def test_every_tier_reaching_mcp_is_disabled_and_names_its_own_state(
    tmp_path: Path,
) -> None:
    """The witness comes off a real run; the universe is anchored independently.

    ``assert states`` and "every value is disabled" are both satisfied by a
    vocabulary missing a tier, so on their own they cannot see an extractor
    that drops one. :data:`KNOWN_TIERS` is the independent floor that can:
    a tier the extractor stops reporting reds here by name instead of
    quietly shrinking every other pin's universe.

    The floor is a floor, not an equality: a tier added later is expected to
    appear here without a test edit, and is caught by the per-tier pin.
    """

    _service, record = _analyzed(tmp_path)
    states = _tier_states(record)

    assert states, (
        "the run's report document carried no tier container the session can "
        "read; the guard would have nothing to check a tier claim against"
    )
    assert set(states) >= KNOWN_TIERS, (
        "the derived vocabulary lost a tier the producers still ship: "
        f"missing {sorted(KNOWN_TIERS - set(states))}, derived {sorted(states)}"
    )
    assert set(states.values()) == {TIER_STATE_DISABLED}, (
        f"MCP exposes no tier opt-in, so every tier must arrive unmeasured: {states}"
    )


def test_a_group_container_that_is_not_a_mapping_is_skipped_not_fatal() -> None:
    """A malformed or foreign document must not take the claim lane down.

    ``findings.groups`` values are typed ``object``; nothing in the record
    guarantees each group is a mapping. Every production document happens to
    make them all mappings, so without this pin the narrowing branch would be
    a guard no input reaches — theater by the project's own rule — and the
    first foreign document would turn a claim check into a crash.
    """

    states = mcp_claim_session_mod._tier_states_from_report_document(
        {
            "findings": {
                "groups": {
                    "clones": ["not a mapping"],
                    "near_miss": {"tier": "near_miss", "state": TIER_STATE_DISABLED},
                }
            }
        }
    )

    assert dict(states) == {"near_miss": TIER_STATE_DISABLED}


def test_absence_claim_about_a_disabled_tier_is_rejected(tmp_path: Path) -> None:
    """The sanctioned sentence: it must not validate against a tier that never ran."""

    service, record = _analyzed(tmp_path)

    payload = _validate(
        service,
        record,
        "No near-miss clones were found in this run.",
    )

    assert payload["valid"] is False, (
        "'no near-miss clones' validated clean while the near_miss producer "
        "never ran: the guard has no tier vocabulary"
    )
    assert _patterns(payload) == {"P-6"}
    violations = cast("list[dict[str, object]]", payload["violations"])
    # The violation must name the container state it read, not merely assert.
    assert violations[0]["source_flag"] == "findings.groups.near_miss.state=disabled"
    _assert_reason_is_self_explaining(
        _reason_for(payload, "near_miss"),
        tier="near_miss",
    )


def test_the_same_absence_claim_is_honest_when_the_tier_completed(
    tmp_path: Path,
) -> None:
    """Opposite boundary: at ``complete``/``count: 0`` the claim is true.

    Without this pin a guard that rejected every tier sentence would look
    identical to a guard that reads the container state.
    """

    service, record = _analyzed(tmp_path)
    completed = _with_completed_tiers(record)

    payload = _validate(
        service,
        completed,
        "No near-miss clones were found in this run.",
    )

    assert payload["valid"] is True, (
        "a completed empty measurement makes 'no near-miss clones' true; "
        "the guard must not reject it"
    )
    assert payload["violations"] == []


def test_every_disabled_tier_rejects_an_absence_claim_naming_it(
    tmp_path: Path,
) -> None:
    """No tier is a special case: the rule is the container state, per tier.

    The loop runs over the independent floor UNION the derived vocabulary,
    never the derived vocabulary alone. Iterating only what the extractor
    reports makes the component under test the author of its own coverage:
    a dropped tier is not tested rather than failing, which is how a halved
    vocabulary passed 6875 tests. The union keeps the forward property —
    a tier added later is covered without a test edit — while the floor
    holds the two that exist today.
    """

    service, record = _analyzed(tmp_path)

    for tier in sorted(KNOWN_TIERS | set(_tier_states(record))):
        payload = _validate(
            service,
            record,
            f"There are no {tier} groups anywhere in this repository.",
        )
        assert payload["valid"] is False, f"tier {tier!r} escaped the guard"
        assert _patterns(payload) == {"P-6"}
        assert _cited_ids(payload) == {tier}
        _assert_reason_is_self_explaining(_reason_for(payload, tier), tier=tier)


@pytest.mark.parametrize(
    ("case", "text"),
    [
        # An outcome verb plus a tally: the tier is credited with findings it
        # never produced. A guard that only caught the word "no" would leave
        # this mirror-image fabrication passing clean.
        (
            "outcome_verb",
            "The near_miss tier detected 3 duplicate pairs worth reviewing.",
        ),
        # A tally needs no verb to be a claim. Without this row the count half
        # of the predicate is a branch no input reaches — every other
        # measurement sentence in this file also carries an outcome word, so
        # the branch would be theater.
        ("bare_count", "near_miss: 2 pairs."),
    ],
)
def test_presence_claim_about_a_disabled_tier_is_rejected(
    tmp_path: Path,
    case: str,
    text: str,
) -> None:
    """Both polarities are unsupported while the producer never ran."""

    service, record = _analyzed(tmp_path)

    payload = _validate(service, record, text)

    assert payload["valid"] is False, f"{case}: a presence claim escaped the guard"
    assert _patterns(payload) == {"P-6"}


def test_non_measurement_tier_mentions_stay_valid_while_disabled(
    tmp_path: Path,
) -> None:
    """Naming a tier is not claiming its result.

    True statements about the tier's standing must survive, or the guard
    becomes a keyword sledgehammer that teaches reviewers to stop naming the
    tiers at all.

    Both halves of the predicate are pinned separately: the first two
    sentences name an outcome with nothing measured, and the third names the
    measured thing with no outcome claimed. Dropping either half of the
    requirement reds exactly one of them.
    """

    service, record = _analyzed(tmp_path)

    payload = _validate(
        service,
        record,
        (
            "The near_miss tier is disabled in this run. "
            "renamed_structure has no gate relevance and never reaches a "
            "baseline lane. "
            "near_miss ranks clone pairs by edit distance."
        ),
    )

    assert payload["valid"] is True, (
        f"the guard flagged a non-measurement mention: {payload['violations']}"
    )


def test_prose_spellings_of_a_tier_name_all_reach_the_guard(tmp_path: Path) -> None:
    """Reviews write "near-miss", not ``near_miss``; all three must cite the tier."""

    service, record = _analyzed(tmp_path)

    for spelling in ("near_miss", "near-miss", "near miss"):
        payload = _validate(
            service,
            record,
            f"We found no {spelling} clones anywhere.",
        )
        assert payload["valid"] is False, f"spelling {spelling!r} escaped the guard"
        assert _patterns(payload) == {"P-6"}
        assert _cited_ids(payload) == {"near_miss"}
