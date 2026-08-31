# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""A refusal may only prescribe what its own tool can accept.

A typed refusal that names a parameter is an instruction. The instruction is
executable only when that parameter exists in the input schema of the tool
that emitted the refusal — otherwise the caller is told to do something the
wire will reject, and the typed outcome has no next step at all.

The two halves of that predicate come from different places on purpose. The
prescription is read out of the refusal a live tool call produced; the
parameter vocabulary is read out of the FastMCP input schemas the client
actually sees. Neither side can vouch for the other.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mcp.server.fastmcp import FastMCP

pytest.importorskip("mcp.server.fastmcp")

from codeclone.surfaces.mcp.server import build_mcp_server

# "pass root", "provide run_id", "set limit" — a bare instruction to hand the
# tool a named value.
_BARE_PRESCRIPTION = re.compile(
    r"\b(?:pass|provide|supply|set)\s+(?:an?\s+|the\s+)?([a-z_][a-z0-9_]{2,})\b",
    re.IGNORECASE,
)
# "analyze_repository(root='...')" — an instruction to call a named tool with
# a named argument.
_CALL_PRESCRIPTION = re.compile(
    r"\b([a-z_][a-z0-9_]{2,})\s*\(\s*([a-z_][a-z0-9_]{2,})\s*=",
)

# Arguments a tool needs before it can reach run resolution at all. Kept
# explicit so a newly added tool fails loudly here instead of dropping out of
# the sweep unnoticed.
_REQUIRED_ARGUMENTS: dict[str, dict[str, object]] = {
    "check_patch_contract": {"mode": "verify", "changed_files": ["pkg/mod.py"]},
    "finish_controlled_change": {"intent_id": "no-such-intent"},
    "get_blast_radius": {"files": ["pkg/mod.py"]},
    "get_finding": {"finding_id": "no-such-finding"},
    "get_implementation_context_page": {
        "context_projection_digest": "0" * 64,
        "facet": "modules",
    },
    "get_remediation": {"finding_id": "no-such-finding"},
    "list_hotspots": {"kind": "highest_priority"},
    "manage_change_intent": {"action": "check", "changed_files": ["pkg/mod.py"]},
    "manage_engineering_memory": {"action": "validate_claims", "text": "a claim"},
    "mark_finding_reviewed": {"finding_id": "no-such-finding"},
    "validate_review_claims": {"text": "a claim about pkg/mod.py"},
}

# Tools measured to answer a collided run id with the multi-root refusal. The
# sweep asserts every one of them still reaches it: a probe that stopped
# reaching the refusal would otherwise report a clean run it never made.
_KNOWN_AMBIGUITY_EMITTERS = frozenset(
    {
        "check_authority",
        "check_clones",
        "check_cohesion",
        "check_complexity",
        "check_coupling",
        "check_dead_code",
        "compare_runs",
        "create_review_receipt",
        "evaluate_gates",
        "generate_pr_summary",
        "get_blast_radius",
        "get_finding",
        "get_production_triage",
        "get_remediation",
        "get_report_section",
        "get_run_summary",
        "list_findings",
        "list_hotspots",
        "list_reviewed_findings",
        "mark_finding_reviewed",
        "validate_review_claims",
    }
)

_AMBIGUITY_SIGNATURE = "exists under several repository roots"


def _tool_schemas(
    server: FastMCP,
) -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    """Parameter names and required names per tool, as the MCP client sees them."""

    tools = asyncio.run(server.list_tools())
    properties = {
        tool.name: frozenset(
            cast("dict[str, object]", tool.inputSchema.get("properties") or {})
        )
        for tool in tools
    }
    required = {
        tool.name: frozenset(cast("list[str]", tool.inputSchema.get("required") or []))
        for tool in tools
    }
    return properties, required


