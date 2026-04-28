# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from ._base import MCPToolSchema, SimpleMCPTool


def _run_id(params: dict[str, object]) -> str | None:
    value = params.get("run_id")
    return value if isinstance(value, str) else None


TOOLS = (
    SimpleMCPTool(
        name="get_run_summary",
        schema=MCPToolSchema(title="Get Run Summary"),
        runner=lambda session, params: session.get_run_summary(_run_id(dict(params))),
    ),
    SimpleMCPTool(
        name="clear_session_runs",
        schema=MCPToolSchema(title="Clear Session Runs"),
        runner=lambda session, _params: session.clear_session_runs(),
    ),
)
