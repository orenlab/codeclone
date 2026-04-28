# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from collections.abc import Mapping

from ..session import MCPGateRequest, MCPServiceContractError
from ._base import MCPToolSchema, SimpleMCPTool


def _gate_request(params: Mapping[str, object]) -> MCPGateRequest:
    request = params.get("request")
    if not isinstance(request, MCPGateRequest):
        raise MCPServiceContractError("Tool requires a valid MCPGateRequest.")
    return request


TOOLS = (
    SimpleMCPTool(
        name="evaluate_gates",
        schema=MCPToolSchema(title="Evaluate Gates"),
        runner=lambda session, params: session.evaluate_gates(_gate_request(params)),
    ),
)
