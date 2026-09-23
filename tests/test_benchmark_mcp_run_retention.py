# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The run-retention ladder harness: its shape, never its numbers.

The harness is the regression witness of the RAM line (design 2026-09-02,
section 9, step 1).  What is pinned here is what makes its numbers readable:
the witnesses the design names come before any count, a count is a number
exactly when its witness says it was measured, and a rung that lost a witness
is refused instead of printed.  The full five-root ladder is not run here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.mcp_run_retention import (
    COUNT_KEYS,
    WITNESS_KEYS,
    HarnessError,
    main,
    materialize_roots,
    parse_pymalloc_stats,
    parse_vmmap_empty,
    parse_vmmap_malloc,
    parse_vmmap_summary,
    parse_vmmap_swapped,
    render_table,
)

from ._tmp_tree import write_files

# The design's benchmark-witness clause names these four; the harness may
# carry more, never fewer, and all of them sit before the first count.
_DESIGN_WITNESSES = frozenset(
    {"retained_runs", "freshness", "run_id", "footprint_source"}
)

_VMMAP_SUMMARY = """\
Process:         python3.14 [4242]
Path:            /usr/local/bin/python3.14
Physical footprint:         1.0G
Physical footprint (peak):  9760K
                                VIRTUAL RESIDENT    DIRTY  SWAPPED VOLATILE
REGION TYPE                        SIZE     SIZE     SIZE     SIZE     SIZE
Malloc Large                      23.3M    22.9M    22.9M       0K       0K
Malloc Large (empty)               1.1G   684.3M   684.3M    41.8M       0K
Malloc Small (empty)              52.0M    40.7M    40.7M    2768K       0K
TOTAL                            387.5G   513.0M   356.4M    1.5G       0K
                                 VIRTUAL   RESIDENT      DIRTY    SWAPPED \
ALLOCATION      BYTES DIRTY+SWAP          REGION
MALLOC ZONE                         SIZE       SIZE       SIZE       SIZE \
     COUNT  ALLOCATED  FRAG SIZE  % FRAG   COUNT
TOTAL                              60.5M      28.3M      28.3M         0K \
      2995      26.0M      2342K      9%      34
"""

_PYMALLOC_STATS = """\
# arenas allocated total           =                    3
# arenas allocated current         =                    3
3 arenas * 1048576 bytes/arena     =            3,145,728
# bytes in allocated blocks        =            2,824,176
# bytes in available blocks        =              279,520
1 unused pools * 16384 bytes       =               16,384
"""


def _write_source(root: Path) -> None:
    write_files(
        root,
        ("pkg/__init__.py", ""),
        ("pkg/mod.py", "def alpha(value: int) -> int:\n    return value + 1\n"),
    )


def _complete_rung() -> dict[str, object]:
    rung: dict[str, object] = dict.fromkeys(COUNT_KEYS, 1.0)
    rung.update(
        {
            "rung": "1",
            "retained_runs": 1,
            "run_id": "a" * 64,
            "freshness": "fresh",
            "scope_source": "filesystem_fallback",
            "footprint_source": "vmmap",
            "service_dir_unchanged": True,
        }
    )
    return rung


def test_vmmap_summary_reads_footprint_and_peak_in_mib() -> None:
    assert parse_vmmap_summary(_VMMAP_SUMMARY) == (1024.0, 9760 / 1024)


def test_vmmap_swapped_column_is_read_from_the_region_total_row() -> None:
    assert parse_vmmap_swapped(_VMMAP_SUMMARY) == 1536.0
    assert parse_vmmap_swapped("Physical footprint:  51.7M\n") is None


def test_vmmap_malloc_zones_report_allocated_bytes_and_freed_slack() -> None:
    assert parse_vmmap_malloc(_VMMAP_SUMMARY) == (26.0, 2342 / 1024)
    assert parse_vmmap_malloc("Physical footprint:  51.7M\n") is None


def test_vmmap_empty_allocator_regions_sum_their_dirty_and_swapped_pages() -> None:
    expected = 684.3 + 41.8 + 40.7 + 2768 / 1024
    assert parse_vmmap_empty(_VMMAP_SUMMARY) == pytest.approx(expected)
    assert parse_vmmap_empty("Physical footprint:  51.7M\n") is None


def test_vmmap_summary_without_its_peak_line_is_no_reading() -> None:
    assert parse_vmmap_summary("Physical footprint:         51.7M\n") is None


