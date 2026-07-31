# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Statement-level unreachability over an already-built function CFG."""

from __future__ import annotations

import ast
from collections import deque
from typing import TYPE_CHECKING

from ..models import BlockOrigin, UnreachableReason, UnreachableStatementItem

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from .cfg_model import CFG, Block

__all__ = ["build_unreachable_region", "unreachable_statements"]


def _forward_closure(sources: Iterable[Block]) -> set[int]:
    """Every block id reachable from ``sources`` over ``Block.successors``."""

    queue: deque[Block] = deque(sources)
    seen = {block.id for block in queue}
    while queue:
        block = queue.popleft()
        for successor in block.successors:
            if successor.id not in seen:
                seen.add(successor.id)
                queue.append(successor)
    return seen


def _reachable_block_ids(graph: CFG) -> set[int]:
    """Directed traversal from the entry block over ``Block.successors``."""

    return _forward_closure([graph.entry])


def _statement_span(statement: ast.stmt) -> tuple[int, int] | None:
    """Return the real source span of a statement, or ``None`` if it has none.

    The CFG wraps bare expressions in synthesized ``ast.Expr`` nodes and emits
    positionless meta markers, so the span is read from the deepest positioned
    node rather than assumed present on the statement itself.
    """

    starts: list[int] = []
    ends: list[int] = []
    for node in ast.walk(statement):
        lineno = getattr(node, "lineno", None)
        if isinstance(lineno, int) and lineno > 0:
            starts.append(lineno)
            end_lineno = getattr(node, "end_lineno", None)
            ends.append(end_lineno if isinstance(end_lineno, int) else lineno)
    if not starts:
        return None
    return min(starts), max(ends)


def _reason_for(origin: BlockOrigin) -> UnreachableReason:
    """Name the cause for a reader; the proof is always graph reachability.

    Evidence only. The block was already decided unreachable by traversal
    before this is consulted, so no verdict depends on it. Every origin the
    builder can name is spelled the same as the reason it explains, so the
    only mapping left is for the block whose origin it never named.
    """

    return "unreachable_block" if origin == "normal" else origin


def build_unreachable_region(
    reason: UnreachableReason,
    statements: Sequence[ast.stmt],
) -> UnreachableStatementItem | None:
    """Fold statements into one region, or ``None`` if none carries a position."""

    spans = [
        span
        for span in (_statement_span(statement) for statement in statements)
        if span is not None
    ]
    if not spans:
        return None
    return UnreachableStatementItem(
        reason=reason,
        start_line=min(start for start, _end in spans),
        end_line=max(end for _start, end in spans),
        statement_count=len(spans),
    )


def unreachable_statements(graph: CFG) -> tuple[UnreachableStatementItem, ...]:
    """Return the maximal unreachable regions of one function, in source order.

    One rule and one graph: a statement cannot run exactly when its block is
    not reachable from ``CFG.entry``. Exception dispatch, ``finally`` routing
    and context-manager suppression are edges in that graph, so the cases that
    once needed an abstention list are answered by traversal like everything
    else, and no second structure is consulted.

    A statement's block is unreachable only as part of a whole dead region, so
    regions contained in another are dropped: one dead region is one defect and
    gets one finding.
    """

    reachable = _reachable_block_ids(graph)
    candidates = (
        build_unreachable_region(_reason_for(block.origin), block.statements)
        for block in sorted(graph.blocks, key=lambda item: item.id)
        if block.id not in reachable and block.statements
    )
    # Widest span first at a shared start, so a container is always seen before
    # anything it swallows; the reason breaks the final tie so the order never
    # depends on which block happened to be visited first.
    ordered = sorted(
        (region for region in candidates if region is not None),
        key=lambda item: (item.start_line, -item.end_line, item.reason),
    )
    kept: list[UnreachableStatementItem] = []
    for region in ordered:
        if not any(
            held.start_line <= region.start_line and region.end_line <= held.end_line
            for held in kept
        ):
            kept.append(region)
    return tuple(kept)
