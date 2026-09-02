# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""One surface's call must not change what the other reports.

The api-surface cache profile key was ``bool(args.api_surface)`` while the
workers materialized on ``not skip_metrics and bool(args.api_surface)``. A run
that skipped metrics therefore left rows keyed as if the lane had been
collected and empty of it, and both surfaces resolve the same store.

Measured before the witness: one MCP ``clones_only`` call on a repository whose
``pyproject.toml`` asks for the lane silently turned the next plain CLI run's
``public_symbols`` from 5 to 0 and its ``enabled`` from true to false — on the
repository itself, 5409 to 0 and ``breaking`` 50 to 4949, because an empty
current snapshot against an intact baseline reads every stored symbol as
removed.

The CLI refuses ``--skip-metrics --api-surface`` on the command line and MCP
has no such guard, which is why the poisoning is driven from MCP and observed
from the CLI: a guard on one surface of a shared store is not a guard.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

import pytest

from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest
from codeclone.surfaces.mcp.service import CodeCloneMCPService

# Five exported symbols by construction: ``__all__`` names three top-level
# entities, and ``Beta`` contributes the two method names the visibility owner
# calls public (``__init__`` is in its public-dunder set, ``run`` is plain).
# The count is derived from the fixture's own rule, not copied from a run.
_MODULE_SOURCE = """\
__all__ = ["ALPHA", "Beta", "gamma"]

ALPHA = 1


class Beta:
    def __init__(self) -> None:
        self.value = 1

    def run(self, item: int) -> int:
        return item


def gamma(value: int) -> int:
    return value
"""
_EXPECTED_PUBLIC_SYMBOLS = 5
_EXPECTED_MODULES = 1


def _fixture_repo(root: Path) -> None:
    """A repository whose configuration, not its command line, asks for the lane.

    ``[tool.codeclone] api_surface`` is the shape that reaches both surfaces.
    The CLI refuses ``--skip-metrics --api-surface`` on the command line, so a
    configured lane is the only way the two decisions can disagree.
    """

    package = root / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mod.py").write_text(_MODULE_SOURCE, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[tool.codeclone]\napi_surface = true\n", encoding="utf-8"
    )


def _cli_api_surface_summary(
    root: Path,
    report_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    """What a plain ``codeclone <root> --json`` run reports for the lane."""

    import codeclone.surfaces.cli.workflow as cli

    with monkeypatch.context() as patch:
        patch.setattr(
            sys,
            "argv",
            ["codeclone", str(root), "--no-progress", "--json", str(report_path)],
        )
        try:
            cli.main()
        except SystemExit as exit_signal:
            assert exit_signal.code in (None, 0, 1)
    payload = json.loads(report_path.read_text("utf-8"))
    metrics = cast("dict[str, object]", payload["metrics"])
    summary = cast("dict[str, object]", metrics["summary"])
    return cast("dict[str, object]", summary["api_surface"])


def test_a_clones_only_call_cannot_disable_the_api_lane_for_the_next_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One MCP ``clones_only`` call must not change what the CLI then reports.

    Both roots are the same fixture, and the control is measured first from the
    same field on the same command, so an agreeing warm run cannot be a
    constant. The only difference between them is that something else consulted
    the shared store first — which is not an input to "what is this
    repository's public API".
    """

    control_root = (tmp_path / "control").resolve()
    poisoned_root = (tmp_path / "poisoned").resolve()
    _fixture_repo(control_root)
    _fixture_repo(poisoned_root)

    control = _cli_api_surface_summary(
        control_root, tmp_path / "control.json", monkeypatch
    )
    assert control["enabled"] is True
    assert control["modules"] == _EXPECTED_MODULES
    assert control["public_symbols"] == _EXPECTED_PUBLIC_SYMBOLS

    service = CodeCloneMCPService(history_limit=4)
    service.analyze_repository(
        MCPAnalysisRequest(root=str(poisoned_root), analysis_mode="clones_only")
    )

    poisoned = _cli_api_surface_summary(
        poisoned_root, tmp_path / "poisoned.json", monkeypatch
    )
    assert poisoned == control
