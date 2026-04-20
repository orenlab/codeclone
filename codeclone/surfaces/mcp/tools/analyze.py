# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from typing import cast

from ..session import MCPAnalysisRequest
from ._base import MCPToolSchema, SimpleMCPTool

TOOLS = (
    SimpleMCPTool(
        name="analyze_repository",
        schema=MCPToolSchema(title="Analyze Repository"),
        runner=lambda session, params: session.analyze_repository(
            cast("MCPAnalysisRequest", params["request"])
        ),
    ),
    SimpleMCPTool(
        name="analyze_changed_paths",
        schema=MCPToolSchema(title="Analyze Changed Paths"),
        runner=lambda session, params: session.analyze_changed_paths(
            cast("MCPAnalysisRequest", params["request"])
        ),
    ),
)
