# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A worker that dies mid-run: isolated recovery, or an internal error.

Maintainer ruling 2026-10-26. An incomplete analysis must never look
complete, whatever made it incomplete. When the pool loses files:

* only results the parent fully accepted are kept, each counted once;
* the files the pool did not return are retried once each, in one
  single-use child process -- never in the parent, where a file that kills
  a worker would kill the run;
* the first file that child cannot return -- it died, or hung past the
  deadline -- ends the run with an internal error (exit 5) that names the
  file, the reason and the attempts, and splits the run into confirmed
  files, the culprit and the files not processed. Not a truncation, not an
  unverified measurement, and no second child: a limit that kills every
  process does not turn into a chain of spawns;
* a result the parent cannot accept breaks an engine invariant and ends the
  run the same way.

The deaths are real: children call ``os._exit``. Every probe records which
process ran which file, so the parent's own pid can be shown absent.
"""

from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest

import codeclone.core.discovery as core_discovery
import codeclone.core.parallelism as core_parallelism
import codeclone.core.worker as core_worker
import codeclone.core.worker_recovery as core_recovery
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.cache.store import Cache
from codeclone.core._types import (
    DEFAULT_BATCH_SIZE,
    ProcessingResult,
    _unit_to_group_item,
)
from codeclone.core.parallelism import process
from codeclone.core.pipeline import analyze
from codeclone.core.worker_recovery import WorkerRecoveryError
from codeclone.paths.module_identity.inventory import build_module_registry
from tests import _worker_death_probe as probe
from tests._pipeline_fixtures import analysis_boot

# Batches of four over seventeen files: [a00-a03] [a04-a07] [killer z00-z02]
# [z03-z06] [z07]. Two whole batches are accepted before the death, the
# third breaks the pool, and submitting the fourth raises.
_MID_RUN_BATCH_SIZE = 4
_KILLER_INDEX = 8
_KILLER_NAME = f"{probe.WORKER_KILLER_PREFIX}_mod.py"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_FILES = 17
#: More spawns than this is a chain, whatever the mechanism; the guard keeps a
#: broken bound from spawning until the test times out.
_SPAWN_CHAIN = 3


def _write_tree(root: Path) -> None:
    names = [f"a{index:02d}" for index in range(8)]
    names.append(f"{probe.WORKER_KILLER_PREFIX}_mod")
    names.extend(f"z{index:02d}" for index in range(8))
    for index, name in enumerate(names):
        (root / f"{name}.py").write_text(
            f"def unused_{index}():\n    total = {index}\n    return total\n",
            "utf-8",
        )


class _Run:
    """One ``process`` call over the tree, with what it spawned and ran."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        invoke: Callable[..., object] | None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.root = tmp_path / "proj"
        self.root.mkdir()
        self.probe_dir = tmp_path / probe.PROBE_DIR_NAME
        self.probe_dir.mkdir()
        (self.probe_dir / "attempts.log").write_text("", "utf-8")
        _write_tree(self.root)
        self.boot = analysis_boot(self.root, min_loc=1, min_stmt=1, skip_metrics=False)
        self.boot.args.processes = 2
        cache = Cache(self.root / "cache.json", root=self.root)
        self.discovery = core_discovery.discover(boot=self.boot, cache=cache)
        killer_index = [
            Path(path).name == _KILLER_NAME for path in self.discovery.files_to_process
        ].index(True)
        # Probe validity: the layout puts the death mid-run, on the pool path.
        assert killer_index == _KILLER_INDEX
        assert core_parallelism._should_use_parallel(_FILES, 2)
        if invoke is not None:
            monkeypatch.setattr(core_parallelism, "_invoke_process_file", invoke)
        self.spawns = 0
        real_spawn = core_recovery._start_recovery_process

        def _counting_spawn(args: tuple[object, ...]) -> object:
            self.spawns += 1
            if self.spawns > _SPAWN_CHAIN:
                raise AssertionError("recovery is spawning a chain of processes")
            return real_spawn(args)

        monkeypatch.setattr(core_recovery, "_start_recovery_process", _counting_spawn)
        self.worker_errors: list[str] = []
        self.error: WorkerRecoveryError | None = None
        self.processing: ProcessingResult | None = None
        started = time.monotonic()
        try:
            self.processing = process(
                boot=self.boot,
                discovery=self.discovery,
                cache=cache,
                on_worker_error=self.worker_errors.append,
                batch_size=batch_size,
            )
        except WorkerRecoveryError as exc:
            self.error = exc
        self.elapsed = time.monotonic() - started

    def pids_that_ran(self, name: str) -> list[int]:
        lines = (self.probe_dir / "attempts.log").read_text("utf-8").splitlines()
        return [
            int(pid)
            for pid, ran in (line.split(" ", 1) for line in lines)
            if ran == name
        ]

    def accounting(self) -> dict[str, object]:
        processing = self.processing
        assert processing is not None, self.error
        unit_keys = Counter(
            (unit["filepath"], unit["qualname"]) for unit in processing.units
        )
        dead_keys = Counter(
            (candidate.filepath, candidate.qualname, candidate.start_line)
            for candidate in processing.dead_candidates
        )
        return {
            "accounted": (
                self.discovery.cache_hits
                + processing.files_analyzed
                + processing.files_skipped
            ),
            "analyzed": processing.files_analyzed,
            "skipped": processing.files_skipped,
            "failed_files": processing.failed_files,
            "units": len(processing.units),
            "units_counted_twice": sorted(
                str(key[1]) for key, count in unit_keys.items() if count > 1
            ),
            "dead_rows_counted_twice": sorted(
                str(key[1]) for key, count in dead_keys.items() if count > 1
            ),
            "analyzed_functions": processing.analyzed_functions,
        }


