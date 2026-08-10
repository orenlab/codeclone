# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Package member of one deliberate import-time cycle (package layout).

The cycle pairs a regular package with a plain module file on purpose: the
honest projection for this member is ``pkga/__init__.py``, never ``pkga.py``.
"""

import modb  # type: ignore[import-not-found]

PKGA_TOKEN = "pkga"


def pkga_value() -> str:
    return f"{PKGA_TOKEN}:{modb.MODB_TOKEN}"
