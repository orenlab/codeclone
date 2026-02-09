"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

from typing import Final

BLOCK_PATTERN_REPEATED_STMT_HASH: Final = "repeated_stmt_hash"

BLOCK_HINT_ASSERT_ONLY: Final = "assert_only"
BLOCK_HINT_ASSERT_ONLY_LABEL: Final = "assert-only block"
BLOCK_HINT_CONFIDENCE_DETERMINISTIC: Final = "deterministic"
BLOCK_HINT_ASSERT_ONLY_NOTE: Final = (
    "This block clone consists entirely of assert-only statements. "
    "This often occurs in test suites."
)

BLOCK_GROUP_DISPLAY_NAME_ASSERT_PATTERN: Final = "assert pattern block"


def format_n_way_group_compare_note(*, peer_count: int) -> str:
    return f"N-way group: each block matches {peer_count} peers in this group."


def format_group_instance_compare_meta(
    *, instance_index: int, group_arity: int, peer_count: int
) -> str:
    return f"instance {instance_index}/{group_arity} • matches {peer_count} peers"
