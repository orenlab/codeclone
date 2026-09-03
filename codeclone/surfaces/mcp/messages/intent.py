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
