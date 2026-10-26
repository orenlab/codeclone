# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A worker that dies mid-run must not make any file count twice.

Maintainer ruling 2026-10-23 on the broken process pool:

* only the files whose result the parent never accepted are retried;
* an accepted result is never counted a second time;
* a result that fails acceptance leaves nothing behind, so the retry
  recomputes it whole;
* every run keeps the population identity: found = cached + analysed +
  skipped, with no file in two of those at once.

The death here is real: a ``ProcessPoolExecutor`` child calls ``os._exit``
on a marked file, the parent sees ``BrokenProcessPool``. Before the fix the
sequential fallback re-ran every file, so the batches already accepted were
counted twice -- 25 files accounted out of 17 found, duplicated clone units,
and with metrics on ``analyze`` refused the duplicated dead-code rows and the
CLI died with exit 5.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

import codeclone.core.discovery as core_discovery
import codeclone.core.parallelism as core_parallelism
from codeclone.cache.store import Cache
from codeclone.core._types import (
    DEFAULT_BATCH_SIZE,
    BootstrapResult,
    DiscoveryResult,
    ProcessingResult,
    _unit_to_group_item,
)
from codeclone.core.parallelism import process
from codeclone.core.pipeline import analyze
from tests._pipeline_fixtures import analysis_boot
from tests._worker_death_probe import (
    WORKER_KILLER_PREFIX,
    die_in_worker_on_marked_file,
)

# Batches of four over seventeen files: [a00-a03] [a04-a07] [killer z00-z02]
# [z03-z06] [z07]. Two whole batches are accepted before the death, the
# third breaks the pool, and submitting the fourth raises.
_MID_RUN_BATCH_SIZE = 4
_KILLER_INDEX = 8


def _write_tree(root: Path) -> list[str]:
    names = [f"a{index:02d}" for index in range(8)]
    names.append(f"{WORKER_KILLER_PREFIX}_mod")
    names.extend(f"z{index:02d}" for index in range(8))
    for index, name in enumerate(names):
        (root / f"{name}.py").write_text(
            f"def unused_{index}():\n    total = {index}\n    return total\n",
            "utf-8",
        )
    return names


def _boot(root: Path) -> BootstrapResult:
    boot = analysis_boot(root, min_loc=1, min_stmt=1, skip_metrics=False)
    boot.args.processes = 2
    return boot


def _discover(boot: BootstrapResult, root: Path) -> tuple[Cache, DiscoveryResult]:
    cache = Cache(root / "cache.json", root=root)
    return cache, core_discovery.discover(boot=boot, cache=cache)


def _run(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    kill: bool,
    batch_size: int | None,
) -> tuple[BootstrapResult, DiscoveryResult, ProcessingResult, list[str]]:
    _write_tree(root)
    boot = _boot(root)
    cache, discovery = _discover(boot, root)
    killer_index = [
        Path(path).name.startswith(WORKER_KILLER_PREFIX)
        for path in discovery.files_to_process
    ].index(True)
    # Probe validity: the layout must actually put the death mid-run.
    assert killer_index == _KILLER_INDEX
    assert core_parallelism._should_use_parallel(len(discovery.files_to_process), 2)
    if kill:
        monkeypatch.setattr(
            core_parallelism,
            "_invoke_process_file",
            die_in_worker_on_marked_file,
        )
    fallbacks: list[str] = []
    processing = process(
        boot=boot,
        discovery=discovery,
        cache=cache,
        on_parallel_fallback=lambda exc: fallbacks.append(type(exc).__name__),
        batch_size=DEFAULT_BATCH_SIZE if batch_size is None else batch_size,
    )
    return boot, discovery, processing, fallbacks


