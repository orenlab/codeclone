# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deferred-cycle member: every runtime edge binds after import time.

The TYPE_CHECKING import never executes at runtime; the function-scope import
binds only when ``load_defb`` is called. This module cannot crash at import.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import defb  # type: ignore[import-not-found] # noqa: F401 — the typing-only edge IS the fixture's point

DEFA_TOKEN = "defa"


def load_defb() -> object:
    import defb as runtime_defb

    return runtime_defb