def unexecutable_prescriptions(
    tool: str,
    message: str,
    schemas: dict[str, frozenset[str]],
) -> tuple[str, ...]:
    """Names this refusal tells the caller to use that the wire would reject.

    A name counts as a prescription when it is a parameter of *some* MCP tool,
    or when it is written as an identifier (``checkout_root``) rather than as
    prose. Renaming the prescribed parameter to something no tool has is the
    same defect as naming one this tool lacks, so both must be caught, while
    ordinary prose ("pass an exact qualname") stays out without a
    hand-maintained stop list.
    """

    vocabulary = frozenset().union(*schemas.values()) if schemas else frozenset()
    own = schemas.get(tool, frozenset())
    flagged: list[str] = []
    for match in _BARE_PRESCRIPTION.finditer(message):
        name = match.group(1).lower()
        prescribed = name in vocabulary or "_" in name
        if prescribed and name not in own:
            flagged.append(f"{tool} cannot accept '{name}'")
    for match in _CALL_PRESCRIPTION.finditer(message):
        callee, parameter = match.group(1), match.group(2)
        if callee in schemas and parameter not in schemas[callee]:
            flagged.append(f"{callee} cannot accept '{parameter}'")
    return tuple(dict.fromkeys(flagged))


def _write_identical_worktree(root: Path) -> None:
    package = root / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mod.py").write_text(
        "def alpha(value: int) -> int:\n    return value + 1\n",
        encoding="utf-8",
    )


def _collided_server(tmp_path: Path) -> tuple[FastMCP, str, Path]:
    """Two byte-identical checkouts, analyzed through the real MCP surface.

    Run ids are content-addressed, so this is the live collision rather than a
    hand-built store: both roots answer to one id.
    """

    server = build_mcp_server(history_limit=4)
    run_ids: list[str] = []
    for name in ("worktree-a", "worktree-b"):
        root = tmp_path / name
        _write_identical_worktree(root)
        result = asyncio.run(
            server.call_tool(
                "analyze_repository",
                {"root": str(root), "respect_pyproject": False},
            )
        )
        # FastMCP declares Sequence[ContentBlock] | dict, but a structured
        # tool answers with the (content, structured_payload) pair, and the
        # payload is what carries the run id.
        payload = cast("tuple[object, dict[str, object]]", result)[1]
        run_ids.append(str(payload["run_id"]))
    assert run_ids[0] == run_ids[1], (
        f"identical checkouts must produce one content-addressed run id; got {run_ids}"
    )
    return server, run_ids[0], tmp_path / "worktree-a"


def _probe(
    server: FastMCP,
    tool: str,
    *,
    run_id: str,
    schemas: dict[str, frozenset[str]],
    required: dict[str, frozenset[str]],
    root: Path,
) -> str | None:
    """Call one tool with the collided id; return its refusal text, if any.

    The root is supplied only where the schema demands it. Everywhere else the
    call stays rootless on purpose: that is the caller the refusal addresses,
    and handing the tool a root would resolve the collision the probe exists
    to observe.
    """

    arguments: dict[str, Any] = dict(_REQUIRED_ARGUMENTS.get(tool, {}))
    properties = schemas[tool]
    if "root" in required[tool]:
        arguments["root"] = str(root)
    for name in ("run_id", "before_run_id", "after_run_id"):
        if name in properties:
            arguments[name] = run_id
    try:
        asyncio.run(server.call_tool(tool, arguments))
    except Exception as exc:  # the refusal text is exactly the subject here
        return str(exc)
    return None


@pytest.fixture(scope="module")
def collided_sweep(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, str], dict[str, frozenset[str]]]:
    """Every run-id tool called once against a live two-root collision."""

    server, run_id, root = _collided_server(tmp_path_factory.mktemp("collision"))
    schemas, required = _tool_schemas(server)
    probed = sorted(
        name
        for name, properties in schemas.items()
        if any(item.endswith("run_id") for item in properties)
    )
    assert set(_REQUIRED_ARGUMENTS) <= set(probed), (
        "the required-argument table names tools that are not probed"
    )
    refusals: dict[str, str] = {}
    for tool in probed:
        message = _probe(
            server,
            tool,
            run_id=run_id,
            schemas=schemas,
            required=required,
            root=root,
        )
        if message is not None:
            refusals[tool] = message
    return refusals, schemas


