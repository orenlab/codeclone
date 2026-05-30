# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Structured MCP workspace tips for agent-facing hygiene guidance."""

from __future__ import annotations

from ....paths.gitignore import (
    GITIGNORE_CODECLONE_CACHE_TIP_ID,
    WORKSPACE_HYGIENE_CATEGORY,
    gitignore_codeclone_cache_tip_payload,
)


def gitignore_codeclone_cache_tip() -> dict[str, object]:
    return gitignore_codeclone_cache_tip_payload()


__all__ = [
    "GITIGNORE_CODECLONE_CACHE_TIP_ID",
    "WORKSPACE_HYGIENE_CATEGORY",
    "gitignore_codeclone_cache_tip",
]
