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


def run_id_must_be_quoted(
    tool: str,
    corrections: tuple[tuple[str, str], ...],
    rejection: str,
) -> str:
    """Refusal for a run id the caller serialized as a JSON number.

    The correction is rendered as a JSON object member carrying the caller's
    own digits, so the instruction can be followed by pasting it rather than
    by interpreting it. The rejection that prompted it is carried through
    verbatim: quoting the id is enough only when the encoding was the sole
    fault, and this message must not hide a second one.
    """

    names = ", ".join(name for name, _ in corrections)
    rendered = ", ".join(f'"{name}": "{digits}"' for name, digits in corrections)
    pronoun = "them" if len(corrections) > 1 else "it"
    return (
        f"run id is a string; quote it. {tool} received {names} as a JSON "
        f"number. Resend {pronoun} quoted: {rendered}. Run ids are hex "
        "digests, so an all-digit id is still a string. A JSON number also "
        "drops a leading zero, so restore it if the id began with 0. The id "
        "is unchanged; this is a caller encoding fix, not a different run."
        f"\n\nSchema rejection as received: {rejection}"
    )
