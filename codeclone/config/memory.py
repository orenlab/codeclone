# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .memory_defaults import MEMORY_ENV_DB_PATH, MemoryBackend, MemoryMcpSyncPolicy
from .memory_specs import MEMORY_CONFIG_DEFAULTS
from .pyproject_loader import load_pyproject_config, normalize_path_config_value

_VALID_BACKENDS = frozenset({"sqlite", "postgres"})
_VALID_MCP_SYNC_POLICIES = frozenset(
    {"off", "bootstrap_if_missing", "refresh_when_stale"},
)


@dataclass(frozen=True, slots=True)
class MemoryConfig:
    backend: MemoryBackend
    db_path: Path
    active_retention_days: int
    stale_retention_days: int
    draft_retention_days: int
    rejected_retention_days: int
    archived_retention_days: int
    receipt_retention_days: int
    max_records: int
    max_candidates: int
    max_evidence_per_record: int
    max_statement_chars: int
    max_blast_radius_cache_entries: int
    git_hotspot_period_days: int
    git_hotspot_min_changes: int
    mcp_sync_policy: MemoryMcpSyncPolicy


def _memory_int(value: object, *, key: str) -> int:
    if isinstance(value, bool):
        msg = f"Invalid tool.codeclone.memory.{key}: expected integer"
        raise ValueError(msg)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    msg = f"Invalid tool.codeclone.memory.{key}: expected integer"
    raise ValueError(msg)


def _memory_choice(value: object, *, key: str, valid: frozenset[str]) -> str:
    raw = str(value).strip().lower()
    if raw not in valid:
        msg = f"Invalid tool.codeclone.memory.{key}: expected one of {sorted(valid)}"
        raise ValueError(msg)
    return raw


def resolve_memory_config(
    root_path: Path,
    *,
    pyproject_config: dict[str, object] | None = None,
) -> MemoryConfig:
    loaded = (
        load_pyproject_config(root_path)
        if pyproject_config is None
        else pyproject_config
    )
    memory_obj = loaded.get("memory")
    merged: dict[str, object] = dict(MEMORY_CONFIG_DEFAULTS)
    if isinstance(memory_obj, dict):
        merged.update(memory_obj)

    backend_raw = _memory_choice(
        merged["backend"],
        key="backend",
        valid=_VALID_BACKENDS,
    )

    policy_raw = _memory_choice(
        merged["mcp_sync_policy"],
        key="mcp_sync_policy",
        valid=_VALID_MCP_SYNC_POLICIES,
    )

    db_path_raw = os.environ.get(MEMORY_ENV_DB_PATH, str(merged["db_path"]))
    db_path_value = normalize_path_config_value(
        key="db_path",
        value=db_path_raw,
        root_path=root_path,
        path_config_keys=frozenset({"db_path"}),
    )
    if not isinstance(db_path_value, str):
        raise TypeError("memory db_path must resolve to a string path")

    return MemoryConfig(
        backend=backend_raw,  # type: ignore[arg-type]
        db_path=Path(db_path_value),
        active_retention_days=_memory_int(
            merged["active_retention_days"], key="active_retention_days"
        ),
        stale_retention_days=_memory_int(
            merged["stale_retention_days"], key="stale_retention_days"
        ),
        draft_retention_days=_memory_int(
            merged["draft_retention_days"], key="draft_retention_days"
        ),
        rejected_retention_days=_memory_int(
            merged["rejected_retention_days"], key="rejected_retention_days"
        ),
        archived_retention_days=_memory_int(
            merged["archived_retention_days"], key="archived_retention_days"
        ),
        receipt_retention_days=_memory_int(
            merged["receipt_retention_days"], key="receipt_retention_days"
        ),
        max_records=_memory_int(merged["max_records"], key="max_records"),
        max_candidates=_memory_int(merged["max_candidates"], key="max_candidates"),
        max_evidence_per_record=_memory_int(
            merged["max_evidence_per_record"], key="max_evidence_per_record"
        ),
        max_statement_chars=_memory_int(
            merged["max_statement_chars"], key="max_statement_chars"
        ),
        max_blast_radius_cache_entries=_memory_int(
            merged["max_blast_radius_cache_entries"],
            key="max_blast_radius_cache_entries",
        ),
        git_hotspot_period_days=_memory_int(
            merged["git_hotspot_period_days"],
            key="git_hotspot_period_days",
        ),
        git_hotspot_min_changes=_memory_int(
            merged["git_hotspot_min_changes"],
            key="git_hotspot_min_changes",
        ),
        mcp_sync_policy=policy_raw,  # type: ignore[arg-type]
    )


__all__ = ["MemoryConfig", "resolve_memory_config"]
