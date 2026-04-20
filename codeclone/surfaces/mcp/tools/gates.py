# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from typing import cast

from ..session import MCPGateRequest
from ._base import MCPToolSchema, SimpleMCPTool

TOOLS = (
    SimpleMCPTool(
        name="evaluate_gates",
        schema=MCPToolSchema(title="Evaluate Gates"),
        runner=lambda session, params: session.evaluate_gates(
            cast("MCPGateRequest", params["request"])
        ),
    ),
)
