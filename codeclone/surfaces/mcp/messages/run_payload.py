# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""What a tool says about a run whose payload the server let go."""

from __future__ import annotations

from typing import Final

#: The one reason word of every answer about a held run without its payload
#: that no store reading could stand in for.
PAYLOAD_EVICTED: Final = "payload_evicted"

#: The step that brings the payload back -- true only while the files the
#: run read are unchanged: run ids are content-addressed, so analysing the
#: same tree again registers the same run, whole.
PAYLOAD_EVICTED_NEXT: Final = (
    "Call analyze_repository(root='{root}'): the files run '{run_id}' read "
    "are unchanged, so analysing again registers this same run whole; then "
    "repeat this call."
)

#: The step when the tree moved since the run: no analysis can bring the run
#: back, so saying "analyse again" would send the caller round a loop -- the
#: new analysis is another run, and this answer is refused for this one
#: again.  The tools that read the run store still answer for the run.
PAYLOAD_EVICTED_DRIFTED_NEXT: Final = (
    "Do not analyse to bring run '{run_id}' back: the tree under '{root}' "
    "changed since it ({changed} files differ, or the run recorded no "
    "manifest), so a new analysis is another run and this answer cannot be "
    "produced for '{run_id}' again. Ask the tools that read the run store "
    "about this run -- get_run_summary, get_blast_radius, compare_runs, "
    "evaluate_gates, check_patch_contract, check_authority with "
    "section='candidates' -- or analyse and use the run_id it returns."
)

PAYLOAD_EVICTED_MESSAGE: Final = (
    "This MCP server still knows run '{run_id}', but it no longer holds the "
    "run's analysis in memory, and this answer cannot be read from the run "
    "store. Nothing was answered from it."
)


#: The claims block of a finish whose before-run is held without its payload:
#: the claims are read against the run's findings, which only the payload
#: holds, so they are not validated -- the verdict does not depend on them.
CLAIMS_NOT_VALIDATED: Final = "not_validated"
CLAIMS_NOT_VALIDATED_MESSAGE: Final = (
    "The claims were not validated: the before-run's analysis is no longer "
    "held in memory and its findings are not read from the run store. The "
    "verification verdict does not depend on them."
)


def payload_evicted_next_step(*, root: str, run_id: str) -> str:
    return PAYLOAD_EVICTED_NEXT.format(root=root, run_id=run_id)


def payload_evicted_step(*, root: str, run_id: str, changed: int | None) -> str:
    """The step for a run whose payload went: analyse again only when the
    files it read are unchanged (``changed == 0``); ``None`` means the run
    recorded nothing to compare against, which promises nothing either."""
    if changed == 0:
        return payload_evicted_next_step(root=root, run_id=run_id)
    return PAYLOAD_EVICTED_DRIFTED_NEXT.format(
        root=root, run_id=run_id, changed="?" if changed is None else changed
    )


def payload_evicted_message(*, run_id: str) -> str:
    return PAYLOAD_EVICTED_MESSAGE.format(run_id=run_id)


__all__ = [
    "CLAIMS_NOT_VALIDATED",
    "CLAIMS_NOT_VALIDATED_MESSAGE",
    "PAYLOAD_EVICTED",
    "PAYLOAD_EVICTED_DRIFTED_NEXT",
    "PAYLOAD_EVICTED_MESSAGE",
    "PAYLOAD_EVICTED_NEXT",
    "payload_evicted_message",
    "payload_evicted_next_step",
    "payload_evicted_step",
]
