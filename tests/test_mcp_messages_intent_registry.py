# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""No message names a registry path the root did not configure.

The workspace intent registry has two backends, and where it lives is decided
by configuration -- ``[tool.codeclone] intent_registry_backend`` /
``intent_registry_path``, or their ``CODECLONE_INTENT_REGISTRY_*`` overrides.
The ``file`` backend keeps a directory under ``.codeclone/``; the ``sqlite``
backend keeps one database at ``intent_registry_path``.  Six MCP messages and
one AGENTS.md row used to name the file backend's directory unconditionally,
and two of them told the operator to remove a row from it by hand: on a
sqlite root that directory does not exist, so the advice pointed at nothing.

Two models, decided by what each site holds when its text is built:

* the server instructions, the tool description and the help topics are
  built once per server process, before any repository root is known, so
  they name the configuration keys and the call that reports the resolved
  values (``manage_change_intent(action='list_workspace')``) -- never a path;
* the two ``next_step`` refusals in ``messages/intent.py`` are built at call
  sites that hold the root, so they print the backend and storage path that
  root actually resolves to -- through the same ``intent_registry_summary``
  that ``list_workspace`` already reports, so the operator reads one spelling.

Closed world first: the literal is gone from every message module and from
AGENTS.md.  Then the positive side on both backends: the printed path is the
configured one, on roots configured unlike the library default and unlike
this repository.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from codeclone.surfaces.mcp._workspace_intent_store import (
    clear_workspace_intent_store_cache,
)
from codeclone.surfaces.mcp.messages import help_topics as help_msgs
from codeclone.surfaces.mcp.messages import instructions as instruction_msgs
from codeclone.surfaces.mcp.messages import intent as intent_msgs
from codeclone.surfaces.mcp.messages import tools as tool_msgs
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests.test_workspace_intent_admission_guard import (
    _declare,
    _seed_foreign_unreadable_row,
    _service_with_run,
)
from tests.test_workspace_intent_unreadable_records import (
    _newer_build_payload,
    _seed_raw_payload,
)
from tests.test_workspace_intents import _record

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MESSAGES_DIR = _REPO_ROOT / "codeclone" / "surfaces" / "mcp" / "messages"
_AGENTS_MD = _REPO_ROOT / "AGENTS.md"

#: The file backend's directory, in any spelling with or without a trailing
#: slash.  It is what ``resolve_intent_registry_config`` resolves for
#: ``backend == "file"`` and nothing a message may name on its own.
_FILE_BACKEND_DIRECTORY = re.compile(r"\.codeclone/intents")

#: The message modules the closed-world scan must reach.  A scan that found
#: fewer files than this would be looking at the wrong directory.
_MESSAGE_MODULES_NAMED_IN_THE_FINDING = frozenset(
    {"help_topics.py", "instructions.py", "intent.py", "tools.py"}
)

_CUSTOM_SQLITE_PATH = ".codeclone/db/custom-intents.db"
_UNREADABLE_INTENT_ID = "intent-newer-001"


# ── closed world: the literal is gone ───────────────────────────────────────


def _occurrences(path: Path) -> list[tuple[int, str]]:
    return [
        (number, line.rstrip())
        for number, line in enumerate(
            path.read_text("utf-8").splitlines(),
            start=1,
        )
        if _FILE_BACKEND_DIRECTORY.search(line)
    ]


def test_no_message_names_the_file_backend_directory() -> None:
    """Every message module and AGENTS.md: zero occurrences, listed if not."""
    sources = [*sorted(_MESSAGES_DIR.rglob("*.py")), _AGENTS_MD]
    assert _MESSAGE_MODULES_NAMED_IN_THE_FINDING.issubset(path.name for path in sources)
    assert _AGENTS_MD.is_file()

    found = {
        str(path.relative_to(_REPO_ROOT)): hits
        for path in sources
        if (hits := _occurrences(path))
    }

    total = sum(len(hits) for hits in found.values())
    assert found == {}, f"{total} occurrence(s) of the file backend directory: {found}"


# ── static sites: name the configuration, not a path ────────────────────────


@pytest.mark.parametrize(
    "text",
    [instruction_msgs.SERVER_INSTRUCTIONS, tool_msgs.MANAGE_CHANGE_INTENT],
    ids=["server_instructions", "manage_change_intent"],
)
def test_static_messages_point_at_the_configuration_keys(text: str) -> None:
    """Built with no root in hand, so they say where the path is decided."""
    assert "intent_registry_backend" in text
    assert "intent_registry_path" in text
    assert _FILE_BACKEND_DIRECTORY.search(text) is None


