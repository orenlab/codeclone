# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import hashlib
from typing import TYPE_CHECKING

from .normalize import AstNormalizer, NormalizationConfig

if TYPE_CHECKING:
    from collections.abc import Sequence


def _normalized_stmt_dump(stmt: ast.stmt, normalizer: AstNormalizer) -> str:
    normalized = normalizer.visit(stmt)
    assert isinstance(normalized, ast.AST)
    return ast.dump(normalized, annotate_fields=True, include_attributes=False)


def stmt_hashes(statements: Sequence[ast.stmt], cfg: NormalizationConfig) -> list[str]:
    normalizer = AstNormalizer(cfg)
    return [
        hashlib.sha1(
            _normalized_stmt_dump(stmt, normalizer).encode("utf-8")
        ).hexdigest()
        for stmt in statements
    ]
