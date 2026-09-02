# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""The MCP surface owns no cache policy, and reads the cache the CLI writes.

Three separate errors are pinned here, because they fail differently:

* a removed public cache control comes back onto the tool surface;
* the MCP stops taking its cache location from the owner the CLI uses, and
  grows a second copy of the answer;
* the MCP stops consulting the physical cache at all, and every run reports a
  cold path while looking exactly as healthy as a warm one.

The last one is the reason the first is not allowed to stand in for a fix: a
schema with no cache knob is silent about whether the cache is read.
"""

from __future__ import annotations

import asyncio
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any, cast

import pytest

import codeclone.surfaces.cli.runtime as cli_runtime
import codeclone.surfaces.mcp._session_helpers as mcp_helpers
from codeclone.contracts import DEFAULT_CACHE_PATH, DEFAULT_MAX_CACHE_SIZE_MB
from codeclone.surfaces.mcp._session_shared import _BufferConsole
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import (
    MCPAnalysisRequest,
    MCPServiceContractError,
)

# Public MCP tool parameters withdrawn in 2.1.0a2. Managing the physical cache
# backend is not a per-tool-call policy, so the surface must not offer one.
REMOVED_CACHE_CONTROLS = ("cache_policy", "cache_path", "max_cache_size_mb")
ANALYSIS_TOOLS = ("analyze_repository", "analyze_changed_paths")


def _write_repo(root: Path) -> None:
    package = root / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    for index in range(4):
        (package / f"mod{index}.py").write_text(
            f"def f{index}(a, b):\n"
            "    total = 0\n"
            "    for x in range(a):\n"
            "        total += x * b\n"
            "    return total\n",
            encoding="utf-8",
        )


def _tool_input_schemas() -> dict[str, dict[str, object]]:
    pytest.importorskip("mcp.server.fastmcp")
    from codeclone.surfaces.mcp.server import build_mcp_server

    server = build_mcp_server(history_limit=2)
    tools = asyncio.run(server.list_tools())
    return {tool.name: dict(tool.inputSchema) for tool in tools}


def _properties(schema: dict[str, object]) -> dict[str, object]:
    properties = schema.get("properties")
    assert isinstance(properties, dict), "tool schema carries no properties block"
    return properties


def test_analysis_tools_expose_no_cache_control_parameters() -> None:
    schemas = _tool_input_schemas()

    for name in ANALYSIS_TOOLS:
        assert name in schemas, f"{name} is missing from the MCP tool surface"
        properties = _properties(schemas[name])
        # Population: the schema really is this tool's parameter list, so an
        # empty intersection below means "absent", not "nothing was compared".
        assert "root" in properties, f"{name} schema was read but carries no root"
        present = sorted(set(properties) & set(REMOVED_CACHE_CONTROLS))
        assert present == [], f"{name} still declares cache controls: {present}"


def test_no_mcp_tool_declares_a_cache_control_parameter() -> None:
    schemas = _tool_input_schemas()
    assert len(schemas) >= 30, "tool surface came back too small to be the real one"

    offenders = {
        name: sorted(set(_properties(schema)) & set(REMOVED_CACHE_CONTROLS))
        for name, schema in schemas.items()
        if set(_properties(schema)) & set(REMOVED_CACHE_CONTROLS)
    }
    assert offenders == {}


@pytest.mark.parametrize("control", REMOVED_CACHE_CONTROLS)
def test_analysis_request_rejects_removed_cache_controls(control: str) -> None:
    # A caller that still passes one gets a typed rejection naming the argument,
    # never a silently ignored knob.
    withdrawn: dict[str, Any] = {control: "off"}
    with pytest.raises(TypeError, match=control):
        MCPAnalysisRequest(root="/nonexistent", **withdrawn)


def _cli_cache_path(root: Path, tmp_path: Path) -> Path:
    """Where ``cli.analyze`` would open the cache for this root, asked of the CLI."""

    return cli_runtime.resolve_cache_path(
        root_path=root,
        args=Namespace(cache_path=None),
        from_args=False,
        legacy_cache_path=tmp_path / "legacy-home-cache.json",
        console=_BufferConsole(),
    )


def test_mcp_opens_the_cache_the_cli_would_have_opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The MCP has no cache location of its own left to have.

    The path is not re-derived here and compared to a literal: it is taken from
    the ``Cache`` the MCP actually constructs, and held against what the CLI's
    own resolver answers for the same root and against the ratified value owner
    in ``contracts``. Two roots, because one agreeing answer is a coincidence.

    Ring note: the owner itself (``paths.workspace``) is r2 and this module's
    subject is r4, so the owner is reached through the two surfaces rather than
    imported and replaced with a sentinel. A private MCP copy that reproduced
    the same value for both roots would survive this pin; one that answered
    differently anywhere would not.
    """

    service = CodeCloneMCPService(history_limit=4)
    built: list[tuple[Path, dict[str, Any]]] = []

    real_cache: Any = mcp_helpers.Cache  # type: ignore[attr-defined]

    def recording_cache(path: Path, **kwargs: Any) -> Any:
        built.append((Path(path), dict(kwargs)))
        return real_cache(path, **kwargs)

    monkeypatch.setattr(mcp_helpers, "Cache", recording_cache)

    for name in ("repo", "another repo"):
        root = (tmp_path / name).resolve()
        _write_repo(root)
        opened_before = len(built)

        service.analyze_repository(
            MCPAnalysisRequest(root=str(root), respect_pyproject=False)
        )

        assert len(built) == opened_before + 1, "the MCP built no cache for this root"
        mcp_path, mcp_kwargs = built[-1]
        assert mcp_path == _cli_cache_path(root, tmp_path)
        assert mcp_path == root / DEFAULT_CACHE_PATH
        assert mcp_kwargs["max_size_bytes"] == DEFAULT_MAX_CACHE_SIZE_MB * 1024 * 1024
        # The MCP reads the cache and never writes it; that is the contract this
        # removal must not quietly widen.
        assert mcp_kwargs["write_enabled"] is False


