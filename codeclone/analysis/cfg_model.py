# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import ast

    from ..models import BlockOrigin


@dataclass(eq=False, slots=True)
class Block:
    id: int
    statements: list[ast.stmt] = field(default_factory=list)
    successors: set[Block] = field(default_factory=set)
    is_terminated: bool = False
    #: Why the builder created this block, for explanation only (39Y Y9).
    #: Reachability is decided solely by traversal from ``CFG.entry`` and
    #: complexity solely by the edge/node/component counts, so nothing may read
    #: this to decide either — it exists so a finding can say "code after a
    #: return" instead of the bare graph fact. Same standing as an edge kind
    #: tag: evidence, never a filter.
    origin: BlockOrigin = "normal"

    def add_successor(self, block: Block) -> None:
        self.successors.add(block)

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Block) and self.id == other.id


@dataclass(slots=True)
class CFG:
    """One function's control flow — the single truth about that function.

    Every statement the function contains lives in exactly one block here,
    including statements that cannot run: those become blocks with no incoming
    edge rather than being dropped or held in a parallel structure. Exception
    dispatch, ``finally`` routing and context-manager suppression are modelled
    as ordinary edges, so reachability and complexity read the same graph and
    can never disagree (39Y Y9).
    """

    qualname: str
    blocks: list[Block] = field(default_factory=list)

    entry: Block = field(init=False)
    exit: Block = field(init=False)

    def __post_init__(self) -> None:
        self.entry = self.create_block()
        self.exit = self.create_block()

    def create_block(self) -> Block:
        block = Block(id=len(self.blocks))
        self.blocks.append(block)
        return block
