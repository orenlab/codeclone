"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field


@dataclass(eq=False, slots=True)
class Block:
    id: int
    statements: list[ast.stmt] = field(default_factory=list)
    successors: set[Block] = field(default_factory=set)
    is_terminated: bool = False

    def add_successor(self, block: Block) -> None:
        self.successors.add(block)

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Block) and self.id == other.id


@dataclass(slots=True)
class CFG:
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
