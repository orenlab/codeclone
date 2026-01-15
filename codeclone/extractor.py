from __future__ import annotations

import ast
from dataclasses import dataclass

from .blocks import extract_blocks, BlockUnit
from .fingerprint import sha1, bucket_loc
from .normalize import NormalizationConfig, normalized_ast_dump


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


def _stmt_count(node: ast.AST) -> int:
    body = getattr(node, "body", None)
    return len(body) if isinstance(body, list) else 0


class _QualnameBuilder(ast.NodeVisitor):
    def __init__(self):
        self.stack: list[str] = []
        self.units: list[tuple[str, ast.AST]] = []

    def visit_ClassDef(self, node: ast.ClassDef):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        name = ".".join(self.stack + [node.name]) if self.stack else node.name
        self.units.append((name, node))

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        name = ".".join(self.stack + [node.name]) if self.stack else node.name
        self.units.append((name, node))


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
        dump = normalized_ast_dump(node, cfg)
        fp = sha1(dump)

        # ✅ __init__ INCLUDED as function-level unit
        units.append(Unit(
            qualname=qualname,
            filepath=filepath,
            start_line=start,
            end_line=end,
            loc=loc,
            stmt_count=stmt_count,
            fingerprint=fp,
            loc_bucket=bucket_loc(loc),
        ))

        if (
                not local_name.endswith("__init__")
                and loc >= 40
                and stmt_count >= 10
        ):
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