def _help_point(anchor: str) -> str:
    matches = [
        point
        for spec in help_msgs.HELP_TOPIC_SPECS.values()
        for point in spec.key_points
        if anchor in point
    ]
    assert len(matches) == 1, (anchor, matches)
    return matches[0]


@pytest.mark.parametrize("anchor", ["Multi-agent:", "advisory same-UID"])
def test_help_topics_point_at_the_configuration_keys(anchor: str) -> None:
    point = _help_point(anchor)
    assert "intent_registry_backend" in point
    assert _FILE_BACKEND_DIRECTORY.search(point) is None


# ── refusal sites: print the registry the root resolves to ──────────────────


@pytest.mark.parametrize(
    ("build", "reason"),
    [
        (
            intent_msgs.unreadable_registry_record_next_step,
            "registry_record_unreadable_by_this_build",
        ),
        (
            intent_msgs.workspace_admission_next_step,
            intent_msgs.WORKSPACE_INTENT_INCOMPATIBLE,
        ),
    ],
    ids=["unreadable_record", "admission"],
)
def test_next_step_prints_the_registry_it_is_handed(
    build: Callable[..., str],
    reason: str,
) -> None:
    """The builder prints what it is given -- no constant, no lookup of its own."""
    step = build(
        reason,
        registry_backend="sqlite",
        registry_storage="elsewhere/intents.db",
    )

    assert "sqlite" in step
    assert "elsewhere/intents.db" in step
    assert _FILE_BACKEND_DIRECTORY.search(step) is None
    # In-band: the step still names a call the operator can actually make.
    assert "manage_change_intent" in step


@pytest.fixture(params=["file", "sqlite-custom-path"])
def configured_root(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Path, str, str]]:
    """A root whose registry is configured unlike the default and this repo.

    Yields ``(root, backend, storage)`` where ``storage`` is the repo-relative
    path ``list_workspace`` reports for that configuration.  Two configurations
    on purpose: a message printing one constant path can agree with at most
    one of them.
    """
    if request.param == "file":
        monkeypatch.setenv("CODECLONE_INTENT_REGISTRY_BACKEND", "file")
        monkeypatch.delenv("CODECLONE_INTENT_REGISTRY_PATH", raising=False)
        expected = ("file", ".codeclone/intents")
    else:
        monkeypatch.setenv("CODECLONE_INTENT_REGISTRY_BACKEND", "sqlite")
        monkeypatch.setenv("CODECLONE_INTENT_REGISTRY_PATH", _CUSTOM_SQLITE_PATH)
        expected = ("sqlite", _CUSTOM_SQLITE_PATH)
    clear_workspace_intent_store_cache()
    try:
        yield (tmp_path, *expected)
    finally:
        clear_workspace_intent_store_cache()


def _assert_names_only_the_configured_registry(
    next_step: str,
    *,
    backend: str,
    storage: str,
) -> None:
    assert backend in next_step
    assert storage in next_step
    if backend == "sqlite":
        # The file backend's directory is not this root's registry.
        assert _FILE_BACKEND_DIRECTORY.search(next_step) is None


def test_recover_refusal_names_the_configured_registry(
    configured_root: tuple[Path, str, str],
) -> None:
    root, backend, storage = configured_root
    record = _record(intent_id=_UNREADABLE_INTENT_ID, pid=os.getpid())
    _seed_raw_payload(root, record=record, payload=_newer_build_payload(record))
    service = CodeCloneMCPService(history_limit=2)

    rejected = service.manage_change_intent(
        action="recover",
        root=str(root),
        run_id="abcdef12",
        intent_id=_UNREADABLE_INTENT_ID,
    )

    assert rejected["reason"] == "registry_record_unreadable_by_this_build"
    _assert_names_only_the_configured_registry(
        str(rejected["next_step"]),
        backend=backend,
        storage=storage,
    )


def test_admission_refusal_names_the_configured_registry(
    configured_root: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, backend, storage = configured_root
    service = _service_with_run(root, monkeypatch)
    _seed_foreign_unreadable_row(root)

    refused = _declare(service, root)

    assert refused["reason"] == intent_msgs.WORKSPACE_INTENT_INCOMPATIBLE
    _assert_names_only_the_configured_registry(
        str(refused["next_step"]),
        backend=backend,
        storage=storage,
    )
