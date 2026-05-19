# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple, TextIO

from packaging.version import InvalidVersion, Version

from ... import ui_messages as ui
from ...utils.json_io import read_json_object, write_json_document_atomically
from .attrs import bool_attr
from .types import PrinterLike

_VSCODE_EXTENSION_TIP_KEY = "vscode_extension"
_DEAD_CODE_REACHABILITY_2_0_1_MIGRATION_TIP_KEY = (
    "dead_code_reachability_2_0_1_migration_shown"
)
_DEAD_CODE_REACHABILITY_2_0_2_MIGRATION_TIP_KEY = (
    "dead_code_reachability_2_0_2_migration_shown"
)
_TIPS_SCHEMA_VERSION = 1
_VSCODE_EXTENSION_URL = (
    "https://marketplace.visualstudio.com/items?itemName=orenlab.codeclone"
)
_CI_ENV_KEYS: tuple[str, ...] = (
    "CI",
    "GITHUB_ACTIONS",
    "BUILDKITE",
    "TF_BUILD",
    "TEAMCITY_VERSION",
)
_VSCODE_ENV_KEYS: tuple[str, ...] = (
    "VSCODE_PID",
    "VSCODE_IPC_HOOK",
    "VSCODE_CWD",
)


class _DeadCodeReachabilityMigration(NamedTuple):
    tip_key: str
    baseline_min: Version
    baseline_max: Version
    current_min: Version
    target_version: str


_DEAD_CODE_REACHABILITY_MIGRATIONS: tuple[
    _DeadCodeReachabilityMigration,
    ...,
] = (
    _DeadCodeReachabilityMigration(
        tip_key=_DEAD_CODE_REACHABILITY_2_0_2_MIGRATION_TIP_KEY,
        baseline_min=Version("2.0.1"),
        baseline_max=Version("2.0.1"),
        current_min=Version("2.0.2"),
        target_version="2.0.2",
    ),
    _DeadCodeReachabilityMigration(
        tip_key=_DEAD_CODE_REACHABILITY_2_0_1_MIGRATION_TIP_KEY,
        baseline_min=Version("2.0.0b1"),
        baseline_max=Version("2.0.0"),
        current_min=Version("2.0.1"),
        target_version="2.0.1",
    ),
)


def _tips_state_path(cache_path: Path) -> Path:
    return cache_path.parent / "tips.json"


def _is_vscode_environment(environ: Mapping[str, str]) -> bool:
    if environ.get("TERM_PROGRAM", "").strip().lower() == "vscode":
        return True
    return any(key in environ for key in _VSCODE_ENV_KEYS)


def _is_ci_environment(environ: Mapping[str, str]) -> bool:
    return any(environ.get(key, "").strip() for key in _CI_ENV_KEYS)


def _stream_is_tty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except OSError:
        return False


def _empty_tips_state() -> dict[str, object]:
    return {
        "schema_version": _TIPS_SCHEMA_VERSION,
        "tips": {},
    }


def _load_tips_state(path: Path) -> dict[str, object]:
    try:
        payload = read_json_object(path)
    except (OSError, TypeError, ValueError):
        return _empty_tips_state()
    tips = payload.get("tips")
    if not isinstance(tips, dict):
        return _empty_tips_state()
    return {
        "schema_version": _TIPS_SCHEMA_VERSION,
        "tips": dict(tips),
    }


def _tip_last_shown_version(state: Mapping[str, object], *, tip_key: str) -> str:
    tips = state.get("tips")
    if not isinstance(tips, dict):
        return ""
    entry = tips.get(tip_key)
    if not isinstance(entry, dict):
        return ""
    last_shown_version = entry.get("last_shown_version")
    if isinstance(last_shown_version, str):
        return last_shown_version
    return ""


def _tip_was_shown(state: Mapping[str, object], *, tip_key: str) -> bool:
    tips = state.get("tips")
    if not isinstance(tips, dict):
        return False
    entry = tips.get(tip_key)
    if not isinstance(entry, dict):
        return False
    return entry.get("shown") is True


