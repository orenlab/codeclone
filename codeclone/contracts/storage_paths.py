# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The normative owner of CodeClone's product default storage paths.

One semantic path contract, one value owner. Every other production reference
obtains the value from here; none of them may spell it again.

Why this module and not ``paths.workspace``, which owns the workspace *layout*:
the readers of these six values live in rings the layout module cannot serve.
Measured 2026-09-01: importing the cache path from ``paths/workspace.py`` into
``ui_messages/help.py`` closed a deferred cycle -- ``ui_messages`` -> ``paths``
-> (deferred) ``ui_messages`` -- and took repository health from 91 to 88
against a CI gate at 89. The help surface therefore restated the cache path by
hand, which is exactly how that line went stale. ``contracts`` is r0, imports
nothing from the package, and every consumer already has an edge to it, so the
answer is reachable from all of them and single.

The five ``DEFAULT_*_REPORT_PATH`` names keep the spelling their consumers
already import; ``codeclone.contracts`` re-exports them, so this move adds no
parallel orthography. ``DEFAULT_CACHE_PATH`` is new only as a name -- the value
had two spellings here before and now has one.

Scope: these six product default paths. ``WORKSPACE_DIR_NAME`` and
``CACHE_DB_DIR_NAME`` stay with the layout module that composes the other
workspace artifacts from them; a shared name prefix is not a shared contract.
"""

from __future__ import annotations

from typing import Final

DEFAULT_CACHE_PATH: Final = ".codeclone/db/cache.sqlite3"
DEFAULT_HTML_REPORT_PATH: Final = ".codeclone/report.html"
DEFAULT_JSON_REPORT_PATH: Final = ".codeclone/report.json"
DEFAULT_MARKDOWN_REPORT_PATH: Final = ".codeclone/report.md"
DEFAULT_SARIF_REPORT_PATH: Final = ".codeclone/report.sarif"
DEFAULT_TEXT_REPORT_PATH: Final = ".codeclone/report.txt"

__all__ = [
    "DEFAULT_CACHE_PATH",
    "DEFAULT_HTML_REPORT_PATH",
    "DEFAULT_JSON_REPORT_PATH",
    "DEFAULT_MARKDOWN_REPORT_PATH",
    "DEFAULT_SARIF_REPORT_PATH",
    "DEFAULT_TEXT_REPORT_PATH",
]
