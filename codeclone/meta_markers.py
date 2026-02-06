"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

# Contains `:` characters, so it cannot be produced by valid Python identifiers
# from parsed source code. It is only emitted programmatically by CFG builder.
CFG_META_PREFIX = "__CC_META__::"
