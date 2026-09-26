# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Controls for the live-state boundary (``tests/_live_state.py``).

Every enforcement gets a positive control that goes through the real choke
point -- ``sqlite3.connect``, ``subprocess.run``, ``resolve_memory_config``,
``resolve_under_repo_root``, ``git status`` -- and a negative control showing
the fence lets legitimate
work through. The end-to-end controls run an inner pytest session wired
through this suite's own conftest, so the wiring is measured, not the helper
alone. None of the probes can write live state even when the fence they
measure is missing: the database they name does not exist and is opened
with ``mode=rw``, which SQLite refuses to create, and the git pathspec they
name does not exist, which git refuses to add.
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.utils.repo_identity import resolve_repository_anchor_root
from codeclone.utils.repo_paths import (
    PathOutsideRepoError,
    RepoPathPolicy,
    resolve_under_repo_root,
)
from tests._live_state import (
    HOSTING_CHECKOUT,
    LiveStateGuard,
    LiveStateViolation,
    capture_service_state,
    capture_tree_status,
    is_read_only_git_command,
    live_state_guard,
    service_state_residue,
    sqlite_database_path,
    tree_residue,
)

_PROBE_NAME = "live-state-probe-does-not-exist.sqlite3"


def _guard(request: pytest.FixtureRequest) -> LiveStateGuard:
    return live_state_guard(request.config)


def _live_probe_uri() -> str:
    """A database under the live anchor's service directory that does not
    exist, opened ``mode=rw`` so that without the fence SQLite refuses to
    create it and nothing is written either way."""

    anchor = resolve_repository_anchor_root(HOSTING_CHECKOUT)
    path = anchor / ".codeclone" / "db" / _PROBE_NAME
    assert not path.exists(), f"the probe path must not exist: {path}"
    return f"file:{quote(str(path), safe='/')}?mode=rw"


# ---------------------------------------------------------------------------
# The boundary names the right places
# ---------------------------------------------------------------------------


def test_the_boundary_names_the_hosting_checkout_its_anchor_and_the_home_cache(
    request: pytest.FixtureRequest,
) -> None:
    boundary = _guard(request).boundary
    anchor = resolve_repository_anchor_root(HOSTING_CHECKOUT)

    assert boundary.live_root_of(HOSTING_CHECKOUT) is not None
    assert boundary.live_root_of(anchor) is not None
    assert boundary.state_dir_of(
        HOSTING_CHECKOUT / ".codeclone" / "db" / "cache.sqlite3"
    )
    assert boundary.state_dir_of(
        anchor / ".codeclone" / "memory" / "engineering_memory.sqlite3"
    )
    assert boundary.state_dir_of(Path("~/.cache/codeclone/cache.json").expanduser())


