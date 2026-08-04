# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeGuard

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..utils.repo_identity import (
    RepoIdentityResolution,
    classify_repository_checkout,
    resolve_repository_anchor_root,
)
from ..utils.repo_paths import (
    PathOutsideRepoError,
    RepoPathError,
    RepoPathPolicy,
    resolve_under_repo_root,
)
from .memory_defaults import (
    DEFAULT_INGEST_CONTRACT_CONSTANTS_PATHS,
    DEFAULT_INGEST_DOCUMENT_LINK_PATHS,
    DEFAULT_INGEST_MCP_TOOL_COUNT_DOC_PATHS,
    DEFAULT_INGEST_MCP_TOOL_SCHEMA_SNAPSHOT_PATH,
    DEFAULT_SEMANTIC_ALLOW_MODEL_DOWNLOAD,
    DEFAULT_SEMANTIC_BACKEND,
    DEFAULT_SEMANTIC_DIMENSION,
    DEFAULT_SEMANTIC_EMBED_MAX_DOCUMENTS_PER_BATCH,
    DEFAULT_SEMANTIC_EMBED_MAX_PADDED_TOKENS_PER_BATCH,
    DEFAULT_SEMANTIC_EMBEDDING_CACHE_DIR,
    DEFAULT_SEMANTIC_EMBEDDING_PROVIDER,
    DEFAULT_SEMANTIC_ENABLED,
    DEFAULT_SEMANTIC_FASTEMBED_DIMENSION,
    DEFAULT_SEMANTIC_FASTEMBED_MODEL,
    DEFAULT_SEMANTIC_INDEX_AUDIT,
    DEFAULT_SEMANTIC_INDEX_PATH,
    DEFAULT_SEMANTIC_MAX_RESULTS,
    DEFAULT_SEMANTIC_PROJECTION_TOKEN_ESTIMATOR,
    MEMORY_ENV_DB_PATH,
    MEMORY_ENV_PROJECTION_REBUILD_POLICY,
    MEMORY_ENV_SEMANTIC_ALLOW_MODEL_DOWNLOAD,
    MEMORY_ENV_SEMANTIC_EMBEDDING_CACHE_DIR,
    MEMORY_ENV_SEMANTIC_EMBEDDING_MODEL,
    MEMORY_ENV_SEMANTIC_EMBEDDING_PROVIDER,
    MEMORY_ENV_SEMANTIC_ENABLED,
    MEMORY_ENV_SEMANTIC_INDEX_PATH,
    MemoryBackend,
    MemoryMcpSyncPolicy,
    MemoryProjectionRebuildPolicy,
    MemoryStoreResolution,
    SemanticBackend,
    SemanticEmbeddingProvider,
    SemanticProjectionTokenEstimator,
)
from .memory_specs import (
    INGEST_NESTED_TABLE_KEY,
    MEMORY_CONFIG_DEFAULTS,
    SEMANTIC_NESTED_TABLE_KEY,
)
from .pyproject_loader import copy_str_key_table, load_pyproject_config

_VALID_BACKENDS = frozenset({"sqlite", "postgres"})
_VALID_MCP_SYNC_POLICIES = frozenset(
    {"off", "bootstrap_if_missing", "refresh_when_stale"},
)
_VALID_PROJECTION_REBUILD_POLICIES = frozenset({"off", "enqueue_when_stale"})

_SEMANTIC_ENV_OVERRIDES: dict[str, str] = {
    MEMORY_ENV_SEMANTIC_ENABLED: "enabled",
    MEMORY_ENV_SEMANTIC_EMBEDDING_PROVIDER: "embedding_provider",
    MEMORY_ENV_SEMANTIC_EMBEDDING_MODEL: "embedding_model",
    MEMORY_ENV_SEMANTIC_EMBEDDING_CACHE_DIR: "embedding_cache_dir",
    MEMORY_ENV_SEMANTIC_ALLOW_MODEL_DOWNLOAD: "allow_model_download",
    MEMORY_ENV_SEMANTIC_INDEX_PATH: "index_path",
}


