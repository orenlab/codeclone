# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Final

from .memory_defaults import (
    DEFAULT_MEMORY_ACTIVE_RETENTION_DAYS,
    DEFAULT_MEMORY_ARCHIVED_RETENTION_DAYS,
    DEFAULT_MEMORY_BACKEND,
    DEFAULT_MEMORY_DB_PATH,
    DEFAULT_MEMORY_DRAFT_RETENTION_DAYS,
    DEFAULT_MEMORY_GIT_HOTSPOT_MIN_CHANGES,
    DEFAULT_MEMORY_GIT_HOTSPOT_PERIOD_DAYS,
    DEFAULT_MEMORY_MAX_BLAST_RADIUS_CACHE_ENTRIES,
    DEFAULT_MEMORY_MAX_CANDIDATES,
    DEFAULT_MEMORY_MAX_EVIDENCE_PER_RECORD,
    DEFAULT_MEMORY_MAX_RECORDS,
    DEFAULT_MEMORY_MAX_STATEMENT_CHARS,
    DEFAULT_MEMORY_MCP_SYNC_POLICY,
    DEFAULT_MEMORY_PROJECTION_REBUILD_COALESCE_MIN_DELTA,
    DEFAULT_MEMORY_PROJECTION_REBUILD_COALESCE_WINDOW_SECONDS,
    DEFAULT_MEMORY_PROJECTION_REBUILD_POLICY,
    DEFAULT_MEMORY_PROJECTION_REBUILD_RUNNING_TIMEOUT_SECONDS,
    DEFAULT_MEMORY_PROJECTION_REBUILD_SPAWN_WORKER,
    DEFAULT_MEMORY_RECEIPT_RETENTION_DAYS,
    DEFAULT_MEMORY_REJECTED_RETENTION_DAYS,
    DEFAULT_MEMORY_STALE_RETENTION_DAYS,
    DEFAULT_MEMORY_TRAJECTORIES_ENABLED,
    DEFAULT_MEMORY_TRAJECTORY_EXPORT_ENABLED,
    DEFAULT_MEMORY_TRAJECTORY_EXPORT_INCLUDE_PAYLOADS,
    DEFAULT_MEMORY_TRAJECTORY_EXPORT_MAX_FILE_BYTES,
    DEFAULT_MEMORY_TRAJECTORY_EXPORT_MAX_RECORD_BYTES,
    DEFAULT_MEMORY_TRAJECTORY_RETENTION_DAYS,
)
from .spec import ConfigKeySpec

MEMORY_CONFIG_KEY_SPECS: Final[dict[str, ConfigKeySpec]] = {
    "backend": ConfigKeySpec(expected_type=str),
    "db_path": ConfigKeySpec(expected_type=str),
    "active_retention_days": ConfigKeySpec(expected_type=int),
    "stale_retention_days": ConfigKeySpec(expected_type=int),
    "draft_retention_days": ConfigKeySpec(expected_type=int),
    "rejected_retention_days": ConfigKeySpec(expected_type=int),
    "archived_retention_days": ConfigKeySpec(expected_type=int),
    "receipt_retention_days": ConfigKeySpec(expected_type=int),
    "max_records": ConfigKeySpec(expected_type=int),
    "max_candidates": ConfigKeySpec(expected_type=int),
    "max_evidence_per_record": ConfigKeySpec(expected_type=int),
    "max_statement_chars": ConfigKeySpec(expected_type=int),
    "max_blast_radius_cache_entries": ConfigKeySpec(expected_type=int),
    "git_hotspot_period_days": ConfigKeySpec(expected_type=int),
    "git_hotspot_min_changes": ConfigKeySpec(expected_type=int),
    "mcp_sync_policy": ConfigKeySpec(expected_type=str),
    "projection_rebuild_policy": ConfigKeySpec(expected_type=str),
    "projection_rebuild_running_timeout_seconds": ConfigKeySpec(expected_type=int),
    "projection_rebuild_spawn_worker": ConfigKeySpec(expected_type=bool),
    "projection_rebuild_coalesce_window_seconds": ConfigKeySpec(expected_type=int),
    "projection_rebuild_coalesce_min_delta": ConfigKeySpec(expected_type=int),
    "trajectories_enabled": ConfigKeySpec(expected_type=bool),
    "trajectory_retention_days": ConfigKeySpec(expected_type=int),
    "trajectory_export_enabled": ConfigKeySpec(expected_type=bool),
    "trajectory_export_include_payloads": ConfigKeySpec(expected_type=bool),
    "trajectory_export_max_record_bytes": ConfigKeySpec(expected_type=int),
    "trajectory_export_max_file_bytes": ConfigKeySpec(expected_type=int),
}

