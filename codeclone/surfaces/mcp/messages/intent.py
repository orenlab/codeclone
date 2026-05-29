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
