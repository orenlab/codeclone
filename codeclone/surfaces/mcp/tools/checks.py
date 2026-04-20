# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from ._base import MCPToolSchema, SimpleMCPTool, run_kw

TOOLS = (
    SimpleMCPTool(
        name="check_complexity",
        schema=MCPToolSchema(title="Check Complexity"),
        runner=lambda session, params: run_kw(session.check_complexity, params),
    ),
    SimpleMCPTool(
        name="check_clones",
        schema=MCPToolSchema(title="Check Clones"),
        runner=lambda session, params: run_kw(session.check_clones, params),
    ),
    SimpleMCPTool(
        name="check_coupling",
        schema=MCPToolSchema(title="Check Coupling"),
        runner=lambda session, params: run_kw(session.check_coupling, params),
    ),
    SimpleMCPTool(
        name="check_cohesion",
        schema=MCPToolSchema(title="Check Cohesion"),
        runner=lambda session, params: run_kw(session.check_cohesion, params),
    ),
    SimpleMCPTool(
        name="check_dead_code",
        schema=MCPToolSchema(title="Check Dead Code"),
        runner=lambda session, params: run_kw(session.check_dead_code, params),
    ),
)
