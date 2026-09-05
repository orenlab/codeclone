# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``print_run_outcome`` may not certify a gate it was never shown passing.

Its docstring stated the precondition -- "reached only when no gate refused,
so every branch here is a run that exits 0" -- and the ``gate_passed`` branch
spent it: ``gating_enabled`` alone chose the line that tells the reader
"Gate passed ... exit 0". Prose is not a precondition. Called after a refusal
the block printed a pass over a failing run, and nothing in the process could
have said otherwise, because the refusal never travelled here.

The gate's own verdict does now, and the block refuses rather than guesses.
Both boundaries are pinned apart, because each opposite error is its own
defect: a refusing gate must never reach the verdict line, and a passing gate
must still print it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from codeclone import ui_messages as ui
from codeclone.contracts import ExitCode
from codeclone.contracts.errors import ContractInvariantError
from codeclone.surfaces.cli.post_run import print_run_outcome


class _RecordingConsole:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *objects: object, **_kwargs: object) -> None:
        self.lines.append(" ".join(str(item) for item in objects))

    @property
    def text(self) -> str:
        return ui.strip_markup("\n".join(self.lines))


def _args(**overrides: object) -> Any:
    values: dict[str, object] = {"quiet": False, "update_baseline": False}
    values.update(overrides)
    return SimpleNamespace(**values)


def _print(*, gate_exit_code: int, console: _RecordingConsole) -> None:
    print_run_outcome(
        args=cast("Any", _args()),
        console=cast("Any", console),
        elapsed=0.5,
        notice_new_clones_count=0,
        clone_novelty_available=True,
        baseline_state=cast("Any", SimpleNamespace(updated_path=None, status=None)),
        baseline_display="codeclone.baseline.json",
        gating_enabled=True,
        html_report_path=None,
        has_findings=False,
        api_surface_enabled=False,
        api_surface_diff_available=False,
        files_found=7,
        gate_exit_code=gate_exit_code,
    )


def test_a_refusing_gate_can_never_be_printed_as_a_pass() -> None:
    """The defect, pinned: exit 3 arriving here is a bug, not a verdict.

    The guard is reachable -- this call reaches it -- which is the whole
    difference between an enforced precondition and a comment.
    """

    console = _RecordingConsole()

    with pytest.raises(ContractInvariantError) as raised:
        _print(gate_exit_code=int(ExitCode.GATING_FAILURE), console=console)

    assert "gate" in str(raised.value).lower()
    assert ui.OUTCOME_GATE_PASSED not in console.text


def test_a_contract_refusal_is_refused_on_the_same_terms() -> None:
    """Exit 2 is not exit 0 either: the guard reads the verdict, not one code."""

    console = _RecordingConsole()

    with pytest.raises(ContractInvariantError):
        _print(gate_exit_code=int(ExitCode.CONTRACT_ERROR), console=console)

    assert console.text.strip() == ""


def test_a_passing_gate_still_prints_the_verdict_it_earned() -> None:
    """The opposite boundary: the guard must not swallow the ordinary path."""

    console = _RecordingConsole()

    _print(gate_exit_code=int(ExitCode.SUCCESS), console=console)

    assert ui.OUTCOME_GATE_PASSED in console.text
    assert "exit 0" in console.text


def test_the_workflow_hands_the_gate_verdict_to_the_block() -> None:
    """The wiring, not only the guard: an unwired guard is theatre.

    A guard no caller feeds is a guard no input can trip in production, so
    what is pinned is that the one call site passes the gate's own exit code
    rather than a constant.
    """

    source = Path(__file__).resolve().parents[1] / "codeclone/surfaces/cli/workflow.py"
    text = source.read_text(encoding="utf-8")

    assert "gate_exit_code=gate_result.exit_code," in text
