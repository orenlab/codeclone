# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""What each type gate actually looks at, reconciled against the repository.

``ty-prod-scope`` is named for what it checks and silent about what it does
not.  Measured 2026-09-04 on ``eec81fdb``: a deliberate type error injected
into a file under ``tests/`` leaves that hook green, because the population it
is handed -- ``codeclone .github/actions benchmarks`` -- does not contain the
file.  Neither the hook id, nor its name, nor its output said so, so a green
line read as "my change was type-checked" while carrying no information about
that change at all.  ``tests/`` is not unchecked repository-wide -- the mypy
hook beside it covers the root, and that sibling is why the aggregate gate
still catches the injected error -- but a reader looking at ``ty`` alone was
being told nothing and could not tell.

Both sides of the reconciliation are measured, never listed by hand:

* the checked populations come out of the gate declarations themselves -- the
  ``ty-prod-scope`` hook entry in ``.pre-commit-config.yaml``, the ``ty check``
  step in ``.github/workflows/tests.yml``, and ``[tool.mypy] files`` in
  ``pyproject.toml`` -- parsed as the shell commands and config they are;
* the repository population comes out of ``git ls-files``.

Only the *delta* is declared, as a root-to-reason map, and it reds in both
directions under different tests: a root leaving a gate surfaces as an
undeclared unchecked root, a root joining one leaves a declaration stale.

