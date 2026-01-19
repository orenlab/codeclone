from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Iterable


# =========================
# Core CFG structures
# =========================

@dataclass(eq=False)
class Block:
    id: int
    statements: list[ast.stmt] = field(default_factory=list)
    successors: set["Block"] = field(default_factory=set)
    is_terminated: bool = False

    def add_successor(self, block: Block) -> None:
        self.successors.add(block)

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Block) and self.id == other.id


@dataclass
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


# =========================
# CFG Builder
# =========================

class CFGBuilder:
    def __init__(self) -> None:
        self.cfg: CFG
        self.current: Block

    def build(
            self,
            qualname: str,
            node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> CFG:
        self.cfg = CFG(qualname)
        self.current = self.cfg.entry

        self._visit_statements(node.body)

        if not self.current.is_terminated:
            self.current.add_successor(self.cfg.exit)

        return self.cfg

    # ---------- Internals ----------

    def _visit_statements(self, stmts: Iterable[ast.stmt]) -> None:
        for stmt in stmts:
            if self.current.is_terminated:
                break
            self._visit(stmt)

    def _visit(self, stmt: ast.stmt) -> None:
        match stmt:
            case ast.Return():
                self.current.statements.append(stmt)
                self.current.is_terminated = True
                self.current.add_successor(self.cfg.exit)

            case ast.Raise():
                self.current.statements.append(stmt)
                self.current.is_terminated = True
                self.current.add_successor(self.cfg.exit)

            case ast.If():
                self._visit_if(stmt)

            case ast.While():
                self._visit_while(stmt)

            case ast.For():
                self._visit_for(stmt)

            case _:
                self.current.statements.append(stmt)

    # ---------- Control Flow ----------

    def _visit_if(self, stmt: ast.If) -> None:
        self.current.statements.append(ast.Expr(value=stmt.test))

        then_block = self.cfg.create_block()
        else_block = self.cfg.create_block()
        after_block = self.cfg.create_block()

        self.current.add_successor(then_block)
        self.current.add_successor(else_block)

        self.current = then_block
        self._visit_statements(stmt.body)
        if not self.current.is_terminated:
            self.current.add_successor(after_block)

        self.current = else_block
        self._visit_statements(stmt.orelse)
        if not self.current.is_terminated:
            self.current.add_successor(after_block)

        self.current = after_block

    def _visit_while(self, stmt: ast.While) -> None:
        cond_block = self.cfg.create_block()
        body_block = self.cfg.create_block()
        after_block = self.cfg.create_block()

        self.current.add_successor(cond_block)

        self.current = cond_block
        self.current.statements.append(ast.Expr(value=stmt.test))
        self.current.add_successor(body_block)
        self.current.add_successor(after_block)

        self.current = body_block
        self._visit_statements(stmt.body)
        if not self.current.is_terminated:
            self.current.add_successor(cond_block)

        self.current = after_block

    def _visit_for(self, stmt: ast.For) -> None:
        iter_block = self.cfg.create_block()
        body_block = self.cfg.create_block()
        after_block = self.cfg.create_block()

        self.current.add_successor(iter_block)

        self.current = iter_block
        self.current.statements.append(ast.Expr(value=stmt.iter))
        self.current.add_successor(body_block)
        self.current.add_successor(after_block)

        self.current = body_block
        self._visit_statements(stmt.body)
        if not self.current.is_terminated:
            self.current.add_successor(iter_block)

        self.current = after_block
