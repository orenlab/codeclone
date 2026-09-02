# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Every MCP call a published skill teaches must be a call that answers.

A skill is context a model loads in order to operate. A tool name it cannot
call, a parameter the server rejects, or a required argument it never mentions
is worse than silence: the model follows the instruction, the server refuses,
and the failure surfaces as the product being broken.

Nothing here keeps a list of tool names or parameters. Both sides are read
from their owners — the calls out of the shipped skill text, the surface out
of the server registry — so neither can rot behind a green gate. Rename a
tool, drop a parameter, or write a call the schema rejects, and this reds.
"""

from __future__ import annotations

import ast
import asyncio
import re
from functools import cache
from pathlib import Path
from typing import Final, NamedTuple, cast

import pytest

from codeclone.surfaces.mcp._session_shared import (
    _VALID_FINDING_FAMILIES,
    _VALID_FINDING_NOVELTY,
    _VALID_FINDING_SORT,
    _VALID_HELP_TOPICS,
    _VALID_HOTLIST_KINDS,
    _VALID_REPORT_SECTIONS,
)
from codeclone.surfaces.mcp.server import build_mcp_server
from tests.plugin_test_helpers import CODEX_PLUGIN_SKILL_NAMES, parse_frontmatter

#: Where a closed vocabulary lives, for the parameters the skills spell out
#: with literal values. The bindings are here; the values stay with their
#: owner, so this cannot drift into a second copy of the vocabulary. The MCP
#: schema types these parameters as plain strings, so the schema lanes below
#: cannot see a wrong value — only this can.
VOCABULARY_OWNERS: Final[dict[tuple[str, str], frozenset[str]]] = {
    ("get_report_section", "section"): _VALID_REPORT_SECTIONS,
    ("help", "topic"): _VALID_HELP_TOPICS,
    ("list_findings", "family"): _VALID_FINDING_FAMILIES,
    ("list_findings", "novelty"): _VALID_FINDING_NOVELTY,
    ("list_findings", "sort_by"): _VALID_FINDING_SORT,
    ("list_hotspots", "kind"): _VALID_HOTLIST_KINDS,
}

#: Call-shaped text in the skills that is deliberately not an MCP call. Each
#: entry names why, because an unexplained exemption is how a real defect gets
#: parked here instead of fixed.
NON_TOOL_CALL_SHAPES: Final[dict[str, str]] = {
    # Illustrative repository symbol inside the engineering-memory statement
    # template; it demonstrates card shape, not a tool to call.
    "resolve_cache_path": "example statement body, not an MCP tool",
    # "signal(s)" in the architecture-triage validation row.
    "signal": "English plural in prose, not an MCP tool",
}

#: Floor on how much this guard actually inspected. Extraction returning
#: nothing would otherwise pass every assertion below without reading a line.
MIN_CALLS_INSPECTED: Final = 25

#: The two public skills a router has to tell apart, and the tool each one's
#: answer is built by. Which side of the discriminator a skill sits on is
#: deliberately NOT written here: it is measured out of the handler below, so
#: a handler that gains or loses its baseline comparison moves the requirement
#: on the description instead of leaving a stale promise behind a green gate.
ROUTING_PAIR: Final[dict[str, str]] = {
    "codeclone-hotspots": "list_hotspots",
    "codeclone-production-triage": "get_production_triage",
}

#: Where those handlers are written. Their text is read rather than their
#: return value sampled, because the question is which keys each one
#: publishes at all, not what a fixture happens to make them contain.
HANDLER_SOURCES: Final[tuple[str, ...]] = (
    "codeclone/surfaces/mcp/_session_finding_mixin.py",
    "codeclone/surfaces/mcp/_session_state_mixin.py",
)

#: A handler is baseline-coupled when its own body publishes the baseline
#: comparison: the ``baseline`` block, or the new-vs-known split that only a
#: comparison can produce. Both are keys of the response a caller reads.
_PUBLISHES_BASELINE = re.compile(r'"baseline"|new_by_source_kind')

#: How a description declares its side of the discriminator. Both directions
#: are needed, and they are asserted separately: a description that declares
#: neither cannot route, and one that declares both is not a discriminator.
_DECLARES_BASELINE_REQUIRED = re.compile(r"\brequires? a baseline\b", re.IGNORECASE)
_DECLARES_BASELINE_OPTIONAL = re.compile(
    r"\bno baseline\b|\bwithout a baseline\b", re.IGNORECASE
)

#: The fenced block under "## Loop" is the call chain a skill actually
#: teaches. Its last arrow segment is the tool whose response the model is
#: sent to read, which is the skill's real subject however the frontmatter
#: describes it.
_LOOP_FENCE = re.compile(
    r"^## Loop\s*\n+```\n(?P<fence>.*?)\n```", re.MULTILINE | re.DOTALL
)
_PRIMARY_TOOL = re.compile(r"^([a-z][a-z0-9_]*)")

# No whitespace before "(": prose such as "fixtures (the gate counts
# production)" is a parenthetical, never a call, and admitting it would
# bury the real findings under English.
_CALL_START = re.compile(r"\b([a-z][a-z0-9_]*)\(")
_KWARG = re.compile(r"\b([a-z][a-z0-9_]*)\s*=")
# A value in a positional slot, quoted or not. Restricting this to quoted
# literals let `get_finding(finding_id)` ship in three skills: a bare name
# reads to the server exactly like a quoted one -- as whichever parameter
# comes first -- and is the shape a documented call is likelier to take.
_POSITIONAL_VALUE = re.compile(
    r"""(?:^|,)\s*((?:["'][^"']*["'])|(?:[a-z][a-z0-9_]*))\s*(?:,|$)"""
)
_NESTED_GROUP = re.compile(r"\[[^][]*\]|\{[^{}]*\}")
_ASSIGNMENT = re.compile(r"\b([a-z][a-z0-9_]*)\s*=\s*([^,)]*)")
_STRING_LITERAL = re.compile(r'"([^"]*)"')


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _skill_texts() -> dict[str, str]:
    skills_root = _repo_root() / "plugins" / "codeclone" / "skills"
    return {
        name: (skills_root / name / "SKILL.md").read_text(encoding="utf-8")
        for name in CODEX_PLUGIN_SKILL_NAMES
    }


def _call_shapes(text: str) -> list[tuple[str, str]]:
    """Every ``name(...)`` in the text, with its argument body.

    Scans instead of matching a fixed shape so that calls broken over several
    lines — the ones a skill writes when it has more than two arguments, and
    exactly where a required argument goes missing — are read too.
    """

    calls: list[tuple[str, str]] = []
    for match in _CALL_START.finditer(text):
        depth = 1
        index = match.end()
        while index < len(text) and depth:
            if text[index] == "(":
                depth += 1
            elif text[index] == ")":
                depth -= 1
            index += 1
        if depth:
            continue
        calls.append((match.group(1), text[match.end() : index - 1]))
    return calls


def _registry() -> dict[str, dict[str, object]]:
    pytest.importorskip("mcp.server.fastmcp")
    server = build_mcp_server(history_limit=4)
    return {
        tool.name: cast("dict[str, object]", tool.inputSchema)
        for tool in asyncio.run(server.list_tools())
    }


def _schema_properties(schema: dict[str, object]) -> set[str]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return set()
    return {str(key) for key in properties}


def _schema_required(schema: dict[str, object]) -> set[str]:
    required = schema.get("required")
    if not isinstance(required, list):
        return set()
    return {str(item) for item in required}


class DocumentedCall(NamedTuple):
    """One call written into a shipped skill, resolved against the registry."""

    skill: str
    name: str
    body: str
    schema: dict[str, object] | None


def _documented_calls() -> list[DocumentedCall]:
    """Every call in every public skill, paired with the schema it must obey.

    One traversal for all five lanes: each lane then reads this flat list and
    states only its own rule, so a change to how calls are found cannot make
    one lane read a different corpus than its neighbours.
    """

    registry = _registry()
    return [
        DocumentedCall(skill, name, body, registry.get(name))
        for skill, text in _skill_texts().items()
        for name, body in _call_shapes(text)
    ]


def _tool_calls(calls: list[DocumentedCall]) -> list[DocumentedCall]:
    return [call for call in calls if call.schema is not None]


def test_public_skills_name_only_tools_this_server_registers() -> None:
    """A call-shaped name in a shipped skill answers, or is declared prose."""

    calls = _documented_calls()
    unknown = sorted(
        f"{call.skill}: {call.name}(...)"
        for call in calls
        if call.schema is None and call.name not in NON_TOOL_CALL_SHAPES
    )

    assert len(calls) >= MIN_CALLS_INSPECTED, (
        f"only {len(calls)} call shapes were read from the public skills; "
        "extraction is broken, so nothing was actually checked"
    )
    assert not unknown, f"public skills name tools nobody can call: {unknown}"


def test_public_skill_calls_use_parameters_the_schema_accepts() -> None:
    """Every named argument is a parameter of the tool it is written under."""

    inspected = 0
    rejected: list[str] = []
    for call in _tool_calls(_documented_calls()):
        accepted = _schema_properties(cast("dict[str, object]", call.schema))
        arguments = _KWARG.findall(call.body)
        inspected += len(arguments)
        rejected.extend(
            f"{call.skill}: {call.name}({argument}=...)"
            for argument in arguments
            if argument not in accepted
        )

    assert inspected >= MIN_CALLS_INSPECTED, (
        f"only {inspected} named arguments were read; extraction is broken"
    )
    assert not rejected, (
        f"public skills pass parameters the server rejects: {sorted(rejected)}"
    )


def test_public_skill_calls_name_every_required_parameter() -> None:
    """A spelled-out call names each required parameter.

    An ellipsis in a documented call stands for optional extras. A required
    parameter is never optional, so omitting it teaches a call that fails
    validation before it reaches CodeClone at all.
    """

    spelled_out = [
        (call, named)
        for call in _tool_calls(_documented_calls())
        if (named := set(_KWARG.findall(call.body)))
    ]
    missing = sorted(
        f"{call.skill}: {call.name}(...) omits required {parameter}="
        for call, named in spelled_out
        for parameter in _schema_required(cast("dict[str, object]", call.schema))
        - named
    )

    assert len(spelled_out) >= MIN_CALLS_INSPECTED, (
        f"only {len(spelled_out)} spelled-out calls were read; extraction is broken"
    )
    assert not missing, f"public skills omit required arguments: {missing}"


def test_public_skill_calls_pass_no_value_positionally() -> None:
    """No value sits in a positional slot.

    MCP takes one JSON object per call, so anything written where a
    positional argument would go is silently read as whichever parameter
    happens to come first — and that parameter is usually ``root``. Unquoted
    names count: `get_finding(finding_id)` is the same defect as
    `get_finding("abc")`, and is the form a documented call tends to take.
    """

    positional = sorted(
        f"{call.skill}: {call.name}(…, {value})"
        for call in _tool_calls(_documented_calls())
        for value in _POSITIONAL_VALUE.findall(_NESTED_GROUP.sub("_", call.body))
    )

    assert not positional, (
        f"public skills pass values positionally to MCP tools: {positional}"
    )


def test_public_skill_calls_quote_only_values_the_vocabulary_admits() -> None:
    """A literal value written into a skill is one the validator accepts.

    These parameters are typed ``string`` on the wire, so no schema lane can
    catch a wrong value: the refusal happens inside the tool, after the model
    has already been told what to send. The vocabularies are read from the
    modules that own them rather than restated here.
    """

    bound = [
        (call, parameter, allowed, value)
        for call in _documented_calls()
        for parameter, raw in _ASSIGNMENT.findall(call.body)
        if (allowed := VOCABULARY_OWNERS.get((call.name, parameter))) is not None
        for value in _STRING_LITERAL.findall(raw)
    ]
    invalid = [
        f"{call.skill}: {call.name}({parameter}={value!r}) — "
        f"accepted: {sorted(allowed)}"
        for call, parameter, allowed, value in bound
        if value not in allowed
    ]

    assert bound, "no vocabulary-bound literal was read; extraction is broken"
    assert not invalid, f"public skills quote values the tool rejects: {invalid}"


class RoutingStance(NamedTuple):
    """One routable skill and the three readings that must agree.

    ``tool`` is what the skill is nominally about, ``primary_tool`` is what
    its Loop actually teaches, and the declared flags are what its
    description promises. A ratchet that reads only the first and the last
    holds the symptom: a body can be re-pointed at the neighbouring tool
    while both descriptions stay perfectly correct.
    """

    skill: str
    tool: str
    handler_read: bool
    handler_publishes_baseline: bool
    primary_tool: str
    primary_handler_read: bool
    primary_publishes_baseline: bool
    declares_required: bool
    declares_optional: bool


@cache
def _handler_bodies(names: frozenset[str]) -> dict[str, str]:
    """Source of each named handler, keyed by tool name.

    One traversal for all five lanes below, so no lane can end up reading a
    different corpus than its neighbours. A name defined twice is refused
    rather than resolved, because picking one silently is how a lane starts
    measuring the wrong function.
    """

    bodies: dict[str, str] = {}
    for relative in HANDLER_SOURCES:
        source = (_repo_root() / relative).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.FunctionDef) or node.name not in names:
                continue
            assert node.name not in bodies, f"{node.name} is defined more than once"
            bodies[node.name] = ast.get_source_segment(source, node) or ""
    return bodies


def _primary_tool(text: str) -> str:
    """The tool a skill's Loop fence sends the model to read, or ``""``."""

    fence = _LOOP_FENCE.search(text)
    if fence is None:
        return ""
    terminal = fence.group("fence").split("→")[-1].strip()
    named = _PRIMARY_TOOL.match(terminal)
    return named.group(1) if named else ""


