# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..utils.repo_paths import (
    PathOutsideRepoError,
    RepoPathError,
    RepoPathPolicy,
    resolve_under_repo_root,
)
from .intent_registry_defaults import (
    DEFAULT_INTENT_REGISTRY_BACKEND,
    DEFAULT_INTENT_REGISTRY_DB_PATH,
    DEFAULT_INTENT_REGISTRY_RETENTION_DAYS,
    INTENT_REGISTRY_RETENTION_ENTERPRISE_MESSAGE,
    MAX_INTENT_REGISTRY_RETENTION_DAYS,
    MIN_INTENT_REGISTRY_RETENTION_DAYS,
    IntentRegistryBackend,
)
from .pyproject_loader import _load_toml

INTENT_REGISTRY_BACKENDS: Final[frozenset[str]] = frozenset({"file", "sqlite"})
_VALID_DB_SUFFIXES: Final[frozenset[str]] = frozenset({".sqlite3", ".db"})


class IntentRegistryConfigError(ValueError):
    """Raised for invalid workspace intent registry configuration."""


@dataclass(frozen=True, slots=True)
class IntentRegistryConfig:
    backend: IntentRegistryBackend
    storage_path: Path
    retention_days: int = DEFAULT_INTENT_REGISTRY_RETENTION_DAYS


def resolve_intent_registry_retention_days(
    value: object = None,
    *,
    env_value: object = None,
) -> int:
    raw = env_value if env_value is not None else value
    if raw is None:
        return DEFAULT_INTENT_REGISTRY_RETENTION_DAYS
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise IntentRegistryConfigError(
            "intent_registry_retention_days must be an integer"
        )
    if raw > MAX_INTENT_REGISTRY_RETENTION_DAYS:
        raise IntentRegistryConfigError(INTENT_REGISTRY_RETENTION_ENTERPRISE_MESSAGE)
    if raw < MIN_INTENT_REGISTRY_RETENTION_DAYS:
        raise IntentRegistryConfigError(
            "intent_registry_retention_days must be at least "
            f"{MIN_INTENT_REGISTRY_RETENTION_DAYS}"
        )
    return raw


def resolve_intent_registry_backend(
    value: object = None,
    *,
    env_value: object = None,
) -> IntentRegistryBackend:
    raw = env_value if env_value is not None else value
    if raw is None:
        return DEFAULT_INTENT_REGISTRY_BACKEND
    if not isinstance(raw, str):
        raise IntentRegistryConfigError("intent_registry_backend must be a string")
    backend = raw.strip().lower()
    if backend not in INTENT_REGISTRY_BACKENDS:
        expected = ", ".join(sorted(INTENT_REGISTRY_BACKENDS))
        raise IntentRegistryConfigError(
            f"intent_registry_backend must be one of: {expected}"
        )
    return backend  # type: ignore[return-value]


def resolve_intent_registry_db_path(*, root_path: Path, value: object) -> Path:
    if not isinstance(value, str):
        raise IntentRegistryConfigError("intent_registry_path must be a string")
    raw = value.strip()
    if not raw:
        raise IntentRegistryConfigError("intent_registry_path must not be empty")
    path = Path(raw)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise IntentRegistryConfigError(
            "intent_registry_path must not contain empty, '.', or '..' parts"
        )
    if path.suffix not in _VALID_DB_SUFFIXES:
        raise IntentRegistryConfigError(
            "intent_registry_path must end with .sqlite3 or .db"
        )
    try:
        return resolve_under_repo_root(
            root_path,
            path,
            policy=RepoPathPolicy(),
        )
    except PathOutsideRepoError as exc:
        raise IntentRegistryConfigError(
            "intent_registry_path must be relative to the repository root"
        ) from exc
    except RepoPathError as exc:
        raise IntentRegistryConfigError(f"invalid intent_registry_path: {exc}") from exc


def resolve_intent_registry_config(root: Path) -> IntentRegistryConfig:
    root_path = root.resolve()
    config_path = root_path / "pyproject.toml"
    config: dict[str, object] = {}
    if config_path.is_file():
        try:
            payload = _load_toml(config_path)
        except (OSError, ValueError):
            payload = {}
        if isinstance(payload, dict):
            tool = payload.get("tool")
            if isinstance(tool, dict):
                section = tool.get("codeclone")
                if isinstance(section, dict):
                    config = dict(section)
    backend = resolve_intent_registry_backend(
        config.get("intent_registry_backend"),
        env_value=os.environ.get("CODECLONE_INTENT_REGISTRY_BACKEND"),
    )
    retention_days = resolve_intent_registry_retention_days(
        config.get("intent_registry_retention_days"),
        env_value=os.environ.get("CODECLONE_INTENT_REGISTRY_RETENTION_DAYS"),
    )
    if backend == "file":
        return IntentRegistryConfig(
            backend="file",
            storage_path=root_path.joinpath(".codeclone", "intents"),
            retention_days=retention_days,
        )
    db_value = config.get("intent_registry_path", DEFAULT_INTENT_REGISTRY_DB_PATH)
    env_path = os.environ.get("CODECLONE_INTENT_REGISTRY_PATH")
    if env_path is not None:
        db_value = env_path
    db_path = resolve_intent_registry_db_path(root_path=root_path, value=db_value)
    return IntentRegistryConfig(
        backend="sqlite",
        storage_path=db_path,
        retention_days=retention_days,
    )


def intent_registry_summary(root: Path) -> dict[str, str]:
    config = resolve_intent_registry_config(root)
    try:
        display_path = config.storage_path.relative_to(root.resolve())
        storage = str(display_path)
    except ValueError:
        storage = str(config.storage_path)
    return {
        "registry_backend": config.backend,
        "registry_storage": storage,
        "registry_retention_days": str(config.retention_days),
    }


__all__ = [
    "DEFAULT_INTENT_REGISTRY_BACKEND",
    "DEFAULT_INTENT_REGISTRY_DB_PATH",
    "DEFAULT_INTENT_REGISTRY_RETENTION_DAYS",
    "INTENT_REGISTRY_BACKENDS",
    "INTENT_REGISTRY_RETENTION_ENTERPRISE_MESSAGE",
    "MAX_INTENT_REGISTRY_RETENTION_DAYS",
    "MIN_INTENT_REGISTRY_RETENTION_DAYS",
    "IntentRegistryBackend",
    "IntentRegistryConfig",
    "IntentRegistryConfigError",
    "intent_registry_summary",
    "resolve_intent_registry_backend",
    "resolve_intent_registry_config",
    "resolve_intent_registry_db_path",
    "resolve_intent_registry_retention_days",
]
