# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""A run id sent as a JSON number must be refused with the fix, not the fault.

A short run id is the first eight characters of a sha256 hexdigest, so roughly
one id in forty-three is all digits. A client that serializes such an id as a
JSON number is rejected by the FastMCP argument model before any CodeClone
handler runs, and pydantic's vocabulary ("Input should be a valid string")
reads as *that id is malformed* rather than *quote it*. The id is fine; only
its encoding is wrong.

The two properties pinned here are deliberately separable.

*Executability* is proven by execution, never by matching a sentence: the
correction is parsed back out of the refusal as JSON, applied to the original
arguments, and the call is made again. If following the instruction does not
clear the fault the instruction names, it was not executable.

*Unambiguity* is proven by contrast: the refusal a numeric run id earns must
be distinguishable from the one any other numeric string parameter earns.
A diagnosis that reads the same for ``root`` as for ``run_id`` has told the
caller nothing specific, which is exactly today's defect.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Any, cast

import pytest

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

    from mcp.server.fastmcp import FastMCP

pytest.importorskip("mcp.server.fastmcp")

from codeclone.surfaces.mcp._protocol_diagnostics import (
    string_typed_run_id_parameters,
)
from codeclone.surfaces.mcp._session_shared import CodeCloneMCPRunStore
from codeclone.surfaces.mcp.server import build_mcp_server
from tests.test_mcp_service import _dummy_run_record

# The correction is a JSON object member, so the test can parse it instead of
# trusting its prose: '"run_id": "12345678"'.
#
# The value is matched as anything the refusal chose to put there, never as
# digits. A pattern that only admitted digits would silently fail to see a
# correction offering '-12345678' and would report no prescription at all —
# measured: it let a mutant that dropped the digit guard survive.
_CORRECTION = re.compile(r'"([a-z_]*run_id)"\s*:\s*"([^"]*)"')
# pydantic's own report, i.e. the refusal with no executable part.
_SCHEMA_FAULT = "Input should be a valid string"

_ALL_DIGIT_ID = "12345678"


def _refusal(server: FastMCP, tool: str, arguments: dict[str, Any]) -> str:
    """Call one tool and return the refusal text the caller receives."""

    try:
        asyncio.run(server.call_tool(tool, arguments))
    except Exception as exc:  # the refusal text is exactly the subject here
        return str(exc)
    msg = f"{tool} accepted {arguments!r}; expected a refusal"
    raise AssertionError(msg)


def _corrections(message: str) -> dict[str, str]:
    """Parse the prescribed correction back out of the refusal, as JSON."""

    members = ",".join(match.group(0) for match in _CORRECTION.finditer(message))
    if not members:
        return {}
    return cast("dict[str, str]", json.loads("{" + members + "}"))


def _run_id_parameters(server: FastMCP) -> dict[str, frozenset[str]]:
    """Every tool that declares a run-id parameter, as the client sees it."""

    tools = asyncio.run(server.list_tools())
    named = {}
    for tool in tools:
        properties = cast("dict[str, object]", tool.inputSchema.get("properties") or {})
        holders = frozenset(name for name in properties if name.endswith("run_id"))
        if holders:
            named[tool.name] = holders
    return named


@pytest.fixture(scope="module")
def server() -> FastMCP:
    return build_mcp_server(history_limit=4)


@pytest.fixture(scope="module")
def population(server: FastMCP) -> dict[str, frozenset[str]]:
    return _run_id_parameters(server)


@pytest.fixture(scope="module")
def sweep(
    server: FastMCP, population: dict[str, frozenset[str]]
) -> dict[str, tuple[frozenset[str], str]]:
    """Each run-id tool called once with every run-id parameter as a number."""

    probed: dict[str, tuple[frozenset[str], str]] = {}
    for tool, holders in sorted(population.items()):
        arguments = {name: int(_ALL_DIGIT_ID) for name in sorted(holders)}
        probed[tool] = (holders, _refusal(server, tool, arguments))
    return probed