def _routing_stances() -> list[RoutingStance]:
    """Every side of the discriminator, each measured from its own owner.

    The handler side comes from the shipped server source, the taught side
    from the shipped Loop fence, and the declared side from the shipped
    frontmatter. Nothing here states which skill ought to need a baseline —
    that is the comparison the lanes make.
    """

    texts = _skill_texts()
    primaries = {skill: _primary_tool(texts[skill]) for skill in ROUTING_PAIR}
    bodies = _handler_bodies(
        frozenset(ROUTING_PAIR.values()) | (set(primaries.values()) - {""})
    )
    stances: list[RoutingStance] = []
    for skill, tool in sorted(ROUTING_PAIR.items()):
        body = bodies.get(tool, "")
        primary = primaries[skill]
        primary_body = bodies.get(primary, "")
        description = parse_frontmatter(texts[skill])["description"]
        stances.append(
            RoutingStance(
                skill=skill,
                tool=tool,
                handler_read=bool(body),
                handler_publishes_baseline=bool(_PUBLISHES_BASELINE.search(body)),
                primary_tool=primary,
                primary_handler_read=bool(primary_body),
                primary_publishes_baseline=bool(
                    _PUBLISHES_BASELINE.search(primary_body)
                ),
                declares_required=bool(_DECLARES_BASELINE_REQUIRED.search(description)),
                declares_optional=bool(_DECLARES_BASELINE_OPTIONAL.search(description)),
            )
        )
    return stances


