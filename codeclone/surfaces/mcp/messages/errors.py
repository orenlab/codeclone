# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""MCP contract error messages."""

from __future__ import annotations

from collections.abc import Collection
from typing import Final

ROOT_REQUIRED_ABSOLUTE: Final = (
    "CodeClone MCP analyze_repository requires an absolute repository root."
)

PATH_TRAVERSAL: Final = "path traversal not allowed: {path}"

ROOT_RESOLVE_FAILED: Final = "Unable to resolve repository root '{root}': {error}"

ROOT_NOT_EXISTS: Final = "Repository root '{root}' does not exist."

ROOT_NOT_DIRECTORY: Final = "Repository root '{root}' is not a directory."

CACHE_POLICY_CLI_ONLY: Final = (
    "cache_policy='refresh' is CLI-only. MCP accepts: reuse, off."
)
INVALID_RELATIVE_PATH: Final = "Invalid path '{value}' relative to '{root}': {error}"


def invalid_choice(name: str, value: object, allowed: Collection[str]) -> str:
    allowed_list = ", ".join(sorted(allowed))
    return f"Invalid value for {name}: {value!r}. Expected one of: {allowed_list}."
