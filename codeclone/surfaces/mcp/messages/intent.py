# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Change-intent lifecycle user messages."""

from __future__ import annotations

from typing import Final

QUEUED_PROMOTE_BEFORE_EDIT: Final = "Queued. Promote before editing."

PROMOTE_BEFORE_RUN_EVICTED_NEXT: Final = (
    "Run analyze_repository to create a fresh before-run, then redeclare the intent."
)

PROMOTE_BEFORE_RUN_EVICTED: Final = (
    "Before-run was evicted from bounded history. Re-analyze and redeclare the intent."
)

PROMOTE_STILL_BLOCKED: Final = "Intent is still blocked by active workspace intents."

PROMOTED_RECHECK: Final = (
    "Queued intent promoted. Re-check blast radius and patch budget before editing."
)

QUEUED_SCOPE_WAITING: Final = "Another agent is waiting for this scope."

RESET_LIVE_FOREIGN: Final = (
    "Intent belongs to a live process. Coordinate "
    "with the owning agent or user before resetting it."
)

RECOVERY_HINT: Final = "Use action='recover' with matching run_id to reclaim."
RECOVERY_NEEDS_ANALYSIS_HINT: Final = (
    "Recoverable intent found. Run analyze_repository in this MCP session, "
    "then use action='recover' with the matching run_id."
)
RECOVERY_LIST_NEXT_STEP: Final = (
    "Recovery candidates may require a fresh analyze_repository run after "
    "MCP restart before recover succeeds."
)

SCOPE_CHECK_FORBIDDEN: Final = "Patch touched forbidden or out-of-scope files."
SCOPE_CHECK_RELATED: Final = (
    "Patch touched allowed related files outside primary scope."
)
SCOPE_CHECK_CLEAN: Final = "Patch stayed inside declared scope."

RECOVERY_FOREIGN_ACTIVE: Final = (
    "Intent has a valid lease from a live process. Cannot recover. "
    "Use action='list_workspace' to inspect, then coordinate with the user."
)

RECOVERY_FOREIGN_STALE: Final = (
    "Intent belongs to a live process with an expired lease. "
    "The owner may still be working. Coordinate with the user before recovering."
)

RECOVERY_EXPIRED: Final = "Intent has expired (TTL). Declare a new intent instead."

# The three outcomes of the durable before-execution binding. Each names what
# happened AND what the caller does next: an outcome without a runnable step
# is a dead end wearing a type name.
RECOVERY_LEGACY_RECORD: Final = (
    "This intent was declared by a server that recorded no execution witness, "
    "so which analysis it was declared against cannot be proven. It is not "
    "upgraded by binding it to whatever run answers to its run_id now."
)
RECOVERY_LEGACY_NEXT_STEP: Final = (
    "Clear it with manage_change_intent(action='clear', intent_id=...), then "
    "analyze_repository and start_controlled_change to declare again."
)
RECOVERY_EXECUTION_SUPERSEDED: Final = (
    "The offered run read different source bytes than the execution this "
    "intent was declared on. Two executions share one run_id when the report "
    "is unchanged, so the name matching proves nothing; the content witness "
    "does, and it disagrees. The before-run cannot be re-established from it."
)
RECOVERY_EXECUTION_SUPERSEDED_NEXT_STEP: Final = (
    "Restore the declared source state and analyze_repository again to "
    "re-establish the binding, or clear the intent with "
    "manage_change_intent(action='clear', intent_id=...) and declare again "
    "against the current tree."
)
RECOVERY_NO_CONTENT_WITNESS: Final = (
    "The execution this intent was declared on recorded no content witness, "
    "so no later run can be proven to have read the same source state."
)

DECLARE_FOREIGN_ACTIVE_OVERLAP: Final = (
    "Foreign active intent overlaps your scope. Ask the user, narrow scope, "
    'or restart with on_conflict="queue".'
)

DECLARE_FOREIGN_STALE_OVERLAP: Final = (
    "Foreign stale intent overlaps your scope. Coordinate with the user or "
    "recover the foreign intent before editing."
)