def _stance_conflict(
    stance: RoutingStance, *, via: str, tool: str, publishes: bool
) -> str:
    """One sentence naming which reading disagrees with the description."""

    return (
        f"{stance.skill}: description says baseline "
        f"{'required' if stance.declares_required else 'not required'}, "
        f"but {via} {tool} "
        f"{'publishes' if publishes else 'never publishes'} "
        "the baseline comparison"
    )


def test_routing_pair_handlers_still_split_on_the_baseline() -> None:
    """The discriminator these skills are written around still exists.

    Read first, because every lane below compares a description against this
    measurement: if the handlers were never found, or both landed on the same
    side, the prose lanes would agree with an instrument that measured
    nothing and pass while saying nothing.
    """

    stances = _routing_stances()
    unread = sorted(
        f"{stance.skill} -> {stance.tool}"
        for stance in stances
        if not stance.handler_read
    )

    assert len(stances) == len(ROUTING_PAIR)
    assert not unread, f"routing handlers were not found in the server source: {unread}"
    measured = sorted(
        (stance.tool, stance.handler_publishes_baseline) for stance in stances
    )

    assert {publishes for _, publishes in measured} == {True, False}, (
        f"the routing pair no longer splits on the baseline comparison: {measured}. "
        "Two tools that answer the same question cannot be routed between by "
        "any description, so the skills need redesigning, not rewording."
    )


