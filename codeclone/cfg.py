"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

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

            case ast.AsyncFor():
                self._visit_for(stmt)  # Structure is identical to For

            case ast.Try() | ast.TryStar():
                self._visit_try(stmt)

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
        # Treat WITH as linear flow (enter -> body -> exit), but preserve block structure
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

    def _visit_try(self, stmt: ast.Try | ast.TryStar) -> None:
        # Simplified Try CFG:
        # Try Body -> [Handlers...] -> Finally/After
        # Try Body -> Else -> Finally/After
        
        try_block = self.cfg.create_block()
        self.current.add_successor(try_block)
        
        # We don't know WHERE in the try block exception happens, so we assume
        # any point in try block *could* jump to handlers. 
        # But for structural hashing, we just process the body.
        # Ideally, we should link the try_block (or its end) to handlers?
        # A simple approximation: 
        # 1. Process body.
        # 2. Link entry (or end of body) to handlers?
        # Let's do: Entry -> BodyBlock. 
        # Entry -> HandlerBlocks (to represent potential jump).
        
        # Actually, let's keep it linear but branched.
        # Current -> TryBody
        # Current -> Handlers (Abstractly representing the jump)
        
        handlers_blocks = [self.cfg.create_block() for _ in stmt.handlers]
        else_block = self.cfg.create_block() if stmt.orelse else None
        final_block = self.cfg.create_block() # This is finally or after
        
        # Link current to TryBody
        self.current = try_block
        self._visit_statements(stmt.body)
        
        # If try body finishes successfully:
        if not self.current.is_terminated:
            if else_block:
                self.current.add_successor(else_block)
            else:
                self.current.add_successor(final_block)
                
        # Handle Else
        if else_block:
            self.current = else_block
            self._visit_statements(stmt.orelse)
            if not self.current.is_terminated:
                self.current.add_successor(final_block)

        # Handle Handlers
        # We assume control flow *could* jump from start of Try to any handler
        # (Technically from inside try, but we model structural containment)
        # To make fingerprints stable, we just need to ensure handlers are visited 
        # and linked.
        
        # We link the *original* predecessor (before try) or the try_block start to handlers?
        # Let's link the `try_block` (as a container concept) to handlers.
        # But `try_block` was mutated by `_visit_statements`.
        # Let's use the `try_block` (start of try) to link to handlers.
        for h_block in handlers_blocks:
            try_block.add_successor(h_block)
            
        for handler, h_block in zip(stmt.handlers, handlers_blocks):
            self.current = h_block
            # Record exception type
            if handler.type:
                self.current.statements.append(ast.Expr(value=handler.type))
            self._visit_statements(handler.body)
            if not self.current.is_terminated:
                self.current.add_successor(final_block)

        # Finally logic:
        # If there is a finally block, `final_block` IS the finally block.
        # We visit it. Then we create a new `after_finally` block?
        # Or `final_block` is the start of finally.
        
        if stmt.finalbody:
            self.current = final_block
            self._visit_statements(stmt.finalbody)
            # And then continue to next code?
            # Yes, finally flows to next statement.
            # Unless terminated.
            
        # If no finally, `final_block` is just the merge point (after).
        self.current = final_block

    def _visit_match(self, stmt: ast.Match) -> None:
        # Match subject -> Cases -> After
        
        self.current.statements.append(ast.Expr(value=stmt.subject))
        
        after_block = self.cfg.create_block()
        
        for case_ in stmt.cases:
            case_block = self.cfg.create_block()
            self.current.add_successor(case_block)
            
            # Save current context to restore for next case branching?
            # No, 'current' is the match subject block. It branches to ALL cases.
            
            # Visit Case
            # We must set self.current to case_block for visiting body
            # But we lose reference to 'match subject block' to link next case!
            # So we need a variable `subject_block`.
            pass

        # Re-implementing loop correctly
        subject_block = self.current
        
        for case_ in stmt.cases:
            case_block = self.cfg.create_block()
            subject_block.add_successor(case_block)
            
            self.current = case_block
            # We could record the pattern here? 
            # patterns are complex AST nodes. For now, let's skip pattern structure hash
            # and just hash the body. Or dump pattern as statement?
            # Pattern is not a statement.
            # Let's ignore pattern details for V1, or try to normalize it.
            # If we ignore pattern, then `case []:` and `case {}:` look same. 
            # Ideally: `self.current.statements.append(case_.pattern)` but pattern is not stmt.
            # We can wrap in Expr? `ast.Expr(value=case_.pattern)`? 
            # Pattern is NOT an Expr subclass in 3.10. It's `ast.pattern`.
            # So we cannot append it to `statements` list which expects `ast.stmt`.
            # We will ignore pattern structure for now (it's structural flow we care about).
            
            self._visit_statements(case_.body)
            if not self.current.is_terminated:
                self.current.add_successor(after_block)
                
        self.current = after_block
