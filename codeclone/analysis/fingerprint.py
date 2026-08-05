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
from ..metrics.complexity import cfg_cyclomatic_complexity
from ..models import NearMissElement
from .binding import BindingContext
from .cfg import CFG, CFGBuilder
from .normalizer import NormalizationConfig
from .phase_ledger import INERT_PHASE_LEDGER, AnalysisPhaseKey, PhaseLedger
from .wire import emit_wire, emit_wire_seq

# The domain moves with the fingerprint version. Without it a function whose
# normalization did not change would keep a byte-identical digest across two
# incompatible generations, and generation would be a metadata claim rather
# than a property of the digest itself (39Y-FP section 4).
_FN_DOMAIN: Final = b"ccfp3:fn\x00"
_NEAR_MISS_STMT_DOMAIN: Final = b"ccnm:stmt\x00"
# Statement tokens are compared for equality only, never published as an
# identity: they exist so the near-miss tier can measure a statement-level edit
# distance, and they ride the cache wire once per statement of every
# clone-eligible unit. 64 bits keeps that carriage small. This is a wire width,
# not a classification threshold — a collision can only ever add or drop an
# advisory, gate-neutral near-miss pair, and can never reach a fingerprint, a
# baseline lane or a gate.
_NEAR_MISS_TOKEN_HEX: Final = 16
# Control-flow anchors carry a prefix no hex token can take, so a block
# boundary can never compare equal to a statement.
_NEAR_MISS_BOUNDARY_PREFIX: Final = "B"


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
    bindings: BindingContext,
    *,
    phase_ledger: PhaseLedger = INERT_PHASE_LEDGER,
) -> tuple[CFG, str, int]:
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
        bindings: Lexical scope of the function, positioned at its own scope.
            The fingerprint is a function of (AST x binding context): the same
            body reading a different imported symbol is a different function.

    Returns:
        The built CFG, its 64-character hex SHA-256 fingerprint, and its
        diagnostic CFG cyclomatic complexity (E-N+2P; never the public
        source-decision metric). The graph is returned so downstream analysis
        can reuse the exact structure that produced the fingerprint.
    """
    builder = CFGBuilder()
    with phase_ledger.phase(AnalysisPhaseKey.UNIT_CFG):
        graph = builder.build(qualname, node, cfg, bindings)

    parts: list[str] = [_signature_token(node)]
    for block in sorted(graph.blocks, key=lambda b: b.id):
        succ_ids = ",".join(
            str(s.id) for s in sorted(block.successors, key=lambda s: s.id)
        )
        with phase_ledger.phase(AnalysisPhaseKey.UNIT_NORMALIZE_CFG):
            block_dump = emit_wire_seq(block.statements, cfg, bindings)
        parts.append(f"BLOCK[{block.id}]:{block_dump}|SUCCESSORS:{succ_ids}")
    return (
        graph,
        sha256_hex(_FN_DOMAIN, "|".join(parts)),
        cfg_cyclomatic_complexity(graph),
    )


def near_miss_statement_sequence(
    graph: CFG,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> tuple[NearMissElement, ...]:
    """Return the normalized statement sequence behind the near-miss tier.

    The walk is the one ``_cfg_fingerprint_and_complexity`` already performs —
    blocks in sorted id order, statements through the canonical wire — so the
    sequence and the exact fingerprint always describe the same normalization.
    Nothing here feeds the fingerprint: this is a read of the built graph, and
    ``BASELINE_FINGERPRINT_VERSION`` semantics are untouched (39Y Y8).

    Each block contributes a control-flow anchor carrying its successor ids,
    then one token per statement. The anchors are what keep the tier honest: a
    pair whose statements match but whose control flow diverges shows that
    divergence as an edit rather than hiding it.
    """

    sequence: list[NearMissElement] = []
    for block in sorted(graph.blocks, key=lambda b: b.id):
        succ_ids = ",".join(
            str(s.id) for s in sorted(block.successors, key=lambda s: s.id)
        )
        sequence.append((f"{_NEAR_MISS_BOUNDARY_PREFIX}{block.id}>{succ_ids}", 0, 0))
        for statement in block.statements:
            token = hashlib.sha256(
                _NEAR_MISS_STMT_DOMAIN
                + emit_wire(statement, cfg, bindings).encode("utf-8")
            ).hexdigest()[:_NEAR_MISS_TOKEN_HEX]
            start = int(getattr(statement, "lineno", 0) or 0)
            end = int(getattr(statement, "end_lineno", 0) or 0) or start
            sequence.append((token, start, end))
    return tuple(sequence)


def is_near_miss_statement_token(token: str) -> bool:
    """Return whether a token is a statement rather than a control anchor."""

    return not token.startswith(_NEAR_MISS_BOUNDARY_PREFIX)


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
