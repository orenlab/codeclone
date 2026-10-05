# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A gate never reads a delta its run did not compare (ruling 2026-10-03/05).

Every gate input that is a comparison against the baseline is read off the
run's one normalized comparison state (``contracts.comparison_state``):
``compared(value)`` or ``not_compared(reason)``.  A requested gate whose
input was not compared neither "passes on 0" nor "fails on a raw count": it
takes the evaluator's EXISTING honest outcome for a comparison it cannot
make -- ``CONTRACT_ERROR`` with ``lane:unavailable:<lane>`` for every lane
of every such gate.  No new outcome is invented.

Measured before the change (2026-10-05, the comparison corpus): a partial
run with ``--fail-on-api-break`` exited 3 on ``breaking: 2`` beside a
document saying the API was not compared; with ``--fail-on-new-metrics``
(and ``--ci``, which turns it on) it exited 3 on four raw set-difference
counts the document called not compared.
"""

from __future__ import annotations

import json
import shutil

import pytest

from codeclone.contracts import ExitCode
from codeclone.report.gates import evaluator
from codeclone.report.gates.evaluator import (
    GateState,
    MetricGateConfig,
    evaluate_gate_state,
    metric_gate_reasons_for_state,
)
from codeclone.utils.coerce import as_sequence
from tests import conftest as corpora
from tests._patch_contract_serving import shared_cycles, stored_patch_run

_SET_DIFF_LANES = (
    "lane:unavailable:coupling_cohesion_observations",
    "lane:unavailable:dead_code",
    "lane:unavailable:dependencies",
    "lane:unavailable:risk_observations",
)
_NEW_METRICS_REASONS = (
    "metric:New high-risk functions vs metrics baseline: 1.",
    "metric:New high-coupling classes vs metrics baseline: 1.",
    "metric:New import-time dependency cycles vs metrics baseline: 1.",
    "metric:New dead code items vs metrics baseline: 1.",
)

#: (population, gate flags) -> (exit code, reasons) of the CLI run.  The
#: partial rows are the changed outcomes; the others are positive controls:
#: a comparison that ran keeps its verdict, measured.
CLI_GATE_OUTCOMES: dict[tuple[str, str], tuple[int, tuple[str, ...]]] = {
    ("partial", "--fail-on-api-break"): (2, ("lane:unavailable:api_surface",)),
    ("partial", "--fail-on-new-metrics"): (2, _SET_DIFF_LANES),
    ("partial", "--ci"): (2, _SET_DIFF_LANES),
    ("partial", "--fail-on-typing-regression"): (
        3,
        (
            "metric:Typing coverage regressed vs metrics baseline: "
            "params_delta=-103, returns_delta=-44.",
        ),
    ),
    ("compared", "--fail-on-api-break"): (
        3,
        ("metric:Public API breaking changes vs metrics baseline: 2.",),
    ),
    ("compared", "--fail-on-new-metrics"): (3, _NEW_METRICS_REASONS),
    ("compared", "--ci"): (3, (*_NEW_METRICS_REASONS, "clone:new")),
}


@pytest.fixture(scope="module")
def cli_gate_runs(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[tuple[str, str], tuple[object, dict[str, object]]]:
    """Each row of :data:`CLI_GATE_OUTCOMES` as one CLI execution of the
    comparison corpus: its exit code and its document's gate outcome."""
    base = tmp_path_factory.mktemp("gate_not_compared").resolve()
    baseline = corpora._comparison_baseline(base)
    runs: dict[tuple[str, str], tuple[object, dict[str, object]]] = {}
    for population, flag in CLI_GATE_OUTCOMES:
        root = base / f"{population}{flag}"
        corpora.materialize_comparison_corpus(root, stage_b=True)
        if population == "partial":
            corpora._write_unparsable(root)
        report = base / f"{population}{flag}.json"
        code = corpora._run_codeclone_cli_exit(
            [
                str(root),
                "--no-progress",
                "--baseline",
                str(baseline),
                "--json",
                str(report),
                "--api-surface",
                flag,
            ],
            {},
        )
        document = json.loads(report.read_text("utf-8"))
        runs[(population, flag)] = (code, document["evaluation"]["outcome"])
    return runs


