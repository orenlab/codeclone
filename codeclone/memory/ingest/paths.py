# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from ...config.memory import IngestConfig

CONTRACT_CONSTANTS_SUFFIX: str = "contracts/__init__.py"

DEFAULT_DOCUMENT_LINK_ROOT_FILES: tuple[str, ...] = (
    "README.md",
    "CONTRIBUTING.md",
    "AGENTS.md",
    "CLAUDE.md",
)

DOCS_REGISTRY_PREFIX: str = "docs/"


def _normalize_repo_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _existing_repo_file(root_path: Path, repo_relative: str) -> Path | None:
    normalized = _normalize_repo_path(repo_relative)
    if not normalized or ".." in normalized.split("/"):
        return None
    candidate = root_path / normalized
    if candidate.is_file():
        return candidate
    return None


def resolve_contract_constants_paths(
    *,
    root_path: Path,
    registry_paths: frozenset[str],
    ingest: IngestConfig,
) -> tuple[Path, ...]:
    configured = ingest.contract_constants_paths
    if configured:
        resolved = [
            path
            for item in configured
            if (path := _existing_repo_file(root_path, item)) is not None
        ]
        return tuple(sorted(resolved, key=lambda item: str(item)))

    discovered = sorted(
        {
            _normalize_repo_path(path)
            for path in registry_paths
            if path.endswith(CONTRACT_CONSTANTS_SUFFIX)
        }
    )
    return tuple(
        path
        for item in discovered
        if (path := _existing_repo_file(root_path, item)) is not None
    )


def resolve_document_link_paths(
    *,
    root_path: Path,
    registry_paths: frozenset[str],
    ingest: IngestConfig,
) -> tuple[Path, ...]:
    configured = ingest.document_link_paths
    if configured:
        candidates = configured
    else:
        registry_docs = sorted(
            path
            for path in registry_paths
            if path.startswith(DOCS_REGISTRY_PREFIX) and path.endswith(".md")
        )
        root_docs = [
            name
            for name in DEFAULT_DOCUMENT_LINK_ROOT_FILES
            if _existing_repo_file(root_path, name) is not None
        ]
        candidates = tuple(dict.fromkeys([*root_docs, *registry_docs]))

    resolved = [
        path
        for item in candidates
        if (path := _existing_repo_file(root_path, item)) is not None
    ]
    return tuple(dict.fromkeys(resolved))


def resolve_mcp_tool_schema_snapshot_path(
    *,
    root_path: Path,
    ingest: IngestConfig,
) -> Path | None:
    raw = ingest.mcp_tool_schema_snapshot_path
    if raw is None:
        return None
    return _existing_repo_file(root_path, raw)


def resolve_mcp_tool_contradiction_sources(
    *,
    root_path: Path,
    ingest: IngestConfig,
) -> tuple[Path, tuple[Path, ...]] | None:
    snapshot_raw = ingest.mcp_tool_schema_snapshot_path
    doc_paths = ingest.mcp_tool_count_doc_paths
    if snapshot_raw is None or not doc_paths:
        return None
    snapshot = _existing_repo_file(root_path, snapshot_raw)
    if snapshot is None:
        return None
    docs = tuple(
        path
        for item in doc_paths
        if (path := _existing_repo_file(root_path, item)) is not None
    )
    if not docs:
        return None
    return snapshot, docs


__all__ = [
    "CONTRACT_CONSTANTS_SUFFIX",
    "DEFAULT_DOCUMENT_LINK_ROOT_FILES",
    "DOCS_REGISTRY_PREFIX",
    "resolve_contract_constants_paths",
    "resolve_document_link_paths",
    "resolve_mcp_tool_contradiction_sources",
    "resolve_mcp_tool_schema_snapshot_path",
]