def test_the_population_under_test_is_the_whole_run_id_surface(
    population: dict[str, frozenset[str]],
) -> None:
    """Witness before count: prove the surface is what the sweep will walk.

    Read from ``list_tools()`` rather than a hand list, so a tool that gains or
    loses a run-id parameter joins or leaves the sweep on its own.
    """

    occurrences = sum(len(holders) for holders in population.values())
    assert len(population) == 30, sorted(population)
    assert occurrences == 33
    assert frozenset().union(*population.values()) == {
        "run_id",
        "before_run_id",
        "after_run_id",
    }


def test_every_run_id_tool_prescribes_the_quoted_correction(
    sweep: dict[str, tuple[frozenset[str], str]],
) -> None:
    """The whole population, not one tool: each numeric run id earns the fix."""

    missing = {
        tool: message
        for tool, (holders, message) in sorted(sweep.items())
        if _corrections(message) != dict.fromkeys(holders, _ALL_DIGIT_ID)
    }
    assert missing == {}, f"tools refusing a numeric run id without the fix: {missing}"


def test_following_the_correction_clears_the_fault_it_names(
    server: FastMCP, sweep: dict[str, tuple[frozenset[str], str]]
) -> None:
    """Executability by execution: apply what the refusal says and re-call.

    The re-call may still fail — the run is not registered — but it must fail
    on run resolution, never again on the encoding the correction addressed.
    """

    still_rejected = {}
    for tool, (_holders, message) in sorted(sweep.items()):
        prescribed = _corrections(message)
        # Without this the test would pass on a refusal that prescribes
        # nothing: an empty correction re-calls the tool with no run id at all
        # and never reaches the schema fault it claims to have cleared.
        assert prescribed, f"{tool} prescribed no correction to follow: {message}"
        corrected = _refusal(server, tool, dict(prescribed))
        if _SCHEMA_FAULT in corrected:
            still_rejected[tool] = corrected
    assert still_rejected == {}, (
        f"the prescribed correction did not clear the schema fault: {still_rejected}"
    )


def test_the_correction_carries_the_value_the_caller_sent(server: FastMCP) -> None:
    """Derivation pin: the fix is built from this call, not from an example.

    A hardcoded specimen would satisfy every 'contains a quoted id' assertion
    while handing every caller somebody else's run id.
    """

    for sent in ("12345678", "87654321", "10000000"):
        message = _refusal(server, "get_run_summary", {"run_id": int(sent)})
        assert _corrections(message) == {"run_id": sent}, message


def test_the_refusal_is_specific_to_run_id_and_not_a_generic_type_complaint(
    server: FastMCP,
) -> None:
    """Unambiguity by contrast against a sibling string parameter.

    ``root`` is a string parameter of the same tool. Today both answers are the
    same sentence with a different field name, which is the ambiguity. The
    run-id answer must differ, and the ``root`` answer must not borrow it.
    """

    run_id_refusal = _refusal(server, "get_run_summary", {"run_id": 12345678})
    root_refusal = _refusal(server, "get_run_summary", {"root": 12345678})

    assert _corrections(run_id_refusal) == {"run_id": "12345678"}
    assert _corrections(root_refusal) == {}, (
        f"a numeric root borrowed the run-id diagnosis: {root_refusal}"
    )
    assert _SCHEMA_FAULT in root_refusal
    normalized_run_id = run_id_refusal.replace("run_id", "<param>")
    normalized_root = root_refusal.replace("root", "<param>")
    assert normalized_run_id != normalized_root, (
        "the run-id refusal is the generic string-type complaint with a "
        f"different field name: {run_id_refusal}"
    )


