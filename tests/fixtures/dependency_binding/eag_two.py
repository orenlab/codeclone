# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Second eager member: with eag_one this cycle survives import-time-only
edges, so it must classify as ``import_cycle`` (critical)."""

import eag_one  # type: ignore[import-not-found]

EAG_TWO_TOKEN = "eag_two"


def eag_two_value() -> str:
    return f"{EAG_TWO_TOKEN}:{eag_one.EAG_ONE_TOKEN}"
