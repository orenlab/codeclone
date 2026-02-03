"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import ast
import hashlib

from .normalize import AstNormalizer, NormalizationConfig


def stmt_hash(stmt: ast.stmt, cfg: NormalizationConfig) -> str:
    normalizer = AstNormalizer(cfg)
    stmt = ast.fix_missing_locations(normalizer.visit(stmt))
    dump = ast.dump(stmt, annotate_fields=True, include_attributes=False)
    return hashlib.sha1(dump.encode("utf-8")).hexdigest()
