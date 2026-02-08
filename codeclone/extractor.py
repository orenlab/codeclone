"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import ast
import os
import signal
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from .blocks import BlockUnit, SegmentUnit, extract_blocks, extract_segments
from .cfg import CFGBuilder
from .errors import ParseError
from .fingerprint import bucket_loc, sha1
from .normalize import NormalizationConfig, normalized_ast_dump_from_list

# =========================
# Data structures
# =========================


@dataclass(frozen=True, slots=True)
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

PARSE_TIMEOUT_SECONDS = 5


class _ParseTimeoutError(Exception):
    pass


@contextmanager
def _parse_limits(timeout_s: int) -> Iterator[None]:
    if os.name != "posix" or timeout_s <= 0:
        yield
        return

    old_handler = signal.getsignal(signal.SIGALRM)

    def _timeout_handler(_signum: int, _frame: object) -> None:
        raise _ParseTimeoutError("AST parsing timeout")

    old_limits: tuple[int, int] | None = None
    try:
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.setitimer(signal.ITIMER_REAL, timeout_s)

        try:
            import resource

            old_limits = resource.getrlimit(resource.RLIMIT_CPU)
            soft, hard = old_limits
            hard_ceiling = timeout_s if hard == resource.RLIM_INFINITY else max(1, hard)
            if soft == resource.RLIM_INFINITY:
                new_soft = min(timeout_s, hard_ceiling)
            else:
                new_soft = min(timeout_s, soft, hard_ceiling)
            # Never lower hard limit: raising it back may be disallowed for
            # unprivileged processes and can lead to process termination later.
            resource.setrlimit(resource.RLIMIT_CPU, (new_soft, hard))
        except Exception:
            # If resource is unavailable or cannot be set, rely on alarm only.
            pass

        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_limits is not None:
            try:
                import resource

                resource.setrlimit(resource.RLIMIT_CPU, old_limits)
            except Exception:
                pass


def _parse_with_limits(source: str, timeout_s: int) -> ast.AST:
    try:
        with _parse_limits(timeout_s):
            return ast.parse(source)
    except _ParseTimeoutError as e:
        raise ParseError(str(e)) from e


def _stmt_count(node: ast.AST) -> int:
    body = getattr(node, "body", None)
    return len(body) if isinstance(body, list) else 0


class _QualnameBuilder(ast.NodeVisitor):
    __slots__ = ("stack", "units")

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.units: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        name = ".".join([*self.stack, node.name]) if self.stack else node.name
        self.units.append((name, node))

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        name = ".".join([*self.stack, node.name]) if self.stack else node.name
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
    Generate a structural fingerprint for a function using CFG analysis.

    The fingerprint is computed by:
    1. Building a Control Flow Graph (CFG) from the function
    2. Normalizing each CFG block's statements (variable names, constants, etc.)
    3. Creating a canonical representation of the CFG structure
    4. Hashing the representation with SHA-1

    Functions with identical control flow and normalized statements will
    produce the same fingerprint, even if they differ in variable names,
    constants, or type annotations.

    Args:
        node: Function AST node to fingerprint
        cfg: Normalization configuration (what to ignore)
        qualname: Qualified name for logging/debugging

    Returns:
        40-character hex SHA-1 hash of the normalized CFG
    """
    builder = CFGBuilder()
    graph = builder.build(qualname, node)

    # Use generator to avoid building large list of strings
    parts: list[str] = []
    for block in sorted(graph.blocks, key=lambda b: b.id):
        succ_ids = ",".join(
            str(s.id) for s in sorted(block.successors, key=lambda s: s.id)
        )
        parts.append(
            f"BLOCK[{block.id}]:{normalized_ast_dump_from_list(block.statements, cfg)}"
            f"|SUCCESSORS:{succ_ids}"
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
) -> tuple[list[Unit], list[BlockUnit], list[SegmentUnit]]:
    try:
        tree = _parse_with_limits(source, PARSE_TIMEOUT_SECONDS)
    except SyntaxError as e:
        raise ParseError(f"Failed to parse {filepath}: {e}") from e

    qb = _QualnameBuilder()
    qb.visit(tree)

    units: list[Unit] = []
    block_units: list[BlockUnit] = []
    segment_units: list[SegmentUnit] = []

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

        # Segment-level units (windows within functions, for internal clones)
        if loc >= 30 and stmt_count >= 12:
            segments = extract_segments(
                node,
                filepath=filepath,
                qualname=qualname,
                cfg=cfg,
                window_size=6,
                max_segments=60,
            )
            segment_units.extend(segments)

    return units, block_units, segment_units
