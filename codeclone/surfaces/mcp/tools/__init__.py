# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from ._base import MCPTool
from .analyze import TOOLS as ANALYZE_TOOLS
from .checks import TOOLS as CHECK_TOOLS
from .compare import TOOLS as COMPARE_TOOLS
from .findings import TOOLS as FINDING_TOOLS
from .gates import TOOLS as GATE_TOOLS
from .help import TOOLS as HELP_TOOLS
from .hotspots import TOOLS as HOTSPOT_TOOLS
from .pr import TOOLS as PR_TOOLS
from .report_section import TOOLS as REPORT_SECTION_TOOLS
from .runs import TOOLS as RUN_TOOLS

MCP_TOOLS: tuple[MCPTool, ...] = (
    *ANALYZE_TOOLS,
    *RUN_TOOLS,
    *FINDING_TOOLS,
    *CHECK_TOOLS,
    *HOTSPOT_TOOLS,
    *REPORT_SECTION_TOOLS,
    *COMPARE_TOOLS,
    *GATE_TOOLS,
    *PR_TOOLS,
    *HELP_TOOLS,
)

MCP_TOOLS_BY_NAME: dict[str, MCPTool] = {tool.name: tool for tool in MCP_TOOLS}
