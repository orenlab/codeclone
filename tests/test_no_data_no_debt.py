# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Unread input is not a clean verdict — it is an absence of measurement.

Three independent inputs used to end in the same lie: an empty root, a root
whose every file failed to parse, and a run truncated by a dead worker all
produced a health grade about code the tool never read. This suite owns the
two halves the controller assigned: files must stop disappearing silently
(five mechanisms), and the score must stop asserting health over a population
it never observed.

Both directions are pinned on purpose. A fix that turned false cleanliness
into false alarm — a fully read repository suddenly declared incomplete —
would be the same defect wearing the opposite sign, so every guard here has a
sibling that fails if the new refusal reaches a complete run.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

import codeclone.core.parallelism as core_parallelism
from codeclone.contracts import HEALTH_WEIGHTS
from codeclone.metrics.health import HealthInputs, compute_health
from codeclone.models import HealthScore
from codeclone.scanner import discover_python_files
from tests._pipeline_fixtures import analysis_boot, discover_and_process

# ── health: a population that was never observed ────────────────────


def _health_inputs(*, found: int, analyzed: int, **debt: Any) -> HealthInputs:
    """Health inputs whose only interesting axis is the observed population."""

    base: dict[str, Any] = {
        "files_found": found,
        "files_analyzed_or_cached": analyzed,
        "function_clone_groups": 0,
        "block_clone_groups": 0,
        "complexity_avg": 0.0,
        "complexity_max": 0,
        "high_risk_functions": 0,
        "elevated_complexity_functions": 0,
        "complexity_function_population": 0,
        "coupling_avg": 0.0,
        "coupling_max": 0,
        "high_risk_classes": 0,
        "elevated_coupling_classes": 0,
        "coupling_class_population": 0,
        "cohesion_avg": 0.0,
        "low_cohesion_classes": 0,
        "import_dependency_cycles": 0,
        "deferred_dependency_cycles": 0,
        "dependency_max_depth": 0,
        "dependency_avg_depth": 0.0,
        "dependency_p95_depth": 0,
        "dead_code_items": 0,
    }
    base.update(debt)
    return HealthInputs(**base)


def _weighted_total(score: HealthScore) -> int:
    """Re-derive the total from the dimensions and the shipped weights.

    Deliberately not a literal: a literal would move with any recalibration
    and stop meaning anything. This re-runs the published rule instead, so it
    reds if the aggregation changes shape rather than if a weight is retuned.
    """

    return round(
        sum(score.dimensions[name] * HEALTH_WEIGHTS[name] for name in HEALTH_WEIGHTS)
    )


@pytest.mark.parametrize(
    ("found", "analyzed"),
    [
        pytest.param(0, 0, id="empty-root"),
        pytest.param(40, 0, id="every-found-file-skipped"),
    ],
)
def test_unread_population_is_unmeasured_not_clean(found: int, analyzed: int) -> None:
    """Nothing was read, so there is no health to report — from either input.

    An empty root and a root whose every file failed to parse are different
    accidents with the same evidentiary content: zero observations. Both used
    to come back ``90/100 (A)``.
    """

    score = compute_health(_health_inputs(found=found, analyzed=analyzed))

    assert score.population == "unmeasured"
    assert score.total == 0


def test_truncated_run_is_named_partial() -> None:
    """A worker died: 1017 of 1046 files were read, and that fact must exist.

    The score itself is deliberately left alone here — inventing a penalty for
    truncation would be a calibration decision this change does not own. What
    must exist is the typed fact a gate can consult.
    """

    score = compute_health(
        _health_inputs(
            found=1046, analyzed=1017, complexity_avg=3.8, complexity_max=103
        )
    )

    assert score.population == "partial"
    assert score.total > 0


def test_complete_run_is_scored_exactly_as_before() -> None:
    """The reverse skew: a fully read repository must not be devalued.

    If the refusal leaked into complete runs, false cleanliness would simply
    become false alarm. The total is re-derived from the dimensions and the
    shipped weights, so this stays true across recalibration.
    """

    score = compute_health(
        _health_inputs(
            found=100,
            analyzed=100,
            complexity_avg=4.0,
            complexity_max=40,
            high_risk_functions=3,
            elevated_complexity_functions=9,
            complexity_function_population=900,
            coupling_avg=2.0,
            coupling_max=18,
            coupling_class_population=120,
            dead_code_items=2,
        )
    )

    assert score.population == "complete"
    assert score.total == _weighted_total(score)
    assert score.total > 0
    assert score.grade in {"A", "B", "C", "D", "F"}


