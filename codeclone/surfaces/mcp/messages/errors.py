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

INVALID_RELATIVE_PATH: Final = "Invalid path '{value}' relative to '{root}': {error}"

WITHDRAWN_TOOL_PARAMETER: Final = (
    "{tool} no longer accepts {parameter}. Managing the analysis cache is operator "
    "configuration, not a per-call policy: set cache_path and max_cache_size_mb "
    "under [tool.codeclone] in pyproject.toml, or run the CLI. Withdrawn in CodeClone "
    "2.1.0a2."
)


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


def stale_engine(
    operation: str,
    *,
    loaded: str,
    on_disk: str,
    package_root: str,
) -> str:
    """Refusal for a request this process cannot answer with the code on disk.

    Executable rather than descriptive: the only fix is a restarted server
    process, so the message says that instead of describing a digest mismatch
    and leaving the caller to infer it. Both generations are shown because the
    pair is the evidence -- a single digest cannot be checked by the reader.
    """

    return (
        f"STALE_ENGINE: {operation} was refused and did not execute. This "
        "server process is running CodeClone code that the disk no longer "
        "holds, so any answer it produced would describe a version of the "
        "engine that no longer exists.\n"
        f"  loaded by this process: {loaded}\n"
        f"  on disk now:            {on_disk}\n"
        f"  loaded package root:    {package_root}\n"
        "Restart the CodeClone MCP server process and resend the request. "
        "A long-lived server keeps the modules it imported at startup; only a "
        "new process picks up the current checkout."
    )


def engine_changed_during_operation(
    operation: str,
    *,
    at_entry: str,
    at_exit: str,
    package_root: str,
) -> str:
    """Refusal for a result produced across an engine change.

    The operation ran, so this is not a stale-engine refusal: part of the work
    was done by the code loaded at entry and part of it may have been done by
    modules imported after the checkout moved. The result exists and is
    withheld rather than published, because nothing can say which half of it
    came from which engine.
    """

    return (
        f"ENGINE_CHANGED_DURING_OPERATION: {operation} completed, but the "
        "CodeClone sources on disk changed while it was running, so its "
        "result is withheld instead of returned as a normal success.\n"
        f"  at operation entry: {at_entry}\n"
        f"  at operation exit:  {at_exit}\n"
        f"  loaded package root: {package_root}\n"
        "Restart the CodeClone MCP server process and resend the request. "
        "Modules imported late in an operation come from the tree as it is "
        "then, so a result spanning a change cannot be attributed to one "
        "engine."
    )