DECLARE_FOREIGN_OVERLAP: Final = (
    "Foreign intent overlaps your scope. Ask the user before editing."
)


# ── a registry row this build cannot read ───────────────────────────────────
# The row is present, signed by its writer, and beyond this build's model.
# Saying "not found" about it is the second half of the same defect that used
# to delete it: the operator is told the intent never existed, when what
# actually happened is that this server does not understand it.
#
# Read by SUBSCRIPT, never ``.get``. A permissive lookup lets a raise site
# invent a reason and ship a null next_step to the operator; the subscript
# makes that a failure at the raise, where it is still a programming error.
UNREADABLE_REGISTRY_RECORD_MESSAGES: Final[dict[str, str]] = {
    "registry_record_unreadable_by_this_build": (
        "A workspace intent is stored under this id, and this server cannot "
        "read it. Its integrity digest verifies, so the record was written "
        "whole by another build — a newer generation, an unknown field, or a "
        "status token this one does not define. It has been left exactly as "
        "found: it is another agent's live coordination state, and this "
        "server refusing to understand it is not a reason to destroy it."
    ),
}

UNREADABLE_REGISTRY_RECORD_NEXT_STEPS: Final[dict[str, str]] = {
    "registry_record_unreadable_by_this_build": (
        "Do not edit under this intent from this server. Inspect the record "
        "with manage_change_intent(action='list_workspace', root=...) from "
        "the build that wrote it and finish or clear it there. If that build "
        "is gone and the user confirms the scope is abandoned, remove the "
        "row from .codeclone/intents/ by hand, then analyze_repository and "
        "start_controlled_change to declare again."
    ),
}


def unreadable_registry_record_message(reason: str) -> str:
    return UNREADABLE_REGISTRY_RECORD_MESSAGES[reason]


def unreadable_registry_record_next_step(reason: str) -> str:
    return UNREADABLE_REGISTRY_RECORD_NEXT_STEPS[reason]


# ── refusing to speak for a registry this build cannot fully read ───────────
# The other half of the same law. A row whose integrity witness verifies is
# positive evidence that another writer holds coordination state here; its
# scope is unknown, and unknown scope is not absent conflict. Granting or
# widening write authority over it is refused, in the operator's words, with
# the ids named so the refusal can be acted on.
#
# The reason is this surface's own token, not the read-outcome kind: what the
# registry answered and what this tool refuses to do about it are two facts,
# and one of them belongs to the ring that owns the protocol.
WORKSPACE_INTENT_INCOMPATIBLE: Final = "workspace_intent_incompatible"

# Read by SUBSCRIPT, never ``.get``. A permissive lookup lets a refusal site
# invent a reason and ship a null next_step to the operator; the subscript
# makes that a failure at the refusal, where it is still a programming error.
WORKSPACE_ADMISSION_MESSAGES: Final[dict[str, str]] = {
    WORKSPACE_INTENT_INCOMPATIBLE: (
        "This workspace registry holds an intent this server cannot read. Its "
        "integrity digest verifies, so another build wrote it whole and may "
        "still be holding the scope it declares — a scope this server cannot "
        "determine. Refusing: an intent that cannot be interpreted must not "
        "become indistinguishable from no intent, because that would hand out "
        "edit authority over scope somebody else may hold."
    ),
}

WORKSPACE_ADMISSION_NEXT_STEPS: Final[dict[str, str]] = {
    WORKSPACE_INTENT_INCOMPATIBLE: (
        "Inspect the registry with manage_change_intent(action='list_workspace', "
        "root=...) — the unreadable ids are listed there. Finish or clear each "
        "one from the build that wrote it. If that build is gone and the user "
        "confirms the scope is abandoned, remove the row from .codeclone/intents/ "
        "by hand, then start_controlled_change again. Read-only analysis, "
        "listing, and finishing an intent you already hold stay available."
    ),
}


def workspace_admission_message(reason: str) -> str:
    return WORKSPACE_ADMISSION_MESSAGES[reason]


def workspace_admission_next_step(reason: str) -> str:
    return WORKSPACE_ADMISSION_NEXT_STEPS[reason]
