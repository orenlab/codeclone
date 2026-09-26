# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The live-state boundary: what a test may not write, stated once.

A test may READ the repository that hosts it. The real checkout is a
legitimate measurement subject -- the suppression ratchet analyses it cold,
the architecture guards parse it, the memory extractors walk it -- and none of
that is the hazard. The hazard is a test that WRITES durable CodeClone state
under a live repository: the engineering-memory store, the run store, the
analysis cache, the audit and intent registries, a file dropped into the
package tree, an entry pushed into the git index.

Measured 2026-09-07 (the reference incident): ``codeclone setup status`` run
in-process from a linked worktree opened the SHARED engineering-memory store
of the main checkout and migrated its schema, and every other checkout still
on the older schema died on its next start. A worktree does not save a test
from this, because durable memory state deliberately anchors at the main
checkout (``codeclone.utils.repo_identity``), and ``CODECLONE_MEMORY_DB_PATH``
does not save it either: measured the same day, an absolute path outside the
analysed root is refused by ``memory.db_path must stay under the repository
root`` -- the variable is a containment fence, not a redirect.

So the boundary is enforced here, in the test process, at the points every
durable write has to pass:

* every engineering-memory state path -- the store, the semantic index, the
  embedding cache; default or configured -- that would land under a live
  repository is relocated, layout intact, to a scratch directory that exists
  only for the current test, so a test that never heard of the hazard is
  isolated without knowing it; and the product's one containment gate reads
  such a relocated path as contained exactly where its original is, so a
  consumer that re-validates a memory path under the root it came from --
  the analytics config does -- gets the answer the original would have got,
  whichever consumer it is;
* ``sqlite3.connect`` refuses any database that lives under a live service
  directory -- one choke point, keyed on the physical path, covering every
  SQLite-backed store the product owns;
* a ``git`` subprocess that would mutate a live repository is refused before
  it is spawned, on a read-verb allowlist (an unknown verb under a live root
  is refused, never assumed harmless);
* the working tree of the hosting checkout is compared before and after the
  session, so residue that reached the tree by any other route is named --
  and so are the files inside its ``.codeclone/`` that no other fence
  answers for (a report, any stray file), new, rewritten or removed.

One marker, ``live_state(reason=...)``, lifts the in-process enforcements
for a test whose legitimate subject IS live state. It is loud on purpose:
every opt-in is listed in the terminal summary.