The reconciliation rests on one rule about ``ty check <dir>`` -- that it
reaches every Python file beneath the directory and nothing outside it.  That
rule is not asserted in a comment here; it is executed against the real binary
in ``test_ty_check_of_a_directory_reaches_every_file_beneath_it``.
"""

from __future__ import annotations

import importlib
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO, cast

import pytest
import yaml

# ═══════════════════════════════════════════════════════════════════
# The declared delta.  Everything else in this module is measured.
# ═══════════════════════════════════════════════════════════════════

# Top-level repository roots that hold Python the `ty` gate never looks at.
# A root is listed here with the reason it is out, not with the files in it:
# the files are enumerated from git on every run, so the list cannot rot into
# a stale second copy of the tree.
_TY_UNCHECKED_ROOTS: dict[str, str] = {
    "plugins": (
        "IDE and agent launcher shims. No type gate covers this root at all; "
        "measured 2026-09-04, ty reports 1 diagnostic over it."
    ),
    "scripts": (
        "Repository maintenance scripts. No type gate covers this root at "
        "all; measured 2026-09-04, ty reports 9 diagnostics over it."
    ),
    "tests": (
        "Covered by mypy --strict, not by ty. Measured 2026-09-04, ty over "
        "this root reports 454 diagnostics (419 outside tests/fixtures/), "
        "which is a scope-and-cost decision for the maintainer, not a "
        "silently deferred cleanup."
    ),
}

# Top-level roots that NO type gate covers -- neither ty nor mypy. A type
# error in these files is invisible to every gate this repository runs.
_UNGATED_ROOTS: frozenset[str] = frozenset({"plugins", "scripts"})

_PRECOMMIT_TY_HOOK_ID = "ty-prod-scope"
_WORKFLOW = ".github/workflows/tests.yml"


# ═══════════════════════════════════════════════════════════════════
# Measurement: the repository's Python population
# ═══════════════════════════════════════════════════════════════════


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _tracked_python_files(root: Path) -> frozenset[str]:
    """Every tracked ``.py``/``.pyi`` path, from git rather than a walk.

    ``check=True``: a repository where this cannot be measured must fail
    loudly, never skip into a green that means nothing -- which is the exact
    defect this module exists for.
    """

    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py", "*.pyi"],
        cwd=root,
        capture_output=True,
        check=True,
        text=True,
    )
    return frozenset(path for path in completed.stdout.split("\0") if path)


def _top_root(path: str) -> str:
    return path.split("/", 1)[0]


def _covered_by(paths: frozenset[str], roots: tuple[str, ...]) -> frozenset[str]:
    return frozenset(
        path
        for path in paths
        if any(path == root or path.startswith(f"{root}/") for root in roots)
    )


# ═══════════════════════════════════════════════════════════════════
# Measurement: what each gate declares
# ═══════════════════════════════════════════════════════════════════


def _load_yaml(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", yaml.safe_load(path.read_text(encoding="utf-8")))


def _load_toml(path: Path) -> dict[str, Any]:
    """Read TOML the way the project's own loaders do.

    ``tomli`` is a dependency only below 3.11, so it is reached through
    ``importlib`` rather than a static import -- the idiom already used in
    ``codeclone.config.pyproject_loader``.
    """

    if sys.version_info >= (3, 11):
        import tomllib

        with path.open("rb") as handle:
            return cast("dict[str, Any]", tomllib.load(handle))

    backport = importlib.import_module("tomli")  # pragma: no cover - 3.10 only
    load = cast("Callable[[BinaryIO], dict[str, Any]]", backport.load)
    with path.open("rb") as handle:  # pragma: no cover - 3.10 only
        return load(handle)


def _unwrap_shell_command(command: str) -> list[str]:
    """Peel ``bash -c '...'``/``sh -c '...'`` wrappers off a hook entry."""

    tokens = shlex.split(command)
    for _ in range(4):
        wrapped = (
            len(tokens) >= 3
            and Path(tokens[0]).name in {"bash", "sh"}
            and "-c" in tokens[1:2]
        )
        if not wrapped:
            break
        tokens = shlex.split(tokens[-1])
    return tokens


def _ty_roots(command: str) -> tuple[str, ...]:
    """The path arguments a ``ty check`` invocation is handed.

    Fail-closed on anything this parser was not measured against: a flag in
    the argument tail would make "everything after ``check``" the wrong
    answer, so it reds here rather than quietly shifting the population.
    """

    tokens = _unwrap_shell_command(command)
    assert "ty" in tokens, f"no `ty` token in {command!r}"
    marker = tokens.index("ty")
    assert tokens[marker + 1 :][:1] == ["check"], (
        f"expected `ty check` in {command!r}, found {tokens[marker : marker + 2]!r}"
    )
    arguments = tokens[marker + 2 :]
    assert arguments, f"`ty check` in {command!r} was handed no paths"
    assert all(not argument.startswith("-") for argument in arguments), (
        f"`ty check` in {command!r} grew a flag: {arguments!r}. This parser "
        "reads every argument after `check` as a path; teach it the flag "
        "before the population can be trusted again."
    )
    return tuple(arguments)


def _precommit_ty_roots(root: Path) -> tuple[str, ...]:
    config = _load_yaml(root / ".pre-commit-config.yaml")
    for repo in cast("list[dict[str, Any]]", config["repos"]):
        for hook in cast("list[dict[str, Any]]", repo.get("hooks", [])):
            if hook.get("id") == _PRECOMMIT_TY_HOOK_ID:
                return _ty_roots(cast(str, hook["entry"]))
    raise AssertionError(
        f"no hook with id {_PRECOMMIT_TY_HOOK_ID!r} in .pre-commit-config.yaml"
    )


def _workflow_ty_roots(root: Path) -> tuple[str, ...]:
    workflow = _load_yaml(root / _WORKFLOW)
    commands = [
        run
        for job in cast("dict[str, Any]", workflow["jobs"]).values()
        for step in cast("list[dict[str, Any]]", job.get("steps", []))
        if isinstance(run := step.get("run"), str) and "ty check" in run
    ]
    assert len(commands) == 1, (
        f"expected exactly one `ty check` step in {_WORKFLOW}, found {commands!r}"
    )
    return _ty_roots(commands[0])


def _mypy_covered(root: Path, paths: frozenset[str]) -> frozenset[str]:
    mypy = cast("dict[str, Any]", _load_toml(root / "pyproject.toml")["tool"]["mypy"])
    files = tuple(cast("list[str]", mypy["files"]))
    excluded = tuple(cast("list[str]", mypy.get("exclude", [])))
    covered = _covered_by(paths, files)
    return frozenset(
        path
        for path in covered
        if not any(re.search(pattern, path) for pattern in excluded)
    )


# ═══════════════════════════════════════════════════════════════════
# The reconciliation, reported rather than merely asserted
# ═══════════════════════════════════════════════════════════════════


class _Populations:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repository = _tracked_python_files(root)
        self.ty_roots = _precommit_ty_roots(root)
        self.ty_checked = _covered_by(self.repository, self.ty_roots)
        self.ty_unchecked = self.repository - self.ty_checked
        self.mypy_checked = _mypy_covered(root, self.repository)
        self.ungated = self.repository - self.ty_checked - self.mypy_checked

    @staticmethod
    def _roots(paths: frozenset[str]) -> frozenset[str]:
        return frozenset(_top_root(path) for path in paths)

    @property
    def ty_unchecked_roots(self) -> frozenset[str]:
        return self._roots(self.ty_unchecked)

    @property
    def ungated_roots(self) -> frozenset[str]:
        return self._roots(self.ungated)

    def accounting(self) -> str:
        """The numbers behind any verdict this module returns."""

        def tally(paths: frozenset[str]) -> str:
            per_root = sorted(
                (root, sum(1 for p in paths if _top_root(p) == root))
                for root in self._roots(paths)
            )
            return ", ".join(f"{root}={count}" for root, count in per_root) or "-"

        def row(label: str, paths: frozenset[str]) -> str:
            return f"  {label:<18} {len(paths):>5}  {tally(paths)}"

        return "\n".join(
            (
                "",
                row("repository python", self.repository),
                f"  {'ty roots':<18} {'':>5}  {list(self.ty_roots)}",
                row("ty checked", self.ty_checked),
                row("ty unchecked", self.ty_unchecked),
                row("mypy checked", self.mypy_checked),
                row("covered by neither", self.ungated),
                f"  declared unchecked by ty: {sorted(_TY_UNCHECKED_ROOTS)}",
                f"  declared ungated        : {sorted(_UNGATED_ROOTS)}",
            )
        )


@pytest.fixture(scope="module")
def populations() -> _Populations:
    return _Populations(_repo_root())


# ═══════════════════════════════════════════════════════════════════
# The pins
# ═══════════════════════════════════════════════════════════════════


def test_the_two_ty_gate_declarations_name_the_same_population() -> None:
    """The hook and the CI step are two hand-kept copies of one population.

    Nothing links them, so they can drift into disagreeing about what
    "production scope" means while both stay green.
    """

    root = _repo_root()
    precommit = _precommit_ty_roots(root)
    workflow = _workflow_ty_roots(root)
    assert precommit == workflow, (
        "the pre-commit hook and the CI step check different populations:\n"
        f"  .pre-commit-config.yaml: {list(precommit)}\n"
        f"  {_WORKFLOW}: {list(workflow)}"
    )


def test_the_reconciliation_is_arithmetically_closed(
    populations: _Populations,
) -> None:
    """Checked plus unchecked is the whole tree, and neither side is empty.

    A parser that silently returned no roots would make every other pin here
    vacuously agreeable; this is the one that notices.
    """

    assert len(populations.ty_checked) + len(populations.ty_unchecked) == len(
        populations.repository
    ), populations.accounting()
    assert populations.ty_checked, populations.accounting()
    assert populations.ty_unchecked, populations.accounting()
    for declared in populations.ty_roots:
        assert _covered_by(populations.repository, (declared,)), (
            f"the ty gate is handed {declared!r}, which holds no tracked "
            f"Python at all.{populations.accounting()}"
        )


def test_no_python_root_sits_outside_the_ty_gate_undeclared(
    populations: _Populations,
) -> None:
    """Reds when a root LEAVES the gate, or when new Python lands nowhere.

    This is the direction that matters on the day someone trims the hook
    arguments: the trimmed root reappears here as an unchecked root nobody
    declared.
    """

    undeclared = sorted(populations.ty_unchecked_roots - set(_TY_UNCHECKED_ROOTS))
    assert not undeclared, (
        f"Python under {undeclared} is checked by no `ty` gate and is not "
        "declared in _TY_UNCHECKED_ROOTS. Either put the root back in the "
        "gate arguments, or declare it here with the reason it stays out."
        f"{populations.accounting()}"
    )


def test_every_root_declared_unchecked_is_still_outside_the_gate(
    populations: _Populations,
) -> None:
    """Reds when a root JOINS the gate and the declaration goes stale.

    The opposite boundary from the test above, on purpose: closing part of
    the gap must not leave a note behind claiming the gap is still open.
    """

    stale = sorted(set(_TY_UNCHECKED_ROOTS) - populations.ty_unchecked_roots)
    assert not stale, (
        f"_TY_UNCHECKED_ROOTS still declares {stale} as outside the `ty` "
        "gate, but the gate now reaches it. Drop the stale declaration."
        f"{populations.accounting()}"
    )


def test_the_test_suite_is_covered_by_mypy_and_not_by_ty(
    populations: _Populations,
) -> None:
    """The sibling that makes the ty gate's silence survivable.

    A tests-only patch gets a green ``ty-prod-scope`` that says nothing about
    it; what actually type-checks that patch is the mypy hook running beside
    it. If mypy ever drops the root, the repository goes blind on the test
    suite and only this line notices.
    """

    tests = _covered_by(populations.repository, ("tests",))
    assert tests, populations.accounting()
    assert not (tests & populations.ty_checked), (
        "`ty` now reaches tests/. Update _TY_UNCHECKED_ROOTS and this pin."
        f"{populations.accounting()}"
    )
    uncovered = sorted(tests - populations.mypy_checked)[:5]
    assert not uncovered, (
        "tests/ is checked by neither ty nor mypy -- the test suite is now "
        f"type-checked by nothing. First uncovered: {uncovered}"
        f"{populations.accounting()}"
    )


def test_the_population_no_type_gate_covers_is_the_declared_one(
    populations: _Populations,
) -> None:
    """Where a type error is invisible to every gate this repository runs.

    Not a smaller version of the pins above: ty and mypy each leave a
    different hole, and only their union says which files nothing watches.
    """

    assert populations.ungated_roots == _UNGATED_ROOTS, (
        "the set of roots no type gate covers has moved.\n"
        f"  measured: {sorted(populations.ungated_roots)}\n"
        f"  declared: {sorted(_UNGATED_ROOTS)}"
        f"{populations.accounting()}"
    )


def test_ty_check_of_a_directory_reaches_every_file_beneath_it(
    tmp_path: Path,
) -> None:
    """The expansion rule every pin above is built on, executed not assumed.

    ``ty check <dir>`` recurses to the bottom of ``<dir>`` and stops at its
    edge. Were either half false, ``_covered_by`` would be modelling a gate
    that does not exist and the whole reconciliation would be theatre.
    """

    binary = shutil.which("ty", path=str(Path(sys.executable).parent)) or shutil.which(
        "ty"
    )
    assert binary is not None, (
        "`ty` is not installed. It ships in the same `dev` extra as pytest, "
        "so an environment that can run this suite can run it; install with "
        "`uv sync --all-extras`."
    )

    inside = tmp_path / "named" / "a" / "b" / "deep.py"
    outside = tmp_path / "unnamed" / "sibling.py"
    for module in (inside, outside):
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text("def f(x: int) -> str:\n    return x\n", encoding="utf-8")

    completed = subprocess.run(
        [binary, "check", "--output-format", "concise", "named"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    report = completed.stdout + completed.stderr

    assert completed.returncode == 1, f"expected diagnostics, got:\n{report}"
    assert "named/a/b/deep.py" in report, (
        f"ty did not recurse into the directory it was handed:\n{report}"
    )
    assert "sibling.py" not in report, (
        f"ty reached outside the directory it was handed:\n{report}"
    )
