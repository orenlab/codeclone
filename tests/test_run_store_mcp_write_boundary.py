# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The MCP surface writes the run store only inside CodeClone's service
directories.

The server states its write boundary to every client: it writes CodeClone's
own service data, and only inside ``.codeclone/`` of the analysed repository
and the per-user CodeClone cache directory.  The analysis cache has obeyed
that boundary since 2026-09-02 -- a cache path outside it is read and never
written, and the answer says so in one line.  The run store did not: measured
on 2d370f30, ``CODECLONE_RUN_STORE_PATH=../escaped/runs.sqlite3`` and an
absolute path outside the root each had the server create the store there and
publish into it.

Now the same rule as the cache, one decision at the publication site: a
publication MCP starts writes the store only when its path is a service path
of the analysed root, and otherwise opens nothing for writing (``disabled``),
says one line in ``warnings[]``, and takes no intent lease on that store
either (a lease is a write).  The CLI is unchanged: the boundary is the MCP
surface's law, not the CLI's.

Every repository and every store lives under ``tmp_path``.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

from codeclone.api.intent_run_lease import RUN_LEASE_HELD
from codeclone.api.run_store_serving import SERVING_REASON_STORE_ABSENT
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest
from tests.conftest import RunStoreCorpusRunner

#: The publication outcomes, spelled as the closed vocabulary spells them
#: (``codeclone.models``; this ring-4 module may not import it).
_DISABLED: Final = "disabled"
_PUBLISHED: Final = "published"

#: The one line, the cache's words with the store's name.
_LINE: Final = (
    "Run store {store_path} is outside CodeClone's service directories; MCP "
    "reads it and will not write it. Move it under .codeclone/ for MCP to "
    "publish runs into it."
)
_MARKER: Final = "is outside CodeClone's service directories"
_DEFAULT: Final = (".codeclone", "db", "runs.sqlite3")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@e.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@e.com",
        },
    )


def _repository(base: Path) -> Path:
    root = (base / "repo").resolve()
    root.joinpath("pkg").mkdir(parents=True)
    root.joinpath("pkg", "__init__.py").write_text("", "utf-8")
    root.joinpath("pkg", "a.py").write_text(
        "".join(f"def f{n}(x: int) -> int:\n    return x + {n}\n\n" for n in range(3)),
        "utf-8",
    )
    for args in (("init", "-q"), ("add", "."), ("commit", "-qm", "init")):
        _git(root, *args)
    return root


def _rollout(monkeypatch: pytest.MonkeyPatch, path: str | None) -> None:
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
    if path is None:
        monkeypatch.delenv("CODECLONE_RUN_STORE_PATH", raising=False)
    else:
        monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", path)


@dataclass(frozen=True, slots=True)
class _Answer:
    """One MCP analysis and one ``start_controlled_change`` against it."""

    outcome: str
    warnings: tuple[str, ...]
    lease_held: bool
    lease_reason: str


def _analyze_and_start(root: Path) -> _Answer:
    service = CodeCloneMCPService(history_limit=2)
    answer = service.analyze_repository(
        MCPAnalysisRequest(root=str(root), respect_pyproject=False)
    )
    link = service._runs.records()[-1].execution.run_snapshot_link
    assert link is not None, "the execution stated no bridge"
    started = service.start_controlled_change(
        root=str(root), scope={"allowed_files": ["pkg/a.py"]}, intent="edit pkg.a"
    )
    assert started["status"] == "active", started
    entry = service._intent_run_leases.get(str(started["intent_id"]))
    assert entry is not None, "start took no lease decision at all"
    lease = entry[1]
    warnings = tuple(str(item) for item in answer["warnings"])  # type: ignore[attr-defined]
    service.manage_change_intent(action="clear", intent_id=str(started["intent_id"]))
    return _Answer(
        outcome=link.outcome,
        warnings=warnings,
        lease_held=lease.held,
        lease_reason=lease.reason,
    )


def _boundary_lines(warnings: tuple[str, ...]) -> list[str]:
    return [line for line in warnings if _MARKER in line and "Run store" in line]


def _stored_runs(store: Path) -> int:
    with closing(sqlite3.connect(f"file:{store}?mode=ro", uri=True)) as raw:
        (count,) = raw.execute("SELECT count(*) FROM runs").fetchone()
    return int(count)


# -- outside the boundary: nothing written, one line, no lease ---------------------


#: ``(id, the variable's value relative to tmp_path's repo, the file the
#: resolver names)``.  The two prefix neighbours are the ones a string-prefix
#: test would admit: a sibling whose name starts with ``.codeclone`` and a path
#: that enters ``.codeclone/`` and climbs back out of it.
_OUTSIDE: Final = (
    ("relative-escape", "../escaped/runs.sqlite3", "../escaped/runs.sqlite3"),
    ("absolute-outside", "<abs>", "<abs>"),
    ("prefix-sibling", ".codeclone-x/runs.sqlite3", ".codeclone-x/runs.sqlite3"),
    (
        "climbs-out-of-service",
        ".codeclone/../escaped/runs.sqlite3",
        ".codeclone/../escaped/runs.sqlite3",
    ),
)


