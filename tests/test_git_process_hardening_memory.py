# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Engineering Memory's git readers never run a program the analysed
repository names, never write into its ``.git``, and answer exactly what they
answer for a clean twin.

Same shape as ``test_git_process_hardening``: arm one mechanism, call the real
readers, assert silence and an unchanged answer, then show plain ``git`` in an
armed copy runs the marker.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from codeclone.memory import report_trust
from codeclone.memory.ingest.extractors import extract_git_hotspots
from codeclone.memory.models import MemoryProject
from codeclone.memory.project import GitProvenance, read_git_provenance

from .hostile_git_fixtures import (
    CLEAN_POPULATIONS,
    FixtureRepo,
    build_population,
    build_repo,
    git_dir_digest,
    install_legacy_git,
    isolate_git_environment,
    plain_git_fires,
    twin_copy,
)

_NOW = "2026-10-03T00:00:00Z"


def _hotspot_statements(root: Path) -> list[str]:
    project = MemoryProject(
        id="proj-test",
        root=str(root),
        git_remote=None,
        git_branch=None,
        git_head=None,
        python_tag="cp314",
        created_at_utc=_NOW,
        updated_at_utc=_NOW,
    )
    batch = extract_git_hotspots(
        project=project,
        root_path=root,
        git=GitProvenance(remote=None, branch="main", head="h", available=True),
        report_digest=None,
        analysis_fingerprint=None,
        min_changes=1,
    )
    return sorted(record.statement for record in batch.records)


MemoryCall = Callable[[Path], object]

_MEMORY_CALLS: dict[str, MemoryCall] = {
    "read_git_provenance": read_git_provenance,
    "report_trust._git_head_commit": report_trust._git_head_commit,
    "report_trust._git_tracked_py_paths": report_trust._git_tracked_py_paths,
    "report_trust._git_head_commit_unix": report_trust._git_head_commit_unix,
    "extract_git_hotspots": _hotspot_statements,
}


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    isolate_git_environment(monkeypatch, tmp_path)


def _assert_silent_and_equal(armed: FixtureRepo, twin: FixtureRepo) -> None:
    for name, call in _MEMORY_CALLS.items():
        armed.clear_markers()
        answer = call(armed.root)
        assert armed.fired() == [], f"{name} ran a program the repository named"
        assert answer == call(twin.root), f"{name} answered differently"


def test_fsmonitor_named_by_the_repository_never_runs_from_memory(
    tmp_path: Path,
) -> None:
    armed = build_repo(tmp_path / "armed")
    twin = twin_copy(armed, tmp_path / "twin")
    armed.set_config("core.fsmonitor", armed.program("fsmonitor", "printf 'token\\0'"))
    control = twin_copy(armed, tmp_path / "control")
    _assert_silent_and_equal(armed, twin)
    assert plain_git_fires(armed, control, ("ls-files", "--", "*.py"), "fsmonitor")


def test_signature_program_named_by_the_repository_never_runs_from_memory(
    tmp_path: Path,
) -> None:
    armed = build_repo(tmp_path / "armed", forged_signature=True)
    twin = twin_copy(armed, tmp_path / "twin")
    armed.set_config("log.showSignature", "true")
    armed.set_config("gpg.program", armed.program("gpg"))
    control = twin_copy(armed, tmp_path / "control")
    _assert_silent_and_equal(armed, twin)
    assert plain_git_fires(armed, control, ("log", "-1", "--format=%ct"), "gpg")


@pytest.mark.parametrize("call_name", sorted(_MEMORY_CALLS))
@pytest.mark.parametrize("population", CLEAN_POPULATIONS)
def test_memory_reads_answer_as_plain_git_did_on_a_clean_tree(
    tmp_path: Path, population: str, call_name: str
) -> None:
    repo = build_population(tmp_path / "repo", population)
    legacy_twin = twin_copy(repo, tmp_path / "legacy")
    call = _MEMORY_CALLS[call_name]
    owner_answer = call(repo.root)
    with pytest.MonkeyPatch.context() as patch:
        install_legacy_git(patch)
        legacy_answer = call(legacy_twin.root)
    assert owner_answer == legacy_answer


@pytest.mark.parametrize("call_name", sorted(_MEMORY_CALLS))
def test_memory_reads_never_write_the_repository(
    tmp_path: Path, call_name: str
) -> None:
    repo = build_repo(tmp_path / "repo")
    before = git_dir_digest(repo.root)
    _MEMORY_CALLS[call_name](repo.root)
    assert git_dir_digest(repo.root) == before