class SemanticConfig(BaseModel):
    """Validated semantic-retrieval config.

    The single validation authority for ``[tool.codeclone.memory.semantic]``:
    ``frozen`` + ``extra="forbid"`` reject unknown keys, bad literals, and
    non-positive sizes here, so no flat ConfigKeySpec table duplicates these
    field definitions. ``enabled=false`` + ``diagnostic`` keep the default
    offline and zero-extra-dependency. ``fastembed`` is the community local
    quality provider and remains opt-in.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = DEFAULT_SEMANTIC_ENABLED
    backend: SemanticBackend = DEFAULT_SEMANTIC_BACKEND
    index_path: str = Field(default=DEFAULT_SEMANTIC_INDEX_PATH, min_length=1)
    embedding_provider: SemanticEmbeddingProvider = DEFAULT_SEMANTIC_EMBEDDING_PROVIDER
    embedding_model: str | None = Field(default=None, min_length=1)
    embedding_cache_dir: str = Field(
        default=DEFAULT_SEMANTIC_EMBEDDING_CACHE_DIR, min_length=1
    )
    allow_model_download: bool = DEFAULT_SEMANTIC_ALLOW_MODEL_DOWNLOAD
    dimension: int = Field(default=DEFAULT_SEMANTIC_DIMENSION, gt=0)
    max_results: int = Field(default=DEFAULT_SEMANTIC_MAX_RESULTS, gt=0)
    index_audit: bool = DEFAULT_SEMANTIC_INDEX_AUDIT
    embed_max_documents_per_batch: int = Field(
        default=DEFAULT_SEMANTIC_EMBED_MAX_DOCUMENTS_PER_BATCH,
        gt=0,
    )
    embed_max_padded_tokens_per_batch: int = Field(
        default=DEFAULT_SEMANTIC_EMBED_MAX_PADDED_TOKENS_PER_BATCH,
        gt=0,
    )
    projection_token_estimator: SemanticProjectionTokenEstimator = (
        DEFAULT_SEMANTIC_PROJECTION_TOKEN_ESTIMATOR
    )

    @model_validator(mode="before")
    @classmethod
    def _apply_provider_defaults(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if normalized.get("embedding_provider") == "fastembed":
            normalized.setdefault("embedding_model", DEFAULT_SEMANTIC_FASTEMBED_MODEL)
            normalized.setdefault("dimension", DEFAULT_SEMANTIC_FASTEMBED_DIMENSION)
        return normalized


class IngestConfig(BaseModel):
    """Validated memory ingest path config.

    Empty ``contract_constants_paths`` / ``document_link_paths`` enable
    registry-aware auto-discovery. MCP tool-count contradiction checks run
    only when both ``mcp_tool_schema_snapshot_path`` and
    ``mcp_tool_count_doc_paths`` are configured.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_constants_paths: tuple[str, ...] = DEFAULT_INGEST_CONTRACT_CONSTANTS_PATHS
    document_link_paths: tuple[str, ...] = DEFAULT_INGEST_DOCUMENT_LINK_PATHS
    mcp_tool_schema_snapshot_path: str | None = (
        DEFAULT_INGEST_MCP_TOOL_SCHEMA_SNAPSHOT_PATH
    )
    mcp_tool_count_doc_paths: tuple[str, ...] = DEFAULT_INGEST_MCP_TOOL_COUNT_DOC_PATHS

    @model_validator(mode="before")
    @classmethod
    def _normalize_path_lists(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        for key in (
            "contract_constants_paths",
            "document_link_paths",
            "mcp_tool_count_doc_paths",
        ):
            raw = normalized.get(key)
            if raw is None:
                continue
            if isinstance(raw, str):
                normalized[key] = (raw,)
            elif isinstance(raw, list):
                normalized[key] = tuple(str(item) for item in raw)
        snapshot = normalized.get("mcp_tool_schema_snapshot_path")
        if snapshot == "":
            normalized["mcp_tool_schema_snapshot_path"] = None
        return normalized


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
    projection_rebuild_policy: MemoryProjectionRebuildPolicy
    projection_rebuild_running_timeout_seconds: int
    projection_rebuild_spawn_worker: bool
    projection_rebuild_coalesce_window_seconds: int
    projection_rebuild_coalesce_min_delta: int
    trajectories_enabled: bool
    trajectory_retention_days: int
    trajectory_export_enabled: bool
    trajectory_export_include_payloads: bool
    trajectory_export_max_record_bytes: int
    trajectory_export_max_file_bytes: int
    semantic: SemanticConfig = field(default_factory=SemanticConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    # Why db_path landed where it did (see MemoryStoreResolution). Set by
    # resolve_memory_config; the dataclass default only serves direct
    # constructions that never ran resolution.
    store_resolution: MemoryStoreResolution = "per_root_no_git"


# Store resolution witness per repository identity. Linked worktrees share
# the main checkout store; "per_root_git_unresolvable" is degraded (git
# state present, main checkout unreachable) and warn-worthy in responses.
_STORE_RESOLUTION_BY_REPO_IDENTITY: dict[
    RepoIdentityResolution, MemoryStoreResolution
] = {
    "main_checkout": "main_checkout",
    "linked_worktree": "shared_main_checkout",
    "no_git": "per_root_no_git",
    "git_unresolvable": "per_root_git_unresolvable",
}


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


def _memory_bool(value: object, *, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
    msg = f"Invalid tool.codeclone.memory.{key}: expected boolean"
    raise ValueError(msg)


def _memory_choice(value: object, *, key: str, valid: frozenset[str]) -> str:
    raw = str(value).strip().lower()
    if raw not in valid:
        msg = f"Invalid tool.codeclone.memory.{key}: expected one of {sorted(valid)}"
        raise ValueError(msg)
    return raw


def _is_memory_backend(value: str) -> TypeGuard[MemoryBackend]:
    return value in _VALID_BACKENDS


def _is_mcp_sync_policy(value: str) -> TypeGuard[MemoryMcpSyncPolicy]:
    return value in _VALID_MCP_SYNC_POLICIES


def _is_projection_rebuild_policy(
    value: str,
) -> TypeGuard[MemoryProjectionRebuildPolicy]:
    return value in _VALID_PROJECTION_REBUILD_POLICIES


def _memory_backend(value: object) -> MemoryBackend:
    raw = _memory_choice(value, key="backend", valid=_VALID_BACKENDS)
    if _is_memory_backend(raw):
        return raw
    raise AssertionError("unreachable validated memory backend")


def _memory_mcp_sync_policy(value: object) -> MemoryMcpSyncPolicy:
    raw = _memory_choice(
        value,
        key="mcp_sync_policy",
        valid=_VALID_MCP_SYNC_POLICIES,
    )
    if _is_mcp_sync_policy(raw):
        return raw
    raise AssertionError("unreachable validated memory MCP sync policy")


def _memory_projection_rebuild_policy(
    value: object,
) -> MemoryProjectionRebuildPolicy:
    raw = _memory_choice(
        value,
        key="projection_rebuild_policy",
        valid=_VALID_PROJECTION_REBUILD_POLICIES,
    )
    if _is_projection_rebuild_policy(raw):
        return raw
    raise AssertionError("unreachable validated memory projection rebuild policy")


def _format_nested_memory_config_error(
    *,
    section: str,
    exc: ValidationError,
) -> str:
    errors = exc.errors()
    if not errors:
        return f"Invalid tool.codeclone.memory.{section} configuration"
    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", ()))
    message = first.get("msg", "invalid value")
    suffix = f".{loc}" if loc else ""
    return f"Invalid tool.codeclone.memory.{section}{suffix}: {message}"


def _resolve_ingest_config(raw: object) -> IngestConfig:
    data = (
        copy_str_key_table(raw, key="tool.codeclone.memory.ingest")
        if isinstance(raw, dict)
        else {}
    )
    try:
        return IngestConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(
            _format_nested_memory_config_error(section="ingest", exc=exc)
        ) from exc


def _resolve_semantic_config(
    raw: object,
    *,
    root_path: Path,
    default_state_root: Path,
) -> SemanticConfig:
    data = (
        copy_str_key_table(raw, key="tool.codeclone.memory.semantic")
        if isinstance(raw, dict)
        else {}
    )
    for env_var, field_name in _SEMANTIC_ENV_OVERRIDES.items():
        env_value = os.environ.get(env_var)
        if env_value is not None:
            data[field_name] = env_value
    # Explicit values (pyproject or env) keep resolving under the analyzed
    # root; only DEFAULT paths ride the shared repository anchor so that
    # linked worktrees converge on the main checkout `.codeclone/memory/`.
    explicit_index_path = "index_path" in data
    explicit_cache_dir = "embedding_cache_dir" in data
    try:
        config = SemanticConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(
            _format_nested_memory_config_error(section="semantic", exc=exc)
        ) from exc
    index_path = _resolve_memory_state_path(
        key="memory.semantic.index_path",
        value=config.index_path,
        root_path=root_path if explicit_index_path else default_state_root,
    )
    cache_dir = _resolve_memory_state_path(
        key="memory.semantic.embedding_cache_dir",
        value=config.embedding_cache_dir,
        root_path=root_path if explicit_cache_dir else default_state_root,
    )
    return config.model_copy(
        update={"index_path": str(index_path), "embedding_cache_dir": str(cache_dir)}
    )


def _resolve_memory_state_path(*, key: str, value: object, root_path: Path) -> Path:
    if not isinstance(value, str):
        raise TypeError(f"{key} must resolve to a string path")
    try:
        return resolve_under_repo_root(
            root_path,
            value,
            policy=RepoPathPolicy(allow_absolute=True),
        )
    except PathOutsideRepoError as exc:
        raise ValueError(f"{key} must stay under the repository root") from exc
    except RepoPathError as exc:
        raise ValueError(f"Invalid tool.codeclone.{key}: {exc}") from exc


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
    memory_table: dict[str, object] = (
        copy_str_key_table(memory_obj, key="tool.codeclone.memory")
        if isinstance(memory_obj, dict)
        else {}
    )
    merged: dict[str, object] = dict(MEMORY_CONFIG_DEFAULTS)
    merged.update(memory_table)

    backend = _memory_backend(merged["backend"])
    mcp_sync_policy = _memory_mcp_sync_policy(merged["mcp_sync_policy"])
    env_projection_policy = os.environ.get(MEMORY_ENV_PROJECTION_REBUILD_POLICY)
    projection_policy_value: object = (
        env_projection_policy
        if env_projection_policy is not None
        else merged["projection_rebuild_policy"]
    )
    projection_rebuild_policy = _memory_projection_rebuild_policy(
        projection_policy_value
    )

    # Default repository state anchors at the git common directory's main
    # checkout: every linked worktree of one repository resolves the same
    # store. Explicit config and env overrides keep per-checkout resolution.
    default_state_root = resolve_repository_anchor_root(root_path)

    env_db_path = os.environ.get(MEMORY_ENV_DB_PATH)
    store_resolution: MemoryStoreResolution
    if env_db_path is not None:
        db_path_raw: object = env_db_path
        db_path_root = root_path
        store_resolution = "explicit_env"
    elif "db_path" in memory_table:
        db_path_raw = merged["db_path"]
        db_path_root = root_path
        store_resolution = "explicit_config"
    else:
        db_path_raw = merged["db_path"]
        db_path_root = default_state_root
        store_resolution = _STORE_RESOLUTION_BY_REPO_IDENTITY[
            classify_repository_checkout(root_path)
        ]
    db_path_value = _resolve_memory_state_path(
        key="memory.db_path",
        value=db_path_raw,
        root_path=db_path_root,
    )

    return MemoryConfig(
        backend=backend,
        db_path=db_path_value,
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
        mcp_sync_policy=mcp_sync_policy,
        projection_rebuild_policy=projection_rebuild_policy,
        projection_rebuild_running_timeout_seconds=_memory_int(
            merged["projection_rebuild_running_timeout_seconds"],
            key="projection_rebuild_running_timeout_seconds",
        ),
        projection_rebuild_spawn_worker=_memory_bool(
            merged["projection_rebuild_spawn_worker"],
            key="projection_rebuild_spawn_worker",
        ),
        projection_rebuild_coalesce_window_seconds=_memory_int(
            merged["projection_rebuild_coalesce_window_seconds"],
            key="projection_rebuild_coalesce_window_seconds",
        ),
        projection_rebuild_coalesce_min_delta=_memory_int(
            merged["projection_rebuild_coalesce_min_delta"],
            key="projection_rebuild_coalesce_min_delta",
        ),
        trajectories_enabled=_memory_bool(
            merged["trajectories_enabled"], key="trajectories_enabled"
        ),
        trajectory_retention_days=_memory_int(
            merged["trajectory_retention_days"], key="trajectory_retention_days"
        ),
        trajectory_export_enabled=_memory_bool(
            merged["trajectory_export_enabled"], key="trajectory_export_enabled"
        ),
        trajectory_export_include_payloads=_memory_bool(
            merged["trajectory_export_include_payloads"],
            key="trajectory_export_include_payloads",
        ),
        trajectory_export_max_record_bytes=_memory_int(
            merged["trajectory_export_max_record_bytes"],
            key="trajectory_export_max_record_bytes",
        ),
        trajectory_export_max_file_bytes=_memory_int(
            merged["trajectory_export_max_file_bytes"],
            key="trajectory_export_max_file_bytes",
        ),
        semantic=_resolve_semantic_config(
            merged.get(SEMANTIC_NESTED_TABLE_KEY),
            root_path=root_path,
            default_state_root=default_state_root,
        ),
        ingest=_resolve_ingest_config(merged.get(INGEST_NESTED_TABLE_KEY)),
        store_resolution=store_resolution,
    )


__all__ = ["IngestConfig", "MemoryConfig", "SemanticConfig", "resolve_memory_config"]
