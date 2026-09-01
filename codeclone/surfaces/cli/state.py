# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import time
from typing import Final

from ...paths.workspace import legacy_home_cache_path

console: object | None = None

#: This CLI process's own agent identity epoch, stamped once as this leaf
#: module is imported -- the earliest moment any CLI surface can ask for it.
#:
#: It lives here, and not beside its first consumer, because two CLI surfaces
#: need the same number: ``workflow`` writes it into the records this process
#: declares, and ``session_stats`` compares it against the records it reads
#: back. A surface that answers "when did this process start?" by reading the
#: clock again answers with the moment of the *read*, so it matches only a
#: record declared inside that same whole second and reports every older
#: intent of this very process as somebody else's.
CLI_SESSION_START_EPOCH: Final = int(time.time())

LEGACY_CACHE_PATH = legacy_home_cache_path()


def get_console() -> object:
    global console
    if console is None:
        from .console import make_plain_console

        console = make_plain_console()
    return console


def set_console(value: object) -> None:
    global console
    console = value
