# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from ._base import MCPToolSchema, SimpleMCPTool, run_kw

TOOLS = (
    SimpleMCPTool(
        name="get_report_section",
        schema=MCPToolSchema(title="Get Report Section"),
        runner=lambda session, params: run_kw(session.get_report_section, params),
    ),
)
