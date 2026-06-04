# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from ..findings.clones.golden_fixtures import (
    GoldenFixturePatternError,
    normalize_golden_fixture_patterns,
)
from .memory_specs import (
    MEMORY_CONFIG_KEY_SPECS,
    MEMORY_NESTED_TABLE_KEY,
    MEMORY_PATH_CONFIG_KEYS,
    SEMANTIC_NESTED_TABLE_KEY,
)
from .spec import CONFIG_KEY_SPECS, PATH_CONFIG_KEYS, ConfigKeySpec

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Set


class ConfigValidationError(ValueError):
    """Raised when pyproject.toml contains invalid CodeClone configuration."""


def validate_config_value(
    *,
    key: str,
    value: object,
    config_key_specs: Mapping[str, ConfigKeySpec] = CONFIG_KEY_SPECS,
) -> object:
    spec = config_key_specs[key]
    if value is None:
        if spec.allow_none:
            return None
        raise ConfigValidationError(
            "Invalid value type for tool.codeclone."
            f"{key}: expected {spec.expected_name or spec.expected_type.__name__}"
        )

    expected_type = spec.expected_type
    if expected_type is bool:
        return _validated_config_instance(
            key=key,
            value=value,
            expected_type=bool,
            expected_name="bool",
        )

    if expected_type is int:
        return _validated_config_instance(
            key=key,
            value=value,
            expected_type=int,
            expected_name="int",
            reject_bool=True,
        )

    if expected_type is str:
        return _validated_config_instance(
            key=key,
            value=value,
            expected_type=str,
            expected_name="str",
        )

    if expected_type is list:
        return _validated_string_list(key=key, value=value)

    raise ConfigValidationError(f"Unsupported config key spec for tool.codeclone.{key}")


def load_pyproject_config(
    root_path: Path,
    *,
    load_toml: Callable[[Path], object] | None = None,
    config_key_specs: Mapping[str, ConfigKeySpec] = CONFIG_KEY_SPECS,
    path_config_keys: Set[str] | frozenset[str] = PATH_CONFIG_KEYS,
) -> dict[str, object]:
    config_path = root_path / "pyproject.toml"
    if not config_path.exists():
        if config_path.is_symlink():
            raise ConfigValidationError("pyproject.toml must not be a symlink.")
        return {}

    load_toml_fn = _load_toml if load_toml is None else load_toml

    payload: object
    try:
        payload = load_toml_fn(config_path)
    except ConfigValidationError:
        raise
    except OSError as exc:
        raise ConfigValidationError(
            f"Cannot read pyproject.toml at {config_path}: {exc}"
        ) from exc
    except ValueError as exc:
        raise ConfigValidationError(f"Invalid TOML in {config_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ConfigValidationError(
            f"Invalid pyproject payload at {config_path}: root must be object"
        )

    tool_obj = payload.get("tool")
    if tool_obj is None:
        return {}
    if not isinstance(tool_obj, dict):
        raise ConfigValidationError(
            f"Invalid pyproject payload at {config_path}: 'tool' must be object"
        )

    codeclone_obj = tool_obj.get("codeclone")
    if codeclone_obj is None:
        return {}
    if not isinstance(codeclone_obj, dict):
        raise ConfigValidationError(
            "Invalid pyproject payload at "
            f"{config_path}: 'tool.codeclone' must be object"
        )

    unknown = sorted(
        set(codeclone_obj.keys()) - set(config_key_specs) - {MEMORY_NESTED_TABLE_KEY}
    )
    if unknown:
        raise ConfigValidationError(
            "Unknown key(s) in tool.codeclone: " + ", ".join(unknown)
        )

    validated: dict[str, object] = {}
    for key in sorted(codeclone_obj.keys()):
        if key == MEMORY_NESTED_TABLE_KEY:
            continue
        value = validate_config_value(
            key=key,
            value=codeclone_obj[key],
            config_key_specs=config_key_specs,
        )
        validated[key] = normalize_path_config_value(
            key=key,
            value=value,
            root_path=root_path,
            path_config_keys=path_config_keys,
        )

    memory_obj = codeclone_obj.get(MEMORY_NESTED_TABLE_KEY)
    if memory_obj is not None:
        validated[MEMORY_NESTED_TABLE_KEY] = _validate_nested_memory_table(
            memory_obj=memory_obj,
            root_path=root_path,
            config_path=config_path,
        )
    return validated


