# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A store the open would refuse is refused before the model is built, and
the warning names the step that cures it.

Measured on 2d370f30: a store of another generation (or of this generation
without an index this build declares) is refused by ``RunStore``'s open --
but the publication built the whole canonical model first, 3.5-4.9 s per
analysis of this repository, only to have the open throw it away; and the
one warning line named the refusal's type and nothing else, while the
refusal itself carries the action that cures it (move or delete the file;
``codeclone run-store migrate --path ...``).

Now the publication takes the open's own look at an existing file before it
builds anything: the same decision, by the same function, so a store the
open would refuse is refused with the same type and the same ``failed``
outcome, the model never built, and the line carries the refusal's
``next_step``.  A compatible store and an absent file are built and
published exactly as before.

Every store lives inside its temporary repository's ``.codeclone/``.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest

from codeclone.canonical.errors import (
    STORE_GENERATION_NEXT_STEP,
    StoreSchemaIncompleteError,
)
from codeclone.core.canonical_snapshot import bridge_run_snapshot
from codeclone.models import (
    RUN_SNAPSHOT_PUBLICATION_FAILED,
    RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
    RunSnapshotLink,
    RunSnapshotPublication,
)
from tests._run_store_schema_evidence import INDEX, byte_state, drop_the_index
from tests.conftest import RunStoreCorpusRunner, RunStoreMcpRunner

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_GENERATION_2: Final = (
    Path(__file__).parent / "fixtures" / "run_store_generation_2" / "runs.sqlite3"
)
_ARGS: Final = ("--fail-health", "0", "--min-loc", "3", "--min-stmt", "2")
_BUILD: Final = "codeclone.core.canonical_snapshot.canonical_snapshot_from_producers"


def _line(failure: str, next_step: str) -> str:
    return f"analysis complete, publication failed ({failure}); next_step: {next_step}"


def _corpus(tmp_path: Path) -> tuple[Path, Path]:
    """A small package and the store path inside its own ``.codeclone/``."""
    root = (tmp_path / "corpus").resolve()
    package = root / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", "utf-8")
    units = "\n\n".join(
        f"def unit_{index}(value: int) -> int:\n"
        f'    """Unit {index}."""\n'
        f"    return value + {index}\n"
        for index in range(12)
    )
    (package / "gen.py").write_text(f'"""Gen."""\n\n\n{units}', "utf-8")
    store = root / ".codeclone" / "db" / "runs.sqlite3"
    return root, store


def _foreign_generation(store: Path) -> dict[str, object]:
    """The previous generation's real store at the path, and its byte state
    taken before any connection touched it."""
    store.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_GENERATION_2, store)
    return byte_state(store)


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Every canonical-model build the publication starts, counted where it
    starts -- the spy on the one build the look exists to spare."""
    import codeclone.core.canonical_snapshot as snapshot_module

    real = snapshot_module.canonical_snapshot_from_producers
    started: list[int] = []

    def counted(**kwargs: object) -> object:
        started.append(1)
        return real(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(_BUILD, counted)
    return started


@pytest.fixture
def links(monkeypatch: pytest.MonkeyPatch) -> list[RunSnapshotLink]:
    """Every link the report edge states, taken where it states them."""
    stated: list[RunSnapshotLink] = []

    def spy(
        *,
        publication: RunSnapshotPublication,
        report_document: Mapping[str, object] | None,
    ) -> RunSnapshotLink:
        link = bridge_run_snapshot(
            publication=publication, report_document=report_document
        )
        stated.append(link)
        return link

    monkeypatch.setattr("codeclone.core.reporting.bridge_run_snapshot", spy)
    return stated


def _warnings(answer: Mapping[str, object]) -> list[str]:
    return [str(item) for item in answer["warnings"]]  # type: ignore[attr-defined]


def _failed_lines(answer: Mapping[str, object]) -> list[str]:
    return [line for line in _warnings(answer) if "publication failed" in line]


# -- a foreign generation ---------------------------------------------------------


def test_a_foreign_generation_is_refused_before_the_model_is_built(
    tmp_path: Path,
    run_store_mcp: RunStoreMcpRunner,
    builds: list[int],
    links: list[RunSnapshotLink],
) -> None:
    root, store = _corpus(tmp_path)
    before = _foreign_generation(store)

    answer = run_store_mcp(root, store)

    assert answer["run_id"], "the analysis did not finish"
    assert builds == [], "the model was built for a store the open refuses"
    assert (links[-1].outcome, links[-1].failure) == (
        RUN_SNAPSHOT_PUBLICATION_FAILED,
        "StoreCompatibilityError",
    )
    assert _failed_lines(answer) == [
        _line("StoreCompatibilityError", STORE_GENERATION_NEXT_STEP)
    ], answer["warnings"]
    assert byte_state(store) == before, "the refused store was written"


def test_the_cli_says_the_step_for_a_foreign_generation(
    tmp_path: Path,
    run_store_cli: RunStoreCorpusRunner,
    builds: list[int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI prints the link's own line, so it gains the step with MCP --
    one line, every surface the same words -- and spares the same build."""
    root, store = _corpus(tmp_path)
    before = _foreign_generation(store)

    run_store_cli(root, *_ARGS, store=store)

    printed = " ".join(capsys.readouterr().out.split())
    assert builds == []
    assert printed.count("publication failed") == 1, printed
    assert f"next_step: {STORE_GENERATION_NEXT_STEP}" in printed, printed
    assert byte_state(store) == before


