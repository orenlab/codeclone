# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Published MCP call shapes must match the live ``list_tools()`` schema.

Two pages publish the MCP tool surface, and both are held here against the
same live registry rather than against each other:

- ``docs/reference/mcp-tools.md`` -- the per-tool reference. Measured
  2026-09-04: names all 39 registered tools, 33 with a parenthesised call
  shape.
- ``docs/internal/contracts/mcp-tools.md`` -- the contract page. Measured
  the same day: names 9 of the 39 and publishes 5 call shapes, because it
  documents what the surface *guarantees*, not every tool.

That population difference is why one rule is not shared.
``test_every_tool_with_required_arguments_publishes_a_call`` demands a
published shape for each of the 24 tools that mark an argument required;
that is a completeness duty the reference page owes and the contract page
does not. Applying it to the contract page would demand 24 call shapes on
a page that documents 9 tools. Every other rule here runs over both.

The guarded failure classes, all derived from the live schema and never
from today's spellings:

1. Omission: a published call must name every argument its tool marks
   ``required``. A reader who copies the published shape and is refused
   for a missing argument can at least ask which one.
2. Invention: a published call must not name an argument the tool does
   not accept. This is the worse class -- the reader types the invented
   name verbatim and is refused for a parameter that never existed. It
   was measured live on six calls, three of them confusable with a real
   sibling argument (``detail`` for ``detail_level``, ``changed_files``
   for ``changed_paths``, ``run_id_a``/``run_id_b`` for
   ``before_run_id``/``after_run_id``).
3. Misattribution and value-as-parameter: a parameter published outside a
   call shape, as ``name=value`` in prose, must belong to the tool it is
   published under. Measured on the contract page: ``compact=true``, where
   ``compact`` is a parameter of none of the 39 tools -- it is the default
   *value* of ``help``'s ``detail``. A default value read back as a
   parameter name is a distinct confusion from an invented name, so it is
   reported as one.