@pytest.mark.parametrize(
    ("sent", "expected"),
    [
        pytest.param(12345678, {"run_id": "12345678"}, id="int"),
        pytest.param(12345678.0, {"run_id": "12345678"}, id="integral-float"),
        pytest.param(1234.5678, {}, id="fractional-float"),
        pytest.param(True, {}, id="bool"),
        pytest.param(-12345678, {}, id="negative"),
    ],
)
def test_each_branch_of_the_correction_has_a_reachable_input(
    server: FastMCP, sent: object, expected: dict[str, str]
) -> None:
    """Every guard is proven reachable, and every refusal it declines is too.

    A correction is offered only where quoting the received number reproduces
    the id the caller meant. A fraction, a boolean and a negative cannot have
    come from an all-digit id, so they keep the schema refusal rather than
    receive a prescription that would hand back a value nobody sent.
    """

    message = _refusal(server, "get_run_summary", {"run_id": sent})
    assert _corrections(message) == expected, message
    if not expected:
        assert _SCHEMA_FAULT in message


def test_a_second_schema_fault_is_not_swallowed_by_the_run_id_refusal(
    server: FastMCP,
) -> None:
    """The prescription must not hide the other reason the call was rejected."""

    message = _refusal(server, "get_finding", {"run_id": 12345678})
    assert _corrections(message) == {"run_id": "12345678"}
    assert "finding_id" in message, message


def test_an_all_digit_run_id_resolves_once_it_is_quoted(tmp_path: Path) -> None:
    """The instruction is not merely followable, it is worth following.

    Run ids are opaque strings to the store, so an all-digit id is an ordinary
    id. Without this, the refusal could prescribe a correction that leads
    nowhere.
    """

    store = CodeCloneMCPRunStore(history_limit=4)
    store.register(_dummy_run_record(tmp_path, _ALL_DIGIT_ID))
    assert store.resolve_any_root(_ALL_DIGIT_ID).run_id == _ALL_DIGIT_ID


def test_a_run_id_parameter_that_admits_numbers_is_never_prescribed_a_fix() -> None:
    """The guard against the widening this refusal was chosen over.

    Every run-id parameter is a string today, so this input cannot be reached
    through the live tool population; it is reachable through the published
    function, which is where the contract has to hold if the parameter type is
    ever widened. Quoting is the fix only while the schema refuses a number.
    """

    assert string_typed_run_id_parameters(
        {"properties": {"run_id": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}
    ) == {"run_id"}
    assert (
        string_typed_run_id_parameters(
            {
                "properties": {
                    "run_id": {"anyOf": [{"type": "string"}, {"type": "integer"}]}
                }
            }
        )
        == frozenset()
    )
    # A variant naming no type of its own cannot be read as a string, so the
    # parameter falls back to the schema refusal rather than to a guess.
    assert (
        string_typed_run_id_parameters(
            {"properties": {"run_id": {"anyOf": [{"$ref": "#/$defs/RunId"}]}}}
        )
        == frozenset()
    )


def test_the_caller_receives_the_refusal_through_the_protocol_handler() -> None:
    """What the client is handed, not what the server method returns.

    Every other pin here drives ``FastMCP.call_tool``. The MCP client never
    calls that: it sends a CallToolRequest, and the registered handler turns
    the raised refusal into the error text of a CallToolResult. The two are
    the same path only because FastMCP binds the one to the other at setup,
    which is a fact about a dependency, not a fact this repository controls.
    """

    import mcp.types as types

    server = build_mcp_server(history_limit=4)
    handler = server._mcp_server.request_handlers[types.CallToolRequest]
    request = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(
            name="get_run_summary", arguments={"run_id": 12345678}
        ),
    )
    served = cast("Any", asyncio.run(cast("Any", handler(request))))
    delivered = cast("Any", served.root)
    assert delivered.isError is True
    text = "\n".join(block.text for block in delivered.content)
    assert text.startswith("run id is a string; quote it."), text
    assert _corrections(text) == {"run_id": _ALL_DIGIT_ID}, text