MEMORY_PATH_CONFIG_KEYS: Final[frozenset[str]] = frozenset({"db_path"})

MEMORY_CONFIG_DEFAULTS: Final[dict[str, object]] = {
    "backend": DEFAULT_MEMORY_BACKEND,
    "db_path": DEFAULT_MEMORY_DB_PATH,
    "active_retention_days": DEFAULT_MEMORY_ACTIVE_RETENTION_DAYS,
    "stale_retention_days": DEFAULT_MEMORY_STALE_RETENTION_DAYS,
    "draft_retention_days": DEFAULT_MEMORY_DRAFT_RETENTION_DAYS,
    "rejected_retention_days": DEFAULT_MEMORY_REJECTED_RETENTION_DAYS,
    "archived_retention_days": DEFAULT_MEMORY_ARCHIVED_RETENTION_DAYS,
    "receipt_retention_days": DEFAULT_MEMORY_RECEIPT_RETENTION_DAYS,
    "max_records": DEFAULT_MEMORY_MAX_RECORDS,
    "max_candidates": DEFAULT_MEMORY_MAX_CANDIDATES,
    "max_evidence_per_record": DEFAULT_MEMORY_MAX_EVIDENCE_PER_RECORD,
    "max_statement_chars": DEFAULT_MEMORY_MAX_STATEMENT_CHARS,
    "max_blast_radius_cache_entries": DEFAULT_MEMORY_MAX_BLAST_RADIUS_CACHE_ENTRIES,
    "git_hotspot_period_days": DEFAULT_MEMORY_GIT_HOTSPOT_PERIOD_DAYS,
    "git_hotspot_min_changes": DEFAULT_MEMORY_GIT_HOTSPOT_MIN_CHANGES,
    "mcp_sync_policy": DEFAULT_MEMORY_MCP_SYNC_POLICY,
    "projection_rebuild_policy": DEFAULT_MEMORY_PROJECTION_REBUILD_POLICY,
    "projection_rebuild_running_timeout_seconds": (
        DEFAULT_MEMORY_PROJECTION_REBUILD_RUNNING_TIMEOUT_SECONDS
    ),
    "projection_rebuild_spawn_worker": DEFAULT_MEMORY_PROJECTION_REBUILD_SPAWN_WORKER,
    "projection_rebuild_coalesce_window_seconds": (
        DEFAULT_MEMORY_PROJECTION_REBUILD_COALESCE_WINDOW_SECONDS
    ),
    "projection_rebuild_coalesce_min_delta": (
        DEFAULT_MEMORY_PROJECTION_REBUILD_COALESCE_MIN_DELTA
    ),
    "trajectories_enabled": DEFAULT_MEMORY_TRAJECTORIES_ENABLED,
    "trajectory_retention_days": DEFAULT_MEMORY_TRAJECTORY_RETENTION_DAYS,
    "trajectory_export_enabled": DEFAULT_MEMORY_TRAJECTORY_EXPORT_ENABLED,
    "trajectory_export_include_payloads": (
        DEFAULT_MEMORY_TRAJECTORY_EXPORT_INCLUDE_PAYLOADS
    ),
    "trajectory_export_max_record_bytes": (
        DEFAULT_MEMORY_TRAJECTORY_EXPORT_MAX_RECORD_BYTES
    ),
    "trajectory_export_max_file_bytes": DEFAULT_MEMORY_TRAJECTORY_EXPORT_MAX_FILE_BYTES,
}

MEMORY_NESTED_TABLE_KEY: Final = "memory"
INGEST_NESTED_TABLE_KEY: Final = "ingest"

# Nested sub-table under [tool.codeclone.memory]. Field-level validation is
# owned by the pydantic SemanticConfig (codeclone/config/memory.py), so there
# is intentionally no flat SEMANTIC_CONFIG_KEY_SPECS here — a single
# validation authority, no duplicated key specs.
SEMANTIC_NESTED_TABLE_KEY: Final = "semantic"

__all__ = [
    "INGEST_NESTED_TABLE_KEY",
    "MEMORY_CONFIG_DEFAULTS",
    "MEMORY_CONFIG_KEY_SPECS",
    "MEMORY_NESTED_TABLE_KEY",
    "MEMORY_PATH_CONFIG_KEYS",
    "SEMANTIC_NESTED_TABLE_KEY",
]