4. Default drift: ```param` defaults to `value``` must equal the live
   schema default of that parameter on the tool it is published under.
   The ambiguous ``value (default)`` spelling is refused outright, because
   it names no parameter and so cannot be checked at all -- both pages
   carried it, and both stated the wrong default under it (``normal``,
   where ``help``'s ``detail`` defaults to ``compact``).
5. Vocabulary dialect: a backticked token that becomes a live ``help``
   topic once ``-`` is read as ``_`` must be spelled the way the registry
   spells it. Measured: ``change-control`` against the live
   ``change_control``.

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
the pin would report success over a call it never checked. For the same
reason ``test_documented_calls_are_all_inspected`` runs a deliberately
looser scanner beside the strict one: a call published without its
backticks is invisible to every rule above, so it is reported as
uninspected rather than passed over.

What is *not* inspected here, measured rather than assumed:

- Response fields. ``status="not_found"`` and ``edit_allowed=true`` read
  like parameter assignments but name response keys, which the input
  schema does not own. They are recognised and skipped: a name that is
  neither an accepted parameter anywhere nor a live default value is
  outside this guard's jurisdiction.
- Fenced code blocks. The reference page publishes 5 multi-line calls
  inside `````python`` fences; a backtick-keyed matcher cannot read them
  and a regex cannot parse a multi-line call with dict and list literals
  without inventing argument tokens. The census below excludes fenced
  lines on both sides so it reports a real number, and those 5 calls
  remain unguarded for parameter correctness.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Final, NamedTuple

import pytest

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_REFERENCE_DOC: Final = _REPO_ROOT / "docs" / "reference" / "mcp-tools.md"
_CONTRACT_DOC: Final = _REPO_ROOT / "docs" / "internal" / "contracts" / "mcp-tools.md"
_DOC_PATHS: Final = (_REFERENCE_DOC, _CONTRACT_DOC)

# A backticked ``name(...)`` anywhere in a line. Bold, headings, table cells
# and mid-sentence prose all reach this matcher unchanged.
_CALL_SHAPE: Final = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)\(([^`)]*)\)`")
# A backticked bare identifier: how both pages name a tool in prose.
_BARE_NAME: Final = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
# A backticked ``name=value`` that is not inside a call shape.
_ASSIGNMENT: Final = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^`]*)`")
# The one default spelling this guard can check against the schema.
_DEFAULT_CLAIM: Final = re.compile(
    r"`([A-Za-z_][A-Za-z0-9_]*)`\s+defaults to\s+`([^`]+)`"
)
# The spelling it cannot: a value marked default with no parameter named.
_DEFAULT_MARKER: Final = re.compile(r"`?\b([A-Za-z_][A-Za-z0-9_-]*)`?\s+\(default\)")
# Any backticked token that could be a vocabulary value.
_VOCABULARY_TOKEN: Final = re.compile(r"`([A-Za-z][A-Za-z0-9_-]*)`")
# Deliberately looser than _CALL_SHAPE: finds a call whether or not it is
# published as code. Used only to prove the strict matcher saw everything.
_LOOSE_CALL: Final = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\(")
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


class PublishedAssignment(NamedTuple):
    """One backticked ``name=value`` published outside a call shape."""

    line: int
    name: str
    value: str
    tool: str | None


class PublishedDefault(NamedTuple):
    """One ```param` defaults to `value``` claim."""

    line: int
    name: str
    value: str
    tool: str | None


class ToolSchema(NamedTuple):
    """The live input schema of one registered tool."""

    accepted: frozenset[str]
    required: frozenset[str]
    defaults: dict[str, str]


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


def prose_lines(document: str) -> tuple[tuple[int, str], ...]:
    """Numbered lines outside fenced code blocks.

    Fenced blocks publish multi-line calls with dict and list literals; a
    backtick-keyed matcher cannot see them and a regex cannot split their
    arguments without inventing tokens. Excluding them on *both* sides of
    the census keeps its number honest instead of loud.
    """
    kept: list[tuple[int, str]] = []
    fenced = False
    for number, line in enumerate(document.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            kept.append((number, line))
    return tuple(kept)


def parse_prose_claims(
    document: str,
    known_tools: frozenset[str],
) -> tuple[tuple[PublishedAssignment, ...], tuple[PublishedDefault, ...]]:
    """Return prose parameter claims, each bound to the tool it follows.

    Attribution is positional: the most recently published tool name, on
    this line or an earlier one. Both pages introduce a tool and then
    discuss its arguments, so this reads the document the way a reader
    does. A claim published before any tool name is attributed to nothing
    and reported as unattributable rather than assumed correct.
    """
    assignments: list[PublishedAssignment] = []
    defaults: list[PublishedDefault] = []
    tool: str | None = None
    for number, line in prose_lines(document):
        masked = _CALL_SHAPE.sub(
            lambda m: "`" + "x" * (len(m.group(0)) - 2) + "`", line
        )
        events: list[tuple[int, str, tuple[str, str]]] = [
            (match.start(), "tool", (match.group(1), ""))
            for pattern in (_CALL_SHAPE, _BARE_NAME)
            for match in pattern.finditer(line)
            if match.group(1) in known_tools
        ]
        events.extend(
            (match.start(), "assign", (match.group(1), match.group(2)))
            for match in _ASSIGNMENT.finditer(masked)
        )
        events.extend(
            (match.start(), "default", (match.group(1), match.group(2)))
            for match in _DEFAULT_CLAIM.finditer(line)
        )
        for _, kind, (name, value) in sorted(events, key=lambda event: event[0]):
            if kind == "tool":
                tool = name
            elif kind == "assign":
                assignments.append(PublishedAssignment(number, name, value, tool))
            else:
                defaults.append(PublishedDefault(number, name, value, tool))
    return tuple(assignments), tuple(defaults)


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


def uninspected_calls(
    document: str,
    known_tools: frozenset[str],
) -> list[str]:
    """Calls the loose scanner sees and the strict one does not.

    Dropping the backticks around a published call hides it from every
    rule in this module. Silence is the wrong answer to that: the call is
    still published, and a reader will still copy it.
    """
    lines = prose_lines(document)
    strict = {
        (number, match.group(1))
        for number, line in lines
        for match in _CALL_SHAPE.finditer(line)
        if match.group(1) in known_tools
    }
    loose = {
        (number, match.group(1))
        for number, line in lines
        for match in _LOOSE_CALL.finditer(line)
        if match.group(1) in known_tools
    }
    return [f"line {number} `{tool}(`" for number, tool in sorted(loose - strict)]


@pytest.fixture(scope="module")
def live_schemas() -> dict[str, ToolSchema]:
    """Read every registered tool's input schema from ``list_tools()``."""
    pytest.importorskip("mcp.server.fastmcp")

    from codeclone.surfaces.mcp.server import build_mcp_server

    server = build_mcp_server(history_limit=4)
    schemas: dict[str, ToolSchema] = {}
    for tool in asyncio.run(server.list_tools()):
        properties = (tool.inputSchema or {}).get("properties") or {}
        schemas[tool.name] = ToolSchema(
            accepted=frozenset(properties),
            required=frozenset((tool.inputSchema or {}).get("required") or ()),
            defaults={
                name: str(spec["default"])
                for name, spec in properties.items()
                if isinstance(spec, dict) and "default" in spec
            },
        )
    return schemas


@pytest.fixture(scope="module")
def default_value_owners(live_schemas: dict[str, ToolSchema]) -> dict[str, list[str]]:
    """Live default values, mapped back to the parameters that own them."""
    owners: dict[str, set[str]] = {}
    for schema in live_schemas.values():
        for parameter, value in schema.defaults.items():
            owners.setdefault(value, set()).add(parameter)
    return {value: sorted(names) for value, names in owners.items()}


@pytest.fixture(scope="module")
def help_topics() -> frozenset[str]:
    """The live ``help`` topic vocabulary, read from its owning module."""
    pytest.importorskip("mcp.server.fastmcp")

    from codeclone.surfaces.mcp.messages.help_topics import HELP_TOPIC_SPECS

    return frozenset(HELP_TOPIC_SPECS)


def _name(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


def _calls(
    path: Path,
    live_schemas: dict[str, ToolSchema],
) -> tuple[PublishedCall, ...]:
    return parse_published_calls(
        path.read_text(encoding="utf-8"), frozenset(live_schemas)
    )


@pytest.mark.parametrize("doc_path", _DOC_PATHS, ids=_name)
def test_published_calls_name_every_required_argument(
    doc_path: Path,
    live_schemas: dict[str, ToolSchema],
) -> None:
    omissions = [
        f"{_name(doc_path)}:{call.line} `{call.text}` omits required "
        f"{sorted(live_schemas[call.tool].required - set(call.arguments))}"
        for call in _calls(doc_path, live_schemas)
        if live_schemas[call.tool].required - set(call.arguments)
    ]
    assert not omissions, "\n".join(omissions)


@pytest.mark.parametrize("doc_path", _DOC_PATHS, ids=_name)
def test_published_calls_name_no_argument_the_tool_rejects(
    doc_path: Path,
    live_schemas: dict[str, ToolSchema],
) -> None:
    inventions = [
        f"{_name(doc_path)}:{call.line} `{call.text}` names "
        f"{sorted(set(call.arguments) - live_schemas[call.tool].accepted)}, "
        f"which {call.tool} does not accept"
        for call in _calls(doc_path, live_schemas)
        if set(call.arguments) - live_schemas[call.tool].accepted
    ]
    assert not inventions, "\n".join(inventions)


@pytest.mark.parametrize("doc_path", _DOC_PATHS, ids=_name)
def test_published_argument_tokens_all_resolve_to_names(
    doc_path: Path,
    live_schemas: dict[str, ToolSchema],
) -> None:
    """A token the parser cannot read is unchecked, so it must not pass."""
    unreadable = [
        f"{_name(doc_path)}:{call.line} `{call.text}` publishes "
        f"{list(call.unresolved)}, which is not an argument name"
        for call in _calls(doc_path, live_schemas)
        if call.unresolved
    ]
    assert not unreadable, "\n".join(unreadable)


@pytest.mark.parametrize("doc_path", _DOC_PATHS, ids=_name)
def test_prose_parameters_belong_to_the_tool_they_follow(
    doc_path: Path,
    live_schemas: dict[str, ToolSchema],
    default_value_owners: dict[str, list[str]],
) -> None:
    """``name=value`` in prose must name a parameter of its own tool.

    A name that is neither an accepted parameter anywhere nor a live
    default value is a response key, which the input schema does not own;
    those are skipped by
    ``test_prose_parameter_population_is_accounted_for``.
    """
    accepted_anywhere = {
        name for schema in live_schemas.values() for name in schema.accepted
    }
    assignments, _ = parse_prose_claims(
        doc_path.read_text(encoding="utf-8"), frozenset(live_schemas)
    )
    failures: list[str] = []
    for claim in assignments:
        where = f"{_name(doc_path)}:{claim.line} `{claim.name}={claim.value}`"
        if claim.name in accepted_anywhere:
            if claim.tool is None:
                failures.append(f"{where} follows no published tool")
            elif claim.name not in live_schemas[claim.tool].accepted:
                failures.append(
                    f"{where} is published under {claim.tool}, "
                    f"which does not accept {claim.name}"
                )
        elif claim.name in default_value_owners:
            failures.append(
                f"{where} publishes a value as a parameter: `{claim.name}` is the "
                f"live default of {default_value_owners[claim.name]}, not an "
                f"argument any tool accepts"
            )
    assert not failures, "\n".join(failures)


@pytest.mark.parametrize("doc_path", _DOC_PATHS, ids=_name)
def test_published_defaults_match_the_live_schema(
    doc_path: Path,
    live_schemas: dict[str, ToolSchema],
) -> None:
    _, defaults = parse_prose_claims(
        doc_path.read_text(encoding="utf-8"), frozenset(live_schemas)
    )
    failures: list[str] = []
    for claim in defaults:
        where = (
            f"{_name(doc_path)}:{claim.line} `{claim.name}` defaults to `{claim.value}`"
        )
        if claim.tool is None or claim.name not in live_schemas[claim.tool].accepted:
            failures.append(f"{where} names no parameter of {claim.tool}")
            continue
        live = live_schemas[claim.tool].defaults.get(claim.name)
        if live != claim.value:
            failures.append(
                f"{where}, but {claim.tool}.{claim.name} defaults to {live}"
            )
    assert not failures, "\n".join(failures)


@pytest.mark.parametrize("doc_path", _DOC_PATHS, ids=_name)
def test_no_default_is_published_without_naming_its_parameter(
    doc_path: Path,
) -> None:
    """``value (default)`` names no parameter, so nothing can check it.

    Both pages carried this spelling and both stated the wrong value under
    it. The checkable form is ```param` defaults to `value```.
    """
    unattributed = [
        f"{_name(doc_path)}:{number} '{match.group(0).strip()}' marks a default "
        f"without naming its parameter; publish it as "
        f"`<parameter>` defaults to `{match.group(1)}`"
        for number, line in prose_lines(doc_path.read_text(encoding="utf-8"))
        for match in _DEFAULT_MARKER.finditer(line)
    ]
    assert not unattributed, "\n".join(unattributed)


@pytest.mark.parametrize("doc_path", _DOC_PATHS, ids=_name)
def test_help_topics_are_spelled_the_way_the_registry_spells_them(
    doc_path: Path,
    help_topics: frozenset[str],
) -> None:
    """A hyphenated topic is a topic the server will refuse."""
    dialects = [
        f"{_name(doc_path)}:{number} `{token}` is not a live help topic; "
        f"the registry spells it `{token.replace('-', '_')}`"
        for number, line in prose_lines(doc_path.read_text(encoding="utf-8"))
        for token in _VOCABULARY_TOKEN.findall(line)
        if token not in help_topics and token.replace("-", "_") in help_topics
    ]
    assert not dialects, "\n".join(dialects)


@pytest.mark.parametrize("doc_path", _DOC_PATHS, ids=_name)
def test_documented_calls_are_all_inspected(
    doc_path: Path,
    live_schemas: dict[str, ToolSchema],
) -> None:
    """Nothing published as a call may be invisible to the rules above."""
    missed = uninspected_calls(
        doc_path.read_text(encoding="utf-8"), frozenset(live_schemas)
    )
    assert not missed, (
        f"{_name(doc_path)} publishes calls no rule inspects, because they are "
        f"not published as code: {missed}"
    )


@pytest.mark.parametrize("doc_path", _DOC_PATHS, ids=_name)
def test_prose_parameter_population_is_accounted_for(
    doc_path: Path,
    live_schemas: dict[str, ToolSchema],
    default_value_owners: dict[str, list[str]],
) -> None:
    """Every prose ``name=value`` is inspected or named as out of scope.

    A guard that quietly drops what it cannot classify reports success
    over ground it never covered. Each assignment lands in exactly one of
    the two buckets, and the skipped bucket is response keys only.
    """
    accepted_anywhere = {
        name for schema in live_schemas.values() for name in schema.accepted
    }
    assignments, _ = parse_prose_claims(
        doc_path.read_text(encoding="utf-8"), frozenset(live_schemas)
    )
    inspected = [
        claim
        for claim in assignments
        if claim.name in accepted_anywhere or claim.name in default_value_owners
    ]
    skipped = [claim for claim in assignments if claim not in inspected]
    assert len(inspected) + len(skipped) == len(assignments)
    for claim in skipped:
        assert claim.name not in accepted_anywhere, (
            f"{_name(doc_path)}:{claim.line} `{claim.name}` was skipped although "
            f"it is a live parameter"
        )


def test_every_tool_with_required_arguments_publishes_a_call(
    live_schemas: dict[str, ToolSchema],
) -> None:
    """Completeness is the reference page's duty, not the contract page's.

    Measured 2026-09-04: the contract page names 9 of the 39 registered
    tools because it documents guarantees, not the tool list. Holding it
    to this rule would demand 24 call shapes it has no reason to publish.
    """
    undocumented = tools_without_a_published_call(
        _calls(_REFERENCE_DOC, live_schemas), live_schemas
    )
    assert not undocumented, (
        f"{_name(_REFERENCE_DOC)} publishes no call shape for tools that require "
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


def test_a_call_stripped_of_its_backticks_is_reported_not_skipped(
    live_schemas: dict[str, ToolSchema],
) -> None:
    """The census must see the one form every other rule is blind to."""
    known = frozenset(live_schemas)
    assert uninspected_calls("`help(topic)` is published as code.", known) == []
    assert uninspected_calls("help(topic) is published as prose.", known) == [
        "line 1 `help(`"
    ]
    # A fenced call is excluded on both sides, so the census stays honest.
    assert uninspected_calls("```python\nhelp(topic)\n```", known) == []


def test_prose_claims_bind_to_the_most_recent_tool() -> None:
    """Attribution follows the reader: the tool most recently published.

    Every line below is legitimate Markdown from these pages. A claim
    introduced under one tool and discussed on the next line must not be
    read against a different tool, and one published before any tool must
    not be read against nothing and passed.
    """
    known = frozenset({"generate_pr_summary", "help"})
    document = "\n".join(
        (
            "`topic=overview` before any tool is named.",
            "**`generate_pr_summary(run_id, format)`**",
            '`format` defaults to `markdown`; `format="json"` is machine-facing.',
            "**`help(topic, detail)`**",
            '`detail` defaults to `compact`, and `detail="normal"` adds warnings.',
        )
    )

    assignments, defaults = parse_prose_claims(document, known)

    assert [(a.line, a.name, a.tool) for a in assignments] == [
        (1, "topic", None),
        (3, "format", "generate_pr_summary"),
        (5, "detail", "help"),
    ]
    assert [(d.line, d.name, d.value, d.tool) for d in defaults] == [
        (3, "format", "markdown", "generate_pr_summary"),
        (5, "detail", "compact", "help"),
    ]


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
