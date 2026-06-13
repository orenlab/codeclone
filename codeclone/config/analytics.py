# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..audit.validation import DEFAULT_AUDIT_PATH
from ..utils.repo_paths import RepoPathPolicy, resolve_under_repo_root
from .analytics_specs import ANALYTICS_NESTED_TABLE_KEY
from .memory import resolve_memory_config
from .pyproject_loader import load_pyproject_config

DEFAULT_ANALYTICS_DB_RELATIVE = ".codeclone/analytics/corpus_clustering.sqlite3"
DEFAULT_ANALYTICS_VECTORS_RELATIVE = ".codeclone/analytics/corpus_vectors"
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_EMBEDDING_DIMENSION = 384
DEFAULT_EMBEDDING_PROVIDER = "fastembed"
DEFAULT_MIN_CORRELATION_SAMPLE_SIZE = 5
DEFAULT_CLUSTER_RANDOM_SEED = 42
DEFAULT_PCA_DIMENSIONS = 64
DEFAULT_MIN_CLUSTER_SIZE = 8
DEFAULT_MIN_SAMPLES = 3
DEFAULT_CLUSTER_SELECTION_METHOD = "eom"


class AnalyticsPyprojectTable(BaseModel):
    """Validated ``[tool.codeclone.analytics]`` table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    db_path: str | None = None
    vectors_path: str | None = None
    embedding_model: str | None = None
    embedding_dimension: int | None = Field(default=None, gt=0)
    embedding_provider: Literal["fastembed"] | None = None
    embedding_cache_dir: str | None = None
    min_correlation_sample_size: int | None = Field(default=None, gt=0)
    cluster_random_seed: int | None = None
    default_pca_dimensions: int | None = Field(default=None, gt=0)
    default_min_cluster_size: int | None = Field(default=None, gt=0)
    default_min_samples: int | None = Field(default=None, gt=0)
    default_cluster_selection_method: Literal["eom", "leaf"] | None = None
    allow_model_download: bool | None = None


@dataclass(frozen=True, slots=True)
class AnalyticsConfig:
    db_path: Path
    vectors_path: Path
    audit_db_path: Path
    embedding_model: str
    embedding_dimension: int
    embedding_provider: str
    embedding_cache_dir: Path
    min_correlation_sample_size: int
    cluster_random_seed: int
    default_pca_dimensions: int
    default_min_cluster_size: int
    default_min_samples: int
    default_cluster_selection_method: str
    allow_model_download: bool


def _resolve_path(root_path: Path, raw: str | None, default_relative: str) -> Path:
    policy = RepoPathPolicy(allow_absolute=True)
    selected = raw if raw is not None else default_relative
    return resolve_under_repo_root(root_path, selected, policy=policy)


def resolve_analytics_config(root_path: Path) -> AnalyticsConfig:
    resolved_root = root_path.resolve()
    payload = load_pyproject_config(resolved_root)
    raw_table = payload.get(ANALYTICS_NESTED_TABLE_KEY)
    table = (
        AnalyticsPyprojectTable.model_validate(raw_table)
        if isinstance(raw_table, dict)
        else None
    )
    # The FastEmbed model artifact is a multi-hundred-MB download; analytics
    # vectors are kept separate (own LanceDB sidecar + embedding_generation_id),
    # but the model weights are shared with Engineering Memory rather than
    # re-downloaded into a second cache. Default the model cache + download
    # policy to the resolved memory semantic config (single source of truth).
    memory_semantic = resolve_memory_config(resolved_root).semantic
    return AnalyticsConfig(
        db_path=_resolve_path(
            resolved_root,
            table.db_path if table is not None else None,
            DEFAULT_ANALYTICS_DB_RELATIVE,
        ),
        vectors_path=_resolve_path(
            resolved_root,
            table.vectors_path if table is not None else None,
            DEFAULT_ANALYTICS_VECTORS_RELATIVE,
        ),
        audit_db_path=_resolve_path(
            resolved_root,
            (
                str(payload["audit_path"])
                if payload.get("audit_path") is not None
                else None
            ),
            DEFAULT_AUDIT_PATH,
        ),
        embedding_model=(
            table.embedding_model
            if table is not None and table.embedding_model is not None
            else DEFAULT_EMBEDDING_MODEL
        ),
        embedding_dimension=(
            table.embedding_dimension
            if table is not None and table.embedding_dimension is not None
            else DEFAULT_EMBEDDING_DIMENSION
        ),
        embedding_provider=(
            table.embedding_provider
            if table is not None and table.embedding_provider is not None
            else DEFAULT_EMBEDDING_PROVIDER
        ),
        embedding_cache_dir=_resolve_path(
            resolved_root,
            table.embedding_cache_dir if table is not None else None,
            memory_semantic.embedding_cache_dir,
        ),
        min_correlation_sample_size=(
            table.min_correlation_sample_size
            if table is not None and table.min_correlation_sample_size is not None
            else DEFAULT_MIN_CORRELATION_SAMPLE_SIZE
        ),
        cluster_random_seed=(
            table.cluster_random_seed
            if table is not None and table.cluster_random_seed is not None
            else DEFAULT_CLUSTER_RANDOM_SEED
        ),
        default_pca_dimensions=(
            table.default_pca_dimensions
            if table is not None and table.default_pca_dimensions is not None
            else DEFAULT_PCA_DIMENSIONS
        ),
        default_min_cluster_size=(
            table.default_min_cluster_size
            if table is not None and table.default_min_cluster_size is not None
            else DEFAULT_MIN_CLUSTER_SIZE
        ),
        default_min_samples=(
            table.default_min_samples
            if table is not None and table.default_min_samples is not None
            else DEFAULT_MIN_SAMPLES
        ),
        default_cluster_selection_method=(
            table.default_cluster_selection_method
            if table is not None and table.default_cluster_selection_method is not None
            else DEFAULT_CLUSTER_SELECTION_METHOD
        ),
        allow_model_download=(
            table.allow_model_download
            if table is not None and table.allow_model_download is not None
            else memory_semantic.allow_model_download
        ),
    )


__all__ = [
    "DEFAULT_ANALYTICS_DB_RELATIVE",
    "DEFAULT_ANALYTICS_VECTORS_RELATIVE",
    "DEFAULT_MIN_CORRELATION_SAMPLE_SIZE",
    "AnalyticsConfig",
    "AnalyticsPyprojectTable",
    "resolve_analytics_config",
]
