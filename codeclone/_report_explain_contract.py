"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

from typing import Final

from .ui_messages import (
    REPORT_BLOCK_GROUP_DISPLAY_NAME_ASSERT_PATTERN,
    fmt_report_block_group_compare_note_n_way,
)

BLOCK_PATTERN_REPEATED_STMT_HASH: Final = "repeated_stmt_hash"

BLOCK_HINT_ASSERT_ONLY: Final = "assert_only"
BLOCK_HINT_ASSERT_ONLY_LABEL: Final = "Assert-only block"
BLOCK_HINT_CONFIDENCE_DETERMINISTIC: Final = "deterministic"
BLOCK_HINT_ASSERT_ONLY_NOTE: Final = (
    "This block clone consists entirely of assert-only statements. "
    "This often occurs in test suites."
)


def format_n_way_group_compare_note(*, peer_count: int) -> str:
    return fmt_report_block_group_compare_note_n_way(peer_count=peer_count)


def resolve_group_compare_note(*, group_arity: int, peer_count: int) -> str | None:
    if group_arity > 2:
        return format_n_way_group_compare_note(peer_count=peer_count)
    return None


def resolve_group_display_name(*, hint_id: str | None) -> str | None:
    if hint_id == BLOCK_HINT_ASSERT_ONLY:
        return REPORT_BLOCK_GROUP_DISPLAY_NAME_ASSERT_PATTERN
    return None


def format_group_instance_compare_meta(
    *, instance_index: int, group_arity: int, peer_count: int
) -> str:
    return f"instance {instance_index}/{group_arity} • matches {peer_count} peers"