@pytest.mark.parametrize(
    ("value", "named"),
    [(value, named) for _id, value, named in _OUTSIDE],
    ids=[case_id for case_id, _value, _named in _OUTSIDE],
)
def test_mcp_writes_no_store_outside_the_service_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str, named: str
) -> None:
    root = _repository(tmp_path)
    absolute = tmp_path / "outside" / "runs.sqlite3"
    configured = str(absolute) if value == "<abs>" else value
    store_path = absolute if named == "<abs>" else root / named
    _rollout(monkeypatch, configured)

    answer = _analyze_and_start(root)

    assert not store_path.exists(), f"MCP created a store outside: {store_path}"
    assert not Path(f"{store_path}-wal").exists()
    assert answer.outcome == _DISABLED, answer
    assert _boundary_lines(answer.warnings) == [_LINE.format(store_path=store_path)], (
        answer.warnings
    )
    # Nothing was published there, so the road finds no store to lease in;
    # a store that does hold the run is refused by the write boundary itself
    # (tests/test_intent_run_lease_door.py, the same decision).
    assert not answer.lease_held, answer
    assert answer.lease_reason == SERVING_REASON_STORE_ABSENT, answer


# -- inside the boundary: published, quiet, leased (positive controls) ---------------


@pytest.mark.parametrize(
    "value",
    [None, ".codeclone/db/elsewhere.sqlite3"],
    ids=["default-path", "explicit-inside-codeclone"],
)
def test_mcp_publishes_into_a_store_inside_the_service_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    root = _repository(tmp_path)
    store_path = root.joinpath(*_DEFAULT) if value is None else root / value
    _rollout(monkeypatch, value)

    answer = _analyze_and_start(root)

    assert answer.outcome == _PUBLISHED, answer
    assert _boundary_lines(answer.warnings) == [], answer.warnings
    assert _stored_runs(store_path) == 1
    assert answer.lease_held, answer
    assert answer.lease_reason == RUN_LEASE_HELD


# -- CI is environment information, never an authority -----------------------------


#: The CI keys the rollout's CI gate reads (``codeclone.utils.ci``).
_CI_KEYS: Final = ("CI", "GITHUB_ACTIONS", "BUILDKITE", "TF_BUILD", "TEAMCITY_VERSION")

#: ``(id, CI, CODECLONE_RUN_STORE_FORCE)``: every row is one under which the
#: rollout is ON -- an unset ``CI`` needs no force; any non-empty ``CI``,
#: ``false`` included, is CI and needs the force.  The control in each row
#: proves the row reached the publication at all.
_CI_ROWS: Final = (
    ("ci-unset", None, None),
    ("ci-false-forced", "false", "1"),
    ("ci-true-forced", "true", "1"),
)


def _ci(monkeypatch: pytest.MonkeyPatch, ci: str | None, force: str | None) -> None:
    for key in _CI_KEYS:
        monkeypatch.delenv(key, raising=False)
    if ci is not None:
        monkeypatch.setenv("CI", ci)
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
    if force is None:
        monkeypatch.delenv("CODECLONE_RUN_STORE_FORCE", raising=False)
    else:
        monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", force)


@pytest.mark.parametrize(
    ("ci", "force"),
    [(ci, force) for _id, ci, force in _CI_ROWS],
    ids=[case_id for case_id, _ci_value, _force in _CI_ROWS],
)
def test_the_boundary_holds_whatever_ci_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ci: str | None, force: str | None
) -> None:
    _ci(monkeypatch, ci, force)
    control_root = _repository(tmp_path / "control")
    monkeypatch.delenv("CODECLONE_RUN_STORE_PATH", raising=False)
    control = _analyze_and_start(control_root)
    assert control.outcome == _PUBLISHED, control
    assert _stored_runs(control_root.joinpath(*_DEFAULT)) == 1

    root = _repository(tmp_path / "subject")
    outside = tmp_path / "outside" / "runs.sqlite3"
    monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(outside))
    answer = _analyze_and_start(root)

    assert not outside.exists(), "MCP wrote a store outside its service directories"
    assert not outside.parent.exists()
    assert answer.outcome == _DISABLED, answer
    assert _boundary_lines(answer.warnings) == [_LINE.format(store_path=outside)]
    assert not answer.lease_held, answer
    assert answer.lease_reason == SERVING_REASON_STORE_ABSENT, answer


# -- the CLI keeps its own write law ------------------------------------------------


def test_the_cli_still_publishes_into_a_store_outside_the_root(
    tmp_path: Path, run_store_cli: RunStoreCorpusRunner
) -> None:
    """The same outside path the MCP cases refuse: the CLI writes it, because
    a user who runs the CLI with that variable asked for exactly that file."""
    root = _repository(tmp_path)
    outside = tmp_path / "outside" / "runs.sqlite3"

    run_store_cli(root, "--fail-health", "0", store=outside)

    assert _stored_runs(outside) == 1