_COMPLETE: dict[str, object] = {
    "accounted": _FILES,
    "analyzed": _FILES,
    "skipped": 0,
    "failed_files": (),
    "units": _FILES,
    "units_counted_twice": [],
    "dead_rows_counted_twice": [],
    "analyzed_functions": _FILES,
}


def test_a_healthy_pool_counts_every_file_once_and_spawns_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive control: same layout and batches, no death, no recovery."""

    run = _Run(tmp_path, monkeypatch, invoke=None, batch_size=_MID_RUN_BATCH_SIZE)

    assert (run.error, run.spawns, run.worker_errors) == (None, 0, [])
    assert run.accounting() == _COMPLETE


@pytest.mark.parametrize(
    "batch_size", [_MID_RUN_BATCH_SIZE, DEFAULT_BATCH_SIZE], ids=["mid-run", "last"]
)
def test_a_worker_death_is_recovered_in_one_isolated_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, batch_size: int
) -> None:
    run = _Run(
        tmp_path, monkeypatch, invoke=probe.die_once_in_worker, batch_size=batch_size
    )

    assert run.error is None
    assert run.worker_errors, "no worker died; the probe proves nothing"
    assert run.spawns == 1
    assert run.accounting() == _COMPLETE
    killer_pids = run.pids_that_ran(_KILLER_NAME)
    assert len(killer_pids) == 2 and len(set(killer_pids)) == 2
    assert os.getpid() not in killer_pids
    # The duplicated dead-code rows were what turned this into exit 5.
    assert run.processing is not None
    result = analyze(boot=run.boot, discovery=run.discovery, processing=run.processing)
    assert result.files_analyzed_or_cached == _FILES


def _assert_internal_error(
    run: _Run, *, reason: str, attempts: int
) -> WorkerRecoveryError:
    error = run.error
    assert error is not None and run.processing is None
    assert Path(str(error.culprit)).name == _KILLER_NAME
    assert reason in error.reason, error.reason
    assert error.attempts == attempts
    assert Path(error.unverified[0]).name == _KILLER_NAME
    message = str(error)
    assert _KILLER_NAME in message
    assert f"attempts on this file: {attempts}" in message
    assert f"not processed: {len(error.not_processed)}" in message
    # The three classes cover the run, each file in exactly one of them.
    classes = [*error.confirmed, str(error.culprit), *error.not_processed]
    assert sorted(classes) == sorted(run.discovery.files_to_process)
    assert os.getpid() not in run.pids_that_ran(_KILLER_NAME)
    assert multiprocessing.active_children() == []
    return error


def test_a_second_death_is_an_internal_error_naming_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _Run(
        tmp_path,
        monkeypatch,
        invoke=probe.die_always_in_worker,
        batch_size=_MID_RUN_BATCH_SIZE,
    )

    _assert_internal_error(run, reason="exited with code 13", attempts=2)
    assert run.spawns == 1


def test_a_hung_retry_is_an_internal_error_after_the_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core_recovery, "ISOLATED_RECOVERY_TIMEOUT_SECONDS", 2.0)

    run = _Run(tmp_path, monkeypatch, invoke=probe.hang_after_first_death)

    _assert_internal_error(run, reason="no result within 2 s", attempts=2)
    assert run.spawns == 1
    assert run.elapsed < probe.HANG_SECONDS / 2


def test_a_limit_that_kills_every_process_spawns_one_recovery_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every child dies whatever it runs. Recovery spawns one process, its
    first file fails, and the run ends -- it does not try file after file."""

    run = _Run(tmp_path, monkeypatch, invoke=probe.die_on_every_file)

    error = run.error
    assert error is not None and run.processing is None
    assert run.spawns == 1
    assert "exited with code 13" in error.reason
    assert sorted(Path(path).name for path in error.unverified) == sorted(
        Path(path).name for path in run.discovery.files_to_process
    )
    # The culprit plus sixteen files never run: the message names ten of
    # them and counts the rest.
    assert len(error.not_processed) == _FILES - 1
    assert str(error).endswith(f"and {_FILES - 1 - 10} more)")
    assert multiprocessing.active_children() == []


