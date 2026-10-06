# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The one owner of every git process CodeClone starts.

CodeClone runs git inside a repository it is analysing, and that repository's
own git state -- ``.git/config``, the files it includes, ``config.worktree``,
``.git/hooks``, ``.gitattributes``, ``.git/info/attributes`` -- can name
programs git then runs. Whoever hands over a working tree together with its
``.git`` would choose what CodeClone executes, with CodeClone's environment.
And "read-only" git calls used to rewrite ``.git/index``.

Every git process therefore starts here, in one call form. Each defence below
was measured on git 2.54 against a repository whose state names a marker
program, with a clean twin as control (``tests/test_git_process_hardening*``):

* ``--no-optional-locks`` -- ``git status`` refreshes stat data and rewrites
  the index; this is git's own switch for a reader that must not write.
* ``-c core.fsmonitor=`` -- the filesystem monitor is a program the repository
  names, run by ``status``, ``diff`` and ``ls-files``. An empty value turns it
  off as a boolean (git >= 2.36) and as an unset hook path (older git).
* ``-c core.hooksPath=/dev/null`` -- ``post-index-change`` runs after every
  index write, the private index below included.
* ``-c log.showSignature=false`` -- ``git log`` would run ``gpg.program`` on
  every signed commit.
* ``--no-ext-diff --no-textconv`` on ``diff`` -- ``diff.external``,
  ``diff.<driver>.command`` and ``diff.<driver>.textconv`` run when a patch is
  printed.
* every filter driver the repository itself defines is blanked on the verbs
  that read working-tree content (``status``, ``diff``, ``hash-object``): git
  has no switch that turns drivers off, so the owner lists the repository's
  own configuration and overrides each driver it names. A driver from the
  operator's global or system configuration still runs, so results do not
  change for, say, a globally installed LFS driver. A driver whose name
  ``-c`` cannot spell (it contains ``=``) is refused, never run.
* a worktree ``diff`` reads a private copy of the index (``GIT_INDEX_FILE``,
  mtime kept, ``core.splitIndex=false``): with stat-only dirt it refreshes and
  rewrites the index even under ``--no-optional-locks``, and a split index
  would also write a new shared index into ``.git``.
* the child environment drops every variable git itself drops when it enters
  another repository (``git rev-parse --local-env-vars``), so an inherited
  ``GIT_DIR`` or ``GIT_INDEX_FILE`` cannot point the answer at another
  repository; drops the MCP server's HTTP auth token; and sets
  ``GIT_NO_LAZY_FETCH`` so a promisor remote of the repository's choosing is
  never contacted for a missing object (git >= 2.44).

Callers see the command they asked for: errors carry ``["git", *args]``, never
the call form, so user-facing messages do not change.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Final, NamedTuple, TypeVar

GIT_EXECUTABLE: Final = "git"

#: Global options of every call, before the verb.
_CALL_FORM: Final[tuple[str, ...]] = (
    "--no-optional-locks",
    "-c",
    "core.fsmonitor=",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "log.showSignature=false",
)

#: Added when git reads a private copy of the index.
_PRIVATE_INDEX_FORM: Final[tuple[str, ...]] = ("-c", "core.splitIndex=false")

#: What a blanked filter driver is set to. git consults ``clean`` and
#: ``smudge`` only while no ``process`` is configured (gitattributes(5)), and an
#: empty ``process`` is configured but names nothing: one override turns every
#: program of the driver off. Measured: blanking ``clean`` beside it changes no
#: answer. ``required=false``: a required driver without a program makes git
#: refuse the whole read.
_FILTER_DRIVER_BLANKS: Final[tuple[tuple[str, str], ...]] = (
    ("process", ""),
    ("required", "false"),
)


class _VerbPolicy(NamedTuple):
    reads_worktree_content: bool
    verb_options: tuple[str, ...] = ()


#: Every verb CodeClone runs. A verb without a policy is refused: a new
#: caller decides what its verb can run before it can run it.
_VERB_POLICIES: Final[Mapping[str, _VerbPolicy]] = MappingProxyType(
    {
        "cat-file": _VerbPolicy(reads_worktree_content=False),
        "diff": _VerbPolicy(
            reads_worktree_content=True,
            verb_options=("--no-ext-diff", "--no-textconv"),
        ),
        "hash-object": _VerbPolicy(reads_worktree_content=True),
        "log": _VerbPolicy(reads_worktree_content=False),
        "ls-files": _VerbPolicy(reads_worktree_content=False),
        "remote": _VerbPolicy(reads_worktree_content=False),
        "rev-parse": _VerbPolicy(reads_worktree_content=False),
        "status": _VerbPolicy(reads_worktree_content=True),
    }
)

