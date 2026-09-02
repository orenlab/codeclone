# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""The MCP surface owns no cache policy, and writes its own cache service data.

Four separate errors are pinned here, because they fail differently:

* a removed public cache control comes back onto the tool surface;
* the MCP stops taking its cache location from the owner the CLI uses, and
  grows a second copy of the answer;
* the MCP stops consulting the physical cache at all, and every run reports a
  cold path while looking exactly as healthy as a warm one;
* the MCP stops *writing* the cache it produced, so a root nobody analyses
  through the CLI stays cold forever and pays a full analysis every call --
  or writes it somewhere that is not CodeClone's to write.

The third is the reason the first is not allowed to stand in for a fix: a
schema with no cache knob is silent about whether the cache is read. The
fourth is the reason ``cache.used`` is never the evidence here: that field was
measured ``true`` on a run that reused nothing, so reuse is read from the run's
own analysed/cached counts instead.
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
import codeclone.surfaces.mcp.messages.facts as facts
from codeclone.api.workspace import is_codeclone_service_path
from codeclone.contracts import DEFAULT_CACHE_PATH, DEFAULT_MAX_CACHE_SIZE_MB
from codeclone.contracts.errors import CacheError
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
        # The default store is CodeClone's own service directory, so this
        # surface writes what its analysis produced (RULING 2026-09-02). The
        # boundary that replaces the old blanket refusal is asserted by
        # ``test_an_mcp_analysis_writes_only_inside_service_directories``.
        assert mcp_kwargs["write_enabled"] is True


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
    assert store.exists(), "an MCP analysis left the store cold"

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


def _reuse_counts(
    service: CodeCloneMCPService, summary: dict[str, object], root: Path
) -> dict[str, int]:
    """How many files this run reused, taken from the run it registered.

    Deliberately not ``cache.used``: that field reports that a physical store
    was consulted, and was measured ``true`` on a run whose reuse was zero. The
    analysed/cached pair is the count itself.
    """

    record = service._runs.get_for_root(str(summary["run_id"]), root=root)
    files = cast("dict[str, object]", record.summary["inventory"])["files"]
    counts = cast("dict[str, object]", files)
    return {
        "total_found": int(cast("int", counts["total_found"])),
        "analyzed": int(cast("int", counts["analyzed"])),
        "cached": int(cast("int", counts["cached"])),
    }


def test_a_root_only_mcp_has_analysed_is_warm_the_second_time(tmp_path: Path) -> None:
    """The cold-forever defect: MCP read the cache and never wrote it.

    Both runs are MCP; no CLI ever touches this root. The first must leave the
    store behind, and the second must reuse every file it found. The cold run
    is asserted first from the same counters, so a warm second run cannot be a
    counter wired to a constant.
    """

    root = (tmp_path / "repo").resolve()
    _write_repo(root)
    store = root / DEFAULT_CACHE_PATH
    service = CodeCloneMCPService(history_limit=4)

    assert not store.exists()
    first = service.analyze_repository(
        MCPAnalysisRequest(root=str(root), respect_pyproject=False)
    )
    cold = _reuse_counts(service, first, root)
    assert cold["total_found"] > 0, "the fixture repository analysed no files"
    assert cold["cached"] == 0
    assert cold["analyzed"] == cold["total_found"]
    assert store.exists() and store.stat().st_size > 0, (
        "an MCP analysis wrote no cache, so this root stays cold forever"
    )

    second = service.analyze_repository(
        MCPAnalysisRequest(root=str(root), respect_pyproject=False)
    )
    warm = _reuse_counts(service, second, root)
    assert warm["total_found"] == cold["total_found"]
    assert warm["cached"] == cold["total_found"]
    assert warm["analyzed"] == 0
    assert second["cache"] == {"used": True, "freshness": "reused"}


def _file_state(base: Path) -> dict[Path, tuple[int, int]]:
    return {
        path: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in base.rglob("*")
        if path.is_file()
    }