def _accounting(
    discovery: DiscoveryResult, processing: ProcessingResult
) -> dict[str, object]:
    units_per_file = Counter(unit["filepath"] for unit in processing.units)
    unit_keys = Counter(
        (unit["filepath"], unit["qualname"]) for unit in processing.units
    )
    dead_keys = Counter(
        (candidate.filepath, candidate.qualname, candidate.start_line)
        for candidate in processing.dead_candidates
    )
    return {
        "found": discovery.files_found,
        "accounted": (
            discovery.cache_hits + processing.files_analyzed + processing.files_skipped
        ),
        "analyzed": processing.files_analyzed,
        "skipped": processing.files_skipped,
        "failed_files": processing.failed_files,
        "units_counted_twice": sorted(
            str(qualname) for (_path, qualname), count in unit_keys.items() if count > 1
        ),
        "files_without_a_unit": sorted(
            Path(path).name
            for path in discovery.files_to_process
            if units_per_file[path] == 0
        ),
        "dead_rows_counted_twice": sorted(
            key[1] for key, count in dead_keys.items() if count > 1
        ),
        "analyzed_functions": processing.analyzed_functions,
    }


def _complete(found: int) -> dict[str, object]:
    return {
        "found": found,
        "accounted": found,
        "analyzed": found,
        "skipped": 0,
        "failed_files": (),
        "units_counted_twice": [],
        "files_without_a_unit": [],
        "dead_rows_counted_twice": [],
        "analyzed_functions": found,
    }


def test_healthy_pool_counts_every_file_once_and_never_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive control: the same layout and batches, no death."""

    _boot_result, discovery, processing, fallbacks = _run(
        tmp_path, monkeypatch, kill=False, batch_size=_MID_RUN_BATCH_SIZE
    )

    assert fallbacks == []
    assert _accounting(discovery, processing) == _complete(17)


def test_worker_death_mid_run_counts_every_file_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boot, discovery, processing, fallbacks = _run(
        tmp_path, monkeypatch, kill=True, batch_size=_MID_RUN_BATCH_SIZE
    )

    # The probe reached the mechanism: the pool really broke.
    assert fallbacks == ["BrokenProcessPool"]
    assert _accounting(discovery, processing) == _complete(17)
    # The duplicated dead-code rows were what turned this into exit 5.
    result = analyze(boot=boot, discovery=discovery, processing=processing)
    assert result.files_analyzed_or_cached == 17


def test_worker_death_in_the_last_batch_retries_the_lost_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A death with no later submission still leaves files unconfirmed.

    One batch holds all seventeen files, so no ``submit`` raises after the
    death. The killer and whatever was in flight beside it were never
    accepted; they are retried, not written off as lost.
    """

    _boot_result, discovery, processing, fallbacks = _run(
        tmp_path, monkeypatch, kill=True, batch_size=None
    )

    assert fallbacks == ["BrokenProcessPool"]
    assert _accounting(discovery, processing) == _complete(17)


def test_a_result_that_fails_acceptance_leaves_nothing_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal half-way through accepting a result must not leave a part.

    The second unit of one file refuses conversion, once. Before the refusal
    the parent had already counted the file and kept its first unit; the
    retry then counted it again. Acceptance now finishes everything that can
    refuse before it accumulates anything.
    """

    names = _write_tree(tmp_path)
    target = tmp_path / f"{names[3]}.py"
    target.write_text(
        "def first():\n    one = 1\n    return one\n\n\n"
        "def second():\n    two = 2\n    return two\n",
        "utf-8",
    )
    boot = _boot(tmp_path)
    cache, discovery = _discover(boot, tmp_path)
    real_convert = _unit_to_group_item
    refused: list[str] = []

    def _refuse_once(unit: object) -> object:
        qualname = getattr(unit, "qualname", "")
        if qualname.endswith(":second") and not refused:
            refused.append(qualname)
            raise RuntimeError("unit refused once")
        return real_convert(unit)  # type: ignore[arg-type]

    monkeypatch.setattr(core_parallelism, "_unit_to_group_item", _refuse_once)
    errors: list[str] = []
    processing = process(
        boot=boot,
        discovery=discovery,
        cache=cache,
        on_worker_error=errors.append,
    )

    assert refused, "the refusal never fired; the probe proves nothing"
    assert errors == ["unit refused once"]
    accounting = _accounting(discovery, processing)
    expected = _complete(17)
    expected["analyzed_functions"] = 18
    assert accounting == expected
    assert processing.analyzed_lines == sum(
        len(Path(path).read_text("utf-8").splitlines())
        for path in discovery.files_to_process
    )