@pytest.mark.parametrize(("population", "flag"), list(CLI_GATE_OUTCOMES))
def test_the_cli_gate_reads_the_comparison_state(
    cli_gate_runs: dict[tuple[str, str], tuple[object, dict[str, object]]],
    population: str,
    flag: str,
) -> None:
    exit_code, reasons = CLI_GATE_OUTCOMES[(population, flag)]
    code, outcome = cli_gate_runs[(population, flag)]
    assert (code, outcome["exit_code"], tuple(as_sequence(outcome["reasons"]))) == (
        exit_code,
        exit_code,
        reasons,
    )


# -- the evaluator's own laws, over a hand-built state ----------------------------

_TRUSTED = dict.fromkeys(
    (
        "api_surface",
        "adoption_counts",
        "clones.blocks",
        "clones.functions",
        "coupling_cohesion_observations",
        "dead_code",
        "dependencies",
        "module_identity",
        "risk_observations",
    ),
    "trusted",
)


def _config(**gates: object) -> MetricGateConfig:
    return MetricGateConfig(
        **{  # type: ignore[arg-type]
            "fail_complexity": -1,
            "fail_coupling": -1,
            "fail_cohesion": -1,
            "fail_cycles": False,
            "fail_dead_code": False,
            "fail_health": -1,
            "fail_on_new_metrics": False,
            **gates,
        }
    )


def _evaluate(state: GateState, **gates: object) -> tuple[int, tuple[str, ...]]:
    result = evaluate_gate_state(
        state=state,
        config=_config(**gates),
        lane_trust=_TRUSTED,
        enabled_lanes=tuple(_TRUSTED),
    )
    return result.exit_code, result.reasons


def test_an_uncompared_delta_is_an_unavailable_lane_never_a_zero() -> None:
    """``None`` refuses; the measured zero beside it passes and a measured
    break fails -- the three outcomes of one gate, by its input alone."""
    assert _evaluate(GateState(api_breaking_changes=None), fail_on_api_break=True) == (
        int(ExitCode.CONTRACT_ERROR),
        ("lane:unavailable:api_surface",),
    )
    assert _evaluate(GateState(api_breaking_changes=0), fail_on_api_break=True) == (
        int(ExitCode.SUCCESS),
        (),
    )
    assert _evaluate(GateState(api_breaking_changes=2), fail_on_api_break=True) == (
        int(ExitCode.GATING_FAILURE),
        ("metric:Public API breaking changes vs metrics baseline: 2.",),
    )


def test_only_a_requested_gate_refuses_on_an_uncompared_delta() -> None:
    """A delta nobody gates on is not a refusal: an uncompared API surface
    under a typing-regression request is answered by that request alone."""
    state = GateState(
        api_breaking_changes=None,
        diff_typing_param_permille_delta=-5,
        diff_typing_return_permille_delta=0,
        diff_docstring_permille_delta=0,
    )
    assert _evaluate(state, fail_on_typing_regression=True) == (
        int(ExitCode.GATING_FAILURE),
        (
            "metric:Typing coverage regressed vs metrics baseline: "
            "params_delta=-5, returns_delta=0.",
        ),
    )


def test_the_population_refusal_answers_before_an_uncompared_delta() -> None:
    """On a population nobody measured every comparison is withheld; the
    population's own refusal keeps answering, as it did before the state."""
    state = GateState(
        health_population="unmeasured",
        **dict.fromkeys(evaluator.GATE_COMPARISON_TERMS, None),  # type: ignore[arg-type]
    )
    code, reasons = _evaluate(state, fail_on_new_metrics=True)
    assert code == int(ExitCode.GATING_FAILURE)
    assert len(reasons) == 1 and reasons[0].startswith("metric:")


def test_a_reason_reader_never_reads_an_uncompared_delta_as_a_number() -> None:
    """The reasons function has no refusal of its own: asked for a requested
    gate over an uncompared delta it refuses loudly rather than answer
    ``0`` -- the second guard, reachable without the evaluator's first."""
    with pytest.raises(ValueError, match="did not compare"):
        metric_gate_reasons_for_state(
            state=GateState(api_breaking_changes=None),
            config=_config(fail_on_api_break=True),
        )
    assert (
        metric_gate_reasons_for_state(
            state=GateState(api_breaking_changes=None),
            config=_config(fail_on_api_break=False),
        )
        == ()
    )


