# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Module-file member of the same import-time cycle (module layout).

Its honest projection is ``modb.py`` — the layout the phantom-path bug
happened to guess right, kept in the SAME cycle as the package member so one
finding must carry both layouts correctly at once.
"""

import pkga  # type: ignore[import-not-found]

MODB_TOKEN = "modb"


def modb_value() -> str:
    return f"{MODB_TOKEN}:{pkga.PKGA_TOKEN}"
