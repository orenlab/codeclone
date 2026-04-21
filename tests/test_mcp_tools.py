# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable

import pytest

from codeclone.surfaces.mcp.session import (
    MCPAnalysisRequest,
    MCPGateRequest,
    MCPServiceContractError,
)
from codeclone.surfaces.mcp.tools._base import MCPToolSchema, SimpleMCPTool
from codeclone.surfaces.mcp.tools.analyze import _analysis_request
from codeclone.surfaces.mcp.tools.gates import _gate_request
from codeclone.surfaces.mcp.tools.runs import _run_id


class _Session:
    def __init__(self) -> None:
        self.value = "ok"

    def __getattr__(self, name: str) -> Callable[..., object]:
        raise AttributeError(name)


def test_analysis_request_requires_typed_request() -> None:
    request = MCPAnalysisRequest(root="/repo")

    assert _analysis_request({"request": request}) is request

    with pytest.raises(MCPServiceContractError, match="valid MCPAnalysisRequest"):
        _analysis_request({"request": object()})


def test_gate_request_requires_typed_request() -> None:
    request = MCPGateRequest(fail_on_new=True)

    assert _gate_request({"request": request}) is request

    with pytest.raises(MCPServiceContractError, match="valid MCPGateRequest"):
        _gate_request({"request": "broken"})


def test_run_id_accepts_only_strings() -> None:
    assert _run_id({"run_id": "abc123"}) == "abc123"
    assert _run_id({"run_id": 123}) is None


def test_simple_mcp_tool_runs_bound_runner() -> None:
    tool = SimpleMCPTool(
        name="demo",
        schema=MCPToolSchema(title="Demo"),
        runner=lambda session, params: (session.value, dict(params)),
    )

    assert tool.run(_Session(), {"alpha": 1}) == ("ok", {"alpha": 1})
