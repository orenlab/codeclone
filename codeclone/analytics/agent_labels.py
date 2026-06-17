# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence

from ..contracts import CORPUS_AGENT_LABEL_CONTRACT_VERSION

_AGENT_FAMILY_RULES: tuple[tuple[str, str], ...] = (
    ("cursor-", "cursor"),
    ("claude-", "claude"),
    ("codex-", "codex"),
    ("vscode-", "vscode"),
    ("mcp-client", "mcp"),
)


def map_agent_family(agent_client_raw: str | None) -> str:
    """Map raw agent client label to a deterministic agent family string."""
    if not agent_client_raw:
        return "unknown"
    normalized = agent_client_raw.strip().lower()
    if not normalized:
        return "unknown"
    for prefix, family in _AGENT_FAMILY_RULES:
        if normalized.startswith(prefix) or prefix in normalized:
            return family
    return "unknown"


def agent_label_contract_version() -> str:
    return CORPUS_AGENT_LABEL_CONTRACT_VERSION


def agent_family_rules() -> Sequence[tuple[str, str]]:
    return _AGENT_FAMILY_RULES


__all__ = [
    "agent_family_rules",
    "agent_label_contract_version",
    "map_agent_family",
]