def _remember_tip_version(
    *,
    path: Path,
    state: Mapping[str, object],
    tip_key: str,
    codeclone_version: str,
) -> None:
    tips = state.get("tips")
    updated_tips = dict(tips) if isinstance(tips, dict) else {}
    updated_tips[tip_key] = {"last_shown_version": codeclone_version}
    write_json_document_atomically(
        path,
        {
            "schema_version": _TIPS_SCHEMA_VERSION,
            "tips": updated_tips,
        },
        sort_keys=True,
        indent=True,
        trailing_newline=True,
    )


def _remember_tip_shown(
    *,
    path: Path,
    state: Mapping[str, object],
    tip_key: str,
) -> None:
    tips = state.get("tips")
    updated_tips = dict(tips) if isinstance(tips, dict) else {}
    updated_tips[tip_key] = {"shown": True}
    write_json_document_atomically(
        path,
        {
            "schema_version": _TIPS_SCHEMA_VERSION,
            "tips": updated_tips,
        },
        sort_keys=True,
        indent=True,
        trailing_newline=True,
    )


def _tip_context_allowed(
    *,
    args: object,
    environ: Mapping[str, str],
    stream: TextIO,
) -> bool:
    if bool_attr(args, "quiet") or bool_attr(args, "ci"):
        return False
    if _is_ci_environment(environ):
        return False
    return _stream_is_tty(stream)


def _dead_code_reachability_migration(
    *,
    baseline_generator_version: str | None,
    codeclone_version: str,
) -> _DeadCodeReachabilityMigration | None:
    if not baseline_generator_version:
        return None
    try:
        baseline_version = Version(baseline_generator_version)
        current_version = Version(codeclone_version)
    except InvalidVersion:
        return None
    for migration in _DEAD_CODE_REACHABILITY_MIGRATIONS:
        if (
            migration.baseline_min <= baseline_version <= migration.baseline_max
            and current_version >= migration.current_min
        ):
            return migration
    return None


def maybe_print_vscode_extension_tip(
    *,
    args: object,
    console: PrinterLike,
    codeclone_version: str,
    cache_path: Path,
    environ: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
) -> bool:
    effective_environ = os.environ if environ is None else environ
    effective_stream = sys.stdout if stream is None else stream
    if not _tip_context_allowed(
        args=args,
        environ=effective_environ,
        stream=effective_stream,
    ):
        return False
    if not _is_vscode_environment(effective_environ):
        return False

    state_path = _tips_state_path(cache_path)
    state = _load_tips_state(state_path)
    if (
        _tip_last_shown_version(state, tip_key=_VSCODE_EXTENSION_TIP_KEY)
        == codeclone_version
    ):
        return False

    console.print(ui.fmt_vscode_extension_tip(url=_VSCODE_EXTENSION_URL))
    try:
        _remember_tip_version(
            path=state_path,
            state=state,
            tip_key=_VSCODE_EXTENSION_TIP_KEY,
            codeclone_version=codeclone_version,
        )
    except OSError:
        return True
    return True


def maybe_print_dead_code_reachability_migration_note(
    *,
    args: object,
    console: PrinterLike,
    codeclone_version: str,
    cache_path: Path,
    baseline_generator_version: str | None,
    baseline_trusted_for_diff: bool,
    environ: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
) -> bool:
    if not baseline_trusted_for_diff:
        return False
    migration = _dead_code_reachability_migration(
        baseline_generator_version=baseline_generator_version,
        codeclone_version=codeclone_version,
    )
    if migration is None:
        return False

    effective_environ = os.environ if environ is None else environ
    effective_stream = sys.stdout if stream is None else stream
    if not _tip_context_allowed(
        args=args,
        environ=effective_environ,
        stream=effective_stream,
    ):
        return False

    state_path = _tips_state_path(cache_path)
    state = _load_tips_state(state_path)
    if _tip_was_shown(
        state,
        tip_key=migration.tip_key,
    ):
        return False

    console.print(
        ui.fmt_dead_code_reachability_migration_note(
            target_version=migration.target_version,
        )
    )
    try:
        _remember_tip_shown(
            path=state_path,
            state=state,
            tip_key=migration.tip_key,
        )
    except OSError:
        return True
    return True


__all__ = [
    "maybe_print_dead_code_reachability_migration_note",
    "maybe_print_vscode_extension_tip",
]