def test_routing_pair_descriptions_declare_a_baseline_stance() -> None:
    """Each description says which side of the discriminator it is on.

    A router picks from descriptions alone. One that mentions neither leaves
    the choice to adjectives; one that mentions both discriminates nothing.
    """

    silent = sorted(
        stance.skill
        for stance in _routing_stances()
        if stance.declares_required == stance.declares_optional
    )

    assert not silent, (
        f"public skill descriptions declare no single baseline stance: {silent}. "
        "Each must state whether it needs a baseline or answers without one."
    )


def test_routing_pair_descriptions_declare_the_stance_their_handler_has() -> None:
    """The side a description claims is the side its handler is actually on.

    This is the edge the discriminator rides on. A skill that advertises
    baseline-relative content its tool never publishes sends the router to a
    tool that cannot answer, and the failure reads as the product being wrong.
    """

    wrong = sorted(
        _stance_conflict(
            stance,
            via="its handler",
            tool=stance.tool,
            publishes=stance.handler_publishes_baseline,
        )
        for stance in _routing_stances()
        if stance.declares_required != stance.handler_publishes_baseline
    )

    assert not wrong, f"public skill descriptions contradict their handlers: {wrong}"


def test_routing_pair_descriptions_declare_opposite_stances() -> None:
    """The pair lands on opposite sides, which is what makes it routable.

    Each skill can be individually truthful and the pair still be useless:
    two descriptions on the same side leave a model splitting hairs on
    adjectives, which is the state this guard exists to keep out.
    """

    stances = _routing_stances()
    requires = sorted(stance.skill for stance in stances if stance.declares_required)
    optional = sorted(stance.skill for stance in stances if stance.declares_optional)

    assert len(requires) == 1 and len(optional) == 1, (
        f"the routing pair does not declare opposite baseline stances: "
        f"requires={requires} optional={optional}"
    )


