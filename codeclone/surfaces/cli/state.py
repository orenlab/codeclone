# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from pathlib import Path

console: object | None = None
LEGACY_CACHE_PATH = Path("~/.cache/codeclone/cache.json").expanduser()


def get_console() -> object:
    global console
    if console is None:
        from .console import make_plain_console

        console = make_plain_console()
    return console


def set_console(value: object) -> None:
    global console
    console = value
