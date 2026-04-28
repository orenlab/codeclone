# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib

from .. import qualnames as _qualnames
from ..metrics.complexity import cyclomatic_complexity
from .cfg import CFGBuilder
from .normalizer import (
    AstNormalizer,
    NormalizationConfig,
    normalized_ast_dump_from_list,
)


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def bucket_loc(loc: int) -> str:
    # Helps avoid grouping wildly different sizes if desired
    if loc < 20:
        return "0-19"
    if loc < 50:
        return "20-49"
    if loc < 100:
        return "50-99"
    return "100+"


def _cfg_fingerprint_and_complexity(
    node: _qualnames.FunctionNode,
    cfg: NormalizationConfig,
    qualname: str,
) -> tuple[str, int]:
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
    cfg_normalizer = AstNormalizer(cfg)

    # Use generator to avoid building large list of strings
    parts: list[str] = []
    for block in sorted(graph.blocks, key=lambda b: b.id):
        succ_ids = ",".join(
            str(s.id) for s in sorted(block.successors, key=lambda s: s.id)
        )
        block_dump = normalized_ast_dump_from_list(
            block.statements,
            cfg,
            normalizer=cfg_normalizer,
        )
        parts.append(f"BLOCK[{block.id}]:{block_dump}|SUCCESSORS:{succ_ids}")
    return sha1("|".join(parts)), cyclomatic_complexity(graph)


_CFG_FINGERPRINT_AND_COMPLEXITY_IMPL = _cfg_fingerprint_and_complexity
