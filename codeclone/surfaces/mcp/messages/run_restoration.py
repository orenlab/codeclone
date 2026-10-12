# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""What a tool says about a run it cannot answer for, by reason.

One message and one next step per reason of the restoration vocabulary
(``api.run_restoration.RESTORATION_REASONS``).  A next step is an action
that can change the answer, never "try again" where trying again cannot.
"""

from __future__ import annotations

from typing import Final

#: ``status`` of every typed answer about a run that is not answered.
RUN_UNAVAILABLE_STATUS: Final = "unavailable"

_ANALYZE: Final = (
    "Call analyze_repository(root='{root}') and use the run_id it returns."
)

RUN_UNAVAILABLE_MESSAGES: Final[dict[str, str]] = {
    "run_not_found": (
        "This MCP server does not hold run '{run_id}', and the run store of "
        "{root} holds no record of it: nothing shows that it was ever "
        "published there."
    ),
    "run_expired": (
        "Run '{run_id}' was published under {root} and has since been "
        "collected from its run store; the store keeps the newest "
        "{max_runs} registered runs, none older than {max_days} days."
    ),
    "run_not_published": (
        "Run '{run_id}' has a record in the run store of {root}, but its "
        "analysis snapshot is not published there."
    ),
    "store_disabled": (
        "This MCP server does not hold run '{run_id}', and the run store is "
        "not read for {root} ({detail}), so no record of it was looked up."
    ),
    "incompatible_generation": (
        "The run store of {root} cannot be read by this server as it stands, "
        "so run '{run_id}' was not looked up."
    ),
    "integrity": (
        "The record of run '{run_id}' in the run store of {root} does not "
        "prove against its own bytes; nothing was answered from it."
    ),
    "store_unavailable": (
        "The run store of {root} could not be read at this moment, so run "
        "'{run_id}' was not looked up."
    ),
}

RUN_UNAVAILABLE_NEXT_STEPS: Final[dict[str, str]] = {
    "run_not_found": _ANALYZE,
    "run_expired": (
        "Call analyze_repository(root='{root}'): a collected run cannot be "
        "brought back, and the new analysis is a new run."
    ),
    "run_not_published": _ANALYZE,
    "store_disabled": (
        "Analyse in this server (analyze_repository(root='{root}')), or set "
        "CODECLONE_RUN_STORE_ENABLED=1 and CODECLONE_SERVE_FROM=run_store "
        "for the server so that runs are found again after a restart."
    ),
    "incompatible_generation": "{store_next_step}",
    "integrity": _ANALYZE,
    "store_unavailable": "Repeat this call; the store refused only for now.",
}

#: The line an analysis answer carries when its run was stored but its
#: execution record was not: no other process can find this run.
RUN_NOT_RESTORABLE_WARNING: Final = (
    "run {run_id} is held by this server only: its execution record was not "
    "written to the run store, so a restarted or another server cannot find it"
)


__all__ = [
    "RUN_NOT_RESTORABLE_WARNING",
    "RUN_UNAVAILABLE_MESSAGES",
    "RUN_UNAVAILABLE_NEXT_STEPS",
    "RUN_UNAVAILABLE_STATUS",
]
