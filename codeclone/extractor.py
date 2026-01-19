from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Sequence

from .blocks import extract_blocks, BlockUnit
from .cfg import CFGBuilder
from .fingerprint import sha1, bucket_loc
from .normalize import NormalizationConfig, normalized_ast_dump_from_list


# =========================
# Data structures
# =========================


@dataclass(frozen=True)
class Unit:
    qualname: str
    filepath: str
    start_line: int
    end_line: int
    loc: int
    stmt_count: int
    fingerprint: str
    loc_bucket: str


# =========================
# Helpers
# =========================


def _stmt_count(node: ast.AST) -> int:
    body = getattr(node, "body", None)
    return len(body) if isinstance(body, list) else 0


class _QualnameBuilder(ast.NodeVisitor):
    def __init__(self) -> None:
        self.stack: list[str] = []
        self.units: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        name = ".".join(self.stack + [node.name]) if self.stack else node.name
        self.units.append((name, node))

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        name = ".".join(self.stack + [node.name]) if self.stack else node.name
        self.units.append((name, node))


# =========================
# CFG fingerprinting
# =========================


def get_cfg_fingerprint(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    cfg: NormalizationConfig,
    qualname: str,
) -> str:
    """
    Build CFG, normalize it into a canonical form, and hash it.
    """
    builder = CFGBuilder()
    graph = builder.build(qualname, node)

    parts: list[str] = []

    # Stable order for deterministic hash
    for block in sorted(graph.blocks, key=lambda b: b.id):
        # NOTE: normalized_ast_dump_from_list must accept Sequence[ast.AST] (covariant),
        # but even if it still accepts list[ast.AST], passing list[ast.stmt] will fail
        # due to invariance. We pass as Sequence[ast.AST] via a typed view.
        stmts_as_ast: Sequence[ast.AST] = block.statements
        normalized_stmts = normalized_ast_dump_from_list(stmts_as_ast, cfg)

        successor_ids = sorted(succ.id for succ in block.successors)

        parts.append(
            f"BLOCK[{block.id}]:{normalized_stmts}"
            f"|SUCCESSORS:{','.join(map(str, successor_ids))}"
        )

    return sha1("|".join(parts))


# =========================
# Public API
# =========================


def extract_units_from_source(
    source: str,
    filepath: str,
    module_name: str,
    cfg: NormalizationConfig,
    min_loc: int,
    min_stmt: int,
) -> tuple[list[Unit], list[BlockUnit]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], []

    qb = _QualnameBuilder()
    qb.visit(tree)

    units: list[Unit] = []
    block_units: list[BlockUnit] = []

    for local_name, node in qb.units:
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)

        if not start or not end or end < start:
            continue

        loc = end - start + 1
        stmt_count = _stmt_count(node)

        if loc < min_loc or stmt_count < min_stmt:
            continue

        qualname = f"{module_name}:{local_name}"
        fingerprint = get_cfg_fingerprint(node, cfg, qualname)

        # Function-level unit (including __init__)
        units.append(
            Unit(
                qualname=qualname,
                filepath=filepath,
                start_line=start,
                end_line=end,
                loc=loc,
                stmt_count=stmt_count,
                fingerprint=fingerprint,
                loc_bucket=bucket_loc(loc),
            )
        )

        # Block-level units (exclude __init__)
        if not local_name.endswith("__init__") and loc >= 40 and stmt_count >= 10:
            blocks = extract_blocks(
                node,
                filepath=filepath,
                qualname=qualname,
                cfg=cfg,
                block_size=4,
                max_blocks=15,
            )
            block_units.extend(blocks)

    return units, block_units
