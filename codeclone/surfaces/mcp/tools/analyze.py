# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from collections.abc import Mapping

from ..session import MCPAnalysisRequest, MCPServiceContractError
from ._base import MCPToolSchema, SimpleMCPTool


def _analysis_request(params: Mapping[str, object]) -> MCPAnalysisRequest:
    request = params.get("request")
    if not isinstance(request, MCPAnalysisRequest):
        raise MCPServiceContractError("Tool requires a valid MCPAnalysisRequest.")
    return request


TOOLS = (
    SimpleMCPTool(
        name="analyze_repository",
        schema=MCPToolSchema(title="Analyze Repository"),
        runner=lambda session, params: session.analyze_repository(
            _analysis_request(params)
        ),
    ),
    SimpleMCPTool(
        name="analyze_changed_paths",
        schema=MCPToolSchema(title="Analyze Changed Paths"),
        runner=lambda session, params: session.analyze_changed_paths(
            _analysis_request(params)
        ),
    ),
)
