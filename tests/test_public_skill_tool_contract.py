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

import asyncio
import re
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
from tests.plugin_test_helpers import CODEX_PLUGIN_SKILL_NAMES

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

# No whitespace before "(": prose such as "fixtures (the gate counts
# production)" is a parenthetical, never a call, and admitting it would
# bury the real findings under English.
_CALL_START = re.compile(r"\b([a-z][a-z0-9_]*)\(")
_KWARG = re.compile(r"\b([a-z][a-z0-9_]*)\s*=")
_QUOTED_POSITIONAL = re.compile(r'(?:^|,)\s*(["\'][^"\']*["\'])\s*(?:,|$)')
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
    """No literal sits in a positional slot.

    MCP takes one JSON object per call, so a quoted literal written where a
    positional argument would go is silently read as whichever parameter
    happens to come first — and that parameter is usually ``root``.
    """

    positional = sorted(
        f"{call.skill}: {call.name}(…, {literal})"
        for call in _tool_calls(_documented_calls())
        for literal in _QUOTED_POSITIONAL.findall(_NESTED_GROUP.sub("_", call.body))
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
