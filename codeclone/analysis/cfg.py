# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, TypeVar

from ..meta_markers import CFG_META_PREFIX
from .binding import BindingContext
from .cfg_model import CFG, Block
from .normalizer import NormalizationConfig
from .wire import emit_wire

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["CFG", "CFGBuilder"]

TryStar = getattr(ast, "TryStar", ast.Try)
_AstNodeT = TypeVar("_AstNodeT", bound=ast.AST)


@dataclass(slots=True)
class _LoopContext:
    continue_target: Block
    break_target: Block
    #: Depth of the finally stack when the loop was entered. A ``break`` only
    #: routes through a ``finally`` that sits between it and the loop, which is
    #: exactly a finally pushed after this frame (39Y Y9, decision row F5).
    finally_depth: int = 0


def _meta_expr(value: str) -> ast.Expr:
    return ast.Expr(value=ast.Name(id=f"{CFG_META_PREFIX}{value}", ctx=ast.Load()))


def _list_of_ast(value: object, item_type: type[_AstNodeT]) -> list[_AstNodeT] | None:
    if not isinstance(value, list):
        return None
    result: list[_AstNodeT] = []
    for item in value:
        if not isinstance(item, item_type):
            return None
        result.append(item)
    return result


def _try_star_parts(
    stmt: ast.stmt,
) -> (
    tuple[list[ast.stmt], list[ast.ExceptHandler], list[ast.stmt], list[ast.stmt]]
    | None
):
    if TryStar is ast.Try or not isinstance(stmt, TryStar):
        return None
    body = _list_of_ast(getattr(stmt, "body", None), ast.stmt)
    handlers = _list_of_ast(getattr(stmt, "handlers", None), ast.ExceptHandler)
    orelse = _list_of_ast(getattr(stmt, "orelse", None), ast.stmt)
    finalbody = _list_of_ast(getattr(stmt, "finalbody", None), ast.stmt)
    if body is None or handlers is None or orelse is None or finalbody is None:
        return None
    return body, handlers, orelse, finalbody


# =========================
# CFG Builder
# =========================