# -- a new deferred cycle is a new cycle, never a new import cycle ----------------

#: The three builders of the gate's record, each over the same change: the
#: patch battery's ``deferred_cycle`` -- a fresh baseline, then two modules
#: importing each other inside their functions.  The run states one new
#: cycle and no new import-time cycle; only the import-time one gates
#: (``dependency_delta`` reads ``diff_new_import_cycles``).
_ROADS = ("cli", "document", "store")
#: One builder's reading: (new cycles, new import cycles, exit code, reasons).
_RoadGate = tuple[int | None, int | None, int, tuple[str, ...]]


@pytest.fixture(scope="module")
def deferred_cycle_gates(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, _RoadGate]:
    """Per builder, under ``fail_on_new_metrics``: (new cycles, new import
    cycles, exit code, reasons).  The CLI analyses its own copy of the
    cycle's tree against the same baseline, so the battery's tree is never
    written; its record is read off the document it writes."""
    cycle = shared_cycles(tmp_path_factory)["deferred_cycle"]
    after = cycle.after
    assert after is not None
    config = _config(fail_on_new_metrics=True)
    clones = {
        "clone_new_count": len(after.new_func) + len(after.new_block),
        "clone_total": after.func_clones_count + after.block_clones_count,
    }
    documented = evaluator.evaluate_gates(
        report_document=after.served_report,
        config=config,
        enabled_lanes=after.served_report.contract.enabled_lanes,
        **clones,
    )
    document_state = evaluator._gate_state_from_report_document(
        report_document=after.served_report, **clones
    )
    served = stored_patch_run(cycle.store_path, after)
    stored = evaluate_gate_state(
        state=served.gate_state,
        config=config,
        lane_trust=served.lane_trust,
        enabled_lanes=served.enabled_lanes,
    )
    copy = tmp_path_factory.mktemp("deferred_cycle_cli") / "tree"
    shutil.copytree(
        cycle.root, copy, ignore=shutil.ignore_patterns(".codeclone", ".cache")
    )
    report = copy.parent / "report.json"
    code = corpora._run_codeclone_cli_exit(
        [
            str(copy),
            "--no-progress",
            "--api-surface",
            "--baseline",
            str(copy / "codeclone.baseline.json"),
            "--json",
            str(report),
            "--fail-on-new-metrics",
        ],
        {},
    )
    written = json.loads(report.read_text("utf-8"))
    outcome = written["evaluation"]["outcome"]
    cli_state = evaluator._gate_state_from_report_document(report_document=written)
    assert outcome["exit_code"] == (code or 0)
    return {
        "cli": (
            cli_state.diff_new_cycles,
            cli_state.diff_new_import_cycles,
            int(outcome["exit_code"]),
            tuple(str(reason) for reason in as_sequence(outcome["reasons"])),
        ),
        "document": (
            document_state.diff_new_cycles,
            document_state.diff_new_import_cycles,
            documented.exit_code,
            tuple(documented.reasons),
        ),
        "store": (
            served.gate_state.diff_new_cycles,
            served.gate_state.diff_new_import_cycles,
            stored.exit_code,
            tuple(stored.reasons),
        ),
    }


@pytest.mark.parametrize("road", _ROADS)
def test_a_new_deferred_cycle_does_not_fail_the_new_import_cycle_gate(
    deferred_cycle_gates: dict[str, _RoadGate],
    road: str,
) -> None:
    """A new deferred cycle is counted, never gated: one new cycle, no new
    import-time cycle, and ``fail_on_new_metrics`` passes on every builder
    (measured 2026-10-06: ``(1, 0, 0, ())`` on all three).  The population
    distinguishes the two terms, so an import-cycle input read off every
    new cycle fails this gate with the import-cycle reason."""
    new_cycles, new_import_cycles, exit_code, reasons = deferred_cycle_gates[road]
    assert new_cycles == 1
    assert (new_import_cycles, exit_code, reasons) == (0, int(ExitCode.SUCCESS), ())
