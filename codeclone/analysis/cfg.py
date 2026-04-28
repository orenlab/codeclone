# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..meta_markers import CFG_META_PREFIX
from .cfg_model import CFG, Block

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["CFG", "CFGBuilder"]

TryStar = getattr(ast, "TryStar", ast.Try)


@dataclass(slots=True)
class _LoopContext:
    continue_target: Block
    break_target: Block


def _meta_expr(value: str) -> ast.Expr:
    return ast.Expr(value=ast.Name(id=f"{CFG_META_PREFIX}{value}", ctx=ast.Load()))


# =========================
# CFG Builder
# =========================


class CFGBuilder:
    __slots__ = ("_loop_stack", "cfg", "current")

    def __init__(self) -> None:
        self.cfg: CFG
        self.current: Block
        self._loop_stack: list[_LoopContext] = []

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

            case ast.Break():
                self._visit_break(stmt)

            case ast.Continue():
                self._visit_continue(stmt)

            case ast.If():
                self._visit_if(stmt)

            case ast.While():
                self._visit_while(stmt)

            case ast.For():
                self._visit_for(stmt)

            case ast.AsyncFor():
                self._visit_for(stmt)  # Structure is identical to For

            case ast.Try():
                self._visit_try(
                    body=stmt.body,
                    handlers=stmt.handlers,
                    orelse=stmt.orelse,
                    finalbody=stmt.finalbody,
                )
            case _ if TryStar is not None and isinstance(stmt, TryStar):
                self._visit_try(
                    body=stmt.body,
                    handlers=stmt.handlers,
                    orelse=stmt.orelse,
                    finalbody=stmt.finalbody,
                )

            case ast.With() | ast.AsyncWith():
                self._visit_with(stmt)

            case ast.Match():
                self._visit_match(stmt)

            case _:
                self.current.statements.append(stmt)

    # ---------- Control Flow ----------

    def _visit_if(self, stmt: ast.If) -> None:
        then_block = self.cfg.create_block()
        else_block = self.cfg.create_block()
        after_block = self.cfg.create_block()

        self._emit_condition(stmt.test, then_block, else_block)

        self.current = then_block
        self._visit_statements(stmt.body)
        if not self.current.is_terminated:
            self.current.add_successor(after_block)

        self.current = else_block
        self._visit_statements(stmt.orelse)
        if not self.current.is_terminated:
            self.current.add_successor(after_block)

        self.current = after_block

    def _visit_loop_body(
        self,
        *,
        body_block: Block,
        continue_target: Block,
        break_target: Block,
        body: Iterable[ast.stmt],
    ) -> None:
        self._loop_stack.append(
            _LoopContext(continue_target=continue_target, break_target=break_target)
        )
        self.current = body_block
        self._visit_statements(body)
        if not self.current.is_terminated:
            self.current.add_successor(continue_target)
        self._loop_stack.pop()

    def _visit_loop_else(
        self,
        *,
        else_block: Block | None,
        orelse: Iterable[ast.stmt],
        after_block: Block,
    ) -> None:
        if else_block is None:
            return
        self.current = else_block
        self._visit_statements(orelse)
        if not self.current.is_terminated:
            self.current.add_successor(after_block)

    def _create_loop_followup_blocks(
        self, *, has_else: bool
    ) -> tuple[Block, Block | None, Block]:
        body_block = self.cfg.create_block()
        else_block = self.cfg.create_block() if has_else else None
        after_block = self.cfg.create_block()
        return body_block, else_block, after_block

    def _enter_loop_header(
        self, *, has_else: bool
    ) -> tuple[Block, Block, Block | None, Block]:
        header_block = self.cfg.create_block()
        body_block, else_block, after_block = self._create_loop_followup_blocks(
            has_else=has_else
        )
        self.current.add_successor(header_block)
        self.current = header_block
        return header_block, body_block, else_block, after_block

    def _visit_while(self, stmt: ast.While) -> None:
        cond_block, body_block, else_block, after_block = self._enter_loop_header(
            has_else=bool(stmt.orelse)
        )
        false_target = else_block if else_block is not None else after_block
        self._emit_condition(stmt.test, body_block, false_target)

        self._visit_loop_body(
            body_block=body_block,
            continue_target=cond_block,
            break_target=after_block,
            body=stmt.body,
        )
        self._visit_loop_else(
            else_block=else_block,
            orelse=stmt.orelse,
            after_block=after_block,
        )

        self.current = after_block

    def _visit_for(self, stmt: ast.For | ast.AsyncFor) -> None:
        iter_block, body_block, else_block, after_block = self._enter_loop_header(
            has_else=bool(stmt.orelse)
        )
        self.current.statements.append(ast.Expr(value=stmt.iter))
        self.current.add_successor(body_block)
        self.current.add_successor(
            else_block if else_block is not None else after_block
        )

        self._visit_loop_body(
            body_block=body_block,
            continue_target=iter_block,
            break_target=after_block,
            body=stmt.body,
        )
        self._visit_loop_else(
            else_block=else_block,
            orelse=stmt.orelse,
            after_block=after_block,
        )

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

    def _visit_try(
        self,
        *,
        body: list[ast.stmt],
        handlers: list[ast.ExceptHandler],
        orelse: list[ast.stmt],
        finalbody: list[ast.stmt],
    ) -> None:
        try_entry = self.cfg.create_block()
        self.current.add_successor(try_entry)
        self.current = try_entry

        handler_test_blocks = [self.cfg.create_block() for _ in handlers]
        handler_body_blocks = [self.cfg.create_block() for _ in handlers]
        else_block = self.cfg.create_block() if orelse else None
        final_block = self.cfg.create_block()

        for idx, (handler, test_block, body_block) in enumerate(
            zip(handlers, handler_test_blocks, handler_body_blocks, strict=True)
        ):
            test_block.statements.append(_meta_expr(f"TRY_HANDLER_INDEX:{idx}"))
            if handler.type is not None:
                type_repr = ast.dump(handler.type, annotate_fields=False)
                test_block.statements.append(
                    _meta_expr(f"TRY_HANDLER_TYPE:{type_repr}")
                )
            else:
                test_block.statements.append(_meta_expr("TRY_HANDLER_TYPE:BARE"))
            test_block.add_successor(body_block)
            if idx + 1 < len(handler_test_blocks):
                test_block.add_successor(handler_test_blocks[idx + 1])
            else:
                test_block.add_successor(final_block)

        # Process each statement in try body
        # Link only statements that can raise to exception handlers
        for stmt_node in body:
            if self.current.is_terminated:
                break

            if _stmt_can_raise(stmt_node) and handler_test_blocks:
                self.current.add_successor(handler_test_blocks[0])

            self._visit(stmt_node)

        # Normal exit from try
        if not self.current.is_terminated:
            if else_block:
                self.current.add_successor(else_block)
            else:
                self.current.add_successor(final_block)

        # Process handlers
        for handler, body_block in zip(handlers, handler_body_blocks, strict=True):
            self.current = body_block
            self._visit_statements(handler.body)
            if not self.current.is_terminated:
                self.current.add_successor(final_block)

        # Process else
        if else_block:
            self.current = else_block
            self._visit_statements(orelse)
            if not self.current.is_terminated:
                self.current.add_successor(final_block)

        # Process finally
        self.current = final_block
        if finalbody:
            self._visit_statements(finalbody)

    def _visit_match(self, stmt: ast.Match) -> None:
        self.current.statements.append(ast.Expr(value=stmt.subject))

        previous_test_block: Block | None = None
        after_block = self.cfg.create_block()

        for idx, case_ in enumerate(stmt.cases):
            case_test_block = self.cfg.create_block()
            case_body_block = self.cfg.create_block()

            if previous_test_block is None:
                self.current.add_successor(case_test_block)
            else:
                previous_test_block.add_successor(case_test_block)

            case_test_block.statements.append(_meta_expr(f"MATCH_CASE_INDEX:{idx}"))

            # Record pattern structure
            pattern_repr = ast.dump(case_.pattern, annotate_fields=False)
            case_test_block.statements.append(
                _meta_expr(f"MATCH_PATTERN:{pattern_repr}")
            )
            if case_.guard is not None:
                case_test_block.statements.append(ast.Expr(value=case_.guard))

            case_test_block.add_successor(case_body_block)

            self.current = case_body_block
            self._visit_statements(case_.body)
            if not self.current.is_terminated:
                self.current.add_successor(after_block)

            previous_test_block = case_test_block

        if previous_test_block is not None:
            previous_test_block.add_successor(after_block)

        self.current = after_block

    def _emit_condition(
        self, test: ast.expr, true_block: Block, false_block: Block
    ) -> None:
        if isinstance(test, ast.BoolOp) and isinstance(test.op, (ast.And, ast.Or)):
            self._emit_boolop(test, true_block, false_block)
            return

        self.current.statements.append(ast.Expr(value=test))
        self.current.add_successor(true_block)
        self.current.add_successor(false_block)

    def _emit_boolop(
        self, test: ast.BoolOp, true_block: Block, false_block: Block
    ) -> None:
        values = test.values
        op = test.op
        current = self.current

        for idx, value in enumerate(values):
            current.statements.append(ast.Expr(value=value))
            is_last = idx == len(values) - 1

            if isinstance(op, ast.And):
                if is_last:
                    current.add_successor(true_block)
                    current.add_successor(false_block)
                else:
                    next_block = self.cfg.create_block()
                    current.add_successor(next_block)
                    current.add_successor(false_block)
                    current = next_block
            else:
                if is_last:
                    current.add_successor(true_block)
                    current.add_successor(false_block)
                else:
                    next_block = self.cfg.create_block()
                    current.add_successor(true_block)
                    current.add_successor(next_block)
                    current = next_block

        self.current = current

    def _visit_break(self, stmt: ast.Break) -> None:
        self._visit_loop_exit(stmt, target_kind="break")

    def _visit_continue(self, stmt: ast.Continue) -> None:
        self._visit_loop_exit(stmt, target_kind="continue")

    def _visit_loop_exit(
        self,
        stmt: ast.Break | ast.Continue,
        *,
        target_kind: str,
    ) -> None:
        self.current.statements.append(stmt)
        self.current.is_terminated = True
        if self._loop_stack:
            loop_frame = self._loop_stack[-1]
            target = (
                loop_frame.break_target
                if target_kind == "break"
                else loop_frame.continue_target
            )
            self.current.add_successor(target)
            return
        self.current.add_successor(self.cfg.exit)


def _stmt_can_raise(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Raise):
        return True

    for node in ast.walk(stmt):
        if isinstance(
            node,
            (
                ast.Call,
                ast.Attribute,
                ast.Subscript,
                ast.Await,
                ast.YieldFrom,
            ),
        ):
            return True

    return False
