# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The workspace and content snapshots never run a program the analysed
repository names, never write into its ``.git``, and answer exactly what they
answer for a clean twin.

Every mechanism test arms one mechanism in a temporary repository
(``hostile_git_fixtures``), calls the real snapshot owners, and asserts that no
marker appeared and that each answer equals the one for an unarmed
byte-for-byte twin. Each ends with a positive control: plain ``git`` in an
armed copy does run the marker, so the mechanism was live and the silence is
the owner's doing.

The module also holds the ratchet: no module of the package but the git owner
starts git, and every module that starts any process is named.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from codeclone.paths import git_snapshot

from .hostile_git_fixtures import (
    CLEAN_POPULATIONS,
    FixtureRepo,
    arm_promisor_remote,
    build_population,
    build_repo,
    drop_object,
    git_dir_digest,
    install_legacy_git,
    isolate_git_environment,
    plain_git_fires,
    setup_git,
    twin_copy,
)

_ALL_PATHS = ("a.py", "b.py", "c.py", "staged.py", "untracked.py")

SnapshotCall = Callable[[Path], object]


def _content_snapshot(root: Path) -> object:
    snapshot = git_snapshot.collect_git_content_snapshot(root, _ALL_PATHS)
    return dataclasses.replace(snapshot, root="<root>")


_SNAPSHOT_CALLS: dict[str, SnapshotCall] = {
    "git_repository_available": git_snapshot.git_repository_available,
    "list_git_workspace_paths": git_snapshot.list_git_workspace_paths,
    "workspace_snapshot": lambda root: git_snapshot.collect_git_workspace_snapshot(
        root, include_digests=False
    ),
    "workspace_snapshot_with_digests": (
        lambda root: git_snapshot.collect_git_workspace_snapshot(
            root, include_digests=True
        )
    ),
    "content_snapshot": _content_snapshot,
}


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    isolate_git_environment(monkeypatch, tmp_path)


def _armed_and_twin(
    tmp_path: Path, arm: Callable[[FixtureRepo], None], *, attributes: str = ""
) -> tuple[FixtureRepo, FixtureRepo, FixtureRepo]:
    """``(armed, twin, control)``: one repository, an unarmed copy of it, and
    an armed copy reserved for the plain-git positive control."""

    armed = build_repo(tmp_path / "armed", attributes=attributes)
    twin = twin_copy(armed, tmp_path / "twin")
    arm(armed)
    control = twin_copy(armed, tmp_path / "control")
    return armed, twin, control


def _assert_silent_and_equal(armed: FixtureRepo, twin: FixtureRepo) -> None:
    for name, call in _SNAPSHOT_CALLS.items():
        armed.clear_markers()
        answer = call(armed.root)
        assert armed.fired() == [], f"{name} ran a program the repository named"
        assert answer == call(twin.root), f"{name} answered differently"


# --- core.fsmonitor ---------------------------------------------------------


def _arm_fsmonitor(repo: FixtureRepo) -> None:
    repo.set_config("core.fsmonitor", repo.program("fsmonitor", "printf 'token\\0'"))


def test_fsmonitor_named_by_the_repository_never_runs_from_a_snapshot(
    tmp_path: Path,
) -> None:
    armed, twin, control = _armed_and_twin(tmp_path, _arm_fsmonitor)
    _assert_silent_and_equal(armed, twin)
    assert plain_git_fires(armed, control, ("status", "--porcelain=v1"), "fsmonitor")


# --- the hook git runs after writing the index -------------------------------


def _arm_index_hook(repo: FixtureRepo) -> None:
    hook = repo.root / ".git" / "hooks" / "post-index-change"
    hook.write_text(
        f"#!/bin/sh\necho hook >> '{repo.markers / 'post_index_change'}.marker'\n",
        "utf-8",
    )
    hook.chmod(0o755)


def test_index_hook_named_by_the_repository_never_runs_from_a_snapshot(
    tmp_path: Path,
) -> None:
    armed, twin, control = _armed_and_twin(tmp_path, _arm_index_hook)
    _assert_silent_and_equal(armed, twin)
    assert plain_git_fires(
        armed, control, ("status", "--porcelain=v1"), "post_index_change"
    )


# --- filter drivers ----------------------------------------------------------


def _define_driver(repo: FixtureRepo, key: str, value: str, scope: str) -> None:
    if scope == "local":
        repo.set_config(key, value)
    elif scope == "worktree":
        repo.set_config("extensions.worktreeConfig", "true")
        repo.set_config(key, value, scope="--worktree")
    else:  # included from the repository's own configuration
        included = repo.programs / "included.gitconfig"
        setup_git(repo.root, "config", "--file", str(included), key, value)
        repo.set_config("include.path", str(included))


