# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Patch-contract next_step hints and status messages."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

NEXT_STEP_HINTS: Final[dict[str, str]] = {
    "no_before_run": (
        "Run analyze_repository(root=<repo root>), then pass the run_id as"
        " before_run_id — or pass intent_id to auto-resolve."
    ),
    "no_after_run": (
        "Run analyze_repository(root=<repo root>) after editing, then pass"
        " the new run_id as after_run_id."
    ),
    "after_run_not_new": (
        "No analysis of this root has run since the intent went active, or "
        "the one offered is the intent's own before-run. Call "
        "analyze_repository(root=<intent root>) now, after the edit, and pass "
        "its run_id as after_run_id. A different run_id verifies structurally; "
        "an identical one is accepted as analyzer_invariant, because a fresh "
        "recompute landing on the same content-addressed id proves the change "
        "is invisible to analysis. Do not redeclare the intent."
    ),
    "change_predates_declaration": (
        "The declared before-run already contained these changes, so this "
        "intent has no BEFORE and re-analysing cannot create one: both runs "
        "read the same bytes. Bind the intent to a run taken before the edit "
        "-- manage_change_intent(action='declare', run_id=<pre-edit run_id>) "
        "-- and finish against that intent_id. If no such run exists, commit "
        "or stash the work in progress, run analyze_repository to record the "
        "pre-change state, restore the work and analyse again."
    ),
    "after_run_required_for_governance": (
        "Governance config changes require a post-edit analysis."
        " Run analyze_repository(root=<repo root>) and pass after_run_id."
    ),
    "before_run_root_mismatch": (
        "The before-run belongs to a different repository root than the"
        " intent. Run analyze_repository(root=<intent root>) on the intent's"
        " own root and pass that run_id as before_run_id."
    ),
    "incomparable_runs": (
        "Before and after runs are not comparable."
        " Re-run analyze_repository(root=<repo root>) with the same settings."
    ),
    "intent_not_active": (
        "Queued intent must be promoted before editing or"
        " verification. Call"
        " manage_change_intent(action='promote')."
    ),
    "report_digest_mismatch": (
        "Intent was declared against a different report. Call "
        "finish_controlled_change(intent_id=..., before_run_id=...) with the "
        "original intent_id and its original before_run_id. Do not redeclare "
        "on the after-run: a fresh intent would bind to the post-edit report, "
        "making before and after the same run. If the original before-run is "
        "gone from this session, bridge it with "
        "manage_change_intent(action='declare', run_id=<pre-edit run_id>) "
        "before verifying."
    ),
    "state_artifact_mutation": (
        "Baseline, cache, or generated state was touched. Revert those paths, "
        "then call finish_controlled_change(changed_files=[...]) again with "
        "changed_files listing only source files. Baseline and generated "
        "state require a separate explicit workflow and never verify through "
        "this contract."
    ),
    "scope_violation": (
        "Patch touched files outside declared scope. Either revert the "
        "out-of-scope files and call finish_controlled_change(intent_id=...) "
        "again, or — after user approval — call "
        "start_controlled_change(root=..., scope=...) with the widened scope "
        "and finish against the new intent_id."
    ),
}


def next_step_hint(reason: str) -> str | None:
    return NEXT_STEP_HINTS.get(reason)


# Outcomes that are already terminal and successful: remediation would be
# meaningless, so they carry no next_step. They still owe the reader an
# explanation of what the outcome does and does not prove.
ACCEPTED_OUTCOME_REASONS: Final[frozenset[str]] = frozenset({"analyzer_invariant"})

# Reasons finish resolves outside the patch-contract hint table.
WORKFLOW_OUTCOME_REASONS: Final[frozenset[str]] = frozenset({"workspace_hygiene"})

# The complete typed-outcome vocabulary of finish/verify. A new outcome must
# join this set, and must arrive with executable remediation and a help-topic
# mention — see the procedure-coverage guard in the MCP service tests. Typed
# outcomes are a contract with the next agent, not session lore.
FINISH_OUTCOME_REASONS: Final[frozenset[str]] = frozenset(
    {*NEXT_STEP_HINTS, *ACCEPTED_OUTCOME_REASONS, *WORKFLOW_OUTCOME_REASONS}
)


QUEUED_BUDGET_MESSAGE: Final = (
    "Budget computed for queued intent. Do not edit until promoted."
)

STATE_ARTIFACT_VIOLATION_MESSAGE: Final = (
    "Patch touched CodeClone generated state. "
    "This requires a separate explicit workflow."
)

PATCH_CONTRACT_EXPIRED_MESSAGE: Final = (
    "Patch contract expired: intent was declared for another report digest."
)

BUDGET_RELAXED_ADVISORY: Final = (
    "Relaxed patch budget is advisory; gate failures are not blocking."
)
BUDGET_OUTSIDE: Final = "Current run is already outside the selected patch budget."
BUDGET_INSIDE: Final = "Current run is inside the selected patch budget."

