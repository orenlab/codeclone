# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import tempfile
from json import JSONDecodeError
from pathlib import Path
from typing import Any

import orjson


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


def read_json_document(path: Path) -> object:
    try:
        return orjson.loads(path.read_text("utf-8"))
    except JSONDecodeError:
        return orjson.loads(path.read_bytes())


def read_json_object(path: Path) -> dict[str, Any]:
    payload = read_json_document(path)
    if not isinstance(payload, dict):
        raise TypeError("JSON payload must be an object")
    return payload


def write_json_text_atomically(path: Path, text: str) -> None:
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
    write_json_text_atomically(
        path,
        json_text(
            document,
            sort_keys=sort_keys,
            indent=indent,
            trailing_newline=trailing_newline,
        ),
    )