def test_the_sweep_still_reaches_the_multi_root_refusal(
    collided_sweep: tuple[dict[str, str], dict[str, frozenset[str]]],
) -> None:
    """Witness before count: prove the instrument is on before reading it.

    Without this, a sweep that quietly stopped producing refusals would report
    a clean result it never measured.
    """

    refusals, _schemas = collided_sweep
    ambiguity = {
        tool for tool, text in refusals.items() if _AMBIGUITY_SIGNATURE in text
    }
    assert ambiguity >= _KNOWN_AMBIGUITY_EMITTERS, (
        "tools that no longer reach the multi-root refusal: "
        f"{sorted(_KNOWN_AMBIGUITY_EMITTERS - ambiguity)}"
    )


def test_refusals_prescribe_only_parameters_their_own_tool_accepts(
    collided_sweep: tuple[dict[str, str], dict[str, frozenset[str]]],
) -> None:
    """No tool may answer a collided run id with an instruction it would reject."""

    refusals, schemas = collided_sweep
    violations = {
        tool: found
        for tool, text in sorted(refusals.items())
        if (found := unexecutable_prescriptions(tool, text, schemas))
    }
    assert violations == {}, (
        f"refusals prescribe parameters their own tool cannot accept: {violations}"
    )


def test_predicate_flags_a_prescription_the_emitting_tool_cannot_accept() -> None:
    """The blind side: a name absent from the tool's own schema must be flagged."""

    schemas = {
        "get_report_section": frozenset({"run_id", "section"}),
        "check_clones": frozenset({"run_id", "root"}),
    }
    assert unexecutable_prescriptions(
        "get_report_section",
        "Run id 'abc' exists under several repository roots (a, b); "
        "pass root to select one.",
        schemas,
    ) == ("get_report_section cannot accept 'root'",)


def test_predicate_accepts_a_prescription_the_emitting_tool_can_honour() -> None:
    """The panicky side: the same words are executable where the parameter exists."""

    schemas = {
        "get_report_section": frozenset({"run_id", "section"}),
        "check_clones": frozenset({"run_id", "root"}),
    }
    assert (
        unexecutable_prescriptions(
            "check_clones",
            "Run id 'abc' exists under several repository roots (a, b); "
            "pass root to select one.",
            schemas,
        )
        == ()
    )


def test_predicate_ignores_prose_that_is_not_a_parameter_name() -> None:
    """Prose must not be read as a prescription, or the ratchet cries wolf."""

    schemas = {"get_implementation_context": frozenset({"run_id", "root"})}
    assert (
        unexecutable_prescriptions(
            "get_implementation_context",
            "Pass an exact qualname as module:symbol with a colon separator.",
            schemas,
        )
        == ()
    )


def test_predicate_flags_a_prescription_no_tool_at_all_would_accept() -> None:
    """Renaming the prescribed parameter must not launder it past the ratchet."""

    schemas = {
        "get_report_section": frozenset({"run_id", "section"}),
        "check_clones": frozenset({"run_id", "root"}),
    }
    assert unexecutable_prescriptions(
        "get_report_section",
        "Run id 'abc' exists under several repository roots (a, b); "
        "pass checkout_root to select one.",
        schemas,
    ) == ("get_report_section cannot accept 'checkout_root'",)


def test_predicate_flags_a_cross_tool_call_form_with_an_unknown_parameter() -> None:
    """A refusal may also prescribe another tool; that call must be valid too."""

    schemas = {
        "get_report_section": frozenset({"run_id"}),
        "analyze_repository": frozenset({"root"}),
    }
    assert unexecutable_prescriptions(
        "get_report_section",
        "Call analyze_repository(checkout='/repo') and retry.",
        schemas,
    ) == ("analyze_repository cannot accept 'checkout'",)


def test_predicate_accepts_a_valid_cross_tool_call_form() -> None:
    """The executable cross-tool prescription must stay unflagged."""

    schemas = {
        "get_report_section": frozenset({"run_id"}),
        "analyze_repository": frozenset({"root"}),
    }
    assert (
        unexecutable_prescriptions(
            "get_report_section",
            "Call analyze_repository(root='/repo') and retry.",
            schemas,
        )
        == ()
    )
