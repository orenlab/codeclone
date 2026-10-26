# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Final

_SAFE_GIT_DIFF_REF_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?![-./])[A-Za-z0-9._/@{}^~+-]+$"
)


def validate_git_diff_ref(git_diff_ref: str) -> str:
    """Validate a safe, single git revision expression for `git diff`.

    CodeClone intentionally accepts a conservative subset of git revision
    syntax here: common branch names, tags, revision operators (`~`, `^`),
    reflog selectors (`@{...}`), and dotted range expressions. Whitespace,
    control characters, option-like prefixes, and unsupported punctuation are
    rejected before any subprocess call.
    """

    if git_diff_ref != git_diff_ref.strip():
        raise ValueError(
            "Invalid git diff ref "
            f"{git_diff_ref!r}: surrounding whitespace is not allowed."
        )
    if not git_diff_ref:
        raise ValueError("Invalid git diff ref '': value must not be empty.")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in git_diff_ref):
        raise ValueError(
            "Invalid git diff ref "
            f"{git_diff_ref!r}: whitespace and control characters are not allowed."
        )
    if not _SAFE_GIT_DIFF_REF_RE.fullmatch(git_diff_ref):
        raise ValueError(
            "Invalid git diff ref "
            f"{git_diff_ref!r}: expected a safe revision expression."
        )
    return git_diff_ref


#: Global options of every ``git diff --name-only`` CodeClone runs inside an
#: analysed repository, whose ``.git`` may come from someone else. Measured on
#: git 2.54 against a repository that names a marker program:
#: ``core.fsmonitor`` runs on every diff; with stat-only dirt ``diff`` rewrites
#: the index -- even under ``--no-optional-locks`` -- and git then runs the
#: ``post-index-change`` hook. ``--no-optional-locks`` is git's own switch for
#: a reader that must not write.
_HARDENED_GIT_OPTIONS: Final[tuple[str, ...]] = (
    "--no-optional-locks",
    "-c",
    "core.fsmonitor=",
    "-c",
    "core.hooksPath=/dev/null",
)

#: ``git rev-parse --local-env-vars`` on git 2.54: what git clears itself
#: before it works in another repository. Inherited, they would point the
#: question at another repository, index or configuration.
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

#: Every configured filter driver program key, any scope.
_FILTER_DRIVER_KEY_PATTERN: Final = r"^filter\..*\.(clean|smudge|process)$"
_FILTER_KEY_PREFIX: Final = "filter."
#: ``git config --get-regexp`` exits 1 when no key matches.
_GIT_CONFIG_NO_MATCH: Final = 1


class GitInvocationRefused(OSError):
    """The git call cannot be made safe, so it is not made."""


def git_child_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment for a git child, without repository-local variables."""

    source = os.environ if environ is None else environ
    return {
        key: value for key, value in source.items() if key not in _REPOSITORY_LOCAL_ENV
    }


def _filter_driver_blanks(
    root_path: Path, *, env: Mapping[str, str], timeout: float
) -> tuple[str, ...]:
    """``-c`` overrides that switch off every configured filter driver.

    A clean filter named by the repository's configuration (and assigned in
    ``.gitattributes`` or ``.git/info/attributes``) runs whenever ``diff``
    hashes a working-tree file -- measured with content and with stat-only
    dirt, under the options above. git has no switch that turns drivers off,
    so each configured driver is blanked: an empty ``process`` is configured
    but names nothing, which disables ``clean`` and ``smudge`` too, and
    ``required=false`` keeps git from refusing the read. A driver whose name
    ``-c`` cannot spell (it contains ``=``) is refused, never run.
    """

    completed = subprocess.run(
        [
            "git",
            *_HARDENED_GIT_OPTIONS,
            "config",
            "--name-only",
            "--get-regexp",
            _FILTER_DRIVER_KEY_PATTERN,
        ],
        cwd=root_path,
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode == _GIT_CONFIG_NO_MATCH:
        return ()
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            ["git", "config", "--get-regexp", _FILTER_DRIVER_KEY_PATTERN],
            completed.stdout,
            completed.stderr,
        )
    names = sorted(
        {
            key[len(_FILTER_KEY_PREFIX) : key.rindex(".")]
            for key in completed.stdout.splitlines()
            if key.startswith(_FILTER_KEY_PREFIX)
            and key.rindex(".") > len(_FILTER_KEY_PREFIX)
        }
    )
    blanks: list[str] = []
    for name in names:
        if "=" in name:
            raise GitInvocationRefused(
                f"git filter driver {name!r} cannot be switched off, so git is not run"
            )
        blanks.extend(
            ("-c", f"filter.{name}.process=", "-c", f"filter.{name}.required=false")
        )
    return tuple(blanks)


def run_git_diff_name_only(
    root_path: Path, git_diff_ref: str, *, timeout: float
) -> subprocess.CompletedProcess[str]:
    """``git diff --name-only REF --`` that runs no program the repository names.

    *git_diff_ref* must already be validated (:func:`validate_git_diff_ref`).
    Raises what :func:`subprocess.run` raises with ``check=True``, and
    :class:`GitInvocationRefused` when the call cannot be made safe.
    """

    env = git_child_environment()
    blanks = _filter_driver_blanks(root_path, env=env, timeout=timeout)
    return subprocess.run(
        [
            "git",
            *_HARDENED_GIT_OPTIONS,
            *blanks,
            "diff",
            "--name-only",
            git_diff_ref,
            "--",
        ],
        cwd=root_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
