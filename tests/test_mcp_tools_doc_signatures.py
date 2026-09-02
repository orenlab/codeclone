# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Published MCP call shapes must match the live ``list_tools()`` schema.

``docs/reference/mcp-tools.md`` publishes each tool as ``tool(args)``. That
argument list is what a reader types, so two failure classes are guarded,
both derived from the live schema and never from today's spellings:

1. Omission: a published call must name every argument its tool marks
   ``required``. A reader who copies the published shape and is refused for
   a missing argument can at least ask which one.
2. Invention: a published call must not name an argument the tool does not
   accept. This is the worse class -- the reader types the invented name
   verbatim and is refused for a parameter that never existed. It was
   measured live on six calls, three of them confusable with a real
   sibling argument (``detail`` for ``detail_level``, ``changed_files``
   for ``changed_paths``, ``run_id_a``/``run_id_b`` for
   ``before_run_id``/``after_run_id``).

Discovery is keyed on the *shape of the value* -- a backticked identifier
followed by a parenthesised argument list, anywhere in the document --
never on the Markdown that happens to surround it today. A rule keyed on
presentation is a rule that silently stops matching: this project has
twice shipped one that covered less than it claimed (a constant ratchet
matched by name fragment and reached 49 of 110; a route rule read only
dict keys ending in ``route`` and stayed green while a broken route was
published under another key). ``test_call_shapes_are_found_in_unusual_markdown``
is the standing proof that this one matches on shape.

An argument token this parser cannot resolve to an identifier is a failure,
not a skip. Dropping it silently would reintroduce exactly the hole above:
the pin would report success over a call it never checked.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Final, NamedTuple

import pytest

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_DOC_PATH: Final = _REPO_ROOT / "docs" / "reference" / "mcp-tools.md"