def test_the_boundary_leaves_a_temporary_directory_alone(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    boundary = _guard(request).boundary

    assert boundary.live_root_of(tmp_path) is None
    assert (
        boundary.state_dir_of(tmp_path / ".codeclone" / "db" / "cache.sqlite3") is None
    )


# ---------------------------------------------------------------------------
# Enforcement 1: the live repository's default durable state goes to scratch
# ---------------------------------------------------------------------------


def test_the_live_repository_default_memory_store_is_relocated_to_scratch(
    request: pytest.FixtureRequest,
) -> None:
    guard = _guard(request)

    config = resolve_memory_config(HOSTING_CHECKOUT)

    assert config.db_path == (
        guard.scratch / ".codeclone" / "memory" / "engineering_memory.sqlite3"
    )
    assert guard.boundary.live_root_of(config.db_path) is None
    # The semantic paths are CONFIGURED in this repository's pyproject and so
    # resolve under the analysed root rather than its anchor; they move too.
    assert Path(config.semantic.index_path).is_relative_to(guard.scratch)
    assert Path(config.semantic.embedding_cache_dir).is_relative_to(guard.scratch)


def test_a_relocated_path_is_contained_exactly_where_its_original_is(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    """The product's one containment gate reads a relocated path as the path
    it stands for: contained under the live root the original came from,
    foreign anywhere else, and scratch itself is not a passport.

    Two originals with two roots: the store is a DEFAULT and so comes from
    the anchor (the main checkout, for a linked worktree); the embedding
    cache is CONFIGURED in this repository's pyproject and so comes from the
    analysed root.
    """

    guard = _guard(request)
    anchor = resolve_repository_anchor_root(HOSTING_CHECKOUT)
    config = resolve_memory_config(HOSTING_CHECKOUT)
    store = config.db_path
    cache = Path(config.semantic.embedding_cache_dir)
    assert store.is_relative_to(guard.scratch), "the probe is not relocated"
    assert cache.is_relative_to(guard.scratch), "the probe is not relocated"
    policy = RepoPathPolicy(allow_absolute=True)

    assert resolve_under_repo_root(anchor, store, policy=policy) == store
    assert resolve_under_repo_root(HOSTING_CHECKOUT, cache, policy=policy) == cache
    # A path beneath a twin follows it.
    beneath = cache / "model"
    assert resolve_under_repo_root(HOSTING_CHECKOUT, beneath, policy=policy) == (
        beneath
    )

    # Foreign where the original is foreign.
    with pytest.raises(PathOutsideRepoError):
        resolve_under_repo_root(tmp_path, cache, policy=policy)
    if anchor != guard.hosting_checkout:
        # In a linked worktree the store's original lies under the main
        # checkout, which is not this worktree -- as on the pristine product.
        with pytest.raises(PathOutsideRepoError):
            resolve_under_repo_root(HOSTING_CHECKOUT, store, policy=policy)
    # Under scratch, standing for nothing: as foreign as any outside path.
    with pytest.raises(PathOutsideRepoError):
        resolve_under_repo_root(
            HOSTING_CHECKOUT, guard.scratch / "not-a-twin.sqlite3", policy=policy
        )


def test_a_consumer_that_re_validates_a_relocated_path_gets_the_original_answer(
    request: pytest.FixtureRequest,
) -> None:
    """The analytics config takes the memory config's embedding cache and
    re-validates it under the analysed root -- the consumer that measured the
    containment hole (2026-09-07: ``path escapes repository root``). It gets
    the relocated path back, with no analytics-specific hook. Its OWN state
    paths are not memory state: they resolve where they always did, and the
    SQLite fence, not a relocation, stands between a test and them."""

    from codeclone.config.analytics import resolve_analytics_config

    guard = _guard(request)
    memory = resolve_memory_config(HOSTING_CHECKOUT)

    config = resolve_analytics_config(HOSTING_CHECKOUT)

    assert config.embedding_cache_dir == Path(memory.semantic.embedding_cache_dir)
    assert config.embedding_cache_dir.is_relative_to(guard.scratch)
    assert guard.boundary.live_root_of(config.db_path) == guard.boundary.live_root_of(
        HOSTING_CHECKOUT
    )


def test_a_temporary_repository_keeps_its_own_default_memory_store(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    config = resolve_memory_config(root)

    assert (
        config.db_path == root / ".codeclone" / "memory" / "engineering_memory.sqlite3"
    )


def test_a_test_scratch_anchor_is_private_and_removed_when_the_test_ends(
    request: pytest.FixtureRequest,
) -> None:
    """Drives the guard's own per-test lifecycle for a synthetic test, so the
    pin is order-independent: the running test's scratch is handed back at
    the end and its teardown removes it as usual."""

    guard = _guard(request)
    current = guard.scratch
    assert current != guard.session_scratch
    assert current.is_dir() and current.is_relative_to(guard.scratch_root)

    guard.enter_test("synthetic::test_probe", None)
    probe = guard.scratch
    assert probe != current and probe.is_dir()
    (probe / "left-here").write_text("by the synthetic test\n", encoding="utf-8")
    guard.exit_test()

    assert not probe.exists()
    assert guard.scratch == guard.session_scratch
    guard.enter_test(request.node.nodeid, None)
    assert guard.scratch != guard.session_scratch


# ---------------------------------------------------------------------------
# Enforcement 2: the SQLite open fence
# ---------------------------------------------------------------------------


def test_an_open_of_a_database_under_a_live_service_directory_is_refused(
    request: pytest.FixtureRequest,
) -> None:
    guard = _guard(request)

    with pytest.raises(
        LiveStateViolation, match="reaches live CodeClone state"
    ) as caught:
        sqlite3.connect(_live_probe_uri(), uri=True)

    # The refusal is also recorded for the teardown check, so a product
    # ``except Exception`` cannot make the attempt quiet. Cleared here because
    # this test's own teardown would otherwise report the control as a hit.
    assert guard.violations == [caught.value]
    guard.violations.clear()


def test_an_open_of_a_database_elsewhere_passes_through(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "fine.sqlite3")
    try:
        assert connection.execute("select 1").fetchone() == (1,)
    finally:
        connection.close()


def test_the_fence_reads_every_database_form_sqlite_accepts(tmp_path: Path) -> None:
    target = tmp_path / "x.sqlite3"

    assert sqlite_database_path(":memory:") is None
    assert sqlite_database_path("") is None
    assert sqlite_database_path("file::memory:?cache=shared") is None
    assert sqlite_database_path("file:x?mode=memory") is None
    assert sqlite_database_path(None) is None
    assert sqlite_database_path(str(target)) == target
    assert sqlite_database_path(target) == target
    assert sqlite_database_path(bytes(target)) == target
    assert (
        sqlite_database_path(f"file:{quote(str(target), safe='/')}?mode=ro") == target
    )
    assert (
        sqlite_database_path("relative.sqlite3")
        == Path.cwd().resolve() / "relative.sqlite3"
    )


@pytest.mark.live_state(reason="positive control: the marker must lift the fence")
def test_the_opt_in_marker_lifts_the_fence(request: pytest.FixtureRequest) -> None:
    assert _guard(request).lifted

    # Past the fence, SQLite itself refuses ``mode=rw`` on a missing file.
    with pytest.raises(sqlite3.OperationalError):
        sqlite3.connect(_live_probe_uri(), uri=True)


# ---------------------------------------------------------------------------
# Enforcement 3: the git mutation fence
# ---------------------------------------------------------------------------


def test_a_mutating_git_command_under_a_live_root_is_refused(
    request: pytest.FixtureRequest,
) -> None:
    guard = _guard(request)

    with pytest.raises(LiveStateViolation, match="would mutate the live repository"):
        subprocess.run(
            ["git", "add", "-N", "live-state-probe-does-not-exist.py"],
            cwd=HOSTING_CHECKOUT,
            capture_output=True,
        )

    assert len(guard.violations) == 1
    guard.violations.clear()


def test_the_git_fence_follows_dash_c_into_a_live_root(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    guard = _guard(request)

    with pytest.raises(LiveStateViolation):
        subprocess.run(
            ["git", "-C", str(HOSTING_CHECKOUT), "update-index", "--refresh"],
            cwd=tmp_path,
            capture_output=True,
        )

    assert len(guard.violations) == 1
    guard.violations.clear()


def test_a_reading_git_command_under_a_live_root_passes_through() -> None:
    completed = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=HOSTING_CHECKOUT,
        capture_output=True,
        check=True,
        text=True,
    )
    assert completed.stdout.strip() == "true"


def test_a_mutating_git_command_in_a_temporary_repository_passes_through(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True)

    listed = subprocess.run(
        ["git", "ls-files"], cwd=tmp_path, capture_output=True, check=True, text=True
    )
    assert listed.stdout.split() == ["a.py"]


@pytest.mark.parametrize(
    ("verb", "arguments", "read_only"),
    [
        ("status", ("--porcelain",), True),
        ("ls-files", ("-z", "--", "codeclone"), True),
        ("rev-parse", ("--abbrev-ref", "HEAD"), True),
        ("log", ("-1", "--format=%ct", "HEAD"), True),
        ("diff", ("--name-only", "HEAD", "--"), True),
        ("remote", ("get-url", "origin"), True),
        ("remote", ("add", "origin", "url"), False),
        ("config", ("--get", "user.name"), True),
        ("config", ("user.name", "Someone"), False),
        ("worktree", ("list", "--porcelain"), True),
        ("worktree", ("add", "path"), False),
        ("stash", ("list",), True),
        ("stash", (), False),
        ("symbolic-ref", ("HEAD",), True),
        ("symbolic-ref", ("HEAD", "refs/heads/main"), False),
        ("branch", ("--show-current",), True),
        ("branch", ("feature",), False),
        ("tag", ("--list",), True),
        ("tag", ("v1",), False),
        ("hash-object", ("file",), True),
        ("hash-object", ("-w", "file"), False),
        ("add", ("-N", "file"), False),
        ("rm", ("--cached", "file"), False),
        ("commit", ("-m", "x"), False),
        ("update-index", ("--refresh",), False),
        ("checkout", ("--", "file"), False),
        ("frobnicate", (), False),
    ],
)
def test_the_read_verb_table_refuses_what_it_does_not_know(
    verb: str, arguments: tuple[str, ...], read_only: bool
) -> None:
    assert is_read_only_git_command(verb, arguments) is read_only


# ---------------------------------------------------------------------------
# Enforcement 4: the tree residue gate
# ---------------------------------------------------------------------------


def test_the_tree_gate_names_what_a_test_leaves_behind_and_what_it_took(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    (tmp_path / "taken.py").write_text("x = 1\n", encoding="utf-8")
    before = capture_tree_status(tmp_path)
    assert before is not None

    (tmp_path / "leftover.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "taken.py").unlink()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "m.cpython.pyc").write_bytes(b"")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "v").write_text("", encoding="utf-8")
    after = capture_tree_status(tmp_path)
    assert after is not None

    assert tree_residue(before, after) == (("?? leftover.py",), ("?? taken.py",))


def test_the_tree_gate_says_when_it_cannot_measure(tmp_path: Path) -> None:
    assert capture_tree_status(tmp_path / "not-a-repository") is None


def test_the_service_state_gate_names_what_a_test_writes_into_codeclone(
    tmp_path: Path,
) -> None:
    """New, rewritten and removed files inside ``.codeclone/`` are named;
    the state other fences own there is not.

    ``report.html`` exists before, as it does in a checkout where someone
    ran ``codeclone --html`` by hand: rewriting it is residue even though
    no new path appears.
    """
    service = tmp_path / ".codeclone"
    (service / "db").mkdir(parents=True)
    (service / "report.html").write_text("<html>by hand</html>", encoding="utf-8")
    (service / "notes.txt").write_text("kept by the operator", encoding="utf-8")
    (service / "db" / "cache.sqlite3").write_bytes(b"")
    before = capture_service_state(tmp_path)

    (service / "report.html").write_text("<html>by a test</html>", encoding="utf-8")
    (service / "report.json").write_text("{}", encoding="utf-8")
    (service / "notes.txt").unlink()
    # The controller's own writes, concurrent with any session:
    (service / "db" / "cache.sqlite3-wal").write_bytes(b"")
    (service / "db" / "intents.sqlite3.lock").write_bytes(b"")
    (service / "intents").mkdir()
    (service / "intents" / "1-2-intent-a.json").write_text("{}", encoding="utf-8")
    (service / "memory").mkdir()
    (service / "memory" / ".memory_init.lock").write_bytes(b"")
    after = capture_service_state(tmp_path)

    assert service_state_residue(before, after) == (
        ("report.json",),
        ("report.html",),
        ("notes.txt",),
    )


def _assert_no_service_state_residue(guard: LiveStateGuard) -> None:
    """Nothing a test wrote is left inside the host's ``.codeclone/``.

    ``git status`` folds an existing ignored directory into one entry, so the
    tree gate below is blind inside it; this snapshot is not, and it needs
    no git.
    """
    appeared, rewritten, vanished = service_state_residue(
        guard.service_baseline, capture_service_state(guard.hosting_checkout)
    )
    assert (appeared, rewritten, vanished) == ((), (), ()), (
        "the suite left residue in the hosting checkout's .codeclone/ "
        f"({guard.hosting_checkout}):\n  appeared: {list(appeared)}\n"
        f"  rewritten: {list(rewritten)}\n  vanished: {list(vanished)}"
    )


def test_the_suite_left_no_residue_in_the_hosting_checkout(
    request: pytest.FixtureRequest,
) -> None:
    """Runs last (the conftest reorders it): the tree, before and after.

    A write that reached the hosting checkout by a route the in-process
    fences do not see -- a child process, a file written into the package --
    shows up here as an entry that appeared or vanished. Runtime artifacts of
    the run itself (``__pycache__``, ``.pytest_cache``, coverage output) are
    excluded by name; inside ``.codeclone/`` the service-state snapshot
    answers first.
    """

    guard = _guard(request)
    _assert_no_service_state_residue(guard)
    if guard.baseline is None:
        pytest.skip(
            "INCONCLUSIVE: git status of the hosting checkout was unavailable, "
            "so residue could not be measured"
        )
    after = capture_tree_status(guard.hosting_checkout)
    assert after is not None, "git status became unavailable during the session"

    appeared, vanished = tree_residue(guard.baseline, after)

    assert (appeared, vanished) == ((), ()), (
        "the suite left residue in the hosting checkout "
        f"({guard.hosting_checkout}):\n  appeared: {list(appeared)}\n"
        f"  vanished: {list(vanished)}"
    )


# ---------------------------------------------------------------------------
# The wiring, end to end: an inner session through this suite's own conftest
# ---------------------------------------------------------------------------

_INNER_CONFTEST = """
from tests.conftest import (
    pytest_collection_modifyitems,
    pytest_configure,
    pytest_runtest_setup,
    pytest_runtest_teardown,
    pytest_sessionfinish,
    pytest_sessionstart,
    pytest_terminal_summary,
)
"""

_INNER_PROBE = """
import sqlite3
from urllib.parse import quote

from codeclone.utils.repo_identity import resolve_repository_anchor_root
from tests._live_state import HOSTING_CHECKOUT

PROBE = "file:{path}?mode=rw".format(
    path=quote(
        str(
            resolve_repository_anchor_root(HOSTING_CHECKOUT)
            / ".codeclone" / "db" / "live-state-probe-does-not-exist.sqlite3"
        ),
        safe="/",
    )
)
"""


def _inner_session(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", str(HOSTING_CHECKOUT))
    pytester.makeconftest(_INNER_CONFTEST)


def test_a_test_that_opens_a_live_database_reds_under_the_wired_mechanism(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _inner_session(pytester, monkeypatch)
    pytester.makepyfile(
        test_offender=_INNER_PROBE
        + """
def test_offender():
    sqlite3.connect(PROBE, uri=True)
"""
    )

    result = pytester.runpytest_subprocess("-p", "no:cacheprovider", "test_offender.py")

    result.assert_outcomes(failed=1, errors=1)
    result.stdout.fnmatch_lines(["*LiveStateViolation*reaches live CodeClone state*"])
    result.stdout.fnmatch_lines(["*the test reached for live CodeClone state*"])


def test_a_swallowed_violation_still_reds_at_teardown(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A product ``except Exception`` around the open cannot make it quiet."""

    _inner_session(pytester, monkeypatch)
    pytester.makepyfile(
        test_swallow=_INNER_PROBE
        + """
def test_swallow():
    try:
        sqlite3.connect(PROBE, uri=True)
    except Exception:
        pass
"""
    )

    result = pytester.runpytest_subprocess("-p", "no:cacheprovider", "test_swallow.py")

    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*the test reached for live CodeClone state*"])


def test_a_marked_test_runs_lifted_and_is_listed_in_the_summary(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _inner_session(pytester, monkeypatch)
    pytester.makepyfile(
        test_opted=_INNER_PROBE
        + """
import pytest

@pytest.mark.live_state(reason="control: the live store is the subject")
def test_opted_in():
    with pytest.raises(sqlite3.OperationalError):
        sqlite3.connect(PROBE, uri=True)
"""
    )

    result = pytester.runpytest_subprocess("-p", "no:cacheprovider", "test_opted.py")

    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(
        [
            "*live-state opt-ins*",
            "*test_opted_in*control: the live store is the subject*",
        ]
    )


def test_a_marker_without_a_reason_is_refused(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal is a worded refusal naming the test, not a crash.

    Measured 2026-09-07 (mutation M8): with the reason check removed, the
    setup hook crashed on ``None.strip()`` -- also one ERROR -- and the
    refusal's wording was matched in the traceback's echo of the hook's own
    source, so the pin stayed green with the check gone. The wording now
    carries the test's node id, which no source echo contains, and a crash
    is refused outright.
    """

    _inner_session(pytester, monkeypatch)
    pytester.makepyfile(
        test_unreasoned="""
import pytest

@pytest.mark.live_state
def test_unreasoned():
    pass
"""
    )

    result = pytester.runpytest_subprocess(
        "-p", "no:cacheprovider", "test_unreasoned.py"
    )

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        [
            "*test_unreasoned.py::test_unreasoned: "
            "@pytest.mark.live_state requires reason=*"
        ]
    )
    result.stdout.no_fnmatch_line("*AttributeError*")


# The same gate, end to end: an inner session whose guard stands on a
# temporary checkout, so the control writes into a host that is not live.
_INNER_HOST_CONFTEST = """
import os
from pathlib import Path

from tests._live_state import LIVE_STATE_GUARD_KEY, LiveStateGuard
from tests.conftest import (
    pytest_collection_modifyitems,
    pytest_configure,
    pytest_runtest_setup,
    pytest_runtest_teardown,
    pytest_sessionfinish,
    pytest_terminal_summary,
)


def pytest_sessionstart(session):
    session.config.stash[LIVE_STATE_GUARD_KEY] = LiveStateGuard.install(
        hosting_checkout=Path(os.environ["LIVE_STATE_TEST_HOST"])
    )
"""

_INNER_HOST_WRITER = """
import os
from pathlib import Path

from tests.test_live_state_isolation import (
    test_the_suite_left_no_residue_in_the_hosting_checkout,
)


def test_writer():
    target = Path(os.environ["LIVE_STATE_TEST_HOST"]) / ".codeclone" / {relative!r}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("written by a test", encoding="utf-8")
"""


@pytest.mark.parametrize(
    ("relative", "outcomes", "named"),
    [
        pytest.param(
            "report.html",
            {"passed": 1, "failed": 1},
            # fnmatch reads ``[...]`` as a character class, hence the ``?``.
            [
                "*residue in the hosting checkout's .codeclone/*",
                "*appeared: ?'report.html'?*",
            ],
            id="report-reds",
        ),
        pytest.param(
            "intents/1-2-intent-a.json",
            {"passed": 2},
            [],
            id="controller-state-passes",
        ),
    ],
)
def test_a_write_into_the_host_codeclone_reds_the_wired_gate(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    relative: str,
    outcomes: dict[str, int],
    named: list[str],
) -> None:
    """The gate, run last by the wired conftest, names a report a test left
    in the host's ``.codeclone/`` -- and lets be both the controller's own
    state and a file the operator had there before the session began."""

    host = tmp_path / "host"
    (host / ".codeclone").mkdir(parents=True)
    (host / ".codeclone" / "notes.txt").write_text("the operator's", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=host, check=True)
    monkeypatch.setenv("PYTHONPATH", str(HOSTING_CHECKOUT))
    monkeypatch.setenv("LIVE_STATE_TEST_HOST", str(host))
    pytester.makeconftest(_INNER_HOST_CONFTEST)
    pytester.makepyfile(test_writes=_INNER_HOST_WRITER.format(relative=relative))

    result = pytester.runpytest_subprocess("-p", "no:cacheprovider", "test_writes.py")

    result.assert_outcomes(**outcomes)
    result.stdout.fnmatch_lines(named)