def test_routing_pair_bodies_teach_a_tool_matching_their_declared_stance() -> None:
    """The tool a skill's Loop teaches is on the side its description claims.

    The description is a promise about which question gets answered; the Loop
    fence is what the model will actually call. Two skills can describe
    themselves as perfect opposites and still collide, because a body can be
    re-pointed at the neighbouring tool without touching a word of either
    description — which is exactly how these two skills shipped.
    """

    stances = _routing_stances()
    unread = sorted(
        f"{stance.skill}: {stance.primary_tool or '(no Loop fence)'}"
        for stance in stances
        if not stance.primary_handler_read
    )
    mismatched = sorted(
        _stance_conflict(
            stance,
            via="its Loop teaches",
            tool=stance.primary_tool,
            publishes=stance.primary_publishes_baseline,
        )
        for stance in stances
        if stance.declares_required != stance.primary_publishes_baseline
    )
    taught = sorted(stance.primary_tool for stance in stances)

    assert not unread, (
        f"a Loop fence names a tool this guard cannot read: {unread}. "
        f"Add its module to HANDLER_SOURCES rather than leaving it unmeasured."
    )
    assert not mismatched, (
        f"public skill bodies teach a tool their description contradicts: {mismatched}"
    )
    assert len(set(taught)) == len(taught), (
        f"the routing pair teaches the same tool from both skills: {taught}. "
        "No wording can route between two skills whose loops end at the same "
        "call, however well their descriptions discriminate."
    )
