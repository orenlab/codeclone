# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The CLI and MCP git readers never run a program the analysed repository
names, never write into its ``.git``, never hand git the MCP server's auth
token, and keep their answers.

``--diff-against`` (CLI) and ``git_diff_ref`` (MCP) both resolve changed paths
with ``git diff --name-only <ref> --``. With stat-only dirt that command
refreshes and rewrites the index even under ``--no-optional-locks``, so it is
the read that reaches the repository's ``post-index-change`` hook and the one
that needs a private index. MCP ``analyze_repository`` is driven end to end
once per mechanism the analysis path was measured to reach.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from codeclone.surfaces.cli import changed_scope
from codeclone.surfaces.mcp import _session_shared
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest
from codeclone.surfaces.mcp.auth import MCP_AUTH_TOKEN_ENV
from codeclone.surfaces.mcp.service import CodeCloneMCPService

from .hostile_git_fixtures import (
    CLEAN_POPULATIONS,
    FixtureRepo,
    build_population,
    build_repo,
    git_dir_digest,
    install_legacy_git,
    isolate_git_environment,
    marker_program,
    plain_git_fires,
    setup_git,
    twin_copy,
)

ChangedPaths = Callable[[Path], tuple[str, ...]]


def _cli_changed_paths(root: Path) -> tuple[str, ...]:
    return changed_scope._git_diff_changed_paths(root_path=root, git_diff_ref="HEAD")


def _mcp_changed_paths(root: Path) -> tuple[str, ...]:
    return _session_shared._git_diff_lines_payload(root_path=root, git_diff_ref="HEAD")


_CHANGED_PATH_CALLS = pytest.mark.parametrize(
    "changed_paths", [_cli_changed_paths, _mcp_changed_paths], ids=["cli", "mcp"]
)

_DIFF_AGAINST_HEAD = ("diff", "--name-only", "HEAD", "--")


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    isolate_git_environment(monkeypatch, tmp_path)


def _arm_fsmonitor(repo: FixtureRepo) -> None:
    repo.set_config("core.fsmonitor", repo.program("fsmonitor", "printf 'token\\0'"))


def _arm_clean_filter(repo: FixtureRepo) -> None:
    repo.set_config("filter.evil.clean", repo.program("clean_filter", "cat"))


def _arm_process_filter(repo: FixtureRepo) -> None:
    repo.set_config("filter.evil.process", repo.program("process_filter", "exit 1"))


def _arm_index_hook(repo: FixtureRepo) -> None:
    marker_program(
        repo.root / ".git" / "hooks" / "post-index-change",
        repo.markers,
        "post_index_change",
    )


def _arm_diff_external(repo: FixtureRepo) -> None:
    repo.set_config("diff.external", repo.program("diff_external"))


def _arm_textconv(repo: FixtureRepo) -> None:
    repo.set_config("diff.evil.textconv", repo.program("textconv", 'cat "$1"'))


_ATTRIBUTES = "*.py filter=evil diff=evil\n"


@pytest.mark.parametrize(
    ("arm", "marker"),
    [
        (_arm_fsmonitor, "fsmonitor"),
        (_arm_clean_filter, "clean_filter"),
        (_arm_process_filter, "process_filter"),
        (_arm_index_hook, "post_index_change"),
    ],
    ids=["fsmonitor", "clean_filter", "process_filter", "index_hook"],
)
@_CHANGED_PATH_CALLS
def test_changed_path_resolution_never_runs_a_repository_program(
    tmp_path: Path,
    changed_paths: ChangedPaths,
    arm: Callable[[FixtureRepo], None],
    marker: str,
) -> None:
    armed = build_repo(tmp_path / "armed", attributes=_ATTRIBUTES)
    twin = twin_copy(armed, tmp_path / "twin")
    arm(armed)
    control = twin_copy(armed, tmp_path / "control")

    assert changed_paths(armed.root) == changed_paths(twin.root)
    assert armed.fired() == []
    assert plain_git_fires(armed, control, _DIFF_AGAINST_HEAD, marker)


