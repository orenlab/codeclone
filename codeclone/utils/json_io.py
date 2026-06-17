# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import orjson

DEFAULT_MAX_JSON_BYTES = 64 * 1024 * 1024


class BoundedReadError(OSError):
    """Raised when a bounded file read exceeds the configured byte cap."""


def json_text(
    data: object,
    *,
    sort_keys: bool = False,
    indent: bool = False,
    trailing_newline: bool = False,
) -> str:
    options = 0
    if sort_keys:
        options |= orjson.OPT_SORT_KEYS
    if indent:
        options |= orjson.OPT_INDENT_2
    text = orjson.dumps(data, option=options).decode("utf-8")
    if trailing_newline:
        text += "\n"
    return text


def read_bounded_bytes(
    path: Path,
    *,
    max_bytes: int = DEFAULT_MAX_JSON_BYTES,
) -> bytes:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    with path.open("rb") as handle:
        payload = handle.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise BoundedReadError(
            f"File too large ({len(payload)} bytes, max {max_bytes}) at {path}"
        )
    return payload


def read_json_document(
    path: Path,
    *,
    max_bytes: int = DEFAULT_MAX_JSON_BYTES,
) -> object:
    return orjson.loads(read_bounded_bytes(path, max_bytes=max_bytes))


def read_json_object(
    path: Path,
    *,
    max_bytes: int = DEFAULT_MAX_JSON_BYTES,
) -> dict[str, object]:
    payload = read_json_document(path, max_bytes=max_bytes)
    if not isinstance(payload, dict):
        raise TypeError("JSON payload must be an object")
    return payload


def _validate_atomic_target(path: Path) -> None:
    if path.is_symlink():
        raise OSError(f"Refusing to replace symlink target: {path}")
    parent = path.parent
    if parent.exists() and parent.is_symlink():
        raise OSError(f"Refusing to write through symlink directory: {parent}")


def write_json_text_atomically(path: Path, text: str) -> None:
    _validate_atomic_target(path)
    fd_num, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd_num, "wb") as fd:
            fd.write(text.encode("utf-8"))
            fd.flush()
            os.fsync(fd.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def write_json_document_atomically(
    path: Path,
    document: object,
    *,
    sort_keys: bool = False,
    indent: bool = False,
    trailing_newline: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _validate_atomic_target(path)
    write_json_text_atomically(
        path,
        json_text(
            document,
            sort_keys=sort_keys,
            indent=indent,
            trailing_newline=trailing_newline,
        ),
    )


__all__ = [
    "DEFAULT_MAX_JSON_BYTES",
    "BoundedReadError",
    "json_text",
    "read_bounded_bytes",
    "read_json_document",
    "read_json_object",
    "write_json_document_atomically",
    "write_json_text_atomically",
]
