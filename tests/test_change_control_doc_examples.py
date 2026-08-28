# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Published change-control scope examples must survive the finish check.

``start_controlled_change`` validates scope entries only for absolute roots
and ``..`` traversal, so a directory (``"tests/"``) or a glob (``"pkg/**"``)
is accepted silently and the intent goes ``active`` with
``edit_allowed: true``. The finish scope check then matches changed files
against ``allowed_files`` by exact string membership, so the very files such
an entry was written to cover land in ``unexpected_files`` and the patch is
reported ``violated`` / ``scope_violation``.

Measured on the example this guard was written for: the Codex integration
page published ``{"allowed_files": ["src/module.py", "tests/"]}``. Starting
with that scope verbatim and editing a file under ``tests/`` returned
``status: "violated"``, ``reason: "scope_violation"``, with
``unexpected_files: ["tests/test_module.py"]`` and the directory entry
sitting in ``untouched_in_declared``.

The verdict is re-derived by executing the real ``_intent_check_result``
rather than by restating a path grammar here. That matters twice: the guard
dies if the checker is neutered, and it stays correct under a future ruling
that teaches the checker directory or glob forms — at which point such an
example may return to the page and this test still passes. Which grammar
``allowed_files`` should speak is not settled here; that ``start`` accepts a
form ``finish`` cannot honour is what this pin holds.

Scope of the scan, deliberately bounded: every page under ``docs/``, because
a scope example is a public-surface claim wherever it appears. The skill and
hook copies under ``plugins/`` state the scope fields in prose without
publishing a path list, so they carry no example this matcher could read.

This module lives apart from the other docs-vs-code guards on purpose: it
imports the change-control surface (ring r4), and a test module's ring is
the highest ring it imports, so folding it into a ring-r2 docs test would
retroactively make that module's existing r2 imports boundary violations.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final, cast

import pytest

from codeclone.surfaces.mcp._intent import (
    IntentRecord,
    IntentStatus,
    normalize_intent_scope,
)
from codeclone.surfaces.mcp._session_intent_mixin import _MCPSessionIntentMixin

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_DOCS_ROOT: Final = _REPO_ROOT / "docs"

pytestmark = pytest.mark.skipif(
    not _DOCS_ROOT.is_dir(), reason="repo docs source tree is not present"
)

_ALLOWED_FILES_BLOCK_RE: Final = re.compile(r"allowed_files\"?\s*:\s*\[([^\]]*)\]")
_QUOTED_ENTRY_RE: Final = re.compile(r"\"([^\"]*)\"")
_GLOB_METACHARACTERS: Final = "*?["
# Placeholders, not paths: a page writing `[...]` is naming the field, not
# publishing an entry a reader would copy.
_NON_ENTRIES: Final[frozenset[str]] = frozenset({"", "..."})


def _documented_allowed_files_entries() -> list[tuple[str, int, str]]:
    """Every concrete ``allowed_files`` entry published under ``docs/``."""

    found: list[tuple[str, int, str]] = []
    for doc in sorted(_DOCS_ROOT.rglob("*.md")):
        relative = doc.relative_to(_REPO_ROOT).as_posix()
        for number, line in enumerate(
            doc.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for block in _ALLOWED_FILES_BLOCK_RE.findall(line):
                found.extend(
                    (relative, number, entry)
                    for entry in _QUOTED_ENTRY_RE.findall(block)
                    if entry.strip() not in _NON_ENTRIES
                )
    return found


def _scope_check_honours(*, declared: str, changed: str) -> bool:
    """Run the real finish scope check over a one-entry declared scope."""

    record = IntentRecord(
        intent_id="intent-doc-example",
        run_id="0" * 8,
        root=_REPO_ROOT,
        report_digest="0" * 64,
        status=IntentStatus.ACTIVE,
        declared_at_utc="2026-01-01T00:00:00Z",
        scope=normalize_intent_scope({"allowed_files": [declared]}),
        intent_description="doc example",
        expected_effects=(),
        guards=(),
    )
    result = _MCPSessionIntentMixin._intent_check_result(
        cast(Any, None),
        intent=record,
        actual=(changed,),
    )
    return result.status is not IntentStatus.VIOLATED


def _probe_path_for(entry: str) -> str:
    """The changed file an entry is written to cover.

    A concrete file path probes itself. An entry written to cover children —
    a trailing slash, or a glob metacharacter — is probed with a child path,
    because covering children is the only thing such an entry can mean.
    """

    declared = normalize_intent_scope({"allowed_files": [entry]}).allowed_files[0]
    covers_children = entry.rstrip().endswith("/") or any(
        char in entry for char in _GLOB_METACHARACTERS
    )
    return f"{declared}/probe_module.py" if covers_children else declared


def test_documented_scope_examples_survive_the_finish_scope_check() -> None:
    entries = _documented_allowed_files_entries()
    assert entries, "no documented allowed_files examples found to check"

    violations: list[str] = []
    for relative, number, entry in entries:
        try:
            changed = _probe_path_for(entry)
        except ValueError as exc:
            violations.append(
                f"{relative}:{number} publishes {entry!r}, which start rejects: {exc}"
            )
            continue
        declared = normalize_intent_scope({"allowed_files": [entry]}).allowed_files[0]
        if not _scope_check_honours(declared=declared, changed=changed):
            violations.append(
                f"{relative}:{number} publishes {entry!r}; a patch touching "
                f"{changed!r} is reported out of scope by the finish check"
            )

    assert not violations, (
        "docs publish allowed_files forms the finish scope check cannot honour:\n"
        + "\n".join(violations)
    )
