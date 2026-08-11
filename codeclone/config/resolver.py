# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import codeclone.models as domain_models

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def normalize_source_roots(source_roots: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize explicit roots to stable repository-relative POSIX paths."""

    if not source_roots:
        return (".",)
    normalized: set[str] = set()
    for raw_root in source_roots:
        if not raw_root or "\\" in raw_root:
            raise ValueError("source_roots must contain repo-relative POSIX paths")
        path = PurePosixPath(raw_root)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("source_roots must contain repo-relative POSIX paths")
        normalized.add(path.as_posix())
    return tuple(
        sorted(
            normalized,
            key=lambda value: (
                -len(PurePosixPath(value).parts) if value != "." else 0,
                value,
            ),
        )
    )


def detect_source_roots(root_path: Path) -> tuple[str, ...]:
    """Select an unambiguous conventional src layout, otherwise repository root."""

    src_path = root_path / "src"
    if (
        src_path.is_dir()
        and not src_path.is_symlink()
        and not (src_path / "__init__.py").exists()
        and any(path.is_file() for path in src_path.rglob("*.py"))
    ):
        return ("src",)
    return (".",)


def collect_explicit_cli_dests(
    parser: argparse.ArgumentParser,
    *,
    argv: Sequence[str],
) -> set[str]:
    """Return the option dests the user actually supplied on the command line.

    Ask argparse, never the raw tokens. ``allow_abbrev`` defaults to ``True``,
    so ``--min-l 5`` is a flag argparse accepts and expands; comparing tokens
    against full option names cannot see it, and the value the user passed was
    then silently overwritten by ``pyproject.toml``. Re-parsing with every
    default suppressed leaves exactly the supplied options in the namespace --
    the documented argparse way to tell "absent" from "given".

    Call this only for an ``argv`` the parser already accepted: the probe runs
    the same actions again, so ``--help``/``--version`` would fire twice.
    """

    saved_action_defaults = [(action, action.default) for action in parser._actions]
    saved_parser_defaults = dict(parser._defaults)
    try:
        for action in parser._actions:
            action.default = argparse.SUPPRESS
        parser._defaults.clear()
        namespace, _unrecognized = parser.parse_known_args(list(argv))
    finally:
        for action, default in saved_action_defaults:
            action.default = default
        parser._defaults.clear()
        parser._defaults.update(saved_parser_defaults)

    # Positionals were never part of this set: a positional cannot be
    # "not passed" in a way pyproject would override.
    optional_dests = {
        action.dest for action in parser._actions if action.option_strings
    }
    return {dest for dest in vars(namespace) if dest in optional_dests}


def resolve_config(
    *,
    args: argparse.Namespace,
    config_values: Mapping[str, object],
    explicit_cli_dests: set[str],
    root_path: Path | None = None,
) -> domain_models.ResolvedConfig:
    resolved_values = vars(args).copy()
    for key, value in config_values.items():
        if key in explicit_cli_dests:
            continue
        resolved_values[key] = value

    raw_source_roots = resolved_values.get("source_roots")
    if raw_source_roots is None:
        if root_path is not None:
            resolved_values["source_roots"] = detect_source_roots(root_path)
    elif isinstance(raw_source_roots, tuple) and all(
        isinstance(value, str) for value in raw_source_roots
    ):
        resolved_values["source_roots"] = normalize_source_roots(raw_source_roots)
    else:
        raise ValueError("source_roots must be tuple[str, ...] | None")

    return domain_models.ResolvedConfig(
        values=resolved_values,
        explicit_cli_dests=frozenset(explicit_cli_dests),
        pyproject_values=dict(config_values),
    )


def apply_resolved_config(
    *,
    args: argparse.Namespace,
    resolved: domain_models.ResolvedConfig,
) -> None:
    for key, value in resolved.values.items():
        setattr(args, key, value)


def apply_pyproject_config_overrides(
    *,
    args: argparse.Namespace,
    config_values: Mapping[str, object],
    explicit_cli_dests: set[str],
    root_path: Path | None = None,
) -> None:
    apply_resolved_config(
        args=args,
        resolved=resolve_config(
            args=args,
            config_values=config_values,
            explicit_cli_dests=explicit_cli_dests,
            root_path=root_path,
        ),
    )


__all__ = [
    "apply_pyproject_config_overrides",
    "apply_resolved_config",
    "collect_explicit_cli_dests",
    "detect_source_roots",
    "normalize_source_roots",
    "resolve_config",
]
