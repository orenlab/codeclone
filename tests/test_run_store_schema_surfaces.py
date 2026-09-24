# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The run store's schema authority where the surfaces meet it.

An open of an existing store never changes its schema; a store of this
generation that lacks a declared table or index is refused with the one
command that completes it (the store-side pins live in
``tests/test_run_store_ddl_authority.py``).  Here, on the surface ring:

* ``codeclone run-store migrate --path PATH`` answers what is not a store of
  this generation -- another generation, a schema with no witness, an empty
  file, an absent path -- with exit 2 and the refusal's own words, and
  writes none of them;
* MCP ``get_implementation_context`` and ``check_authority`` serve a store
  without the index from memory with the EXISTING reason
  ``incompatible_generation`` -- the store is not corrupt, it cannot be
  opened as it stands -- and the command in ``detail``.  The command is
  taken out of that detail and run: afterwards the same request is served
  from the store.  Both transports hold one ``CodeCloneMCPService``, so the
  streamable-http answer is this answer.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest

from codeclone.surfaces.cli.subcommands import dispatch_subcommand
from tests._run_store_schema_evidence import (
    INDEX,
    byte_state,
    copy_generation_1,
    drop_the_index,
    empty_file,
    foreign_schema,
)
from tests.test_check_authority_candidates_run_store_serving import _served
from tests.test_check_authority_candidates_run_store_serving import (
    _served_block as _candidates_served_block,
)
from tests.test_implementation_context_run_store_serving import (
    _published_store_run_id,
    _served_block,
    _served_run,
)

_WITNESS_REFUSAL: Final = "store witness is not this process's declared generation"
_NO_STORE: Final = "there is no run store at"


def _migrate(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as caught:
        dispatch_subcommand(argv)
    code = caught.value.code
    assert isinstance(code, int)
    return code


_NOT_A_STORE: Final[dict[str, tuple[Callable[[Path], None], str]]] = {
    "generation_1": (copy_generation_1, _WITNESS_REFUSAL),
    "foreign_schema": (foreign_schema, _WITNESS_REFUSAL),
    "empty_file": (empty_file, _NO_STORE),
}


@pytest.mark.parametrize("population", sorted(_NOT_A_STORE))
def test_the_verb_answers_what_is_not_a_store_of_this_generation_with_exit_2(
    tmp_path: Path, population: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "runs.sqlite3"
    build, words = _NOT_A_STORE[population]
    build(path)
    before = byte_state(path)
    capsys.readouterr()
    assert _migrate(["codeclone", "run-store", "migrate", "--path", str(path)]) == 2
    printed = capsys.readouterr().out
    assert words in printed and str(path) in printed, printed
    assert byte_state(path) == before


def test_the_verb_answers_an_absent_path_with_exit_2_and_creates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    absent = tmp_path / "nowhere" / "runs.sqlite3"
    capsys.readouterr()
    assert _migrate(["codeclone", "run-store", "migrate", "--path", str(absent)]) == 2
    assert _NO_STORE in capsys.readouterr().out
    assert not absent.parent.exists()


def _command_in(detail: object, *, store: Path) -> list[str]:
    """The command a served refusal names, as argv, and it names THIS store."""
    found = re.findall(r"`([^`]+)`", str(detail))
    assert len(found) == 1, detail
    argv = shlex.split(found[0])
    assert argv == ["codeclone", "run-store", "migrate", "--path", str(store)], argv
    return argv


def _run_the_named_command(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    assert _migrate(argv) == 0
    assert f"added index {INDEX}" in capsys.readouterr().out
    assert _migrate(argv) == 0
    assert "nothing to migrate" in capsys.readouterr().out


def test_implementation_context_answers_an_incomplete_store_with_its_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service, root, record, _summary, _slices = _served_run(tmp_path, monkeypatch)
    store_run_id = _published_store_run_id(record)
    store = tmp_path / "runs.sqlite3"
    drop_the_index(store)
    before = byte_state(store)
    request = {"paths": ["pkg/callee.py"], "include": ["callers"]}

    answer = service.get_implementation_context(root=str(root), **request)
    assert answer["status"] == "ok"
    serving = answer["serving"]
    assert isinstance(serving, dict)
    assert (serving["source"], serving["reason"], serving["store_run_id"]) == (
        "memory",
        "incompatible_generation",
        store_run_id,
    )
    argv = _command_in(serving["detail"], store=store)
    assert byte_state(store) == before

    _run_the_named_command(argv, capsys)
    answer = service.get_implementation_context(root=str(root), **request)
    assert answer["serving"] == _served_block(store_run_id)


def test_check_authority_answers_an_incomplete_store_with_its_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service, root, _record, store_run_id = _served(tmp_path, monkeypatch)
    store = tmp_path / "runs.sqlite3"
    drop_the_index(store)
    before = byte_state(store)

    answer = service.check_authority(root=str(root), section="candidates")
    serving = answer["serving"]
    assert isinstance(serving, dict)
    assert (serving["source"], serving["reason"], serving["store_run_id"]) == (
        "memory",
        "incompatible_generation",
        store_run_id,
    )
    argv = _command_in(serving["detail"], store=store)
    assert byte_state(store) == before

    _run_the_named_command(argv, capsys)
    answer = service.check_authority(root=str(root), section="candidates")
    assert answer["serving"] == _candidates_served_block(store_run_id)