# ── analyzer invariance ─────────────────────────────────────────────
# An after-run whose content-addressed id equals the before-run's, produced by
# a fresh post-start recompute, is not a missing after-run: it is the strongest
# structural evidence available. Identical digest means identical analysis
# facts, so the structural delta is empty by construction rather than
# unmeasured. The wording below never claims checks "passed" — nothing was
# compared; the change was shown to be invisible to analysis.
ANALYZER_INVARIANT_REASON: Final = "analyzer_invariant"

ANALYZER_INVARIANT_EVIDENCE: Final = (
    "change proven invisible to analysis; identical content-addressed run "
    "under fresh recompute"
)

VERIFY_ACCEPTED_ANALYZER_INVARIANT: Final = (
    "Patch contract accepted: change proven invisible to analysis; identical "
    "content-addressed run under fresh recompute. No structural comparison "
    "was performed because the two runs carry the same analysis facts."
)

ANALYZER_INVARIANT_LIMITATIONS: Final[tuple[str, ...]] = (
    "Structural checks were satisfied by run identity, not by comparing two "
    "different analyses; report this as analyzer-invariance, not as a passed "
    "structural review.",
    "Invariance is evidence about analysis facts only. Behaviour, typing and "
    "runtime effects of the change are outside what CodeClone observed.",
)


# Freshness and observation are two questions, and one refusal used to answer
# both. Under ``dirty_scope_policy="continue_own_wip"`` the edit precedes the
# declaration, so the before-run already holds it: the after-run is genuinely
# a later execution (freshness holds) and yet the pair witnessed no change
# (observation fails, permanently). Contract B of RULING-2026-09-04 applies --
# the pre-WIP state is not reconstructible for 55.8% of measured dirty starts,
# so the controller states the absence instead of comparing the tree with
# itself and calling the empty delta a pass.
CHANGE_PREDATES_DECLARATION_REASON: Final = "change_predates_declaration"

CHANGE_PREDATES_DECLARATION_MESSAGE: Final = (
    "Patch contract unverified: every claimed change was already present in "
    "the working tree when this intent was declared, so the before-run is not "
    "a pre-change state and no structural comparison exists to perform. This "
    "is not a stale after-run -- a later execution did take place; it read "
    "the same bytes."
)

CHANGE_PREDATES_DECLARATION_LIMITATIONS: Final[tuple[str, ...]] = (
    "The change predates the declaration, so this intent carries no before/"
    "after pair; scope was proven, structure was not compared.",
    "Do not report this as analyzer-invariance: nothing was shown to be "
    "invisible to analysis, and nothing was measured either way.",
)


def change_predates_declaration_limitation(paths: Sequence[str]) -> str:
    """Name the paths the start-time snapshot already held."""

    rendered = ", ".join(sorted(paths))
    return (
        f"Already dirty when the intent was declared: {rendered}. The "
        "before-run analysed these bytes, so a structural delta against it "
        "would compare the post-change tree with itself."
    )


def analyzer_invariant_unobserved_limitation(paths: Sequence[str]) -> str:
    """State plainly which changed files the after-run did not record.

    Analysis reads no stat for these and the run did not see them modified,
    so nothing pins the recompute as having happened after that edit. Naming
    them beats implying the whole patch was byte-verified.
    """

    rendered = ", ".join(sorted(paths))
    return (
        f"The after-run recorded no observation of {rendered}: analysis does "
        "not read these files and they were not modified in the working tree "
        "when it ran, so the recompute is not independently proven to "
        "postdate that edit. Invariance for them rests on this being the "
        "newest analysis of the root."
    )


VERIFY_ACCEPTED: Final = "Patch contract accepted."
VERIFY_ACCEPTED_EXTERNAL: Final = (
    "Patch contract accepted; external workspace changes detected."
)
HEALTH_REGRESSION_ADVISORY: Final = (
    "Patch accepted, but repository health changed negatively between "
    "before-run and after-run. Report this as advisory context, not as "
    "regression-free verification."
)
VERIFY_UNVERIFIED_PREFIX: Final = "Patch contract unverified: {reason}."


def verify_message(
    *,
    status: str,
    violations: Sequence[str],
    health_delta: int | None = None,
) -> str:
    if status == "accepted":
        message = VERIFY_ACCEPTED
    elif status == "accepted_with_external_changes":
        message = VERIFY_ACCEPTED_EXTERNAL
    else:
        return "Patch contract violated: " + ", ".join(violations)
    if health_delta is not None and health_delta < 0:
        return f"{message} {HEALTH_REGRESSION_ADVISORY}"
    return message


def budget_message(*, relaxed: bool, would_fail: bool) -> str:
    if relaxed:
        return BUDGET_RELAXED_ADVISORY
    if would_fail:
        return BUDGET_OUTSIDE
    return BUDGET_INSIDE
