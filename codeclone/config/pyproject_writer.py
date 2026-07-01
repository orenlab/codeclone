# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Round-trip pyproject.toml writer for ``[tool.codeclone]`` merges."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ..utils.atomic_write import validate_atomic_target, write_text_atomically
from .analytics_specs import ANALYTICS_NESTED_TABLE_KEY
from .memory_specs import MEMORY_NESTED_TABLE_KEY
from .pyproject_loader import (
    ConfigValidationError,
    load_pyproject_config,
    normalize_path_config_value,
    open_repo_config,
    validate_config_value,
)
from .spec import CONFIG_KEY_SPECS

if TYPE_CHECKING:
    from collections.abc import Mapping

    from tomlkit.items import Table as TomlTable
    from tomlkit.toml_document import TOMLDocument
else:
    TOMLDocument = object
    TomlTable = object


class PyprojectWriterError(ValueError):
    """Raised when a pyproject merge or write cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class PyprojectWriteResult:
    config_path: Path
    changed_keys: tuple[str, ...]
    created_section: bool
    dry_run: bool
    preview_text: str | None = None


def read_pyproject_document(root_path: Path) -> TOMLDocument:
    """Parse ``pyproject.toml`` with tomlkit, preserving comments and layout."""

    config_path = root_path / "pyproject.toml"
    if not config_path.is_file():
        raise PyprojectWriterError(f"pyproject.toml not found under {root_path}")

    tomlkit = _load_tomlkit()
    with open_repo_config(root_path) as handle:
        text = handle.read().decode("utf-8")
    return cast(TOMLDocument, tomlkit.parse(text))


def validate_tool_codeclone_updates(
    *,
    root_path: Path,
    updates: Mapping[str, object],
) -> dict[str, object]:
    """Validate top-level ``tool.codeclone`` keys using the loader contract."""

    if not updates:
        return {}

    nested_keys = {MEMORY_NESTED_TABLE_KEY, ANALYTICS_NESTED_TABLE_KEY}
    nested_requested = sorted(set(updates.keys()) & nested_keys)
    if nested_requested:
        joined = ", ".join(nested_requested)
        raise PyprojectWriterError(
            "Nested tool.codeclone tables are not supported by the writer yet: "
            f"{joined}"
        )

    unknown = sorted(set(updates.keys()) - set(CONFIG_KEY_SPECS))
    if unknown:
        raise PyprojectWriterError(
            "Unknown key(s) in tool.codeclone merge: " + ", ".join(unknown)
        )

    validated: dict[str, object] = {}
    for key in sorted(updates.keys()):
        try:
            value = validate_config_value(key=key, value=updates[key])
        except ConfigValidationError as exc:
            raise PyprojectWriterError(str(exc)) from exc
        validated[key] = normalize_path_config_value(
            key=key,
            value=value,
            root_path=root_path,
        )
    return validated


def apply_tool_codeclone_updates(
    document: TOMLDocument,
    validated_updates: Mapping[str, object],
) -> tuple[str, ...]:
    """Apply validated updates to an in-memory tomlkit document."""

    if not validated_updates:
        return ()

    codeclone_table, _ = _ensure_tool_codeclone_table(document)
    changed: list[str] = []
    for key in sorted(validated_updates.keys()):
        new_value = validated_updates[key]
        if codeclone_table.get(key) == new_value:
            continue
        codeclone_table[key] = new_value
        changed.append(key)
    return tuple(changed)


def serialize_pyproject_document(document: TOMLDocument) -> str:
    """Serialize a tomlkit document with a trailing newline."""

    tomlkit = _load_tomlkit()
    text = str(tomlkit.dumps(document))
    if not text.endswith("\n"):
        text += "\n"
    return text


def write_pyproject_text_atomically(config_path: Path, text: str) -> None:
    """Write pyproject text via temp file + ``os.replace``."""

    try:
        write_text_atomically(config_path, text)
    except OSError as exc:
        raise PyprojectWriterError(str(exc)) from exc


def merge_tool_codeclone(
    root_path: Path,
    updates: Mapping[str, object],
    *,
    dry_run: bool = False,
) -> PyprojectWriteResult:
    """Merge validated ``tool.codeclone`` keys and optionally write the file."""

    config_path = root_path / "pyproject.toml"
    validated = validate_tool_codeclone_updates(root_path=root_path, updates=updates)
    if not validated:
        return PyprojectWriteResult(
            config_path=config_path,
            changed_keys=(),
            created_section=False,
            dry_run=dry_run,
        )

    current = load_pyproject_config(root_path)
    pending = {
        key: value for key, value in validated.items() if current.get(key) != value
    }
    if not pending:
        return PyprojectWriteResult(
            config_path=config_path,
            changed_keys=(),
            created_section=False,
            dry_run=dry_run,
        )

    document = read_pyproject_document(root_path)
    _, created_section = _ensure_tool_codeclone_table(document)
    changed_keys = apply_tool_codeclone_updates(document, pending)
    if not changed_keys:
        return PyprojectWriteResult(
            config_path=config_path,
            changed_keys=(),
            created_section=False,
            dry_run=dry_run,
        )

    preview_text = serialize_pyproject_document(document)
    if dry_run:
        return PyprojectWriteResult(
            config_path=config_path,
            changed_keys=changed_keys,
            created_section=created_section,
            dry_run=True,
            preview_text=preview_text,
        )

    write_pyproject_text_atomically(config_path, preview_text)
    try:
        load_pyproject_config(root_path)
    except ConfigValidationError as exc:
        raise PyprojectWriterError(
            "Written pyproject.toml failed validation after merge"
        ) from exc

    return PyprojectWriteResult(
        config_path=config_path,
        changed_keys=changed_keys,
        created_section=created_section,
        dry_run=False,
    )


def _ensure_tool_codeclone_table(document: TOMLDocument) -> tuple[TomlTable, bool]:
    tomlkit = _load_tomlkit()
    created = False

    tool_raw = document.get("tool")
    if tool_raw is None:
        tool = tomlkit.table()
        document["tool"] = tool
        created = True
    elif not isinstance(tool_raw, tomlkit.items.Table):
        raise PyprojectWriterError("Invalid pyproject.toml: 'tool' must be a table")
    else:
        tool = tool_raw

    codeclone_raw = tool.get("codeclone")
    if codeclone_raw is None:
        codeclone = tomlkit.table()
        tool["codeclone"] = codeclone
        created = True
    elif not isinstance(codeclone_raw, tomlkit.items.Table):
        raise PyprojectWriterError(
            "Invalid pyproject.toml: 'tool.codeclone' must be a table"
        )
    else:
        codeclone = codeclone_raw

    return cast(TomlTable, codeclone), created


def _load_tomlkit() -> Any:  # Any: lazy tomlkit import boundary
    try:
        import tomlkit as tomlkit_module
    except ImportError as exc:
        raise PyprojectWriterError(
            "tomlkit is required for pyproject writes; install codeclone dependencies."
        ) from exc
    return tomlkit_module


def _validate_atomic_target(path: Path) -> None:
    try:
        validate_atomic_target(path)
    except OSError as exc:
        raise PyprojectWriterError(str(exc)) from exc


__all__ = [
    "PyprojectWriteResult",
    "PyprojectWriterError",
    "apply_tool_codeclone_updates",
    "merge_tool_codeclone",
    "read_pyproject_document",
    "serialize_pyproject_document",
    "validate_tool_codeclone_updates",
    "write_pyproject_text_atomically",
]