class CFGBuilder:
    __slots__ = (
        "_finally_stack",
        "_loop_stack",
        "bindings",
        "cfg",
        "current",
        "normalization_config",
    )

    def __init__(self) -> None:
        self.cfg: CFG
        self.current: Block
        self.normalization_config: NormalizationConfig
        self.bindings: BindingContext
        self._loop_stack: list[_LoopContext] = []
        self._finally_stack: list[Block] = []

    def build(
        self,
        qualname: str,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        normalization_config: NormalizationConfig,
        bindings: BindingContext,
    ) -> CFG:
        self.cfg = CFG(qualname)
        self.current = self.cfg.entry
        self.normalization_config = normalization_config
        # The meta statements this builder synthesizes carry wires of their
        # own, so it reads them under the same scope as the function's real
        # statements — one wire, one context.
        self.bindings = bindings
        self._loop_stack = []
        self._finally_stack = []

        self._visit_statements(node.body)

        if not self.current.is_terminated:
            self.current.add_successor(self.cfg.exit)

        return self.cfg

    # ---------- Internals ----------

    def _visit_statements(self, stmts: Iterable[ast.stmt]) -> None:
        for stmt in stmts:
            if self.current.is_terminated:
                # The suite continues past a terminator. Those statements are
                # part of the function and belong in the graph, so they open a
                # fresh block that nothing points at: unreachable by structure
                # rather than by a note kept somewhere else (39Y Y9).
                unreachable = self.cfg.create_block()
                unreachable.origin = "after_terminator"
                self.current = unreachable
            self._visit(stmt)

    def _abrupt_target(self) -> Block:
        """Where ``return``/``raise`` goes: the innermost finally, else the exit.

        A protected region cannot be left without running its ``finally``, so
        the terminator routes there instead of jumping straight out.
        """

        if self._finally_stack:
            return self._finally_stack[-1]
        return self.cfg.exit

    def _visit(self, stmt: ast.stmt) -> None:
        match stmt:
            case ast.Return():
                self.current.statements.append(stmt)
                self.current.is_terminated = True
                self.current.add_successor(self._abrupt_target())

            case ast.Raise():
                self.current.statements.append(stmt)
                self.current.is_terminated = True
                self.current.add_successor(self._abrupt_target())

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
                    kind=type(stmt).__name__,
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
                try_star_parts = _try_star_parts(stmt)
                if try_star_parts is not None:
                    body, handlers, orelse, finalbody = try_star_parts
                    self._visit_try(
                        kind=type(stmt).__name__,
                        body=body,
                        handlers=handlers,
                        orelse=orelse,
                        finalbody=finalbody,
                    )
                    return
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
            _LoopContext(
                continue_target=continue_target,
                break_target=break_target,
                finally_depth=len(self._finally_stack),
            )
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
        # W1: the manager may swallow whatever the body raises — that is what
        # ``pytest.raises`` and ``contextlib.suppress`` are for — so the join
        # after the ``with`` is reachable from the region entry regardless of
        # how the body ends. Post-``with`` code is never provably dead.
        self.current.add_successor(after_block)

        self.current = body_block
        self._visit_statements(stmt.body)
        if not self.current.is_terminated:
            self.current.add_successor(after_block)

        self.current = after_block

    def _visit_try(
        self,
        *,
        kind: str,
        body: list[ast.stmt],
        handlers: list[ast.ExceptHandler],
        orelse: list[ast.stmt],
        finalbody: list[ast.stmt],
    ) -> None:
        try_entry = self.cfg.create_block()
        self.current.add_successor(try_entry)
        self.current = try_entry
        self.current.statements.append(_meta_expr(f"TRY_KIND:{kind}"))

        handler_test_blocks = [self.cfg.create_block() for _ in handlers]
        handler_body_blocks = [self.cfg.create_block() for _ in handlers]
        else_block = self.cfg.create_block() if orelse else None
        # With a ``finally`` the block holds the finally suite and the join is
        # separate, so the suite is not confused with the code that follows the
        # statement. Without one the same block simply is the join.
        has_finally = bool(finalbody)
        final_block = self.cfg.create_block()
        join_block = self.cfg.create_block() if has_finally else final_block

        # D1: one dispatch edge per handler, from the region entry. This is the
        # whole replacement for guessing which statements can raise — a guess
        # that missed ``import`` and left plainly-reachable handlers orphaned.
        # It over-approximates reachability, which for a dead-code detector is
        # the honest direction, and gives the textbook +1 path per handler.
        for test_block in handler_test_blocks:
            try_entry.add_successor(test_block)
        # D2: an exception matching no handler leaves the region entirely,
        # running the finally on its way out if there is one.
        try_entry.add_successor(final_block if has_finally else self.cfg.exit)

        for idx, (handler, test_block, body_block) in enumerate(
            zip(handlers, handler_test_blocks, handler_body_blocks, strict=True)
        ):
            test_block.statements.append(_meta_expr(f"TRY_HANDLER_INDEX:{idx}"))
            if handler.type is not None:
                symbol_config = replace(
                    self.normalization_config,
                    normalize_attributes=False,
                    normalize_names=False,
                )
                type_repr = emit_wire(handler.type, symbol_config, self.bindings)
                test_block.statements.append(
                    _meta_expr(f"TRY_HANDLER_TYPE:{type_repr}")
                )
            else:
                test_block.statements.append(_meta_expr("TRY_HANDLER_TYPE:BARE"))
            test_block.add_successor(body_block)

        # Everything below leaves through the finally: rows F1-F5 all resolve
        # to "route to final_block instead of the natural target", which is
        # exactly what the stack makes the terminators do.
        if has_finally:
            self._finally_stack.append(final_block)

        self._visit_statements(body)
        # F1/F2: normal completion of the try body.
        if not self.current.is_terminated:
            self.current.add_successor(else_block or final_block)

        # F3: a handler body that completes normally.
        for handler, body_block in zip(handlers, handler_body_blocks, strict=True):
            self.current = body_block
            self._visit_statements(handler.body)
            if not self.current.is_terminated:
                self.current.add_successor(final_block)

        if else_block:
            self.current = else_block
            self._visit_statements(orelse)
            if not self.current.is_terminated:
                self.current.add_successor(final_block)

        if has_finally:
            self._finally_stack.pop()
            self.current = final_block
            self._visit_statements(finalbody)
            # F6: the finally continues normally into the join, and also
            # carries the abrupt paths routed into it — a return, or an
            # exception no handler matched — out of the function.
            if not self.current.is_terminated:
                self.current.add_successor(join_block)
                self.current.add_successor(self.cfg.exit)

        self.current = join_block

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
            pattern_repr = emit_wire(
                case_.pattern, self.normalization_config, self.bindings
            )
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
        admits = _literal_condition_admits(test)
        if admits is None:
            self.current.add_successor(true_block)
            self.current.add_successor(false_block)
            return
        # A literal guard is a fact about the source text, so the branch it
        # cannot take gets no edge at all and falls out of reachability by
        # structure. No value is inferred: only ``ast.Constant`` answers.
        taken, skipped = (
            (true_block, false_block) if admits else (false_block, true_block)
        )
        self.current.add_successor(taken)
        skipped.origin = "literal_condition"

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
            if len(self._finally_stack) > loop_frame.finally_depth:
                # A finally was entered inside this loop, so leaving the loop
                # runs it first (decision row F5).
                self.current.add_successor(self._finally_stack[-1])
                return
            target = (
                loop_frame.break_target
                if target_kind == "break"
                else loop_frame.continue_target
            )
            self.current.add_successor(target)
            return
        self.current.add_successor(self._abrupt_target())


def _literal_condition_admits(test: ast.expr) -> bool | None:
    """Whether a *literal* condition admits its branch, else ``None``.

    The entire restraint of the reachability policy lives in this predicate.
    Only ``ast.Constant`` answers: ``if False`` is a fact about the source
    text, whereas ``flag = False`` followed by ``if flag`` is a fact about
    values, and deciding it would require the propagation the policy refuses.
    Nothing here resolves a name, folds a ``BoolOp`` or evaluates a comparison,
    so no condition can be judged by anything but its own literal.
    """

    if not isinstance(test, ast.Constant):
        return None
    return bool(test.value)