What this module does NOT see, stated so nobody assumes otherwise: a child
process that opens a database or writes a file on its own (only the tree
gate catches its residue), a plain file write into the tree that the test
cleans up before the session ends, and ``os.system``/``os.exec*`` spawns.
"""

from __future__ import annotations

import os
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import pytest

LIVE_STATE_MARKER = "live_state"

#: The one test that measures the whole session; the conftest runs it last.
TREE_RESIDUE_GATE_TEST = "test_the_suite_left_no_residue_in_the_hosting_checkout"

#: The checkout whose ``tests/`` package this module belongs to.
HOSTING_CHECKOUT = Path(__file__).resolve().parents[1]


class LiveStateViolation(RuntimeError):
    """A test reached for durable CodeClone state under a live repository."""


# ---------------------------------------------------------------------------
# The boundary
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiveStateBoundary:
    """Live repository roots and the service directories no test may open.

    ``roots`` are the repositories a test could reach without meaning to: the
    checkout hosting the tests, the directory the suite was launched from, and
    the durable-state anchor of each (the main checkout, for a linked
    worktree). ``state_dirs`` are CodeClone's own service directories for
    those roots -- ``.codeclone/``, the legacy ``.cache/codeclone/`` and the
    user's ``~/.cache/codeclone`` -- as the product itself defines them.
    """

    roots: tuple[Path, ...]
    state_dirs: tuple[Path, ...]

    def live_root_of(self, path: Path) -> Path | None:
        """The live root ``path`` lies under, or ``None``."""

        resolved = _realpath(path)
        for root in self.roots:
            if resolved == root or resolved.is_relative_to(root):
                return root
        return None

    def state_dir_of(self, path: Path) -> Path | None:
        """The live service directory ``path`` lies under, or ``None``."""

        resolved = _realpath(path)
        for directory in self.state_dirs:
            if resolved == directory or resolved.is_relative_to(directory):
                return directory
        return None


def discover_live_state_boundary(
    *,
    checkout: Path | None = None,
    launch_dir: Path | None = None,
) -> LiveStateBoundary:
    """Compute the boundary from the product's own notions of anchor and
    service directory, so a change to either moves the fence with it."""

    from codeclone.paths.workspace import service_directories
    from codeclone.utils.repo_identity import resolve_repository_anchor_root

    roots: set[Path] = set()
    for candidate in (checkout or HOSTING_CHECKOUT, launch_dir or Path.cwd()):
        resolved = _realpath(candidate)
        roots.add(resolved)
        roots.add(_realpath(resolve_repository_anchor_root(resolved)))
    state_dirs: set[Path] = set()
    for root in roots:
        state_dirs.update(
            _realpath(directory) for directory in service_directories(root)
        )
    return LiveStateBoundary(
        roots=tuple(sorted(roots)),
        state_dirs=tuple(sorted(state_dirs)),
    )


def _realpath(path: Path) -> Path:
    return Path(os.path.realpath(os.path.expanduser(str(path))))


# ---------------------------------------------------------------------------
# Enforcement 1: a live repository's memory state paths go to scratch
# ---------------------------------------------------------------------------


def make_redirected_state_path_resolver(
    real_resolver: Callable[..., Path],
    *,
    boundary: LiveStateBoundary,
    scratch_anchor: Callable[[], Path],
    on_redirect: Callable[[Path, Path], None],
) -> Callable[..., Path]:
    """Wrap the memory-config state-path resolver so a LIVE destination
    becomes the same path under scratch.

    The product resolves three durable paths through this one function --
    the store, the semantic index and the embedding cache -- and resolves a
    DEFAULT under the repository anchor (the main checkout, for a worktree)
    but a CONFIGURED one under the analysed root. Both can land in a live
    repository, so the redirect keys on where the path lands, not on how it
    was chosen, and keeps the tail (``.codeclone/memory/...``) so lock files
    and siblings derived from it stay together. Every other answer passes
    through untouched: a temporary repository keeps its own state.

    Every relocation is reported as ``(twin, original)`` so the containment
    gate below can read the twin as the path it stands for.
    """

    def resolve_state_path(**kwargs: Any) -> Path:
        resolved = real_resolver(**kwargs)
        live_root = boundary.live_root_of(resolved)
        if live_root is None:
            return resolved
        original = _realpath(resolved)
        twin = scratch_anchor() / original.relative_to(live_root)
        on_redirect(twin, original)
        return twin

    return resolve_state_path


# ---------------------------------------------------------------------------
# Enforcement 1, other side: a relocated path is contained where its original is
# ---------------------------------------------------------------------------


def make_twin_aware_containment(
    real_is_relative_to: Callable[[Path, Path], bool],
    *,
    original_of: Callable[[Path], Path | None],
) -> Callable[[Path, Path], bool]:
    """``repo_paths._is_relative_to`` that reads a relocated path as its
    original.

    The product resolves every state path through one containment gate,
    ``resolve_under_repo_root``, and consumers re-run that gate on paths
    they were handed: the analytics config takes the memory config's
    embedding cache and re-validates it under the analysed root. Measured
    2026-09-07: with the memory paths relocated and nothing else, that read
    refused its own input (``path escapes repository root``), because the
    twin lies under scratch and the gate had no idea what it stood for.

    Relocation must not change the gate's answer, so the gate is told: a
    twin, or a path beneath one, is contained exactly where its original is
    -- under the live root it came from, and nowhere else. This is keyed on
    the recorded relocations, not on scratch: a path under scratch that
    stands for nothing is as foreign as any other outside path. Whatever
    re-validates a relocated path through the gate -- the analytics config
    today, the next consumer tomorrow -- gets the original's answer without
    being named here.
    """

    def is_relative_to(path: Path, root: Path) -> bool:
        if real_is_relative_to(path, root):
            return True
        original = original_of(path)
        return original is not None and real_is_relative_to(original, root)

    return is_relative_to


# ---------------------------------------------------------------------------
# Enforcement 2: the SQLite open fence
# ---------------------------------------------------------------------------


def sqlite_database_path(database: object) -> Path | None:
    """The file a ``sqlite3.connect`` database argument names.

    ``None`` for in-memory and temporary databases. ``file:`` URIs are
    unwrapped the way SQLite reads them; a relative name resolves against the
    working directory, which is exactly where an unqualified name would land.
    """

    if isinstance(database, bytes):
        text = os.fsdecode(database)
    elif isinstance(database, os.PathLike):
        text = os.fsdecode(os.fspath(database))
    elif isinstance(database, str):
        text = database
    else:
        return None
    if text in {"", ":memory:"}:
        return None
    if text.startswith("file:"):
        parts = urlsplit(text)
        query = dict(
            item.split("=", 1) for item in parts.query.split("&") if "=" in item
        )
        if query.get("mode") == "memory":
            return None
        text = unquote(parts.path)
        if text in {"", ":memory:"}:
            return None
    return _realpath(Path(os.path.abspath(os.path.expanduser(text))))


def make_guarded_connect(
    real_connect: Callable[..., sqlite3.Connection],
    *,
    boundary: LiveStateBoundary,
    lifted: Callable[[], bool],
    on_violation: Callable[[LiveStateViolation], None],
) -> Callable[..., sqlite3.Connection]:
    """``sqlite3.connect`` that refuses a database under a live service dir."""

    def guarded_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        database = (
            kwargs["database"] if "database" in kwargs else (args[0] if args else None)
        )
        path = sqlite_database_path(database)
        if path is not None and not lifted():
            state_dir = boundary.state_dir_of(path)
            if state_dir is not None:
                violation = LiveStateViolation(
                    f"sqlite3.connect({database!r}) reaches live CodeClone state "
                    f"under {state_dir}; route the store to tmp_path, or mark the "
                    f"test @pytest.mark.{LIVE_STATE_MARKER}(reason=...) if live "
                    "state is its legitimate subject"
                )
                on_violation(violation)
                raise violation
        return real_connect(*args, **kwargs)

    return guarded_connect


# ---------------------------------------------------------------------------
# Enforcement 3: the git mutation fence
# ---------------------------------------------------------------------------

#: Verbs that never write to the repository whatever their arguments.
_GIT_READ_VERBS = frozenset(
    {
        "blame",
        "cat-file",
        "check-attr",
        "check-ignore",
        "cherry",
        "count-objects",
        "describe",
        "diff",
        "diff-files",
        "diff-index",
        "diff-tree",
        "for-each-ref",
        "grep",
        "log",
        "ls-files",
        "ls-remote",
        "ls-tree",
        "merge-base",
        "name-rev",
        "rev-list",
        "rev-parse",
        "shortlog",
        "show",
        "show-ref",
        "status",
        "var",
        "verify-pack",
        "version",
        "whatchanged",
    }
)

_GIT_CONFIG_READ_FLAGS = frozenset(
    {
        "--get",
        "--get-all",
        "--get-regexp",
        "--get-urlmatch",
        "--list",
        "-l",
        "--show-origin",
        "--show-scope",
    }
)
_GIT_BRANCH_WRITE_FLAGS = frozenset(
    {
        "-d",
        "-D",
        "--delete",
        "-m",
        "-M",
        "--move",
        "-c",
        "-C",
        "--copy",
        "-u",
        "--set-upstream-to",
        "--unset-upstream",
        "--edit-description",
        "-f",
        "--force",
    }
)


def _positionals(arguments: Sequence[str]) -> tuple[str, ...]:
    return tuple(argument for argument in arguments if not argument.startswith("-"))


def _first_is(arguments: Sequence[str], allowed: Iterable[str]) -> bool:
    head = arguments[0] if arguments else None
    return head in set(allowed)


_GIT_BRANCH_READ_FLAGS = frozenset(
    {
        "--list",
        "-l",
        "-a",
        "-r",
        "--all",
        "--remotes",
        "--contains",
        "--points-at",
        "--merged",
        "--no-merged",
        "--show-current",
    }
)
_GIT_TAG_READ_FLAGS = frozenset(
    {"--list", "-l", "--contains", "--points-at", "--merged", "--no-merged"}
)


def _git_branch_is_read_only(arguments: Sequence[str]) -> bool:
    if any(argument in _GIT_BRANCH_WRITE_FLAGS for argument in arguments):
        return False
    return not _positionals(arguments) or any(
        argument in _GIT_BRANCH_READ_FLAGS for argument in arguments
    )


def _git_symbolic_ref_is_read_only(arguments: Sequence[str]) -> bool:
    return (
        "-d" not in arguments
        and "--delete" not in arguments
        and len(_positionals(arguments)) == 1
    )


#: Verbs whose read-only-ness depends on their arguments. The table is data for
#: the same reason the read-verb set above is: a verb absent from both is
#: refused by not being listed, never by being enumerated as mutating.
_GIT_ARGUMENT_SENSITIVE_VERBS: dict[str, Callable[[Sequence[str]], bool]] = {
    "config": lambda arguments: any(
        argument in _GIT_CONFIG_READ_FLAGS for argument in arguments
    ),
    "remote": lambda arguments: (
        not arguments or _first_is(arguments, ("get-url", "show", "-v", "--verbose"))
    ),
    "worktree": lambda arguments: _first_is(arguments, ("list",)),
    "stash": lambda arguments: _first_is(arguments, ("list", "show")),
    "notes": lambda arguments: _first_is(arguments, ("list", "show")),
    "reflog": lambda arguments: not arguments or _first_is(arguments, ("show",)),
    "submodule": lambda arguments: _first_is(arguments, ("status",)),
    "symbolic-ref": _git_symbolic_ref_is_read_only,
    "branch": _git_branch_is_read_only,
    "tag": lambda arguments: (
        not _positionals(arguments)
        or any(argument in _GIT_TAG_READ_FLAGS for argument in arguments)
    ),
    "hash-object": lambda arguments: "-w" not in arguments,
}


def is_read_only_git_command(verb: str, arguments: Sequence[str]) -> bool:
    """Whether ``git <verb> <arguments>`` cannot write to its repository.

    The polarity is deliberate: a verb this table does not know is NOT
    read-only. Every mutating verb -- ``add``, ``rm``, ``commit``, ``stash``,
    ``checkout``, ``reset``, ``worktree add``, ``update-index`` and the rest --
    falls through to refusal without being listed.
    """

    if verb in _GIT_READ_VERBS:
        return True
    predicate = _GIT_ARGUMENT_SENSITIVE_VERBS.get(verb)
    if predicate is None:
        return False
    return predicate(arguments)


def _argv_of(args: object, *, shell: bool) -> tuple[str, ...]:
    if isinstance(args, (str, bytes, os.PathLike)):
        text = os.fsdecode(os.fspath(args)) if not isinstance(args, str) else args
        return tuple(shlex.split(text)) if shell else (text,)
    if isinstance(args, (list, tuple)):
        rendered: list[str] = []
        for item in args:
            if isinstance(item, (bytes, os.PathLike)):
                rendered.append(os.fsdecode(os.fspath(item)))
            else:
                rendered.append(str(item))
        return tuple(rendered)
    return ()


_GIT_GLOBAL_FLAGS_WITH_VALUE = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
)


def git_mutation_under_live_root(
    args: object,
    *,
    cwd: object,
    shell: bool,
    boundary: LiveStateBoundary,
) -> LiveStateViolation | None:
    """The violation a ``git`` spawn would commit, or ``None`` when it is fine.

    The repository a spawn acts on is its working directory, moved by every
    ``-C`` in order -- the same rule git applies. Only a working directory
    under a live root is judged; a temporary repository may do anything.
    """

    argv = _argv_of(args, shell=shell)
    if not argv or Path(argv[0]).name not in {"git", "git.exe"}:
        return None
    if cwd is None:
        effective = Path.cwd()
    elif isinstance(cwd, (str, bytes, os.PathLike)):
        effective = Path(os.fsdecode(cwd))
    else:
        return None
    verb: str | None = None
    arguments: tuple[str, ...] = ()
    index = 1
    while index < len(argv):
        token = argv[index]
        if token == "-C" and index + 1 < len(argv):
            effective = effective / argv[index + 1]
            index += 2
            continue
        if token in _GIT_GLOBAL_FLAGS_WITH_VALUE:
            index += 2
            continue
        if token.startswith("-"):
            if token in {"--version", "--help", "-h"}:
                return None
            index += 1
            continue
        verb = token
        arguments = tuple(argv[index + 1 :])
        break
    if verb is None:
        return None
    live_root = boundary.live_root_of(effective)
    if live_root is None or is_read_only_git_command(verb, arguments):
        return None
    return LiveStateViolation(
        f"git {' '.join(argv[1:])} would mutate the live repository at {live_root}; "
        "give the test a temporary repository, or mark it "
        f"@pytest.mark.{LIVE_STATE_MARKER}(reason=...) if live state is its "
        "legitimate subject"
    )


def make_guarded_popen_init(
    real_init: Callable[..., None],
    *,
    boundary: LiveStateBoundary,
    lifted: Callable[[], bool],
    on_violation: Callable[[LiveStateViolation], None],
) -> Callable[..., None]:
    """``subprocess.Popen.__init__`` that refuses a live-mutating ``git``."""

    def guarded_init(
        self: subprocess.Popen[Any], args: object, *rest: Any, **kwargs: Any
    ) -> None:
        if not lifted():
            # Popen(args, bufsize, executable, stdin, stdout, stderr,
            #       preexec_fn, close_fds, shell, cwd, ...): the two we read
            # may arrive positionally.
            shell = bool(kwargs.get("shell", rest[7] if len(rest) > 7 else False))
            cwd = kwargs.get("cwd", rest[8] if len(rest) > 8 else None)
            violation = git_mutation_under_live_root(
                args, cwd=cwd, shell=shell, boundary=boundary
            )
            if violation is not None:
                on_violation(violation)
                raise violation
        real_init(self, args, *rest, **kwargs)

    return guarded_init


# ---------------------------------------------------------------------------
# Enforcement 4: the tree residue gate
# ---------------------------------------------------------------------------

#: Top-level entries a test run legitimately creates or churns in the
#: hosting checkout, and so never count as residue. ``.codeclone/`` is the
#: controller's own service directory, written concurrently by whatever
#: MCP server is coordinating the session, and git folds an existing ignored
#: directory into one entry, so ``git status`` cannot see inside it at all:
#: its contents are measured by the service-state snapshot below instead.
_TREE_GATE_RUNTIME_HEADS = frozenset(
    {
        ".agent-runs",
        ".codeclone",
        ".coverage",
        ".hypothesis",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "coverage.xml",
    }
)


def is_test_runtime_artifact(relative_path: str) -> bool:
    parts = relative_path.rstrip("/").split("/")
    if "__pycache__" in parts:
        return True
    head = parts[0]
    return (
        head in _TREE_GATE_RUNTIME_HEADS
        or head.startswith(".coverage.")
        or head.endswith(".egg-info")
    )


def capture_tree_status(root: Path) -> frozenset[str] | None:
    """``git status`` entries of ``root``, or ``None`` when git cannot say.

    Ignored entries are included in ``matching`` mode so a directory a test
    manufactures under an ignore pattern -- ``site/``, say -- still appears.
    """

    try:
        completed = subprocess.run(
            [
                "git",
                "status",
                "--porcelain=v1",
                "--untracked-files=normal",
                "--ignored=matching",
                "-z",
            ],
            cwd=root,
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return frozenset(item for item in completed.stdout.split("\0") if item)


def tree_residue(
    before: frozenset[str], after: frozenset[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``(appeared, vanished)`` status entries that are not runtime artifacts."""

    def _path_of(entry: str) -> str:
        return entry[3:] if len(entry) > 3 else entry

    appeared = tuple(
        sorted(
            entry
            for entry in after - before
            if not is_test_runtime_artifact(_path_of(entry))
        )
    )
    vanished = tuple(
        sorted(
            entry
            for entry in before - after
            if not is_test_runtime_artifact(_path_of(entry))
        )
    )
    return appeared, vanished