@pytest.mark.parametrize("split_index", [False, True], ids=["index", "split_index"])
@_CHANGED_PATH_CALLS
def test_changed_path_resolution_never_writes_the_repository(
    tmp_path: Path, changed_paths: ChangedPaths, split_index: bool
) -> None:
    repo = build_repo(tmp_path / "repo", split_index=split_index)
    control = twin_copy(repo, tmp_path / "control")
    before = git_dir_digest(repo.root)
    assert changed_paths(repo.root) == ("a.py", "c.py", "staged.py")
    assert git_dir_digest(repo.root) == before
    # Positive control: plain git, even without optional locks, rewrites it.
    control_before = git_dir_digest(control.root)
    setup_git(control.root, "--no-optional-locks", *_DIFF_AGAINST_HEAD)
    assert git_dir_digest(control.root) != control_before


@pytest.mark.parametrize("population", CLEAN_POPULATIONS)
@_CHANGED_PATH_CALLS
def test_changed_paths_answer_as_plain_git_did_on_a_clean_tree(
    tmp_path: Path, changed_paths: ChangedPaths, population: str
) -> None:
    repo = build_population(tmp_path / "repo", population)
    legacy_twin = twin_copy(repo, tmp_path / "legacy")
    owner_answer = changed_paths(repo.root)
    with pytest.MonkeyPatch.context() as patch:
        install_legacy_git(patch)
        legacy_answer = changed_paths(legacy_twin.root)
    assert owner_answer == legacy_answer


@_CHANGED_PATH_CALLS
def test_git_child_never_sees_the_mcp_auth_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_paths: ChangedPaths,
) -> None:
    """A filter driver from the operator's own global configuration still
    runs (only repository-defined drivers are blanked), so it reports the
    environment git handed it. The token's name comes from the MCP owner."""

    repo = build_repo(tmp_path / "repo", attributes="*.py filter=probe\n")
    report = repo.markers / "env.report"
    program = marker_program(
        repo.programs / "probe.sh",
        repo.markers,
        "operator_filter",
        f'echo "token=${{{MCP_AUTH_TOKEN_ENV}:+present}} '
        f"sentinel=${{CODECLONE_GIT_SENTINEL:-}}\" >> '{report}'\ncat",
    )
    repo.set_config("filter.probe.clean", program, scope="--global")
    monkeypatch.setenv(MCP_AUTH_TOKEN_ENV, "t" * 40)
    monkeypatch.setenv("CODECLONE_GIT_SENTINEL", "kept")

    changed_paths(repo.root)

    assert repo.fired() == ["operator_filter"], "the operator's driver did not run"
    assert set(report.read_text("utf-8").splitlines()) == {"token= sentinel=kept"}


def test_unresolvable_ref_reports_the_command_it_asked_for(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The contract error names ``git diff --name-only <ref> --`` exactly as
    before; the owner's call form is not part of what the user asked for."""

    repo = build_repo(tmp_path / "repo")
    with pytest.raises(SystemExit) as exc:
        changed_scope._git_diff_changed_paths(root_path=repo.root, git_diff_ref="nope")
    assert exc.value.code == 2
    out = " ".join(capsys.readouterr().out.split())
    assert (
        "Command '['git', 'diff', '--name-only', 'nope', '--']' "
        "returned non-zero exit status 128." in out
    )


@pytest.mark.parametrize(
    ("arm", "marker", "attributes", "control_args"),
    [
        (_arm_fsmonitor, "fsmonitor", "", ("status", "--porcelain=v1")),
        (_arm_clean_filter, "clean_filter", _ATTRIBUTES, ("status", "--porcelain=v1")),
        (_arm_diff_external, "diff_external", "", ("diff", "--", "a.py")),
        (_arm_textconv, "textconv", _ATTRIBUTES, ("diff", "--", "a.py")),
    ],
    ids=["fsmonitor", "clean_filter", "diff_external", "textconv"],
)
def test_mcp_analysis_never_runs_a_repository_program(
    tmp_path: Path,
    arm: Callable[[FixtureRepo], None],
    marker: str,
    attributes: str,
    control_args: tuple[str, ...],
) -> None:
    armed = build_repo(tmp_path / "armed", attributes=attributes)
    (armed.root / ".gitignore").write_text(".codeclone/\n", "utf-8")
    arm(armed)
    control = twin_copy(armed, tmp_path / "control")

    CodeCloneMCPService(history_limit=2).analyze_repository(
        MCPAnalysisRequest(root=str(armed.root))
    )
    assert armed.fired() == []
    assert plain_git_fires(armed, control, control_args, marker)