#: ``git rev-parse --local-env-vars`` on git 2.54: what git clears itself
#: before it works in another repository.
_REPOSITORY_LOCAL_ENV: Final = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_CONFIG",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_PARAMETERS",
        "GIT_DIR",
        "GIT_GRAFT_FILE",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_OBJECT_DIRECTORY",
        "GIT_PREFIX",
        "GIT_REPLACE_REF_BASE",
        "GIT_SHALLOW_FILE",
        "GIT_WORK_TREE",
    }
)

#: Read only by the MCP server's HTTP transport at startup
#: (``codeclone.surfaces.mcp.auth.MCP_AUTH_TOKEN_ENV``); git never needs it.
_WITHHELD_ENV: Final = frozenset({"CODECLONE_MCP_AUTH_TOKEN"})

_NO_LAZY_FETCH_ENV: Final = "GIT_NO_LAZY_FETCH"

_Out = TypeVar("_Out", str, bytes)


class GitInvocationRefused(OSError):
    """The owner will not start git: the call cannot be made safe."""


def run_git_bytes(
    root: Path,
    args: Sequence[str],
    *,
    timeout: float,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run ``git <args>`` in ``root`` and return its raw output.

    Raises what ``subprocess.run(..., check=True)`` raises, with the command
    as asked: ``OSError`` (``GitInvocationRefused`` among them),
    ``CalledProcessError`` and ``TimeoutExpired``.
    """

    logical = [GIT_EXECUTABLE, *args]
    with _asked_command(logical), _invocation(root, args, timeout=timeout) as call:
        completed = subprocess.run(
            call.argv,
            cwd=root,
            env=call.env,
            capture_output=True,
            check=False,
            timeout=timeout,
            input=input_bytes,
        )
    return _checked(completed, logical)


def run_git_text(
    root: Path,
    args: Sequence[str],
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    """``run_git_bytes`` decoded as ``subprocess.run(..., text=True)`` does."""

    logical = [GIT_EXECUTABLE, *args]
    with _asked_command(logical), _invocation(root, args, timeout=timeout) as call:
        completed = subprocess.run(
            call.argv,
            cwd=root,
            env=call.env,
            capture_output=True,
            check=False,
            timeout=timeout,
            text=True,
        )
    return _checked(completed, logical)


class _Invocation(NamedTuple):
    argv: list[str]
    env: dict[str, str]


@contextmanager
def _asked_command(logical: list[str]) -> Iterator[None]:
    """A timeout names the command as asked, not the call form."""

    try:
        yield
    except subprocess.TimeoutExpired as exc:
        raise subprocess.TimeoutExpired(
            logical, exc.timeout, output=exc.output, stderr=exc.stderr
        ) from None


def _checked(
    completed: subprocess.CompletedProcess[_Out], logical: list[str]
) -> subprocess.CompletedProcess[_Out]:
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            logical,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return subprocess.CompletedProcess(logical, 0, completed.stdout, completed.stderr)


@contextmanager
def _invocation(
    root: Path, args: Sequence[str], *, timeout: float
) -> Iterator[_Invocation]:
    """The call form for ``git <args>``, valid while the context is open."""

    if not args:
        raise ValueError("git needs a verb")
    verb, rest = args[0], tuple(args[1:])
    policy = _VERB_POLICIES.get(verb)
    if policy is None:
        raise ValueError(f"git {verb} has no call form in the git owner")
    overrides = (
        _filter_driver_overrides(root, timeout=timeout)
        if policy.reads_worktree_content
        else ()
    )
    with _private_index(root, verb, rest, timeout=timeout) as private_index:
        yield _Invocation(
            argv=[
                GIT_EXECUTABLE,
                *_CALL_FORM,
                *overrides,
                *(_PRIVATE_INDEX_FORM if private_index is not None else ()),
                verb,
                *policy.verb_options,
                *rest,
            ],
            env=_child_env(private_index),
        )


def _child_env(private_index: Path | None) -> dict[str, str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in _REPOSITORY_LOCAL_ENV and name not in _WITHHELD_ENV
    }
    env[_NO_LAZY_FETCH_ENV] = "1"
    if private_index is not None:
        env["GIT_INDEX_FILE"] = str(private_index)
    return env


def _config_entries(
    root: Path, scope: str, *, timeout: float
) -> list[tuple[str, str | None]] | None:
    """``(key, value)`` of one configuration scope, includes followed.

    ``None`` when git cannot list it: outside a repository, or when its
    configuration is unreadable -- and then git cannot load a driver from it
    for the real call either.
    """

    completed = subprocess.run(
        [GIT_EXECUTABLE, *_CALL_FORM, "config", scope, "--includes", "--list", "-z"],
        cwd=root,
        env=_child_env(None),
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        return None
    entries: list[tuple[str, str | None]] = []
    for record in os.fsdecode(completed.stdout).split("\0"):
        if not record:
            continue
        key, newline, value = record.partition("\n")
        entries.append((key, value if newline else None))
    return entries


def _is_true(value: str | None) -> bool:
    """git's boolean reading, erring towards listing one scope too many."""

    return value is None or value.strip().lower() not in {"false", "no", "off", "0", ""}


def _filter_driver_names(entries: Sequence[tuple[str, str | None]]) -> set[str]:
    names: set[str] = set()
    for key, _value in entries:
        section, _, remainder = key.partition(".")
        name, dot, _variable = remainder.rpartition(".")
        if section == "filter" and dot and name:
            names.add(name)
    return names


def _filter_driver_overrides(root: Path, *, timeout: float) -> tuple[str, ...]:
    """``-c`` options blanking every filter driver the repository defines."""

    local = _config_entries(root, "--local", timeout=timeout)
    if local is None:
        return ()
    names = _filter_driver_names(local)
    worktree_config = dict(local).get("extensions.worktreeconfig", "false")
    if _is_true(worktree_config):
        names |= _filter_driver_names(
            _config_entries(root, "--worktree", timeout=timeout) or ()
        )
    overrides: list[str] = []
    for name in sorted(names):
        if "=" in name:
            raise GitInvocationRefused(
                f"git would run filter driver {name!r} defined by the repository, "
                "and its name cannot be overridden"
            )
        for variable, value in _FILTER_DRIVER_BLANKS:
            overrides += ["-c", f"filter.{name}.{variable}={value}"]
    return tuple(overrides)


def _reads_worktree_index(verb: str, rest: Sequence[str]) -> bool:
    if verb != "diff":
        return False
    options = rest[: rest.index("--")] if "--" in rest else rest
    return not any(option in {"--cached", "--staged"} for option in options)


@contextmanager
def _private_index(
    root: Path, verb: str, rest: Sequence[str], *, timeout: float
) -> Iterator[Path | None]:
    """A private copy of the index for a worktree ``diff``, else ``None``.

    The copy keeps the index's mtime: git decides which entries are racily
    clean by comparing them with it, and a fresh mtime would change answers.
    A missing index stays missing, which git reads as an empty one. When git
    cannot even locate the index it cannot open the repository, so the diff
    fails on its own, with its own status, and writes nothing.
    """

    if not _reads_worktree_index(verb, rest):
        yield None
        return
    try:
        located = run_git_bytes(
            root, ["rev-parse", "--git-path", "index"], timeout=timeout
        )
    except subprocess.CalledProcessError:
        yield None
        return
    index_path = Path(os.fsdecode(located.stdout).rstrip("\n"))
    if not index_path.is_absolute():
        index_path = root / index_path
    try:
        directory = Path(tempfile.mkdtemp(prefix="codeclone-git-index-"))
    except OSError as exc:
        raise GitInvocationRefused(f"no private index for git: {exc}") from exc
    try:
        private = directory / "index"
        try:
            if index_path.is_file():
                shutil.copy2(index_path, private)
        except OSError as exc:
            raise GitInvocationRefused(f"no private index for git: {exc}") from exc
        yield private
    finally:
        shutil.rmtree(directory, ignore_errors=True)


__all__ = [
    "GIT_EXECUTABLE",
    "GitInvocationRefused",
    "run_git_bytes",
    "run_git_text",
]
