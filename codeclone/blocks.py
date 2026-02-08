"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .blockhash import stmt_hash
from .fingerprint import sha1
from .normalize import NormalizationConfig


@dataclass(frozen=True, slots=True)
class BlockUnit:
    block_hash: str
    filepath: str
    qualname: str
    start_line: int
    end_line: int
    size: int


@dataclass(frozen=True, slots=True)
class SegmentUnit:
    segment_hash: str
    segment_sig: str
    filepath: str
    qualname: str
    start_line: int
    end_line: int
    size: int


def extract_blocks(
    func_node: ast.AST,
    *,
    filepath: str,
    qualname: str,
    cfg: NormalizationConfig,
    block_size: int,
    max_blocks: int,
) -> list[BlockUnit]:
    body = getattr(func_node, "body", None)
    if not isinstance(body, list) or len(body) < block_size:
        return []

    stmt_hashes = [stmt_hash(stmt, cfg) for stmt in body]

    blocks: list[BlockUnit] = []
    last_start: int | None = None
    # Allow some overlap (50%), but at least 3 lines apart
    min_line_distance = max(block_size // 2, 3)

    for i in range(len(stmt_hashes) - block_size + 1):
        start = getattr(body[i], "lineno", None)
        end = getattr(body[i + block_size - 1], "end_lineno", None)
        if not start or not end:
            continue

        if last_start is not None and start - last_start < min_line_distance:
            continue

        bh = "|".join(stmt_hashes[i : i + block_size])

        blocks.append(
            BlockUnit(
                block_hash=bh,
                filepath=filepath,
                qualname=qualname,
                start_line=start,
                end_line=end,
                size=block_size,
            )
        )

        last_start = start
        if len(blocks) >= max_blocks:
            break

    return blocks


def extract_segments(
    func_node: ast.AST,
    *,
    filepath: str,
    qualname: str,
    cfg: NormalizationConfig,
    window_size: int,
    max_segments: int,
) -> list[SegmentUnit]:
    body = getattr(func_node, "body", None)
    if not isinstance(body, list) or len(body) < window_size:
        return []

    stmt_hashes = [stmt_hash(stmt, cfg) for stmt in body]

    segments: list[SegmentUnit] = []

    for i in range(len(stmt_hashes) - window_size + 1):
        start = getattr(body[i], "lineno", None)
        end = getattr(body[i + window_size - 1], "end_lineno", None)
        if not start or not end:
            continue

        window = stmt_hashes[i : i + window_size]
        segment_hash = sha1("|".join(window))
        segment_sig = sha1("|".join(sorted(window)))

        segments.append(
            SegmentUnit(
                segment_hash=segment_hash,
                segment_sig=segment_sig,
                filepath=filepath,
                qualname=qualname,
                start_line=start,
                end_line=end,
                size=window_size,
            )
        )

        if len(segments) >= max_segments:
            break

    return segments