# -- an incomplete schema, and the verb that completes it ---------------------------


def _spelled_command(line: str) -> list[str]:
    """The command the warning names, as argv -- taken from its own words."""
    found = re.findall(r"`([^`]+)`", line)
    assert len(found) == 1, line
    return shlex.split(found[0])


def _run_as_a_user(argv: list[str]) -> int:
    assert argv[:3] == ["codeclone", "run-store", "migrate"], argv
    environment = os.environ.copy()
    environment["PYTHONPATH"] = (
        str(_REPO_ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    )
    done = subprocess.run(
        [sys.executable, "-m", "codeclone.main", *argv[1:]],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    return done.returncode


def test_an_incomplete_schema_is_refused_unbuilt_and_the_named_verb_cures_it(
    tmp_path: Path,
    run_store_mcp: RunStoreMcpRunner,
    builds: list[int],
    links: list[RunSnapshotLink],
) -> None:
    root, store = _corpus(tmp_path)
    first = run_store_mcp(root, store)
    assert first["run_id"]
    assert links[-1].outcome == RUN_SNAPSHOT_PUBLICATION_PUBLISHED
    assert len(builds) == 1, "an absent file is created after one build"
    drop_the_index(store)
    before = byte_state(store)

    refused = run_store_mcp(root, store)

    assert len(builds) == 1, "the model was built for a store the open refuses"
    assert (links[-1].outcome, links[-1].failure) == (
        RUN_SNAPSHOT_PUBLICATION_FAILED,
        "StoreSchemaIncompleteError",
    )
    step = StoreSchemaIncompleteError(
        path=str(store), missing=(("index", INDEX),)
    ).next_step
    lines = _failed_lines(refused)
    assert lines == [_line("StoreSchemaIncompleteError", step)], refused["warnings"]
    assert byte_state(store) == before, "the refused store was written"

    assert _run_as_a_user(_spelled_command(lines[0])) == 0

    cured = run_store_mcp(root, store)
    assert _failed_lines(cured) == []
    assert links[-1].outcome == RUN_SNAPSHOT_PUBLICATION_PUBLISHED
    assert len(builds) == 2


# -- the positive controls: what the look must leave alone ----------------------------


def test_a_compatible_store_is_built_and_published_as_before(
    tmp_path: Path,
    run_store_mcp: RunStoreMcpRunner,
    builds: list[int],
    links: list[RunSnapshotLink],
) -> None:
    root, store = _corpus(tmp_path)
    run_store_mcp(root, store)
    assert store.exists() and len(builds) == 1

    again = run_store_mcp(root, store)

    assert len(builds) == 2, "the look refused a store the open accepts"
    assert links[-1].outcome == RUN_SNAPSHOT_PUBLICATION_PUBLISHED
    assert _failed_lines(again) == []


def test_an_absent_store_file_is_built_created_and_published(
    tmp_path: Path,
    run_store_mcp: RunStoreMcpRunner,
    builds: list[int],
    links: list[RunSnapshotLink],
) -> None:
    root, store = _corpus(tmp_path)
    assert not store.exists()

    answer = run_store_mcp(root, store)

    assert len(builds) == 1, "an absent file was taken for a refused store"
    assert links[-1].outcome == RUN_SNAPSHOT_PUBLICATION_PUBLISHED
    assert store.exists()
    assert _failed_lines(answer) == []
