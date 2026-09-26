# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""The MCP tool count the documentation states is the count the server serves.

Every ``<N> tools`` / ``<N> MCP tools`` phrase in the pages below names the
default server surface: ``build_mcp_server()`` without the IDE governance
channel, which is what ``codeclone-mcp`` and ``codeclone --mcp`` serve unless
VS Code passes ``--ide-governance-channel``. The number is re-derived from the
live ``list_tools()`` on every run and never written into this file, so a
tool registered or withdrawn reddens each page that still carries the old
count.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: The pages that state the size of the default MCP tool surface.
_COUNTING_PAGES = (
    "README.md",
    "docs/index.md",
    "docs/internal/architecture/overview.md",
    "docs/plans-and-retention.md",
)

# ``\s`` spans a line break, so a count wrapped onto the next line is read too.
_STATED_COUNT = re.compile(r"\b(\d+)\s+(?:MCP\s+)?tools\b")


def _served_tool_count() -> int:
    pytest.importorskip("mcp.server.fastmcp")

    from codeclone.surfaces.mcp.server import build_mcp_server

    server = build_mcp_server(history_limit=4)
    return len(asyncio.run(server.list_tools()))


def _stated_counts(page: str) -> list[tuple[int, int]]:
    """``(line, count)`` for every tool count the page states."""
    text = (_REPO_ROOT / page).read_text(encoding="utf-8")
    return [
        (text.count("\n", 0, match.start()) + 1, int(match.group(1)))
        for match in _STATED_COUNT.finditer(text)
    ]


def test_every_counting_page_states_a_tool_count() -> None:
    """The population is real: a page that lost its count, or a pattern that
    stopped matching, would otherwise leave the rule below vacuously green."""
    assert [page for page in _COUNTING_PAGES if not _stated_counts(page)] == []


def test_stated_tool_counts_match_the_served_default_surface() -> None:
    served = _served_tool_count()
    wrong = [
        f"{page}:{line} states {count}"
        for page in _COUNTING_PAGES
        for line, count in _stated_counts(page)
        if count != served
    ]

    assert not wrong, "\n".join(
        [f"the default MCP server serves {served} tools; stale counts:", *wrong]
    )