@pytest.mark.parametrize(("found", "analyzed"), [(40, 20), (1046, 1017), (8, 1)])
def test_coverage_dimension_re_derives_the_share_that_was_read(
    found: int,
    analyzed: int,
) -> None:
    """The one sentinel among seven dimensions, finally pinned.

    ``coverage`` is the only dimension that falls when files go unread; the
    other six count observed debt and are silent about absence. It was
    previously held by nothing at all — replacing the whole expression with
    the literal ``100.0`` left the entire suite green. This re-derives the
    published rule from the two counters, so hard-coding the dimension, or
    inverting the ratio, reds here.
    """

    score = compute_health(_health_inputs(found=found, analyzed=analyzed))

    assert score.dimensions["coverage"] == round(analyzed * 100 / found)


@pytest.mark.parametrize(
    ("found", "analyzed", "expected"),
    [
        (0, 0, "unmeasured"),
        (40, 0, "unmeasured"),
        (40, 1, "partial"),
        (40, 39, "partial"),
        (40, 40, "complete"),
        (1, 1, "complete"),
    ],
)
def test_population_state_covers_every_input_combination(
    found: int,
    analyzed: int,
    expected: str,
) -> None:
    """The guard is reachable from both sides, exhaustively.

    A guard no input can reach is theatre. This walks the boundary in both
    directions so a mutation that widens or narrows it reds here.
    """

    assert compute_health(
        _health_inputs(found=found, analyzed=analyzed)
    ).population == (expected)


# ── link 1a: the extension predicate had two case-sensitive copies ──


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")


def test_uppercase_extension_files_are_discovered(tmp_path: Path) -> None:
    """``Other.PY`` holds Python; a case test made it invisible everywhere."""

    _write(tmp_path / "normal.py", "def visible():\n    return 1\n")
    _write(tmp_path / "Other.PY", "def hidden():\n    return 2\n")
    _write(tmp_path / "pkg" / "Mixed.Py", "def mixed():\n    return 3\n")

    paths, _hard_excluded, _unreadable = discover_python_files(str(tmp_path))

    names = sorted(Path(path).name for path in paths)
    assert names == ["Mixed.Py", "Other.PY", "normal.py"]


def test_non_python_extensions_stay_invisible(tmp_path: Path) -> None:
    """The reverse skew: case-insensitivity must not widen the file set."""

    _write(tmp_path / "keep.py", "def keep():\n    return 1\n")
    _write(tmp_path / "notes.py.txt", "def nope():\n    return 1\n")
    _write(tmp_path / "ext.pyx", "def nope():\n    return 1\n")
    _write(tmp_path / "stub.pyi", "def nope() -> int: ...\n")
    _write(tmp_path / "STUB.PYI", "def nope() -> int: ...\n")

    paths, _hard_excluded, _unreadable = discover_python_files(str(tmp_path))

    assert [Path(path).name for path in paths] == ["keep.py"]


# The classifier half of this predicate is pinned in
# ``tests/test_verification_profile.py``: it is the suite that owns the r4
# surface, and importing it here would make every r2 subject above a ring
# violation.


# ── link 1b: os.walk swallowed PermissionError with no counter at all ──


@contextmanager
def _unreadable(path: Path) -> Iterator[None]:
    original = path.stat().st_mode
    os.chmod(path, 0o000)
    try:
        yield
    finally:
        os.chmod(path, original)


def _requires_enforced_permissions(tmp_path: Path) -> None:
    probe = tmp_path / "_probe"
    probe.mkdir()
    with _unreadable(probe):
        try:
            os.listdir(probe)
        except PermissionError:
            return
    pytest.skip("filesystem does not enforce directory permissions for this user")


def test_unreadable_directory_is_reported_by_the_scanner(tmp_path: Path) -> None:
    """The signal did not exist at all: no exception, no counter, no line."""

    _requires_enforced_permissions(tmp_path)
    _write(tmp_path / "visible" / "mod_a.py", "def a():\n    return 1\n")
    _write(tmp_path / "hidden" / "mod_b.py", "def b():\n    return 2\n")

    with _unreadable(tmp_path / "hidden"):
        paths, _hard_excluded, unreadable = discover_python_files(str(tmp_path))

    assert [Path(path).name for path in paths] == ["mod_a.py"]
    assert [Path(path).name for path in unreadable] == ["hidden"]


def test_readable_tree_reports_no_unreadable_paths(tmp_path: Path) -> None:
    """The reverse skew: a readable tree must never claim truncation."""

    _write(tmp_path / "pkg" / "mod.py", "def a():\n    return 1\n")

    _paths, _hard_excluded, unreadable = discover_python_files(str(tmp_path))

    assert unreadable == ()