def _validate_nested_memory_table(
    *,
    memory_obj: object,
    root_path: Path,
    config_path: Path,
) -> dict[str, object]:
    if not isinstance(memory_obj, dict):
        raise ConfigValidationError(
            "Invalid pyproject payload at "
            f"{config_path}: 'tool.codeclone.memory' must be object"
        )
    unknown = sorted(
        set(memory_obj.keys())
        - set(MEMORY_CONFIG_KEY_SPECS)
        - {SEMANTIC_NESTED_TABLE_KEY}
    )
    if unknown:
        raise ConfigValidationError(
            "Unknown key(s) in tool.codeclone.memory: " + ", ".join(unknown)
        )
    validated: dict[str, object] = {}
    for key in sorted(memory_obj.keys()):
        if key == SEMANTIC_NESTED_TABLE_KEY:
            continue
        value = validate_config_value(
            key=key,
            value=memory_obj[key],
            config_key_specs=MEMORY_CONFIG_KEY_SPECS,
        )
        validated[key] = normalize_path_config_value(
            key=key,
            value=value,
            root_path=root_path,
            path_config_keys=MEMORY_PATH_CONFIG_KEYS,
        )
    semantic_obj = memory_obj.get(SEMANTIC_NESTED_TABLE_KEY)
    if semantic_obj is not None:
        validated[SEMANTIC_NESTED_TABLE_KEY] = _validate_nested_semantic_table(
            semantic_obj=semantic_obj,
            config_path=config_path,
        )
    return validated


def _validate_nested_semantic_table(
    *,
    semantic_obj: object,
    config_path: Path,
) -> dict[str, object]:
    # Structural boundary only: ensure it is a table. Field-level validation
    # (allowed keys, types, literals, ranges) is owned by the pydantic
    # SemanticConfig in resolve_memory_config — one validation authority.
    if not isinstance(semantic_obj, dict):
        raise ConfigValidationError(
            "Invalid pyproject payload at "
            f"{config_path}: 'tool.codeclone.memory.semantic' must be object"
        )
    return dict(semantic_obj)


def normalize_path_config_value(
    *,
    key: str,
    value: object,
    root_path: Path,
    path_config_keys: Set[str] | frozenset[str] = PATH_CONFIG_KEYS,
) -> object:
    if key not in path_config_keys:
        return value
    if not isinstance(value, str):
        return value

    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)
    return str(root_path / path)


def _validated_config_instance(
    *,
    key: str,
    value: object,
    expected_type: type[object],
    expected_name: str,
    reject_bool: bool = False,
) -> object:
    if isinstance(value, expected_type) and (
        not reject_bool or not isinstance(value, bool)
    ):
        return value
    raise ConfigValidationError(
        f"Invalid value type for tool.codeclone.{key}: expected {expected_name}"
    )


def _validated_string_list(*, key: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ConfigValidationError(
            f"Invalid value type for tool.codeclone.{key}: expected list[str]"
        )
    if not all(isinstance(item, str) for item in value):
        raise ConfigValidationError(
            f"Invalid value type for tool.codeclone.{key}: expected list[str]"
        )
    try:
        return normalize_golden_fixture_patterns(value)
    except GoldenFixturePatternError as exc:
        raise ConfigValidationError(str(exc)) from exc


def _load_toml(path: Path) -> object:
    if sys.version_info >= (3, 11):
        import tomllib

        with _open_toml_file_no_follow(path) as config_file:
            return tomllib.load(config_file)

    try:
        tomli_module = importlib.import_module("tomli")
    except ModuleNotFoundError as exc:
        raise ConfigValidationError(
            "Python 3.10 requires dependency 'tomli' to read pyproject.toml."
        ) from exc

    load_fn = getattr(tomli_module, "load", None)
    if not callable(load_fn):
        raise ConfigValidationError("Invalid 'tomli' module: missing callable 'load'.")

    with _open_toml_file_no_follow(path) as config_file:
        return load_fn(config_file)


def open_repo_config(root_path: Path) -> BinaryIO:
    """Open repo ``pyproject.toml`` through the security-hardened config path."""

    return _open_toml_file_no_follow(root_path / "pyproject.toml")


def _open_toml_file_no_follow(path: Path) -> BinaryIO:
    if path.is_symlink():
        raise ConfigValidationError("pyproject.toml must not be a symlink.")
    if getattr(sys, "platform", "") == "win32":
        return path.open("rb")
    flags = os.O_RDONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if isinstance(nofollow, int):
        flags |= nofollow
    fd = os.open(path, flags)
    return os.fdopen(fd, "rb")


__all__ = [
    "CONFIG_KEY_SPECS",
    "PATH_CONFIG_KEYS",
    "ConfigValidationError",
    "_load_toml",
    "load_pyproject_config",
    "normalize_path_config_value",
    "open_repo_config",
    "validate_config_value",
]