# A backticked ``name(...)`` anywhere in a line. Bold, headings, table cells
# and mid-sentence prose all reach this matcher unchanged.
_CALL_SHAPE: Final = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)\(([^`)]*)\)`")
# Published lists separate alternatives with ``|`` as well as ``,``.
_ARGUMENT_SEPARATOR: Final = re.compile(r"[,|]")
_IDENTIFIER: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
# Deliberate "and further optional arguments" markers, not argument names.
_ELISION: Final = frozenset({"...", "…"})


class PublishedCall(NamedTuple):
    """One ``tool(args)`` occurrence found in the published document."""

    line: int
    tool: str
    text: str
    arguments: tuple[str, ...]
    unresolved: tuple[str, ...]


class ToolSchema(NamedTuple):
    """The live input schema of one registered tool."""

    accepted: frozenset[str]
    required: frozenset[str]


def _parse_argument(token: str) -> tuple[str | None, str | None]:
    """Resolve one published token to an argument name, or report it."""
    stripped = token.strip().strip("`*")
    if not stripped or stripped in _ELISION:
        return None, None
    # ``arg=default`` publishes the argument plus its default.
    name = stripped.split("=", 1)[0].strip()
    if _IDENTIFIER.match(name):
        return name, None
    return None, stripped


def parse_published_calls(
    document: str,
    known_tools: frozenset[str],
) -> tuple[PublishedCall, ...]:
    """Return every published call shape naming a registered tool."""
    calls: list[PublishedCall] = []
    for line_number, line in enumerate(document.splitlines(), start=1):
        for match in _CALL_SHAPE.finditer(line):
            tool = match.group(1)
            if tool not in known_tools:
                continue
            arguments: list[str] = []
            unresolved: list[str] = []
            for token in _ARGUMENT_SEPARATOR.split(match.group(2)):
                name, rejected = _parse_argument(token)
                if name is not None:
                    arguments.append(name)
                elif rejected is not None:
                    unresolved.append(rejected)
            calls.append(
                PublishedCall(
                    line=line_number,
                    tool=tool,
                    text=f"{tool}({match.group(2)})",
                    arguments=tuple(arguments),
                    unresolved=tuple(unresolved),
                )
            )
    return tuple(calls)


def tools_without_a_published_call(
    calls: tuple[PublishedCall, ...],
    schemas: dict[str, ToolSchema],
) -> list[str]:
    """Registered tools that mark arguments required but publish no shape.

    The population is read from the live registry, so it grows with the
    server. An empty document fails here rather than passing vacuously.
    """
    published = {call.tool for call in calls}
    return sorted(
        name
        for name, schema in schemas.items()
        if schema.required and name not in published
    )


@pytest.fixture(scope="module")
def live_schemas() -> dict[str, ToolSchema]:
    """Read every registered tool's input schema from ``list_tools()``."""
    pytest.importorskip("mcp.server.fastmcp")

    from codeclone.surfaces.mcp.server import build_mcp_server

    server = build_mcp_server(history_limit=4)
    return {
        tool.name: ToolSchema(
            accepted=frozenset((tool.inputSchema or {}).get("properties") or ()),
            required=frozenset((tool.inputSchema or {}).get("required") or ()),
        )
        for tool in asyncio.run(server.list_tools())
    }


@pytest.fixture(scope="module")
def published_calls(
    live_schemas: dict[str, ToolSchema],
) -> tuple[PublishedCall, ...]:
    """Every registered tool call published by the reference page."""
    return parse_published_calls(
        _DOC_PATH.read_text(encoding="utf-8"),
        frozenset(live_schemas),
    )


def test_published_calls_name_every_required_argument(
    published_calls: tuple[PublishedCall, ...],
    live_schemas: dict[str, ToolSchema],
) -> None:
    omissions = [
        f"{_DOC_PATH.name}:{call.line} `{call.text}` omits required "
        f"{sorted(live_schemas[call.tool].required - set(call.arguments))}"
        for call in published_calls
        if live_schemas[call.tool].required - set(call.arguments)
    ]
    assert not omissions, "\n".join(omissions)


def test_published_calls_name_no_argument_the_tool_rejects(
    published_calls: tuple[PublishedCall, ...],
    live_schemas: dict[str, ToolSchema],
) -> None:
    inventions = [
        f"{_DOC_PATH.name}:{call.line} `{call.text}` names "
        f"{sorted(set(call.arguments) - live_schemas[call.tool].accepted)}, "
        f"which {call.tool} does not accept"
        for call in published_calls
        if set(call.arguments) - live_schemas[call.tool].accepted
    ]
    assert not inventions, "\n".join(inventions)


def test_published_argument_tokens_all_resolve_to_names(
    published_calls: tuple[PublishedCall, ...],
) -> None:
    """A token the parser cannot read is unchecked, so it must not pass."""
    unreadable = [
        f"{_DOC_PATH.name}:{call.line} `{call.text}` publishes "
        f"{list(call.unresolved)}, which is not an argument name"
        for call in published_calls
        if call.unresolved
    ]
    assert not unreadable, "\n".join(unreadable)


def test_every_tool_with_required_arguments_publishes_a_call(
    published_calls: tuple[PublishedCall, ...],
    live_schemas: dict[str, ToolSchema],
) -> None:
    undocumented = tools_without_a_published_call(published_calls, live_schemas)
    assert not undocumented, (
        f"{_DOC_PATH.name} publishes no call shape for tools that require "
        f"arguments: {undocumented}"
    )


def test_an_empty_document_fails_instead_of_passing_vacuously(
    live_schemas: dict[str, ToolSchema],
) -> None:
    """The coverage rule must report, not shrug, when nothing was checked."""
    empty = parse_published_calls("", frozenset(live_schemas))
    assert empty == ()
    expected = sorted(name for name, s in live_schemas.items() if s.required)
    assert expected, "no registered tool marks any argument required"
    assert tools_without_a_published_call(empty, live_schemas) == expected


def test_call_shapes_are_found_in_unusual_markdown() -> None:
    """Discovery keys on the shape of the value, not on its presentation.

    Every line below is legitimate Markdown a maintainer could write. A
    parser anchored on the bold-at-line-start spelling used today would
    silently skip the last five, and report success over calls it never
    read.
    """
    known = frozenset({"compare_runs", "get_finding", "help", "list_hotspots"})
    document = "\n".join(
        (
            "**`compare_runs(before_run_id, after_run_id)`**",
            "#### `get_finding(finding_id, detail_level)`",
            "| Tool | Shape |",
            "|------|-------|",
            "| Help | `help(topic)` |",
            "Call `list_hotspots( kind , limit )` before broader lists.",
            "- `compare_runs(before_run_id=..., focus)` compares two runs.",
        )
    )

    calls = parse_published_calls(document, known)

    assert [(call.line, call.tool, call.arguments) for call in calls] == [
        (1, "compare_runs", ("before_run_id", "after_run_id")),
        (2, "get_finding", ("finding_id", "detail_level")),
        (5, "help", ("topic",)),
        (6, "list_hotspots", ("kind", "limit")),
        (7, "compare_runs", ("before_run_id", "focus")),
    ]
