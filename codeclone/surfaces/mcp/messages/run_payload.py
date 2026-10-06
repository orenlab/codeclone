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

#: The step that brings the payload back: run ids are content-addressed, so
#: analysing the same tree again registers the same run, whole.
PAYLOAD_EVICTED_NEXT: Final = (
    "Call analyze_repository(root='{root}'): run ids are content-addressed, "
    "so analysing the same tree again brings run '{run_id}' back whole; "
    "then repeat this call."
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


def payload_evicted_message(*, run_id: str) -> str:
    return PAYLOAD_EVICTED_MESSAGE.format(run_id=run_id)


__all__ = [
    "CLAIMS_NOT_VALIDATED",
    "CLAIMS_NOT_VALIDATED_MESSAGE",
    "PAYLOAD_EVICTED",
    "PAYLOAD_EVICTED_MESSAGE",
    "PAYLOAD_EVICTED_NEXT",
    "payload_evicted_message",
    "payload_evicted_next_step",
]