# ---------------------------------------------------------------------------
# Enforcement 4, inside the service directory
# ---------------------------------------------------------------------------

#: One file inside ``.codeclone/``: ``(size, mtime_ns)``. A rewrite moves the
#: mtime even when it keeps the size, and reading two integers per file keeps
#: the snapshot cheap next to a report of hundreds of megabytes.
ServiceFileStamp = tuple[int, int]


def is_controller_service_state(relative_path: str) -> bool:
    """Whether a path inside ``.codeclone/`` is state another fence owns.

    Named by the product's own layout, not by hand: every SQLite store and
    its sidecars (the ``-wal``/``-shm``/``-journal`` files and the registry
    lock beside a database) -- refused to a test by the SQLite fence, and
    opened concurrently by the controller; the file-backed intent registry
    -- the controller's coordination state; and engineering memory, which
    the relocation above keeps a test out of and the controller writes at
    any time. Everything else in the directory -- a report, an export, a
    stray file -- has no other owner, so the snapshot answers for it.
    """

    from codeclone.paths.workspace import (
        REGISTRY_DIR_PARTS,
        REL_MEMORY_DB_PATH,
        REL_RUN_STORE_DB_PATH,
    )

    parts = relative_path.split("/")
    controller_dirs = {REGISTRY_DIR_PARTS[1], Path(REL_MEMORY_DB_PATH).parts[1]}
    return parts[0] in controller_dirs or (
        Path(REL_RUN_STORE_DB_PATH).suffix in parts[-1]
    )