def test_a_result_for_another_file_is_an_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _Run(tmp_path, monkeypatch, invoke=probe.answer_for_another_file)

    _assert_internal_error(run, reason="result breaks an engine invariant", attempts=1)
    assert run.spawns == 0


def test_a_result_the_parent_cannot_accept_is_an_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal half-way through acceptance is not retried: it breaks an
    engine invariant, and the run ends without a result to misread."""

    refused: list[str] = []

    def _refuse_the_killer(unit: object) -> object:
        if str(getattr(unit, "filepath", "")).endswith(_KILLER_NAME) and not refused:
            refused.append(str(getattr(unit, "qualname", "")))
            raise RuntimeError("unit refused")
        return _unit_to_group_item(unit)  # type: ignore[arg-type]

    monkeypatch.setattr(core_parallelism, "_unit_to_group_item", _refuse_the_killer)

    run = _Run(tmp_path, monkeypatch, invoke=None)

    assert refused, "the refusal never fired; the probe proves nothing"
    _assert_internal_error(
        run, reason="result breaks an engine invariant: unit refused", attempts=1
    )
    assert run.spawns == 0


def test_the_recovery_deadline_dwarfs_the_cost_of_the_largest_file() -> None:
    """The deadline is derived, not chosen: a fresh child's start-up plus the
    slowest file of this repository, with ample headroom. Measured here, on
    whatever machine runs the suite, so the rule is checked, not the number.
    """

    started = time.monotonic()
    subprocess.run(
        [sys.executable, "-c", "import codeclone.core.parallelism"],
        check=True,
        cwd=str(_REPO_ROOT),
        timeout=120,
    )
    startup = time.monotonic() - started
    largest = max(
        (path for path in (_REPO_ROOT / "tests").glob("test_*.py")),
        key=lambda path: path.stat().st_size,
    )
    registry = build_module_registry(root=_REPO_ROOT)
    core_worker._install_module_registry(registry)
    started = time.monotonic()
    result = core_worker._invoke_process_file(
        str(largest),
        str(_REPO_ROOT),
        NormalizationConfig(),
        10,
        6,
        collect_structural_findings=True,
        collect_api_surface=True,
        api_include_private_modules=False,
        collect_near_miss=False,
        collect_renamed_structure=False,
        block_min_loc=20,
        block_min_stmt=8,
        segment_min_loc=20,
        segment_min_stmt=10,
    )
    worst_file = time.monotonic() - started

    assert result.success, result.error
    assert (
        10 * (startup + worst_file) <= core_recovery.ISOLATED_RECOVERY_TIMEOUT_SECONDS
    )