def _filter_arm(kind: str, scope: str) -> Callable[[FixtureRepo], None]:
    def arm(repo: FixtureRepo) -> None:
        if kind == "required":
            # A driver git must run but has no program for: plain git refuses
            # every content read; the owner, running no driver, must not.
            _define_driver(repo, "filter.evil.required", "true", scope)
            return
        body = "cat" if kind == "clean" else "exit 1"
        _define_driver(
            repo, f"filter.evil.{kind}", repo.program(f"{kind}_filter", body), scope
        )

    return arm


@pytest.mark.parametrize("scope", ["local", "worktree", "included"])
@pytest.mark.parametrize("kind", ["clean", "process"])
def test_filter_driver_named_by_the_repository_never_runs_from_a_snapshot(
    tmp_path: Path, kind: str, scope: str
) -> None:
    armed, twin, control = _armed_and_twin(
        tmp_path, _filter_arm(kind, scope), attributes="*.py filter=evil\n"
    )
    _assert_silent_and_equal(armed, twin)
    assert plain_git_fires(
        armed, control, ("status", "--porcelain=v1"), f"{kind}_filter"
    )


def test_required_filter_driver_without_a_program_does_not_refuse_a_snapshot(
    tmp_path: Path,
) -> None:
    armed, twin, control = _armed_and_twin(
        tmp_path, _filter_arm("required", "local"), attributes="*.py filter=evil\n"
    )
    _assert_silent_and_equal(armed, twin)
    refused = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=control.root,
        capture_output=True,
        check=False,
    )
    assert refused.returncode != 0, "positive control: plain git did not refuse"


_CONTENT_READS = (
    "content_snapshot",
    "workspace_snapshot",
    "workspace_snapshot_with_digests",
)


def _arm_unspellable_driver(repo: FixtureRepo) -> None:
    repo.set_config("filter.a=b.clean", repo.program("clean_filter", "cat"))


def _git_availability(root: Path) -> dict[str, object]:
    return {
        name: getattr(_SNAPSHOT_CALLS[name](root), "git_available", None)
        for name in _CONTENT_READS
    }


def test_filter_driver_whose_name_cannot_be_overridden_is_refused(
    tmp_path: Path,
) -> None:
    """A driver named ``a=b`` cannot be spelled as ``-c <name>=<value>``: git
    splits at the first ``=``. The owner refuses to run git rather than run it
    with that driver live; every content read then answers git unavailable."""

    armed, _twin, control = _armed_and_twin(
        tmp_path, _arm_unspellable_driver, attributes="*.py filter=a=b\n"
    )
    availability = _git_availability(armed.root)
    assert armed.fired() == [], "a content read ran a program the repository named"
    assert availability == dict.fromkeys(_CONTENT_READS, False)
    assert plain_git_fires(armed, control, ("status", "--porcelain=v1"), "clean_filter")


def test_clean_filter_cannot_vouch_for_modified_content(tmp_path: Path) -> None:
    """C-02b: a repository-defined clean filter that always prints the
    committed bytes made a modified file read as clean, carrying the digest
    of content that is not on disk. With the driver blanked, git hashes what
    is on disk and the file reads as dirty."""

    repo = build_repo(tmp_path / "armed", attributes="*.py filter=liar\n")
    committed = setup_git(repo.root, "show", "HEAD:b.py").stdout
    liar = repo.programs / "liar.sh"
    liar.write_bytes(b"#!/bin/sh\ncat >/dev/null\nprintf '%s' '" + committed + b"'\n")
    liar.chmod(0o755)
    repo.set_config("filter.liar.clean", str(liar))
    # Same length, different bytes, mtime kept: only content can tell.
    stat_before = (repo.root / "b.py").stat()
    (repo.root / "b.py").write_text("def b(x):\n    return x + 9\n", "utf-8")
    os.utime(repo.root / "b.py", ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))

    snapshot = git_snapshot.collect_git_content_snapshot(repo.root, _ALL_PATHS)
    assert snapshot.git_available
    assert "b.py" not in {item.path for item in snapshot.tracked}
    assert "b.py" in snapshot.dirty_paths


# --- external diff programs and text conversion -----------------------------


def _diff_arm(key: str, marker: str, body: str = "") -> Callable[[FixtureRepo], None]:
    def arm(repo: FixtureRepo) -> None:
        repo.set_config(key, repo.program(marker, body))

    return arm


