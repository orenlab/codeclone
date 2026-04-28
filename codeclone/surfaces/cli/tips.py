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
from typing import TextIO

from ... import ui_messages as ui
from ...utils.json_io import read_json_object, write_json_document_atomically
from .attrs import bool_attr
from .types import PrinterLike

_VSCODE_EXTENSION_TIP_KEY = "vscode_extension"
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
    if bool_attr(args, "quiet") or bool_attr(args, "ci"):
        return False
    if _is_ci_environment(effective_environ):
        return False
    if not _stream_is_tty(effective_stream):
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


__all__ = [
    "maybe_print_vscode_extension_tip",
]
