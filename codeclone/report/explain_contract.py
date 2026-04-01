# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Final

BLOCK_PATTERN_REPEATED_STMT_HASH: Final = "repeated_stmt_hash"

BLOCK_HINT_ASSERT_ONLY: Final = "assert_only"
BLOCK_HINT_ASSERT_ONLY_LABEL: Final = "Assert-only block"
BLOCK_HINT_CONFIDENCE_DETERMINISTIC: Final = "deterministic"
BLOCK_HINT_ASSERT_ONLY_NOTE: Final = (
    "This block clone consists entirely of assert-only statements. "
    "This often occurs in test suites."
)

GROUP_DISPLAY_NAME_BY_HINT_ID: Final[dict[str, str]] = {
    BLOCK_HINT_ASSERT_ONLY: "Assert pattern block",
}


def format_n_way_group_compare_note(*, peer_count: int) -> str:
    return f"N-way group: each block matches {peer_count} peers in this group."


def resolve_group_compare_note(*, group_arity: int, peer_count: int) -> str | None:
    if group_arity > 2:
        return format_n_way_group_compare_note(peer_count=peer_count)
    return None


def resolve_group_display_name(*, hint_id: str | None) -> str | None:
    if hint_id is None:
        return None
    return GROUP_DISPLAY_NAME_BY_HINT_ID.get(hint_id)


def format_group_instance_compare_meta(
    *, instance_index: int, group_arity: int, peer_count: int
) -> str:
    return f"instance {instance_index}/{group_arity} • matches {peer_count} peers"
