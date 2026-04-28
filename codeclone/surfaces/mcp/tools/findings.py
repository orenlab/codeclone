# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from ._base import MCPToolSchema, SimpleMCPTool, run_kw

TOOLS = (
    SimpleMCPTool(
        name="list_findings",
        schema=MCPToolSchema(title="List Findings"),
        runner=lambda session, params: run_kw(session.list_findings, params),
    ),
    SimpleMCPTool(
        name="get_finding",
        schema=MCPToolSchema(title="Get Finding"),
        runner=lambda session, params: run_kw(session.get_finding, params),
    ),
    SimpleMCPTool(
        name="get_remediation",
        schema=MCPToolSchema(title="Get Remediation"),
        runner=lambda session, params: run_kw(session.get_remediation, params),
    ),
    SimpleMCPTool(
        name="mark_finding_reviewed",
        schema=MCPToolSchema(title="Mark Finding Reviewed"),
        runner=lambda session, params: run_kw(session.mark_finding_reviewed, params),
    ),
    SimpleMCPTool(
        name="list_reviewed_findings",
        schema=MCPToolSchema(title="List Reviewed Findings"),
        runner=lambda session, params: run_kw(session.list_reviewed_findings, params),
    ),
)
