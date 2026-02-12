"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

from typing import Any

# Any: report items aggregate heterogeneous JSON-like payloads from multiple
# pipelines (function/block/segment) and are narrowed at access sites.
GroupItem = dict[str, Any]


GroupMap = dict[str, list[GroupItem]]