def test_unreadable_directory_counts_as_found_and_skipped(tmp_path: Path) -> None:
    """The fact must ride the counter that already owns lost files."""

    _requires_enforced_permissions(tmp_path)
    _write(tmp_path / "visible" / "mod_a.py", "def a():\n    return 1\n")
    _write(tmp_path / "hidden" / "mod_b.py", "def b():\n    return 2\n")
    boot = analysis_boot(tmp_path, min_loc=1, min_stmt=1, skip_metrics=True)

    with _unreadable(tmp_path / "hidden"):
        _cache, discovery, _processing = discover_and_process(
            boot,
            tmp_path / "cache.json",
            root=tmp_path,
            warm=False,
        )

    assert discovery.files_found == 2
    assert discovery.files_skipped == 1
    assert any("hidden" in warning for warning in discovery.skipped_warnings)


# ── link 1c: files CPython imports fine that the worker threw away ──


def test_bom_and_encoding_cookie_files_are_analysed(tmp_path: Path) -> None:
    """CPython reads these modules; the analyser must read the same set."""

    (tmp_path / "plain.py").write_bytes(b"def plain():\n    return 1\n")
    (tmp_path / "bomfile.py").write_bytes(b"\xef\xbb\xbfdef bom_one():\n    return 1\n")
    (tmp_path / "latin1file.py").write_bytes(
        b"# -*- coding: latin-1 -*-\n"
        b"CAFE = '\xe9'\n"
        b"\n"
        b"\n"
        b"def latin_one():\n"
        b"    return CAFE\n"
    )
    boot = analysis_boot(tmp_path, min_loc=1, min_stmt=1, skip_metrics=True)

    _cache, discovery, processing = discover_and_process(
        boot,
        tmp_path / "cache.json",
        root=tmp_path,
        warm=False,
    )

    assert discovery.files_found == 3
    assert processing.files_analyzed == 3
    assert processing.files_skipped == 0
    assert processing.source_read_failures == ()


def test_undeclared_non_utf8_bytes_are_still_skipped(tmp_path: Path) -> None:
    """The reverse skew: decoding must follow PEP 263, not guess."""

    (tmp_path / "plain.py").write_bytes(b"def plain():\n    return 1\n")
    (tmp_path / "mojibake.py").write_bytes(b"CAFE = '\xe9'\n")
    boot = analysis_boot(tmp_path, min_loc=1, min_stmt=1, skip_metrics=True)

    _cache, _discovery, processing = discover_and_process(
        boot,
        tmp_path / "cache.json",
        root=tmp_path,
        warm=False,
    )

    assert processing.files_analyzed == 1
    assert processing.files_skipped == 1


# ── link 1d: a dead worker truncates the set; the counter must grow ──


class _DeadPoolExecutor(ThreadPoolExecutor):
    """A pool whose workers die: every submission comes back broken.

    Subclasses a real executor so the context-manager protocol is inherited
    rather than restated — the only interesting behaviour is the one override.
    ``BrokenProcessPool`` derives from ``RuntimeError``, which is what the
    production handler sees, so a plain ``RuntimeError`` is a faithful stand-in
    without importing a private failure mode.
    """

    def submit(  # type: ignore[override]
        self,
        _fn: Callable[..., Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> Future[Any]:
        future: Future[Any] = Future()
        future.set_exception(RuntimeError("A child process terminated abruptly"))
        return future


def test_worker_death_grows_the_truncation_counter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Files lost to a dead worker must be counted, not silently dropped."""

    for index in range(4):
        _write(tmp_path / f"mod_{index}.py", f"def f{index}():\n    return {index}\n")
    boot = analysis_boot(tmp_path, min_loc=1, min_stmt=1, skip_metrics=True)
    monkeypatch.setattr(core_parallelism, "_should_use_parallel", lambda *_a: True)
    monkeypatch.setattr(core_parallelism, "ProcessPoolExecutor", _DeadPoolExecutor)

    _cache, discovery, processing = discover_and_process(
        boot,
        tmp_path / "cache.json",
        root=tmp_path,
        warm=False,
    )

    assert discovery.files_found == 4
    assert processing.files_analyzed == 0
    assert processing.files_skipped == 4
    assert len(processing.failed_files) == 4


def test_healthy_parallel_run_reports_no_truncation(tmp_path: Path) -> None:
    """The reverse skew: a live pool must never report lost files."""

    for index in range(4):
        _write(tmp_path / f"mod_{index}.py", f"def f{index}():\n    return {index}\n")
    boot = analysis_boot(tmp_path, min_loc=1, min_stmt=1, skip_metrics=True)

    _cache, _discovery, processing = discover_and_process(
        boot,
        tmp_path / "cache.json",
        root=tmp_path,
        warm=False,
    )

    assert processing.files_analyzed == 4
    assert processing.files_skipped == 0
