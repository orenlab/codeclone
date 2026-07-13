# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import hashlib
from typing import Final

from .. import qualnames as _qualnames
from ..metrics.complexity import cyclomatic_complexity
from .cfg import CFGBuilder
from .normalizer import NormalizationConfig
from .phase_ledger import INERT_PHASE_LEDGER, AnalysisPhaseKey, PhaseLedger
from .wire import emit_wire_seq

_FN_DOMAIN: Final = b"ccfp2:fn\x00"


def sha256_hex(domain: bytes, payload: str) -> str:
    return hashlib.sha256(domain + payload.encode("utf-8")).hexdigest()


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
    *,
    phase_ledger: PhaseLedger = INERT_PHASE_LEDGER,
) -> tuple[str, int]:
    """
    Generate a structural fingerprint for a function using CFG analysis.

    The fingerprint is computed by:
    1. Building a Control Flow Graph (CFG) from the function
    2. Serializing each CFG block's statements through the canonical wire
    3. Creating a canonical representation of the CFG structure
    4. Hashing the domain-separated representation with SHA-256

    Functions with identical control flow and normalized statements will
    produce the same fingerprint, even if they differ in variable names,
    constants, or type annotations.

    Args:
        node: Function AST node to fingerprint
        cfg: Normalization configuration (what to ignore)
        qualname: Qualified name for logging/debugging

    Returns:
        64-character hex SHA-256 hash of the normalized CFG
    """
    builder = CFGBuilder()
    with phase_ledger.phase(AnalysisPhaseKey.UNIT_CFG):
        graph = builder.build(qualname, node, cfg)

    parts: list[str] = [_signature_token(node)]
    for block in sorted(graph.blocks, key=lambda b: b.id):
        succ_ids = ",".join(
            str(s.id) for s in sorted(block.successors, key=lambda s: s.id)
        )
        with phase_ledger.phase(AnalysisPhaseKey.UNIT_NORMALIZE_CFG):
            block_dump = emit_wire_seq(block.statements, cfg)
        parts.append(f"BLOCK[{block.id}]:{block_dump}|SUCCESSORS:{succ_ids}")
    return sha256_hex(_FN_DOMAIN, "|".join(parts)), cyclomatic_complexity(graph)


def _signature_token(node: _qualnames.FunctionNode) -> str:
    args = node.args
    default_count = len(args.defaults) + sum(
        1 for value in args.kw_defaults if value is not None
    )
    return (
        f"SIG:async={int(isinstance(node, ast.AsyncFunctionDef))},"
        f"posonly={len(args.posonlyargs)},args={len(args.args)},"
        f"kwonly={len(args.kwonlyargs)},vararg={int(args.vararg is not None)},"
        f"kwarg={int(args.kwarg is not None)},defaults={default_count}"
    )