@pytest.mark.parametrize(
    ("key", "marker", "body"),
    [
        ("diff.external", "diff_external", ""),
        ("diff.evil.command", "diff_command", ""),
        ("diff.evil.textconv", "textconv", 'cat "$1"'),
    ],
    ids=["diff.external", "diff.driver.command", "diff.driver.textconv"],
)
def test_diff_program_named_by_the_repository_never_runs_from_a_snapshot(
    tmp_path: Path, key: str, marker: str, body: str
) -> None:
    armed, twin, control = _armed_and_twin(
        tmp_path, _diff_arm(key, marker, body), attributes="*.py diff=evil\n"
    )
    _assert_silent_and_equal(armed, twin)
    assert plain_git_fires(armed, control, ("diff", "--", "a.py"), marker)


# --- a promisor remote whose transport is the repository's program ------------


def test_promisor_remote_named_by_the_repository_never_runs_from_a_snapshot(
    tmp_path: Path,
) -> None:
    armed = build_repo(tmp_path / "armed")
    # b.py's blob is read by the content snapshot, c.py's committed blob by
    # the staged-change digest: both are gone, so only a fetch could answer.
    missing_blob = drop_object(armed, ":b.py")
    drop_object(armed, "HEAD:c.py")
    twin = twin_copy(armed, tmp_path / "twin")
    arm_promisor_remote(armed)
    control = twin_copy(armed, tmp_path / "control")

    _assert_silent_and_equal(armed, twin)
    assert plain_git_fires(
        armed,
        control,
        ("cat-file", "--batch"),
        "lazy_fetch",
        stdin=f"{missing_blob}\n".encode(),
    )


# --- environment that would point git at another repository ------------------