def test_pymalloc_stats_report_arenas_and_the_free_space_inside_them() -> None:
    arenas = parse_pymalloc_stats(_PYMALLOC_STATS)

    assert arenas.source == "pymalloc"
    assert arenas.arenas_mb == 3.0
    assert arenas.free_mb == round((279_520 + 16_384) / (1024 * 1024), 1)


def test_pymalloc_stats_missing_a_line_are_unavailable_not_zero() -> None:
    partial = _PYMALLOC_STATS.replace("1 unused pools", "unused pools")
    arenas = parse_pymalloc_stats(partial)

    assert arenas.source.startswith("unavailable:")
    assert arenas.arenas_mb is None
    assert arenas.free_mb is None


def test_copies_are_refused_inside_the_source_tree(tmp_path: Path) -> None:
    _write_source(tmp_path)

    with pytest.raises(HarnessError, match="outside --source"):
        materialize_roots(tmp_path, tmp_path / "roots", copies=1, entries=("pkg",))


def test_copies_are_refused_into_a_directory_that_holds_anything(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _write_source(source)
    occupied = tmp_path / "roots"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("not the harness's", encoding="utf-8")

    with pytest.raises(HarnessError, match="must be empty"):
        materialize_roots(source, occupied, copies=1, entries=("pkg",))
    assert (occupied / "keep.txt").read_text(encoding="utf-8") == "not the harness's"


def test_renderer_refuses_a_rung_that_lost_a_witness() -> None:
    complete = _complete_rung()
    assert render_table({"rungs": [complete]}).splitlines()[1].startswith("1 | ")

    for witness in WITNESS_KEYS:
        rung = dict(complete)
        del rung[witness]
        with pytest.raises(HarnessError, match="lacks witnesses"):
            render_table({"rungs": [rung]})


_VMMAP_COUNTS = (
    "footprint_mb",
    "peak_mb",
    "swapped_mb",
    "malloc_allocated_mb",
    "malloc_frag_mb",
    "malloc_empty_mb",
)


def _assert_rung_is_witnessed(rung: dict[str, object]) -> None:
    """Every witness is present, and a vmmap count exists iff vmmap read."""

    absent = [key for key in WITNESS_KEYS if rung.get(key) is None]
    assert not absent, (rung["rung"], absent)
    measured = rung["footprint_source"] == "vmmap"
    unmeasured = [
        count
        for count in _VMMAP_COUNTS
        if isinstance(rung[count], float) is not measured
    ]
    assert not unmeasured, (rung["rung"], unmeasured)
    assert isinstance(rung["live_records_mb"], float)
    assert isinstance(rung["load_1m"], float)


def _witness_columns(printed: str) -> set[str]:
    """The columns the table prints before its first count."""

    header = next(line for line in printed.splitlines() if line.startswith("rung |"))
    columns = header.split(" | ")
    first_count = min(columns.index(count) for count in COUNT_KEYS)
    return set(columns[:first_count])


def test_one_root_ladder_prints_every_witness_before_any_count(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    _write_source(source)
    ladder = tmp_path / "ladder.json"

    exit_code = main(
        [
            "--source",
            str(source),
            "--roots-dir",
            str(tmp_path / "roots"),
            "--copies",
            "1",
            "--entry",
            "pkg",
            "--json",
            str(ladder),
        ]
    )

    assert exit_code == 0
    result = json.loads(ladder.read_text(encoding="utf-8"))
    rungs = result["rungs"]
    assert [rung["rung"] for rung in rungs] == ["import", "1", "cleared"]
    assert [rung["retained_runs"] for rung in rungs] == [0, 1, 0]
    for rung in rungs:
        _assert_rung_is_witnessed(rung)
    analysed = rungs[1]
    assert analysed["files_analyzed"] + analysed["files_cached"] == 2
    assert analysed["analysis_s"] > 0
    assert analysed["live_records_mb"] > 0
    changes = analysed["service_dir_changes"]
    assert analysed["service_dir_unchanged"] is (not changes)
    assert all(path.startswith(".codeclone/") for path in changes)
    anatomy = result["anatomy"]["1"]
    assert anatomy["run_id"] == analysed["run_id"]
    assert "served_report" in anatomy["fields"]
    assert result["witnesses"]["missing_entries"] == []

    witnessed = _witness_columns(capsys.readouterr().out)
    assert witnessed >= _DESIGN_WITNESSES
    assert witnessed == set(WITNESS_KEYS)