def test_an_mcp_analysis_writes_only_inside_service_directories(
    tmp_path: Path,
) -> None:
    """The boundary itself, not the one flag that happens to sit on it.

    Every file that appears or changes anywhere in the sandbox during one
    analysis is held against the containment predicate. The population is
    asserted first: a run that wrote nothing would satisfy an empty-set check
    while proving nothing at all.
    """

    sandbox = (tmp_path / "sandbox").resolve()
    root = sandbox / "repo"
    _write_repo(root)
    neighbour = sandbox / "outside"
    neighbour.mkdir(parents=True)
    (neighbour / "keep.txt").write_text("untouched", encoding="utf-8")
    before = _file_state(sandbox)

    CodeCloneMCPService(history_limit=2).analyze_repository(
        MCPAnalysisRequest(root=str(root), respect_pyproject=False)
    )

    after = _file_state(sandbox)
    touched = sorted(path for path in after if before.get(path) != after[path])
    assert touched, "the analysis wrote nothing, so containment was not exercised"
    escaped = [
        str(path) for path in touched if not is_codeclone_service_path(path, root=root)
    ]
    assert escaped == [], f"MCP wrote outside its service directories: {escaped}"
    assert (root / DEFAULT_CACHE_PATH) in touched, (
        "the cache is the write this boundary exists to permit"
    )


def test_a_cache_configured_outside_the_service_directories_is_read_only(
    tmp_path: Path,
) -> None:
    """The refusal side of the boundary, reached by repository configuration.

    ``cache_path`` is delivered to this surface from ``pyproject.toml``, so a
    repository can move the store out of ``.codeclone/``. The CLI may write it
    there; MCP may not, and says so instead of going quiet.
    """

    root = (tmp_path / "repo").resolve()
    _write_repo(root)
    (root / "pyproject.toml").write_text(
        '[tool.codeclone]\ncache_path = "build/cc-cache.sqlite3"\n',
        encoding="utf-8",
    )
    relocated = root / "build" / "cc-cache.sqlite3"
    service = CodeCloneMCPService(history_limit=2)

    summary = service.analyze_repository(
        MCPAnalysisRequest(root=str(root), respect_pyproject=True)
    )

    assert not relocated.exists(), "MCP wrote a cache outside its service directories"
    assert not (root / DEFAULT_CACHE_PATH).exists(), (
        "MCP fell back to the default store instead of honouring the configured one"
    )
    assert facts.CACHE_OUTSIDE_SERVICE_DIRECTORIES.format(cache_path=relocated) in cast(
        "list[str]", summary["warnings"]
    )


def test_the_analysis_releases_its_cache_entries_after_writing_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Written first, released second, and the order is a measured cost.

    ``release_loaded_entries`` refuses a dirty store, so a surface that
    released before saving would keep every analysed file's lanes in memory for
    the rest of the run and still write nothing. Both halves are asserted, so
    swapping the two statements fails here rather than quietly costing RAM.
    """

    root = (tmp_path / "repo").resolve()
    _write_repo(root)
    built: list[Any] = []
    real_cache: Any = mcp_helpers.Cache  # type: ignore[attr-defined]

    def recording_cache(path: Path, **kwargs: Any) -> Any:
        cache = real_cache(path, **kwargs)
        built.append(cache)
        return cache

    monkeypatch.setattr(mcp_helpers, "Cache", recording_cache)
    CodeCloneMCPService(history_limit=2).analyze_repository(
        MCPAnalysisRequest(root=str(root), respect_pyproject=False)
    )

    assert len(built) == 1, "the analysis opened no cache to release"
    store = root / DEFAULT_CACHE_PATH
    assert store.exists() and store.stat().st_size > 0
    assert len(built[0].data["files"]) == 0, (
        "the analysis kept its cache entries in memory after writing them"
    )


def test_a_cache_that_cannot_be_written_is_a_warning_not_a_failed_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A store this surface cannot write costs the next run time, not this one.

    Reachability for the failure branch: the input is a store whose save
    raises, and the run still returns its results with the reason attached.
    """

    root = (tmp_path / "repo").resolve()
    _write_repo(root)

    def exploding_save(self: Any) -> None:
        raise CacheError("cache store is read-only")

    # Reached through the surface's own reference to the store class: this
    # module is R4 and may not import the R2 cache package to name it.
    monkeypatch.setattr(
        mcp_helpers.Cache,  # type: ignore[attr-defined]
        "save",
        exploding_save,
    )
    summary = CodeCloneMCPService(history_limit=2).analyze_repository(
        MCPAnalysisRequest(root=str(root), respect_pyproject=False)
    )

    assert summary["run_id"], "a cache write failure must not lose the analysis"
    assert facts.CACHE_SAVE_FAILED.format(error="cache store is read-only") in cast(
        "list[str]", summary["warnings"]
    )
