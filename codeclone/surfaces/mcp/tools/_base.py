# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from ..session import MCPSession


@dataclass(frozen=True, slots=True)
class MCPToolSchema:
    title: str
    description: str = ""


class MCPTool(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def schema(self) -> MCPToolSchema: ...

    def run(self, session: MCPSession, params: Mapping[str, object]) -> object: ...


@dataclass(frozen=True, slots=True)
class SimpleMCPTool:
    name: str
    schema: MCPToolSchema
    runner: Callable[[MCPSession, Mapping[str, object]], object]

    def run(self, session: MCPSession, params: Mapping[str, object]) -> object:
        return self.runner(session, params)


def run_kw(bound: object, params: Mapping[str, object]) -> object:
    return cast("Any", bound)(**dict(params))