def _warm_the_store_with_the_cli(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import codeclone.surfaces.cli.workflow as cli

    with monkeypatch.context() as patch:
        patch.setattr(sys, "argv", ["codeclone", str(root)])
        try:
            cli.main()
        except SystemExit as exit_signal:
            assert exit_signal.code in (None, 0, 1)


def test_mcp_analysis_reports_the_cache_it_was_given(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cache.used`` tracks the physical store, in both of its two states.

    Asserting only the warm case would pass on a field wired to a constant, so
    the cold case is asserted first, from the same field, on the same root.
    """

    root = tmp_path / "repo"
    _write_repo(root)
    store = _cli_cache_path(root.resolve(), tmp_path)
    service = CodeCloneMCPService(history_limit=4)

    assert not store.exists(), "the store was already warm before the cold run"
    cold = service.analyze_repository(
        MCPAnalysisRequest(root=str(root.resolve()), respect_pyproject=False)
    )
    assert cold["cache"] == {"used": False, "freshness": "fresh"}
    assert not store.exists(), "an MCP analysis wrote the analysis cache"

    _warm_the_store_with_the_cli(root, monkeypatch)
    assert store.exists() and store.stat().st_size > 0, "the CLI warmed no store"

    warm = service.analyze_repository(
        MCPAnalysisRequest(root=str(root.resolve()), respect_pyproject=False)
    )
    assert cast("dict[str, object]", warm["cache"])["used"] is True


def _server() -> object:
    pytest.importorskip("mcp.server.fastmcp")
    from codeclone.surfaces.mcp.server import build_mcp_server

    return build_mcp_server(history_limit=2)


def test_the_refused_names_are_exactly_the_ones_that_left_the_schema() -> None:
    """The refusal is blanket, so it must name only withdrawn parameters.

    Rejecting these names on every tool is safe precisely because no published
    tool declares one -- asserted here against the live schemas, not assumed.
    """

    pytest.importorskip("mcp.server.fastmcp")
    from codeclone.surfaces.mcp.server import WITHDRAWN_CACHE_PARAMETERS

    assert set(WITHDRAWN_CACHE_PARAMETERS) == set(REMOVED_CACHE_CONTROLS)
    schemas = _tool_input_schemas()
    declared = {name for schema in schemas.values() for name in _properties(schema)}
    assert declared, "no tool parameters were compared"
    assert declared & set(WITHDRAWN_CACHE_PARAMETERS) == set()


@pytest.mark.parametrize("tool_name", ANALYSIS_TOOLS)
@pytest.mark.parametrize("control", REMOVED_CACHE_CONTROLS)
def test_a_withdrawn_cache_control_is_refused_not_ignored(
    tool_name: str,
    control: str,
) -> None:
    """Removal must be audible to a client that has not caught up yet.

    FastMCP drops unknown arguments silently, so absence from the schema alone
    would let an old client keep sending a cache policy and keep believing it.
    """

    server = _server()
    with pytest.raises(MCPServiceContractError, match=control):
        asyncio.run(
            server.call_tool(  # type: ignore[attr-defined]
                tool_name,
                {"root": "/tmp", control: "reuse"},
            )
        )


def test_the_refusal_reaches_the_wire_handler(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.fastmcp")
    from mcp.types import CallToolRequest, CallToolRequestParams

    server = _server()
    handler = server._mcp_server.request_handlers[CallToolRequest]  # type: ignore[attr-defined]
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(
            name="analyze_repository",
            arguments={"root": str(tmp_path), "cache_policy": "reuse"},
        ),
    )

    result = asyncio.run(handler(request)).root

    assert result.isError is True
    assert "no longer accepts cache_policy" in result.content[0].text


def test_the_guard_lets_a_call_without_withdrawn_parameters_through(
    tmp_path: Path,
) -> None:
    """Population: some input reaches past the guard, so it is not a wall."""

    root = tmp_path / "repo"
    _write_repo(root)
    server = _server()

    payload = asyncio.run(
        server.call_tool(  # type: ignore[attr-defined]
            "analyze_repository",
            {"root": str(root.resolve()), "respect_pyproject": False},
        )
    )

    assert payload


def test_a_configured_out_of_repo_cache_path_is_still_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The artifact trust boundary keeps its last remaining input.

    Removing the request parameter left repository configuration as the only
    way to move the MCP's cache off the workspace default. That is the same
    input the CLI takes -- but the MCP still confines it to the scan root, and
    a refusal nothing can reach is not a boundary. This is the input that
    reaches it.
    """

    import codeclone.surfaces.mcp._session_state_mixin as mcp_state

    root = tmp_path / "repo"
    _write_repo(root)
    outside = tmp_path / "outside-cache.json"
    monkeypatch.setattr(
        mcp_state,
        "load_repository_config",
        lambda _root: {"cache_path": str(outside)},
    )
    service = CodeCloneMCPService(history_limit=2)

    with pytest.raises(MCPServiceContractError, match="Invalid path"):
        service.analyze_repository(
            MCPAnalysisRequest(root=str(root.resolve()), respect_pyproject=True)
        )