@pytest.mark.parametrize("variable", ["GIT_DIR", "GIT_INDEX_FILE"])
def test_inherited_git_redirect_does_not_reach_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    analysed = build_repo(tmp_path / "analysed")
    other = tmp_path / "other"
    other.mkdir()
    setup_git(other, "init", "-q")
    (other / "other_only.py").write_text("x = 1\n", "utf-8")
    setup_git(other, "add", "-A")
    setup_git(other, "commit", "-qm", "other")
    own_answer = git_snapshot.list_git_workspace_paths(analysed.root)
    assert own_answer.available and "a.py" in own_answer.paths

    redirect = other / ".git" if variable == "GIT_DIR" else other / ".git" / "index"
    monkeypatch.setenv(variable, str(redirect))
    plain = subprocess.run(
        ["git", "ls-files", "--cached"],
        cwd=analysed.root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "other_only.py" in plain.stdout, "positive control: no redirect"

    assert git_snapshot.list_git_workspace_paths(analysed.root) == own_answer


# --- read-only means read-only (C-04) ----------------------------------------


@pytest.mark.parametrize("call_name", sorted(_SNAPSHOT_CALLS))
def test_snapshot_reads_never_write_the_repository(
    tmp_path: Path, call_name: str
) -> None:
    repo = build_repo(tmp_path / "repo")
    control = twin_copy(repo, tmp_path / "control")
    before = git_dir_digest(repo.root)
    _SNAPSHOT_CALLS[call_name](repo.root)
    assert git_dir_digest(repo.root) == before
    # Positive control: the same stat-only dirt makes plain git rewrite it.
    control_before = git_dir_digest(control.root)
    setup_git(control.root, "status", "--porcelain=v1")
    assert git_dir_digest(control.root) != control_before


# --- clean trees answer as before ---------------------------------------------


@pytest.mark.parametrize("call_name", sorted(_SNAPSHOT_CALLS))
@pytest.mark.parametrize("population", CLEAN_POPULATIONS)
def test_snapshot_answers_as_plain_git_did_on_a_clean_tree(
    tmp_path: Path, population: str, call_name: str
) -> None:
    repo = build_population(tmp_path / "repo", population)
    legacy_twin = twin_copy(repo, tmp_path / "legacy")
    call = _SNAPSHOT_CALLS[call_name]
    owner_answer = call(repo.root)
    assert call(repo.root) == owner_answer, "a read changed the next answer"
    with pytest.MonkeyPatch.context() as patch:
        install_legacy_git(patch)
        legacy_first = call(legacy_twin.root)
        legacy_settled = call(legacy_twin.root)
    if population == "stat_dirt" and call_name == "content_snapshot":
        # The one measured difference, and the positive control that this
        # comparison sees one: plain git rewrote the index on its first read,
        # so its first answer called b.py racy and its next one tracked it.
        # The owner never rewrites it and answers the settled answer at once.
        assert legacy_first != legacy_settled
        assert owner_answer == legacy_settled
    else:
        assert owner_answer == legacy_first == legacy_settled


# --- the ratchet: one owner starts git ---------------------------------------

_PACKAGE = Path(__file__).resolve().parents[1] / "codeclone"
_GIT_OWNER = "codeclone/utils/git_process.py"

#: Every module of the package that starts a process, and what it starts.
_PROCESS_LAUNCHERS: dict[str, str] = {
    _GIT_OWNER: "git, for every caller: the one hardened call form",
    "codeclone/baseline/publish.py": "ps, for the publish lock's process start",
    "codeclone/core/parallelism.py": "this interpreter, as analysis workers",
    "codeclone/memory/jobs/spawn.py": "this interpreter, as the projection worker",
    "codeclone/workspace_intent/lifecycle.py": "ps, for an intent holder's start",
}

_LAUNCH_CALLS = frozenset(
    {
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
        "concurrent.futures.ProcessPoolExecutor",
        "multiprocessing.Pool",
        "multiprocessing.Process",
        "os.popen",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.startfile",
        "os.system",
        "pty.spawn",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.getoutput",
        "subprocess.getstatusoutput",
        "subprocess.run",
    }
)
_LAUNCH_PREFIXES = ("os.exec", "os.spawn")


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                aliases[name.asname or name.name.split(".")[0]] = (
                    name.name if name.asname else name.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for name in node.names:
                aliases[name.asname or name.name] = f"{node.module}.{name.name}"
    return aliases


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return None if head is None else f"{head}.{node.attr}"
    return None


def _names_git(node: ast.expr | None) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        words = node.value.split()
        return bool(words) and Path(words[0]).name in {"git", "git.exe"}
    if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
        return _names_git(node.elts[0])
    return False


def _qualified_call(node: ast.Call, aliases: dict[str, str]) -> str:
    dotted = _dotted(node.func) or ""
    head, _, rest = dotted.partition(".")
    return aliases.get(head, head) + (f".{rest}" if rest else "")


def _argv(node: ast.Call) -> ast.expr | None:
    keywords = [keyword.value for keyword in node.keywords if keyword.arg == "args"]
    return keywords[-1] if keywords else (node.args[0] if node.args else None)


def _launch(node: ast.Call, aliases: dict[str, str]) -> tuple[int, str, bool] | None:
    qualified = _qualified_call(node, aliases)
    names_git = _names_git(_argv(node))
    if qualified == "shutil.which":
        return (node.lineno, qualified, True) if names_git else None
    if qualified in _LAUNCH_CALLS or qualified.startswith(_LAUNCH_PREFIXES):
        return (node.lineno, qualified, names_git)
    return None


def process_launches(source: str) -> list[tuple[int, str, bool]]:
    """``(line, qualified call, names git)`` for every process launch."""

    tree = ast.parse(source)
    aliases = _import_aliases(tree)
    calls = (node for node in ast.walk(tree) if isinstance(node, ast.Call))
    return sorted(
        launch for node in calls if (launch := _launch(node, aliases)) is not None
    )


def _package_launches() -> dict[str, list[tuple[int, str, bool]]]:
    found: dict[str, list[tuple[int, str, bool]]] = {}
    for path in sorted(_PACKAGE.rglob("*.py")):
        launches = process_launches(path.read_text("utf-8"))
        if launches:
            found[path.relative_to(_PACKAGE.parent).as_posix()] = launches
    return found


def test_no_module_but_the_owner_starts_git() -> None:
    found = _package_launches()
    direct_git = {
        module: [line for line, _call, names_git in launches if names_git]
        for module, launches in found.items()
        if module != _GIT_OWNER
    }
    assert {module: lines for module, lines in direct_git.items() if lines} == {}
    unnamed = sorted(set(found) - set(_PROCESS_LAUNCHERS))
    assert unnamed == [], "a module starts a process without being named"
    stale = sorted(set(_PROCESS_LAUNCHERS) - set(found))
    assert stale == [], "a named launcher no longer starts anything"


@pytest.mark.parametrize(
    "source",
    [
        'import subprocess\nsubprocess.run(["git", "status"])\n',
        'import subprocess as sp\nsp.Popen(("git", "log"), cwd=".")\n',
        'from subprocess import check_output as co\nco(args=["/usr/bin/git"])\n',
        'import os\nos.system("git status")\n',
        'import os\nos.execvp("git", ["git", "status"])\n',
        'import shutil\nshutil.which("git")\n',
    ],
    ids=["run", "alias", "from-import", "system", "exec", "which"],
)
def test_ratchet_sees_every_spelling_of_a_direct_git_launch(source: str) -> None:
    assert [names_git for _line, _call, names_git in process_launches(source)] == [True]


def test_ratchet_tells_a_launch_that_is_not_git() -> None:
    launches = process_launches('import subprocess\nsubprocess.run(["ps", "-p"])\n')
    assert launches == [(2, "subprocess.run", False)]