def capture_service_state(root: Path) -> dict[str, ServiceFileStamp]:
    """Every file in ``root``'s ``.codeclone/`` no other fence answers for.

    Keyed by the path relative to the service directory. An absent directory
    is an empty snapshot, so a directory a test creates shows up whole.
    """

    from codeclone.paths.workspace import repo_workspace_dir

    service_dir = repo_workspace_dir(root)
    stamps: dict[str, ServiceFileStamp] = {}
    for directory, subdirectories, files in os.walk(service_dir):
        relative_dir = Path(directory).relative_to(service_dir)
        subdirectories[:] = sorted(
            name
            for name in subdirectories
            if not is_controller_service_state((relative_dir / name).as_posix())
        )
        for name in files:
            relative = (relative_dir / name).as_posix()
            if is_controller_service_state(relative):
                continue
            try:
                stat = (Path(directory) / name).stat()
            except FileNotFoundError:
                continue
            stamps[relative] = (stat.st_size, stat.st_mtime_ns)
    return stamps


def service_state_residue(
    before: dict[str, ServiceFileStamp], after: dict[str, ServiceFileStamp]
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """``(appeared, rewritten, vanished)`` files inside ``.codeclone/``."""

    appeared = tuple(sorted(set(after) - set(before)))
    rewritten = tuple(
        sorted(path for path in set(after) & set(before) if after[path] != before[path])
    )
    vanished = tuple(sorted(set(before) - set(after)))
    return appeared, rewritten, vanished


# ---------------------------------------------------------------------------
# The per-process guard the conftest hooks drive
# ---------------------------------------------------------------------------


@dataclass
class LiveStateGuard:
    """Installed once per session; toggled per test by the conftest hooks."""

    boundary: LiveStateBoundary
    hosting_checkout: Path
    scratch_root: Path
    session_scratch: Path
    scratch: Path
    lifted: bool = False
    baseline: frozenset[str] | None = None
    service_baseline: dict[str, ServiceFileStamp] = field(default_factory=dict)
    violations: list[LiveStateViolation] = field(default_factory=list)
    opted_in: list[tuple[str, str]] = field(default_factory=list)
    #: Relocated path -> the live path it stands for.
    twins: dict[Path, Path] = field(default_factory=dict)
    _undo: list[Callable[[], None]] = field(default_factory=list)

    # -- lifecycle ----------------------------------------------------------

    @classmethod
    def install(cls, *, hosting_checkout: Path = HOSTING_CHECKOUT) -> LiveStateGuard:
        """Patch the in-process choke points for the whole session."""

        import codeclone.config.memory as memory_config
        import codeclone.utils.repo_paths as repo_paths

        boundary = discover_live_state_boundary(checkout=hosting_checkout)
        scratch_root = _realpath(Path(tempfile.mkdtemp(prefix="codeclone-live-state-")))
        session_scratch = scratch_root / "session"
        session_scratch.mkdir()
        guard = cls(
            boundary=boundary,
            hosting_checkout=_realpath(hosting_checkout),
            scratch_root=scratch_root,
            session_scratch=session_scratch,
            scratch=session_scratch,
        )
        guard.baseline = capture_tree_status(guard.hosting_checkout)
        guard.service_baseline = capture_service_state(guard.hosting_checkout)

        def lifted() -> bool:
            return guard.lifted

        guard._patch(
            memory_config,
            "_resolve_memory_state_path",
            lambda original: make_redirected_state_path_resolver(
                original,
                boundary=boundary,
                scratch_anchor=lambda: guard.scratch,
                on_redirect=guard.record_twin,
            ),
        )
        guard._patch(
            repo_paths,
            "_is_relative_to",
            lambda original: make_twin_aware_containment(
                original, original_of=guard.original_of
            ),
        )
        guard._patch(
            sqlite3,
            "connect",
            lambda original: make_guarded_connect(
                original,
                boundary=boundary,
                lifted=lifted,
                on_violation=guard.violations.append,
            ),
        )
        guard._patch(
            subprocess.Popen,
            "__init__",
            lambda original: make_guarded_popen_init(
                original,
                boundary=boundary,
                lifted=lifted,
                on_violation=guard.violations.append,
            ),
        )
        return guard

    def _patch(
        self, target: object, name: str, factory: Callable[[Any], object]
    ) -> None:
        """Replace ``target.name`` with ``factory(original)``; undone on uninstall."""

        original = getattr(target, name)
        setattr(target, name, factory(original))
        self._undo.append(lambda: setattr(target, name, original))

    def uninstall(self) -> None:
        while self._undo:
            self._undo.pop()()
        shutil.rmtree(self.scratch_root, ignore_errors=True)

    # -- relocation ---------------------------------------------------------

    def record_twin(self, twin: Path, original: Path) -> None:
        self.twins[twin] = original

    def original_of(self, path: Path) -> Path | None:
        """The live path ``path`` stands for: a recorded twin, or a path
        beneath one, mapped back under its original; ``None`` otherwise."""

        for twin, original in self.twins.items():
            if path == twin:
                return original
            if path.is_relative_to(twin):
                return original / path.relative_to(twin)
        return None

    # -- per test -----------------------------------------------------------

    def enter_test(self, nodeid: str, reason: str | None) -> None:
        """Start a test: lift the fences for an opt-in, else give it scratch."""

        self.violations.clear()
        if reason is not None:
            self.lifted = True
            self.opted_in.append((nodeid, reason))
            return
        self.lifted = False
        self.scratch = _realpath(
            Path(tempfile.mkdtemp(prefix="test-", dir=self.scratch_root))
        )

    def exit_test(self) -> tuple[LiveStateViolation, ...]:
        """End a test: drop its scratch, hand back what it tried to touch."""

        violations = tuple(self.violations)
        self.violations.clear()
        self.lifted = False
        if self.scratch != self.session_scratch:
            shutil.rmtree(self.scratch, ignore_errors=True)
            # The twins under it are gone with it; the session's stay.
            self.twins = {
                twin: original
                for twin, original in self.twins.items()
                if not twin.is_relative_to(self.scratch)
            }
            self.scratch = self.session_scratch
        return violations


#: Where the conftest keeps the session's guard; tests reach it through
#: :func:`live_state_guard` rather than by importing the conftest.
LIVE_STATE_GUARD_KEY: pytest.StashKey[LiveStateGuard] = pytest.StashKey()


def live_state_guard(config: pytest.Config) -> LiveStateGuard:
    """The guard installed for this session (the conftest installs it)."""

    return config.stash[LIVE_STATE_GUARD_KEY]


__all__ = [
    "HOSTING_CHECKOUT",
    "LIVE_STATE_GUARD_KEY",
    "LIVE_STATE_MARKER",
    "TREE_RESIDUE_GATE_TEST",
    "LiveStateBoundary",
    "LiveStateGuard",
    "LiveStateViolation",
    "ServiceFileStamp",
    "capture_service_state",
    "capture_tree_status",
    "discover_live_state_boundary",
    "git_mutation_under_live_root",
    "is_controller_service_state",
    "is_read_only_git_command",
    "is_test_runtime_artifact",
    "live_state_guard",
    "make_guarded_connect",
    "make_guarded_popen_init",
    "make_redirected_state_path_resolver",
    "make_twin_aware_containment",
    "service_state_residue",
    "sqlite_database_path",
    "tree_residue",
]
