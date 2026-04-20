# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from typing import cast

from ._base import MCPToolSchema, SimpleMCPTool

TOOLS = (
    SimpleMCPTool(
        name="get_run_summary",
        schema=MCPToolSchema(title="Get Run Summary"),
        runner=lambda session, params: session.get_run_summary(
            cast("str | None", params.get("run_id"))
        ),
    ),
    SimpleMCPTool(
        name="clear_session_runs",
        schema=MCPToolSchema(title="Clear Session Runs"),
        runner=lambda session, _params: session.clear_session_runs(),
    ),
)
