# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..utils.repo_paths import (
    PathOutsideRepoError,
    RepoPathError,
    RepoPathPolicy,
    resolve_under_repo_root,
)
from .memory_defaults import (
    DEFAULT_SEMANTIC_ALLOW_MODEL_DOWNLOAD,
    DEFAULT_SEMANTIC_BACKEND,
    DEFAULT_SEMANTIC_DIMENSION,
    DEFAULT_SEMANTIC_EMBEDDING_CACHE_DIR,
    DEFAULT_SEMANTIC_EMBEDDING_PROVIDER,
    DEFAULT_SEMANTIC_ENABLED,
    DEFAULT_SEMANTIC_FASTEMBED_DIMENSION,
    DEFAULT_SEMANTIC_FASTEMBED_MODEL,
    DEFAULT_SEMANTIC_INDEX_AUDIT,
    DEFAULT_SEMANTIC_INDEX_PATH,
    DEFAULT_SEMANTIC_MAX_RESULTS,
    MEMORY_ENV_DB_PATH,
    MEMORY_ENV_SEMANTIC_ALLOW_MODEL_DOWNLOAD,
    MEMORY_ENV_SEMANTIC_EMBEDDING_CACHE_DIR,
    MEMORY_ENV_SEMANTIC_EMBEDDING_MODEL,
    MEMORY_ENV_SEMANTIC_EMBEDDING_PROVIDER,
    MEMORY_ENV_SEMANTIC_ENABLED,
    MEMORY_ENV_SEMANTIC_INDEX_PATH,
    MemoryBackend,
    MemoryMcpSyncPolicy,
    SemanticBackend,
    SemanticEmbeddingProvider,
)
from .memory_specs import MEMORY_CONFIG_DEFAULTS, SEMANTIC_NESTED_TABLE_KEY
from .pyproject_loader import load_pyproject_config

_VALID_BACKENDS = frozenset({"sqlite", "postgres"})
_VALID_MCP_SYNC_POLICIES = frozenset(
    {"off", "bootstrap_if_missing", "refresh_when_stale"},
)

_SEMANTIC_ENV_OVERRIDES: dict[str, str] = {
    MEMORY_ENV_SEMANTIC_ENABLED: "enabled",
    MEMORY_ENV_SEMANTIC_EMBEDDING_PROVIDER: "embedding_provider",
    MEMORY_ENV_SEMANTIC_EMBEDDING_MODEL: "embedding_model",
    MEMORY_ENV_SEMANTIC_EMBEDDING_CACHE_DIR: "embedding_cache_dir",
    MEMORY_ENV_SEMANTIC_ALLOW_MODEL_DOWNLOAD: "allow_model_download",
    MEMORY_ENV_SEMANTIC_INDEX_PATH: "index_path",
}


class SemanticConfig(BaseModel):
    """Validated semantic-retrieval config (Phase 20).

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
    trajectories_enabled: bool
    trajectory_retention_days: int
    semantic: SemanticConfig = field(default_factory=SemanticConfig)


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


def _format_semantic_error(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Invalid tool.codeclone.memory.semantic configuration"
    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", ()))
    message = first.get("msg", "invalid value")
    suffix = f".{loc}" if loc else ""
    return f"Invalid tool.codeclone.memory.semantic{suffix}: {message}"


def _resolve_semantic_config(raw: object, *, root_path: Path) -> SemanticConfig:
    data: dict[str, object] = dict(raw) if isinstance(raw, dict) else {}
    for env_var, field_name in _SEMANTIC_ENV_OVERRIDES.items():
        env_value = os.environ.get(env_var)
        if env_value is not None:
            data[field_name] = env_value
    try:
        config = SemanticConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(_format_semantic_error(exc)) from exc
    index_path = _resolve_memory_state_path(
        key="memory.semantic.index_path",
        value=config.index_path,
        root_path=root_path,
    )
    cache_dir = _resolve_memory_state_path(
        key="memory.semantic.embedding_cache_dir",
        value=config.embedding_cache_dir,
        root_path=root_path,
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

    env_db_path = os.environ.get(MEMORY_ENV_DB_PATH)
    db_path_raw: object = env_db_path if env_db_path is not None else merged["db_path"]
    db_path_value = _resolve_memory_state_path(
        key="memory.db_path",
        value=db_path_raw,
        root_path=root_path,
    )

    return MemoryConfig(
        backend=backend_raw,  # type: ignore[arg-type]
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
        mcp_sync_policy=policy_raw,  # type: ignore[arg-type]
        trajectories_enabled=_memory_bool(
            merged["trajectories_enabled"], key="trajectories_enabled"
        ),
        trajectory_retention_days=_memory_int(
            merged["trajectory_retention_days"], key="trajectory_retention_days"
        ),
        semantic=_resolve_semantic_config(
            merged.get(SEMANTIC_NESTED_TABLE_KEY),
            root_path=root_path,
        ),
    )


__all__ = ["MemoryConfig", "SemanticConfig", "resolve_memory_config"]
