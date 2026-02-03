"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from typing import Protocol, cast

from .cfg_model import CFG, Block

__all__ = ["CFG", "CFGBuilder"]

TryStar = getattr(ast, "TryStar", ast.Try)


class _TryLike(Protocol):
    body: list[ast.stmt]
    handlers: list[ast.ExceptHandler]
    orelse: list[ast.stmt]
    finalbody: list[ast.stmt]


# =========================
# CFG Builder
# =========================


class CFGBuilder:
    __slots__ = ("cfg", "current")

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

            case ast.AsyncFor():
                self._visit_for(stmt)  # Structure is identical to For

            case ast.Try():
                self._visit_try(cast(_TryLike, stmt))
            case _ if TryStar is not None and isinstance(stmt, TryStar):
                self._visit_try(cast(_TryLike, stmt))

            case ast.With() | ast.AsyncWith():
                self._visit_with(stmt)

            case ast.Match():
                self._visit_match(stmt)

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

    def _visit_for(self, stmt: ast.For | ast.AsyncFor) -> None:
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

    def _visit_with(self, stmt: ast.With | ast.AsyncWith) -> None:
        # Treat WITH as linear flow (enter -> body -> exit), but preserve
        # block structure
        # We record the context manager expression in the current block
        # Then we enter a new block for the body (to separate it structurally)
        # Then we enter a new block for 'after' (exit)

        # Why new block? Because 'with' implies a scope/context.
        # It helps matching.

        body_block = self.cfg.create_block()
        after_block = self.cfg.create_block()

        # Record the 'items' (context managers)
        # We wrap them in Expr to treat them as statements for hashing
        for item in stmt.items:
            self.current.statements.append(ast.Expr(value=item.context_expr))

        self.current.add_successor(body_block)

        self.current = body_block
        self._visit_statements(stmt.body)
        if not self.current.is_terminated:
            self.current.add_successor(after_block)

        self.current = after_block

    def _visit_try(self, stmt: _TryLike) -> None:
        try_entry = self.cfg.create_block()
        self.current.add_successor(try_entry)
        self.current = try_entry

        handlers_blocks = [self.cfg.create_block() for _ in stmt.handlers]
        else_block = self.cfg.create_block() if stmt.orelse else None
        final_block = self.cfg.create_block()

        # Process each statement in try body
        # Link each to exception handlers
        for stmt_node in stmt.body:
            if self.current.is_terminated:
                break

            # Current statement could raise exception
            for h_block in handlers_blocks:
                self.current.add_successor(h_block)

            self._visit(stmt_node)

        # Normal exit from try
        if not self.current.is_terminated:
            if else_block:
                self.current.add_successor(else_block)
            else:
                self.current.add_successor(final_block)

        # Process handlers
        for handler, h_block in zip(stmt.handlers, handlers_blocks, strict=True):
            self.current = h_block
            if handler.type:
                self.current.statements.append(ast.Expr(value=handler.type))

            self._visit_statements(handler.body)
            if not self.current.is_terminated:
                self.current.add_successor(final_block)

        # Process else
        if else_block:
            self.current = else_block
            self._visit_statements(stmt.orelse)
            if not self.current.is_terminated:
                self.current.add_successor(final_block)

        # Process finally
        self.current = final_block
        if stmt.finalbody:
            self._visit_statements(stmt.finalbody)

    def _visit_match(self, stmt: ast.Match) -> None:
        self.current.statements.append(ast.Expr(value=stmt.subject))

        subject_block = self.current
        after_block = self.cfg.create_block()

        for case_ in stmt.cases:
            case_block = self.cfg.create_block()
            subject_block.add_successor(case_block)

            self.current = case_block

            # Record pattern structure
            pattern_repr = ast.dump(case_.pattern, annotate_fields=False)
            self.current.statements.append(
                ast.Expr(value=ast.Constant(value=f"PATTERN:{pattern_repr}"))
            )

            self._visit_statements(case_.body)
            if not self.current.is_terminated:
                self.current.add_successor(after_block)

        self.current = after_block
