# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Layout pins for the CLI grid.

Where wrapped text lands, what shape the banners have, and which blocks a
degenerate state is allowed to print. Every pin here was shown red under a
targeted mutation of the behaviour it holds (receipt 2026-09-05); a pin that
cannot be turned red by breaking its subject is not a pin.
"""

from __future__ import annotations

import contextlib
import io
from argparse import Namespace
from pathlib import Path
from typing import Any, cast

from rich.console import Console

from codeclone import ui_messages as ui
from codeclone.surfaces.cli import console as cli_console
from codeclone.surfaces.cli import summary as cli_summary
from codeclone.surfaces.cli import workflow as cli_workflow
from codeclone.surfaces.cli.types import PrinterLike
from codeclone.ui_messages.styling import _L, INDENT_UNIT

WIDTH = ui.CLI_LAYOUT_MAX_WIDTH
VALUE_COLUMN = INDENT_UNIT + _L
_LONG_PATH = "/" + "/".join(["directory-segment"] * 8)


def _render(*objects: object, width: int = WIDTH) -> list[str]:
    console = cli_console.make_console(no_color=True, width=width)
    with console.capture() as capture:
        console.print(*objects)
    return capture.get().splitlines()


# ---------------------------------------------------------------------------
# The grid itself
# ---------------------------------------------------------------------------


def test_value_column_lies_on_the_grid() -> None:
    # The label field opens the value column; a continuation hung under a
    # value must land on a grid column, so the field width keeps the sum even.
    assert VALUE_COLUMN % INDENT_UNIT == 0


def test_label_row_continuation_hangs_under_the_value() -> None:
    lines = _render(ui.fmt_banner_root(_LONG_PATH))
    assert len(lines) >= 2, lines
    assert lines[0].startswith("  Root")
    assert lines[0][VALUE_COLUMN] == "/"
    for continuation in lines[1:]:
        assert continuation.startswith(" " * VALUE_COLUMN), continuation
        assert continuation[VALUE_COLUMN] != " ", continuation
    # Folded, never cropped: the path survives byte for byte.
    assert "".join(line[VALUE_COLUMN:] for line in lines) == _LONG_PATH


def test_detail_line_continuation_hangs_under_its_own_indent() -> None:
    warning = ui.fmt_cli_runtime_warning(f"Coverage join ignored: {_LONG_PATH}")
    lines = _render(warning)
    assert lines[0].startswith(f"  {ui.GLYPH_WARN} Coverage join ignored")
    details = lines[1:]
    assert len(details) >= 2, lines
    for detail in details:
        assert detail.startswith(" " * 4) and detail[4] != " ", detail


def test_bullet_continuation_hangs_under_the_bullet_text() -> None:
    lines = _render("    - " + " ".join(["word"] * 40))
    assert len(lines) >= 2, lines
    assert lines[0].startswith("    - word")
    for continuation in lines[1:]:
        assert continuation.startswith(" " * 6) and continuation[6] == "w", continuation


def test_no_rendered_line_exceeds_the_console_width() -> None:
    lines = _render(
        ui.fmt_banner_root(_LONG_PATH),
        ui.fmt_cli_runtime_warning(f"Coverage join ignored: {_LONG_PATH}"),
        ui.fmt_contract_error(ui.ERR_ROOT_NOT_FOUND.format(path=_LONG_PATH)),
    )
    assert max(len(line) for line in lines) <= WIDTH


def test_the_grid_console_is_still_a_rich_console() -> None:
    console = cli_console.make_console(no_color=True, width=WIDTH)
    assert isinstance(console, Console)
    assert cli_console.supports_rich_console(cast(PrinterLike, console))


# ---------------------------------------------------------------------------
# Banners
# ---------------------------------------------------------------------------


def test_contract_error_banner_shape() -> None:
    rendered = ui.strip_markup(ui.fmt_contract_error("Root path does not exist.\nhint"))
    assert rendered.splitlines() == [
        "",
        f"  {ui.GLYPH_FAIL} CONTRACT ERROR",
        "    Root path does not exist.",
        "    hint",
    ]


def test_bracketed_payload_survives_the_error_banner() -> None:
    # The diagnosis that names the wrong value must not lose it to markup:
    # a validator's ``[type=value_error]`` and an OSError's ``[Errno 2]`` are
    # payload, and the banner renders them byte for byte.
    payload = "baseline_scope_id [type=value_error, input_value='nope'] [Errno 2]"
    lines = _render(
        ui.fmt_contract_error(ui.esc(payload)),
        ui.fmt_invalid_baseline_path(
            path=Path("/tmp/[x]/b.json"), error="[Errno 2] gone"
        ),
    )
    joined = "\n".join(lines)
    assert "[type=value_error, input_value='nope']" in joined
    assert "[Errno 2]" in joined
    assert "/tmp/[x]/b.json" in joined


def test_internal_error_banner_shape() -> None:
    rendered = ui.strip_markup(ui.fmt_internal_error(ValueError("boom")))
    lines = rendered.splitlines()
    assert lines[:3] == [
        "",
        f"  {ui.GLYPH_FAIL} INTERNAL ERROR",
        "    Unexpected exception.",
    ]
    assert all(line.startswith("    ") for line in lines[2:] if line)


# ---------------------------------------------------------------------------
# Degenerate states print what answers the question, nothing more
# ---------------------------------------------------------------------------


def _metrics_snapshot(population: str) -> cli_summary.MetricsSnapshot:
    return cli_summary.MetricsSnapshot(
        complexity_avg=0.0,
        complexity_max=0,
        high_risk_count=0,
        coupling_avg=0.0,
        coupling_max=0,
        cohesion_avg=0.0,
        cohesion_max=0,
        cycles_count=0,
        dead_code_count=0,
        health_total=0,
        health_grade="F",
        health_population=population,
    )


def test_unmeasured_population_prints_the_health_line_alone() -> None:
    console = cli_console.make_console(no_color=True, width=WIDTH)
    with console.capture() as capture:
        cli_summary._print_metrics(
            console=cast(Any, console),
            quiet=False,
            metrics=_metrics_snapshot("complete_empty"),
        )
    rows = [line for line in capture.get().splitlines() if line.startswith("  ")]
    assert rows == [f"  {'Health':<{_L}}not measured (no source file in scope)"], rows


def test_measured_population_prints_every_metric_row() -> None:
    console = cli_console.make_console(no_color=True, width=WIDTH)
    with console.capture() as capture:
        cli_summary._print_metrics(
            console=cast(Any, console),
            quiet=False,
            metrics=_metrics_snapshot("complete_nonempty"),
        )
    rows = [line for line in capture.get().splitlines() if line.startswith("  ")]
    assert [row.split()[0] for row in rows] == [
        "Health",
        "Complexity",
        "Coupling",
        "Cohesion",
        "Cycles",
        "Dependencies",
        "Security",
        "Dead",
        "Overloaded",
    ]


def test_empty_scope_summary_stops_at_the_file_row() -> None:
    console = cli_console.make_console(no_color=True, width=WIDTH)
    with console.capture() as capture:
        cli_summary._print_summary(
            console=cast(Any, console),
            quiet=False,
            files_found=0,
            files_analyzed=0,
            cache_hits=0,
            files_skipped=0,
            func_clones_count=0,
            block_clones_count=0,
            segment_clones_count=0,
            suppressed_clone_groups=0,
            low_value_segment_groups=0,
            new_clones_count=None,
            novelty_reason=ui.NOVELTY_REASON_NO_BASELINE,
            metrics_skipped="no_baseline",
        )
    rows = [line for line in capture.get().splitlines() if line.startswith("  ")]
    assert [row.split()[0] for row in rows] == ["Files"], rows


# ---------------------------------------------------------------------------
# The run outcome names the commands that apply, in order
# ---------------------------------------------------------------------------


def test_first_run_outcome_orders_baseline_before_ci() -> None:
    rendered = ui.strip_markup(
        ui.fmt_run_outcome(
            kind="not_compared",
            elapsed=0.05,
            reason=ui.NOVELTY_REASON_NO_BASELINE,
        )
    )
    assert rendered.index(ui.ACTION_UPDATE_BASELINE) < rendered.index(ui.ACTION_CI)
    assert ui.ACTION_FAIL_ON_NEW not in rendered


def test_clean_outcome_offers_no_command() -> None:
    rendered = ui.strip_markup(ui.fmt_run_outcome(kind="clean", elapsed=0.04))
    assert "codeclone ." not in rendered
    assert ui.OUTCOME_CLEAN in rendered


def test_new_clones_outcome_offers_block_and_accept() -> None:
    rendered = ui.strip_markup(
        ui.fmt_run_outcome(kind="new_clones", elapsed=0.06, new_clones=1)
    )
    assert "1 new clone group since the baseline" in rendered
    assert rendered.index(ui.ACTION_FAIL_ON_NEW) < rendered.index(
        ui.ACTION_UPDATE_BASELINE
    )


def test_outcome_commands_share_one_column() -> None:
    rendered = ui.strip_markup(
        ui.fmt_run_outcome(
            kind="new_clones",
            elapsed=0.06,
            new_clones=2,
            show_locations=True,
            api_not_compared=True,
        )
    )
    columns = {
        line.index("codeclone .")
        for line in rendered.splitlines()
        if "codeclone ." in line
    }
    assert len(columns) == 1, rendered


# ---------------------------------------------------------------------------
# The gate block
# ---------------------------------------------------------------------------


def test_gate_block_rows_are_words_on_the_grid() -> None:
    console = cli_console.make_console(no_color=True, width=WIDTH)
    with console.capture() as capture:
        cli_console._print_gating_failure_block(
            console=cast(PrinterLike, console),
            code="new-clones",
            entries=[("new_function_clone_groups", 1), ("new_block_clone_groups", 0)],
            args=cast(Any, Namespace(ci=False, fail_on_new=True)),
        )
    lines = capture.get().splitlines()
    assert lines[0] == ""
    assert lines[1].startswith(f"  {ui.GLYPH_FAIL} GATING FAILURE [new-clones]")
    assert lines[1].endswith("exit 3")
    rows = lines[2:]
    assert [row.strip().split("  ")[0] for row in rows if row.strip()] == [
        "Policy",
        "New function clone groups",
        "New block clone groups",
    ]
    assert all(row.startswith("    ") and not row.startswith("     ") for row in rows)


# ---------------------------------------------------------------------------
# One width for the whole command
# ---------------------------------------------------------------------------


def test_controller_query_screens_share_the_analysis_width() -> None:
    console = cli_workflow._controller_query_console(
        cast(Any, Namespace(no_color=True, quiet=False))
    )
    assert cast(Console, console).width == ui.CLI_LAYOUT_MAX_WIDTH


def test_quiet_query_screens_print_through_the_plain_console() -> None:
    # One line per screen for logs: a width-bound console would fold it.
    console = cli_workflow._controller_query_console(
        cast(Any, Namespace(no_color=True, quiet=True))
    )
    assert isinstance(console, cli_console.PlainConsole)


def test_blast_radius_entries_sharing_a_reason_share_one_line() -> None:
    from codeclone.surfaces.cli.blast_radius import _print_entries

    console = cli_console.make_console(no_color=True, width=WIDTH)
    with console.capture() as capture:
        _print_entries(
            console=cast(PrinterLike, console),
            title="Do not touch",
            entries=[
                {"path": ".codeclone/**", "reason": "state", "severity": "hard"},
                {
                    "path": "codeclone.baseline.json",
                    "reason": "state",
                    "severity": "hard",
                },
                {"path": "docs/**", "reason": "generated", "severity": "soft"},
            ],
        )
    lines = [line for line in capture.get().splitlines() if line.strip()]
    assert lines[0] == "  Do not touch (3)"
    assert lines[1] == "    .codeclone/**, codeclone.baseline.json"
    assert lines[2] == "      state [hard]"
    assert lines[3] == "    docs/**"
    assert lines[4] == "      generated [soft]"


def test_plain_console_output_is_untouched_by_the_grid() -> None:
    # Quiet mode prints for logs: no wrapping, no markup, one line per call.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        cli_console.make_plain_console().print(ui.fmt_banner_root(_LONG_PATH))
    assert buffer.getvalue() == f"  {'Root':<{_L}}{_LONG_PATH}\n"


# ---------------------------------------------------------------------------
# The memory screens share the analysis width
# ---------------------------------------------------------------------------


def test_memory_screens_share_the_analysis_width() -> None:
    from codeclone.surfaces.cli.memory_render import memory_console

    assert cast(Console, memory_console()).width == ui.CLI_LAYOUT_MAX_WIDTH
