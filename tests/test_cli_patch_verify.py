# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import contextlib
import io
import re
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import codeclone.surfaces.cli.changed_scope as cli_changed_scope
import codeclone.surfaces.cli.workflow as cli_workflow
from codeclone.contracts import ExitCode
from codeclone.contracts.comparison_state import COMPARISON_HEALTH, TERM_SCORE_DELTA
from codeclone.core._types import AnalysisResult
from codeclone.models import (
    HealthScore,
    LaneTrust,
    MetricsDiff,
    ObservationLaneName,
    ProjectMetrics,
    TrustVector,
)
from codeclone.report.messages import gates as gate_msgs
from codeclone.surfaces.cli.patch_verify import (
    patch_gate_config,
    render_patch_verify,
    validate_strictness,
)
from codeclone.surfaces.cli.post_run import DiffContext
from tests import conftest as corpora
from tests._report_fixtures import build_test_report_document
from tests.test_observation_contract import TEST_OBSERVATION_BUNDLE


class _RecordingPrinter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *objects: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(item) for item in objects))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "fail_complexity": -1,
        "fail_coupling": -1,
        "fail_cohesion": -1,
        "fail_cycles": False,
        "fail_dead_code": False,
        "fail_health": -1,
        "fail_on_new_metrics": False,
        "fail_on_typing_regression": False,
        "fail_on_docstring_regression": False,
        "fail_on_api_break": False,
        "fail_on_untested_hotspots": False,
        "min_typing_coverage": -1,
        "min_docstring_coverage": -1,
        "coverage_min": 50,
    }
    values.update(overrides)
    return Namespace(**values)


def _analysis(*, function_clones: int = 0) -> AnalysisResult:
    return AnalysisResult(
        func_groups={},
        block_groups={},
        block_groups_report={},
        segment_groups={},
        low_value_segment_groups=0,
        block_group_facts={},
        func_clones_count=function_clones,
        block_clones_count=0,
        segment_clones_count=0,
        files_analyzed_or_cached=1,
        project_metrics=None,
        metrics_payload=None,
        suggestions=(),
        segment_groups_raw_digest="",
        observation_bundle=TEST_OBSERVATION_BUNDLE,
    )


def _diff_context(
    *, new_clones: int = 0, clone_novelty_available: bool = True
) -> DiffContext:
    return DiffContext(
        new_func={f"func-{index}" for index in range(new_clones)},
        new_block=set(),
        new_clones_count=new_clones,
        clone_novelty_available=clone_novelty_available,
        metrics_diff=None,
        coverage_adoption_diff_available=False,
        api_surface_diff_available=False,
    )


def _baseline_state(*, trusted: bool = True, status: str = "ok") -> object:
    """The clone baseline state the verifier reads: whether it is trusted
    for a diff, and its status (a ``BaselineStatus`` -- its ``value`` is
    what the verifier names)."""
    return SimpleNamespace(
        trusted_for_diff=trusted, status=SimpleNamespace(value=status)
    )


#: The clone lanes a baseline of another algorithm revision leaves opaque.
_OPAQUE_CLONE_LANES = frozenset({"clones.functions", "clones.blocks"})


def _report_document(
    *,
    gate_exit_code: int = 0,
    gate_reasons: tuple[str, ...] = (),
    opaque_lanes: frozenset[str] = frozenset(),
) -> dict[str, object]:
    trust = TrustVector(
        root_verified=True,
        lanes=tuple(
            _lane_trust(lane, opaque=lane in opaque_lanes)
            for lane in TEST_OBSERVATION_BUNDLE.contract.enabled_lanes
        ),
    )
    return build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        baseline_trust=trust,
        gate_exit_code=gate_exit_code,
        gate_reasons=gate_reasons,
    )


def _lane_trust(lane: ObservationLaneName, *, opaque: bool) -> LaneTrust:
    if opaque:
        return LaneTrust(name=lane, status="unavailable", reason="algorithm_revision")
    return LaneTrust(name=lane, status="trusted", reason="compatible")


#: The labelled lines of a patch verdict (ruling 2026-10-20 (13)), verbatim.
_VERDICT_LABELS = (
    "Verdict:",
    "Completeness:",
    "Exit:",
    "Proven violations:",
    "Unverified lanes:",
    "Policy failures (missing measurement):",
    "Internal error:",
)


def _verdict_block(text: str) -> tuple[str, ...]:
    """Every labelled verdict line the output holds, in order."""
    return tuple(
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith(_VERDICT_LABELS)
    )


def test_patch_verify_accepts_clean_patch_quiet() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        report_document=_report_document(),
        analysis=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert printer.text == (
        "patch-verify: accepted | health=0 delta=n/a (not compared) "
        "regressions=0 gates=PASS\n"
        "  Verdict: ACCEPTED\n"
        "  Completeness: COMPLETE\n"
        "  Exit: 0\n"
        "  Proven violations: []\n"
        "  Unverified lanes: []"
    )


@pytest.mark.parametrize(
    ("strictness", "expected_code", "expected_text"),
    [
        (
            "ci",
            int(ExitCode.GATING_FAILURE),
            "patch-verify: violated | health=0 delta=n/a (not compared) "
            "regressions=1 gates=VIOLATED\n"
            "  Verdict: VIOLATED\n"
            "  Completeness: COMPLETE\n"
            "  Exit: 3 (proven violation)\n"
            "  Proven violations: [structural_regressions, gate_failures]\n"
            "  Unverified lanes: []",
        ),
        (
            "relaxed",
            int(ExitCode.SUCCESS),
            "patch-verify: violated | health=0 delta=n/a (not compared) "
            "regressions=1 gates=PASS\n"
            "  Verdict: VIOLATED\n"
            "  Completeness: COMPLETE\n"
            "  Exit: 0 (relaxed: violations are advisory)\n"
            "  Proven violations: [structural_regressions]\n"
            "  Unverified lanes: []",
        ),
    ],
)
def test_patch_verify_reports_clone_regressions_by_strictness(
    strictness: str,
    expected_code: int,
    expected_text: str,
) -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness=strictness,
        report_document=_report_document(
            gate_exit_code=(
                int(ExitCode.SUCCESS)
                if strictness == "relaxed"
                else int(ExitCode.GATING_FAILURE)
            )
        ),
        analysis=_analysis(function_clones=1),
        diff_context=_diff_context(new_clones=1),
        baseline_state=cast(Any, _baseline_state()),
        quiet=True,
    )

    assert exit_code == expected_code
    assert printer.text == expected_text


@pytest.mark.parametrize("strictness", ["ci", "strict", "relaxed"])
def test_patch_verify_requires_trusted_baseline(strictness: str) -> None:
    """A baseline this run cannot trust compared nothing: ``unverified`` with
    the contract-error code under every profile, and the reason named --
    never ``accepted``, never the code of a proven violation."""
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness=strictness,
        report_document=_report_document(),
        analysis=_analysis(),
        diff_context=_diff_context(clone_novelty_available=False),
        baseline_state=cast(
            Any,
            _baseline_state(trusted=False, status="mismatch_scope_id"),
        ),
        quiet=True,
    )

    assert exit_code == int(ExitCode.CONTRACT_ERROR)
    assert (
        "Patch verify requires a trusted baseline" in printer.text,
        "\npatch-verify: unverified |" in printer.text,
        _verdict_block(printer.text),
    ) == (
        True,
        True,
        (
            "Verdict: UNVERIFIED",
            "Completeness: INCOMPLETE",
            "Exit: 2 (required verification unavailable)",
            "Proven violations: []",
            "Unverified lanes: [baseline:mismatch_scope_id, clones:not_compared]",
        ),
    ), printer.text


def test_patch_verify_validates_strictness_values() -> None:
    assert validate_strictness("ci") == "ci"
    assert validate_strictness("strict") == "strict"
    assert validate_strictness("relaxed") == "relaxed"
    with pytest.raises(ValueError, match="Invalid --strictness value"):
        validate_strictness("nope")


def test_patch_gate_config_covers_strictness_threshold_profiles() -> None:
    strict = patch_gate_config(
        args=cast(
            Any,
            _args(
                fail_complexity=11,
                fail_coupling=7,
                fail_cohesion=4,
            ),
        ),
        strictness="strict",
    )
    relaxed = patch_gate_config(
        args=cast(Any, _args()),
        strictness="relaxed",
    )

    assert strict.fail_complexity == 10
    assert strict.fail_coupling == 5
    assert strict.fail_cohesion == 3
    assert relaxed.fail_complexity == -1
    assert relaxed.fail_coupling == -1
    assert relaxed.fail_cohesion == -1


def test_patch_verify_rejects_invalid_strictness() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="nope",
        report_document=_report_document(),
        analysis=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=True,
    )

    assert exit_code == int(ExitCode.CONTRACT_ERROR)
    assert "Invalid --strictness value" in printer.text


def test_patch_verify_verbose_accepted() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        report_document=_report_document(),
        analysis=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    text = printer.text
    assert "accepted" in text.lower()
    expected_sections = (
        "Patch Verify",
        "Strictness",
        "Health",
        "Regressions",
        "Gate preview",
        "Patch contract accepted",
    )
    for section in expected_sections:
        assert section in text, f"Missing section: {section}"


def test_patch_verify_verbose_violated() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        report_document=_report_document(gate_exit_code=int(ExitCode.GATING_FAILURE)),
        analysis=_analysis(function_clones=1),
        diff_context=_diff_context(new_clones=1),
        baseline_state=cast(Any, _baseline_state()),
        quiet=False,
    )

    assert exit_code == int(ExitCode.GATING_FAILURE)
    text = printer.text
    assert "violated" in text.lower()
    assert "structural_regressions" in text
    assert "Patch contract violated" in text


def test_patch_verify_renders_canonical_gate_reasons() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        report_document=_report_document(
            gate_exit_code=int(ExitCode.GATING_FAILURE),
            gate_reasons=("clone:new",),
        ),
        analysis=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=False,
    )

    assert exit_code == int(ExitCode.GATING_FAILURE)
    assert "clone:new" in printer.text


def test_patch_verify_missing_canonical_evaluation_fails_closed() -> None:
    """No evaluation in the document: the gate did not run, so the patch is
    not verified -- the contract-error code, never ``accepted`` and never
    the code of a violation nobody proved.

    The gate label used to read ``FAIL`` here, the same word as a gate that
    failed on a fact; this pin held it.  The maintainer's ruling of
    2026-10-23 names a gate that never ran ``UNAVAILABLE``, so the
    label agrees with the verdict beneath it instead of contradicting it."""
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        report_document={},
        analysis=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=True,
    )

    assert exit_code == int(ExitCode.CONTRACT_ERROR)
    assert (printer.lines[0], _verdict_block(printer.text)) == (
        "patch-verify: unverified | health=0 delta=n/a (not compared) "
        "regressions=0 gates=UNAVAILABLE",
        (
            "Verdict: UNVERIFIED",
            "Completeness: INCOMPLETE",
            "Exit: 2 (required verification unavailable)",
            "Proven violations: []",
            "Unverified lanes: [report:evaluation:missing]",
        ),
    ), printer.text


# -- not verified: a required check that did not run ----------------------------
#
# ``violated`` is a proven failure; ``unverified`` is a check that did not run
# completely.  Two claims, two statuses, two texts; the code of a proven
# violation (3) is never spent on what was not compared, and what was not
# compared is never ``accepted``.  ``unverified`` exits with the contract-error
# code (2) the gate itself uses for an unavailable lane, under every profile.

_NOT_COMPARED_COMPACT = "regressions=n/a (not compared)"


def _render(
    *,
    strictness: str,
    report_document: dict[str, object],
    diff_context: DiffContext,
    quiet: bool,
    function_clones: int = 0,
) -> tuple[int, str]:
    printer = _RecordingPrinter()
    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness=strictness,
        report_document=report_document,
        analysis=_analysis(function_clones=function_clones),
        diff_context=diff_context,
        baseline_state=cast(Any, _baseline_state()),
        quiet=quiet,
    )
    return exit_code, printer.text


def _opaque_clone_gate(strictness: str) -> dict[str, object]:
    """The document an opaque-clone-lane run states: the gate reads the
    clone lanes under ``ci`` and ``strict`` (``fail_on_new``) and cannot."""
    if strictness == "relaxed":
        return _report_document(opaque_lanes=_OPAQUE_CLONE_LANES)
    return _report_document(
        gate_exit_code=int(ExitCode.CONTRACT_ERROR),
        gate_reasons=(
            "lane:unavailable:clones.blocks",
            "lane:unavailable:clones.functions",
        ),
        opaque_lanes=_OPAQUE_CLONE_LANES,
    )


@pytest.mark.parametrize("strictness", ["relaxed", "ci", "strict"])
def test_uncompared_clone_lanes_are_unverified_not_accepted_or_violated(
    strictness: str,
) -> None:
    exit_code, text = _render(
        strictness=strictness,
        report_document=_opaque_clone_gate(strictness),
        diff_context=_diff_context(clone_novelty_available=False),
        quiet=True,
    )
    assert exit_code == int(ExitCode.CONTRACT_ERROR), text
    assert text.startswith("patch-verify: unverified |"), text
    assert _NOT_COMPARED_COMPACT in text
    assert "regressions=0" not in text
    assert "clones.blocks:algorithm_revision" in text
    assert "clones.functions:algorithm_revision" in text


def test_the_uncompared_regressions_row_is_never_a_measured_zero() -> None:
    exit_code, text = _render(
        strictness="ci",
        report_document=_opaque_clone_gate("ci"),
        diff_context=_diff_context(clone_novelty_available=False),
        quiet=False,
    )
    assert exit_code == int(ExitCode.CONTRACT_ERROR)
    row = next(line for line in text.splitlines() if "Regressions" in line)
    assert row.split("Regressions", 1)[1].strip() == "not compared", row
    assert "Verdict: UNVERIFIED" in _verdict_block(text)
    assert "Patch contract not verified" in text
    assert "Patch contract violated" not in text
    assert "gate_failures" not in text


def test_a_gate_that_could_not_read_its_lane_is_unverified() -> None:
    """The clone lanes compared and nothing new, but the requested API gate
    reads a lane the baseline does not hold: the lane and its reason are
    named, and the patch is not verified."""
    exit_code, text = _render(
        strictness="ci",
        report_document=_report_document(
            gate_exit_code=int(ExitCode.CONTRACT_ERROR),
            gate_reasons=("lane:unavailable:api_surface",),
        ),
        diff_context=_diff_context(),
        quiet=False,
    )
    assert exit_code == int(ExitCode.CONTRACT_ERROR)
    assert "0 new clone groups" in text
    assert _verdict_block(text) == (
        "Verdict: UNVERIFIED",
        "Completeness: INCOMPLETE",
        "Exit: 2 (required verification unavailable)",
        "Proven violations: []",
        "Unverified lanes: [lane:unavailable:api_surface]",
    )


# -- both facts: a proven violation beside a check that did not run --------------
#
# Ruling 2026-10-20 (13): the verdict is VIOLATED -- the uncertainty of one
# fact never hides the proven failure of another -- and the verification is
# INCOMPLETE, so the exit is the contract-error code the gate itself returns
# for an unavailable lane before it evaluates any failure (2), under every
# profile.  Printing VIOLATED alone would read as a completed verification.

_BOTH_FACTS = (
    "Verdict: VIOLATED",
    "Completeness: INCOMPLETE",
    "Exit: 2 (required verification unavailable)",
    "Proven violations: [structural_regressions]",
    "Unverified lanes: [lane:unavailable:api_surface]",
)
_BOTH_FACTS_SENTENCE = "Patch contract violated; the verification is incomplete."


@pytest.mark.parametrize("quiet", [False, True], ids=["full", "quiet"])
@pytest.mark.parametrize("strictness", ["relaxed", "ci", "strict"])
def test_a_proven_violation_beside_an_unavailable_lane_states_both_facts(
    strictness: str, quiet: bool
) -> None:
    exit_code, text = _render(
        strictness=strictness,
        report_document=_report_document(
            gate_exit_code=int(ExitCode.CONTRACT_ERROR),
            gate_reasons=("lane:unavailable:api_surface",),
        ),
        diff_context=_diff_context(new_clones=1),
        function_clones=1,
        quiet=quiet,
    )
    assert exit_code == int(ExitCode.CONTRACT_ERROR), text
    assert _verdict_block(text) == _BOTH_FACTS, text
    # The closing sentence says both facts too, never a bare "violated".
    assert quiet or _BOTH_FACTS_SENTENCE in text.splitlines()[-1], text


# -- an internal error of the gate: a crash, never an abstention -----------------
#
# Ruling 2026-10-20 (13): INTERNAL_ERROR -> the verification is incomplete ->
# never ACCEPTED -> exit 5, the cause kept in the output.  It is not folded into
# an unavailable lane (2, UNVERIFIED): a crash is not an analytical abstention.
# A proven violation beside it still reads VIOLATED.

_GATE_CRASH = "gate:evaluator raised KeyError: 'api_surface'"


@pytest.mark.parametrize("quiet", [False, True], ids=["full", "quiet"])
@pytest.mark.parametrize("strictness", ["relaxed", "ci", "strict"])
@pytest.mark.parametrize(
    ("new_clones", "verdict", "violations"),
    [
        pytest.param(0, "INTERNAL_ERROR", "", id="alone"),
        pytest.param(1, "VIOLATED", "structural_regressions", id="beside-violation"),
    ],
)
def test_an_internal_gate_error_exits_5_and_keeps_its_cause(
    strictness: str, quiet: bool, new_clones: int, verdict: str, violations: str
) -> None:
    exit_code, text = _render(
        strictness=strictness,
        report_document=_report_document(
            gate_exit_code=int(ExitCode.INTERNAL_ERROR),
            gate_reasons=(_GATE_CRASH,),
        ),
        diff_context=_diff_context(new_clones=new_clones),
        function_clones=new_clones,
        quiet=quiet,
    )
    assert exit_code == int(ExitCode.INTERNAL_ERROR), text
    assert _verdict_block(text) == (
        f"Verdict: {verdict}",
        "Completeness: INCOMPLETE",
        "Exit: 5 (internal error)",
        f"Proven violations: [{violations}]",
        "Unverified lanes: []",
        f"Internal error: [gate:exit:5, {_GATE_CRASH}]",
    ), text
    assert "Patch contract accepted" not in text


#: A gate exit outside the closed contract (0, 2, 3, 5), as the document
#: carries it.
_OUT_OF_CONTRACT = (1, 4, 7, -2)


@pytest.mark.parametrize("code", _OUT_OF_CONTRACT)
def test_a_gate_exit_outside_the_contract_is_a_protocol_error(code: int) -> None:
    """Ruling 2026-10-20 (17): an exit the gate contract does not define is
    a protocol error of the evaluation, not a check that did not run -- exit
    5, never ``UNVERIFIED`` / 2 -- and the code the document carried and the
    gate's own reasons are kept."""
    exit_code, text = _render(
        strictness="ci",
        report_document=_report_document(
            gate_exit_code=code, gate_reasons=("gate:said something",)
        ),
        diff_context=_diff_context(),
        quiet=True,
    )
    assert (exit_code, _verdict_block(text)) == (
        int(ExitCode.INTERNAL_ERROR),
        (
            "Verdict: INTERNAL_ERROR",
            "Completeness: INCOMPLETE",
            "Exit: 5 (internal error)",
            "Proven violations: []",
            "Unverified lanes: []",
            f"Internal error: [gate:protocol_error:exit:{code}, gate:said something]",
        ),
    ), text


# -- relaxed changes the sanction, never the completeness ---------------------
#
# Ruling 2026-10-20 (17): a clone lane relaxed did not compare is a check that
# did not run, whatever the other lane compared; a proven violation relaxed
# lets pass is still a violation -- exit 0, stated as non-blocking, never
# "accepted".


@pytest.mark.parametrize("quiet", [False, True], ids=["full", "quiet"])
@pytest.mark.parametrize(
    ("new_clones", "verdict", "violations"),
    [
        pytest.param(0, "UNVERIFIED", "", id="alone"),
        pytest.param(1, "VIOLATED", "structural_regressions", id="beside-violation"),
    ],
)
def test_one_opaque_clone_lane_beside_a_compared_one_is_unverified_in_relaxed(
    quiet: bool, new_clones: int, verdict: str, violations: str
) -> None:
    exit_code, text = _render(
        strictness="relaxed",
        report_document=_report_document(opaque_lanes=frozenset({"clones.blocks"})),
        diff_context=_diff_context(new_clones=new_clones),
        function_clones=new_clones,
        quiet=quiet,
    )
    assert (exit_code, _verdict_block(text)) == (
        int(ExitCode.CONTRACT_ERROR),
        (
            f"Verdict: {verdict}",
            "Completeness: INCOMPLETE",
            "Exit: 2 (required verification unavailable)",
            f"Proven violations: [{violations}]",
            "Unverified lanes: [clones.blocks:algorithm_revision]",
        ),
    ), text


_RELAXED_SENTENCE = "Patch contract has advisory violations but relaxed mode exits 0."


@pytest.mark.parametrize("quiet", [False, True], ids=["full", "quiet"])
def test_relaxed_states_a_proven_violation_as_non_blocking_never_accepted(
    quiet: bool,
) -> None:
    exit_code, text = _render(
        strictness="relaxed",
        report_document=_report_document(),
        diff_context=_diff_context(new_clones=1),
        function_clones=1,
        quiet=quiet,
    )
    assert (exit_code, _verdict_block(text), "accepted" in text.lower()) == (
        int(ExitCode.SUCCESS),
        (
            "Verdict: VIOLATED",
            "Completeness: COMPLETE",
            "Exit: 0 (relaxed: violations are advisory)",
            "Proven violations: [structural_regressions]",
            "Unverified lanes: []",
        ),
        False,
    ), text
    assert quiet or _RELAXED_SENTENCE in text.splitlines()[-1], text


# -- a population the gate refuses to answer over -----------------------------
#
# Ruling 2026-10-20 (17): the gate's population refusal (``unmeasured``,
# ``complete_empty``; the gate's exit 3) is a measurement the policy required
# and the run did not make -- a policy failure, INCOMPLETE, exit 2, never a
# proven violation.  A violation proven on another lane still reads VIOLATED.

_REFUSALS = {
    "unmeasured": f"metric:{gate_msgs.GATE_REASON_UNMEASURED_POPULATION}",
    "complete_empty": f"metric:{gate_msgs.GATE_REASON_EMPTY_ANALYSIS_SCOPE}",
}


@pytest.mark.parametrize("quiet", [False, True], ids=["full", "quiet"])
@pytest.mark.parametrize("strictness", ["ci", "strict"])
@pytest.mark.parametrize("refusal", sorted(_REFUSALS))
@pytest.mark.parametrize(
    ("new_clones", "verdict", "violations"),
    [
        pytest.param(0, "UNVERIFIED", "", id="alone"),
        pytest.param(1, "VIOLATED", "structural_regressions", id="beside-violation"),
    ],
)
def test_a_population_refusal_is_a_policy_failure_not_a_proven_violation(
    quiet: bool,
    strictness: str,
    refusal: str,
    new_clones: int,
    verdict: str,
    violations: str,
) -> None:
    exit_code, text = _render(
        strictness=strictness,
        report_document=_report_document(
            gate_exit_code=int(ExitCode.GATING_FAILURE),
            gate_reasons=(_REFUSALS[refusal],),
        ),
        diff_context=_diff_context(new_clones=new_clones),
        function_clones=new_clones,
        quiet=quiet,
    )
    assert (exit_code, _verdict_block(text)) == (
        int(ExitCode.CONTRACT_ERROR),
        (
            f"Verdict: {verdict}",
            "Completeness: INCOMPLETE",
            "Exit: 2 (required verification unavailable)",
            f"Proven violations: [{violations}]",
            "Unverified lanes: []",
            f"Policy failures (missing measurement): [{_REFUSALS[refusal]}]",
        ),
    ), text


def test_a_gate_failure_on_a_fact_beside_the_refusal_words_stays_proven() -> None:
    """The control on the boundary: a gate that failed on a measured fact
    (``clone:new``) is a proven violation; only the refusal is a policy
    failure."""
    exit_code, text = _render(
        strictness="ci",
        report_document=_report_document(
            gate_exit_code=int(ExitCode.GATING_FAILURE),
            gate_reasons=("clone:new",),
        ),
        diff_context=_diff_context(new_clones=1),
        function_clones=1,
        quiet=True,
    )
    assert (exit_code, _verdict_block(text)) == (
        int(ExitCode.GATING_FAILURE),
        (
            "Verdict: VIOLATED",
            "Completeness: COMPLETE",
            "Exit: 3 (proven violation)",
            "Proven violations: [structural_regressions, gate_failures]",
            "Unverified lanes: []",
        ),
    ), text


def test_a_crash_inside_the_gate_ends_the_cli_in_exit_5_with_its_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chain as the CLI runs it today: the evaluator itself never writes
    5 into a document -- an exception inside the gate leaves the CLI through
    its internal-error envelope.  The cause is printed, the exit is 5, and no
    verdict is stated over the crash.  (A characterization of the existing
    chain, not of this module.)"""

    def _crash(**_kwargs: object) -> object:
        raise RuntimeError("gate evaluator exploded")

    root = tmp_path / "crash"
    package = root / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""pkg."""\n', "utf-8")
    (package / "util.py").write_text("def helper(x):\n    return x + 1\n", "utf-8")
    monkeypatch.setattr(cli_workflow, "gate_with_config", _crash)
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = corpora._run_codeclone_cli_exit(
            [str(root), "--no-progress", "--no-color", "--patch-verify"], {}
        )
    text = out.getvalue()
    assert code == int(ExitCode.INTERNAL_ERROR), text
    assert "INTERNAL ERROR" in text
    assert "RuntimeError: gate evaluator exploded" in text
    assert "Verdict:" not in text
    assert "Patch contract accepted" not in text


def test_patch_verify_verbose_relaxed_advisory() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="relaxed",
        report_document=_report_document(),
        analysis=_analysis(function_clones=1),
        diff_context=_diff_context(new_clones=1),
        baseline_state=cast(Any, _baseline_state()),
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    text = printer.text
    assert "advisory violations" in text
    assert "relaxed mode exits 0" in text


def test_patch_verify_strict_strictness_quiet_enforces_health() -> None:
    """Strict mode with health_floor=70 and no metrics yields gate failure."""
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="strict",
        report_document=_report_document(gate_exit_code=int(ExitCode.GATING_FAILURE)),
        analysis=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=True,
    )

    assert exit_code == int(ExitCode.GATING_FAILURE)
    assert "violated" in printer.text


def _project_metrics(*, health: int = 85) -> ProjectMetrics:
    return ProjectMetrics(
        complexity_avg=5.0,
        complexity_max=10,
        high_risk_functions=(),
        coupling_avg=3.0,
        coupling_max=5,
        high_risk_classes=(),
        cohesion_avg=1.0,
        cohesion_max=2,
        low_cohesion_classes=(),
        dependency_modules=3,
        dependency_edges=2,
        dependency_edge_list=(),
        dependency_cycles=(),
        dependency_max_depth=2,
        dependency_longest_chains=(),
        dead_code=(),
        health=HealthScore(total=health, grade="A", dimensions={}),
    )


def _analysis_with_metrics(
    *, health: int = 85, function_clones: int = 0
) -> AnalysisResult:
    return AnalysisResult(
        func_groups={},
        block_groups={},
        block_groups_report={},
        segment_groups={},
        low_value_segment_groups=0,
        block_group_facts={},
        func_clones_count=function_clones,
        block_clones_count=0,
        segment_clones_count=0,
        files_analyzed_or_cached=1,
        project_metrics=_project_metrics(health=health),
        metrics_payload=None,
        suggestions=(),
        segment_groups_raw_digest="",
        observation_bundle=TEST_OBSERVATION_BUNDLE,
    )


def test_patch_verify_with_project_metrics_quiet() -> None:
    """Covers _health_after, _health_delta, and gate_state_from_project_metrics."""
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        report_document=_report_document(),
        analysis=_analysis_with_metrics(health=85),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    # The context states no health comparison: the score, never "85->85".
    assert "health=85 delta=n/a (not compared)" in printer.text
    assert "accepted" in printer.text


def test_patch_verify_with_project_metrics_verbose() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        report_document=_report_document(),
        analysis=_analysis_with_metrics(health=85),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    # The context states no health comparison: never "(+0)".
    assert "85 · health delta: not compared" in printer.text


def _diff_context_with_metrics_diff(
    *, new_clones: int = 0, health_delta: int = 0
) -> DiffContext:
    return DiffContext(
        new_func={f"func-{index}" for index in range(new_clones)},
        new_block=set(),
        new_clones_count=new_clones,
        clone_novelty_available=True,
        metrics_diff=MetricsDiff(
            new_high_risk_functions=(),
            new_high_coupling_classes=(),
            new_cycles=(),
            new_dead_code=(),
            health_delta=health_delta,
        ),
        coverage_adoption_diff_available=False,
        api_surface_diff_available=False,
        stated_comparisons={COMPARISON_HEALTH: {TERM_SCORE_DELTA: health_delta}},
    )


def test_patch_verify_health_delta_from_metrics_diff() -> None:
    """Covers _health_delta: the health comparison the run's state states."""
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        report_document=_report_document(),
        analysis=_analysis_with_metrics(health=85),
        diff_context=_diff_context_with_metrics_diff(health_delta=5),
        baseline_state=cast(Any, _baseline_state()),
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "health=80->85" in printer.text


def test_patch_verify_allows_diff_against_without_changed_only() -> None:
    cli_workflow.console = cli_workflow._make_plain_console()
    args = Namespace(
        changed_only=False,
        diff_against="HEAD~1",
        paths_from_git_diff=None,
        patch_verify=True,
        blast_radius=None,
    )

    assert cli_changed_scope._validate_changed_scope_args(args=args) == "HEAD~1"


def test_controller_query_flags_reject_mutually_exclusive_modes() -> None:
    cli_workflow.console = cli_workflow._make_plain_console()
    args = Namespace(
        blast_radius=("pkg/a.py",),
        patch_verify=True,
        strictness="ci",
        update_baseline=False,
        update_metrics_baseline=False,
    )

    with pytest.raises(SystemExit) as exc:
        cli_workflow._validate_controller_query_flags(args=args)

    assert exc.value.code == int(ExitCode.CONTRACT_ERROR)


def test_run_controller_query_routes_blast_radius(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def _render_blast_radius(**kwargs: object) -> int:
        files_obj = kwargs.get("files", ())
        assert isinstance(files_obj, tuple)
        # Standing in for the renderer means answering for what the renderer
        # needs. It navigates these two addresses, so a stub that accepted any
        # object let the caller hand it a document real code cannot read --
        # which is how a withdrawn shape survived at this call site.
        document = kwargs.get("report_document")
        assert isinstance(document, dict)
        integrity = cast("dict[str, Any]", document["integrity"])
        assert integrity["digests"]["envelope"]["value"]
        inventory = cast("dict[str, Any]", document["inventory"])
        assert isinstance(inventory["file_registry"]["items"], list)
        calls.append(tuple(str(path) for path in files_obj))
        return int(ExitCode.SUCCESS)

    monkeypatch.setattr(
        "codeclone.surfaces.cli.blast_radius.render_blast_radius",
        _render_blast_radius,
    )
    args = Namespace(
        blast_radius=("pkg/a.py",),
        patch_verify=False,
        quiet=True,
    )
    result = cli_workflow._run_controller_query(
        args=cast(Any, args),
        report_document=_report_document(),
        root_path=tmp_path,
        analysis_result=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
    )
    assert result == int(ExitCode.SUCCESS)
    assert calls == [("pkg/a.py",)]


def test_run_controller_query_routes_patch_verify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _render_patch_verify(**_kwargs: object) -> int:
        return int(ExitCode.GATING_FAILURE)

    monkeypatch.setattr(
        "codeclone.surfaces.cli.patch_verify.render_patch_verify",
        _render_patch_verify,
    )
    args = Namespace(
        blast_radius=(),
        patch_verify=True,
        quiet=True,
        strictness="strict",
    )
    result = cli_workflow._run_controller_query(
        args=cast(Any, args),
        report_document=_report_document(),
        root_path=tmp_path,
        analysis_result=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
    )
    assert result == int(ExitCode.GATING_FAILURE)


def test_run_controller_query_returns_none_without_controller_mode(
    tmp_path: Path,
) -> None:
    args = Namespace(blast_radius=(), patch_verify=False, quiet=True)
    result = cli_workflow._run_controller_query(
        args=cast(Any, args),
        report_document=None,
        root_path=tmp_path,
        analysis_result=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
    )
    assert result is None


# -- the health line: the health comparison the run's state states ---------------
#
# Not compared -> null (ruling 2026-10-03): the human line says the ruling's
# words, never ``(+0)``, and a measured zero stays ``0``.  The state decides;
# the raw metrics diff beside it carries another number that must never reach
# the line.


def _diff_context_stating(health_delta: int | None) -> DiffContext:
    return DiffContext(
        new_func=set(),
        new_block=set(),
        new_clones_count=0,
        clone_novelty_available=True,
        metrics_diff=MetricsDiff(
            new_high_risk_functions=(),
            new_high_coupling_classes=(),
            new_cycles=(),
            new_dead_code=(),
            health_delta=7,
        ),
        coverage_adoption_diff_available=False,
        api_surface_diff_available=False,
        stated_comparisons=(
            {}
            if health_delta is None
            else {COMPARISON_HEALTH: {TERM_SCORE_DELTA: health_delta}}
        ),
    )


def _patch_verify_text(health_delta: int | None, *, quiet: bool) -> str:
    printer = _RecordingPrinter()
    render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        report_document=_report_document(),
        analysis=_analysis_with_metrics(health=85),
        diff_context=_diff_context_stating(health_delta),
        baseline_state=cast(Any, _baseline_state()),
        quiet=quiet,
    )
    return printer.text


@pytest.mark.parametrize(
    ("health_delta", "line"),
    [
        pytest.param(None, "85 · health delta: not compared", id="not-compared"),
        pytest.param(0, "85 → 85 (0)", id="measured-zero"),
        pytest.param(5, "80 → 85 (+5)", id="rose"),
        pytest.param(-3, "88 → 85 (-3)", id="fell"),
    ],
)
def test_the_rich_health_line_is_the_states_health_comparison(
    health_delta: int | None, line: str
) -> None:
    text = _patch_verify_text(health_delta, quiet=False)
    assert line in text
    assert "(+0)" not in text
    assert "78 → 85" not in text, "the raw metrics diff reached the line"


@pytest.mark.parametrize(
    ("health_delta", "fragment"),
    [
        pytest.param(
            None, "| health=85 delta=n/a (not compared) regressions=", id="not-compared"
        ),
        pytest.param(0, "| health=85->85 regressions=", id="measured-zero"),
        pytest.param(5, "| health=80->85 regressions=", id="rose"),
        pytest.param(-3, "| health=88->85 regressions=", id="fell"),
    ],
)
def test_the_compact_health_line_is_the_states_health_comparison(
    health_delta: int | None, fragment: str
) -> None:
    text = _patch_verify_text(health_delta, quiet=True)
    assert fragment in text
    assert "78->85" not in text, "the raw metrics diff reached the line"


#: The comparison corpus through the real CLI, against the stage-A baseline:
#: the health line each population prints, rich and compact.  ``compared``
#: compares health (+4); with dead code and dependencies skipped two of the
#: lanes health reads were never observed; against a baseline of another
#: scope nothing is trusted -- both state no health comparison.
CLI_HEALTH_LINES: dict[tuple[str, bool], str] = {
    ("compared", False): "66 → 70 (+4)",
    ("compared", True): "| health=66->70 regressions=",
    ("lanes_skipped", False): "82 · health delta: not compared",
    ("lanes_skipped", True): "| health=82 delta=n/a (not compared) regressions=",
    ("foreign_scope", False): "70 · health delta: not compared",
    ("foreign_scope", True): "| health=70 delta=n/a (not compared) regressions=",
}
_CLI_FLAGS: dict[str, tuple[str, ...]] = {
    "compared": ("--api-surface",),
    "lanes_skipped": ("--api-surface", "--skip-dead-code", "--skip-dependencies"),
    "foreign_scope": ("--api-surface",),
}


@pytest.fixture(scope="module")
def cli_patch_verify_runs(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[tuple[str, bool], tuple[str, int | str | None]]:
    base = tmp_path_factory.mktemp("patch_verify_health").resolve()
    baseline = corpora._comparison_baseline(base)
    runs: dict[tuple[str, bool], tuple[str, int | str | None]] = {}
    for population, quiet in CLI_HEALTH_LINES:
        root = base / f"{population}{'-quiet' if quiet else ''}"
        corpora.materialize_comparison_corpus(root, stage_b=True)
        if population == "foreign_scope":
            corpora._rewrite_scope_as_foreign(root)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = corpora._run_codeclone_cli_exit(
                [
                    str(root),
                    "--no-progress",
                    "--baseline",
                    str(baseline),
                    "--patch-verify",
                    *(("--quiet",) if quiet else ()),
                    *_CLI_FLAGS[population],
                ],
                {},
            )
        runs[(population, quiet)] = (out.getvalue(), code)
    return runs


@pytest.mark.parametrize(("population", "quiet"), list(CLI_HEALTH_LINES))
def test_the_cli_patch_verify_health_line_reads_the_runs_state(
    cli_patch_verify_runs: dict[tuple[str, bool], tuple[str, int | str | None]],
    population: str,
    quiet: bool,
) -> None:
    text, _code = cli_patch_verify_runs[(population, quiet)]
    assert CLI_HEALTH_LINES[(population, quiet)] in text, text


@pytest.mark.parametrize("quiet", [False, True])
def test_a_baseline_of_another_scope_is_never_trusted_without_gates(
    cli_patch_verify_runs: dict[tuple[str, bool], tuple[str, int | str | None]],
    quiet: bool,
) -> None:
    """``foreign_scope`` requests no gate: a container of another scope still
    describes nothing about this run, so the patch is not verified -- the
    baseline's refusal named, the contract-error code -- and the clone
    regressions are not compared, never zero.  The first cycle pinned the
    opposite here: the CLI trusted the foreign container because no active
    gate read its lanes (audit 2026-10-19, item 5)."""
    text, code = cli_patch_verify_runs[("foreign_scope", quiet)]
    assert code == int(ExitCode.CONTRACT_ERROR), text
    assert "baseline:mismatch_scope_id" in text
    if quiet:
        assert "patch-verify: unverified |" in text
        assert "regressions=n/a (not compared)" in text
    else:
        assert re.search(r"Regressions\s+not compared", text), text
    assert "Verdict: UNVERIFIED" in _verdict_block(text), text
    assert "Completeness: INCOMPLETE" in _verdict_block(text), text


def test_the_compared_population_is_verified(
    cli_patch_verify_runs: dict[tuple[str, bool], tuple[str, int | str | None]],
) -> None:
    """The control on the same corpus and baseline: the run of this scope
    is compared and gets a verdict of its own, never ``unverified``."""
    text, code = cli_patch_verify_runs[("compared", True)]
    assert "patch-verify: unverified" not in text, text
    assert code in (None, int(ExitCode.SUCCESS), int(ExitCode.GATING_FAILURE))


# -- the gate label: one word per gate outcome (maintainer ruling 2026-10-23) ---
#
# The label used to be ``pass`` for exit 0 and ``FAIL`` for everything else, so
# a check that never ran, a refusal over an unmeasured population, a baseline
# from another project and the gate's own crash all read like a violation
# proven against the patch.  Exit codes are unchanged; only the word is.

_UNMEASURED = f"metric:{gate_msgs.GATE_REASON_UNMEASURED_POPULATION}"
_EMPTY_SCOPE = f"metric:{gate_msgs.GATE_REASON_EMPTY_ANALYSIS_SCOPE}"


def _with_lane_trust(
    document: dict[str, object],
    reasons: dict[str, str],
    *,
    file_status: str | None = None,
) -> dict[str, object]:
    """The document with the named lanes untrusted for the given reasons,
    and the baseline file status the run recorded."""
    meta = cast(dict[str, object], document["meta"])
    cast(dict[str, object], meta["baseline"])["status"] = file_status
    baseline = cast(dict[str, object], document["baseline"])
    rows = cast(list[dict[str, object]], baseline["sorted_lane_trust"])
    for row in rows:
        reason = reasons.get(str(row["name"]))
        if reason is not None:
            row["status"] = "unavailable"
            row["reason"] = reason
    return document


def _gate_labels(
    document: dict[str, object],
) -> tuple[str, str]:
    """The label as the quiet line and the verbose preview print it."""
    labels: list[str] = []
    for quiet in (True, False):
        printer = _RecordingPrinter()
        render_patch_verify(
            console=printer,
            args=cast(Any, _args()),
            strictness="ci",
            report_document=document,
            analysis=_analysis(),
            diff_context=_diff_context(),
            baseline_state=cast(Any, _baseline_state()),
            quiet=quiet,
        )
        pattern = r"gates=(\S+)" if quiet else r"Gate preview\s+(\S+) \(exit"
        match = re.search(pattern, printer.text)
        assert match is not None, printer.text
        labels.append(match.group(1))
    return labels[0], labels[1]


_LANE = "clones.functions"
_OTHER_LANE = "clones.blocks"


@pytest.mark.parametrize(
    ("gate_exit_code", "gate_reasons", "lane_reasons", "file_status", "label"),
    [
        pytest.param(0, (), {}, None, "PASS", id="0-pass"),
        pytest.param(3, ("clone:new",), {}, None, "VIOLATED", id="3-fact"),
        pytest.param(3, (_UNMEASURED,), {}, None, "UNAVAILABLE", id="3-unmeasured"),
        pytest.param(3, (_EMPTY_SCOPE,), {}, None, "UNAVAILABLE", id="3-empty-scope"),
        pytest.param(
            3,
            ("clone:new", _UNMEASURED),
            {},
            None,
            "VIOLATED",
            id="3-fact-beside-refusal",
        ),
        pytest.param(
            2,
            (f"lane:unavailable:{_LANE}",),
            {_LANE: "baseline_scope_id"},
            None,
            "REFUSED",
            id="2-foreign-baseline",
        ),
        pytest.param(
            2,
            (f"lane:unavailable:{_LANE}",),
            {_LANE: "root_digest_mismatch"},
            None,
            "REFUSED",
            id="2-integrity",
        ),
        pytest.param(
            2,
            (f"lane:unavailable:{_LANE}",),
            {_LANE: "algorithm_revision"},
            None,
            "REFUSED",
            id="2-other-contract",
        ),
        pytest.param(
            2,
            (f"lane:unavailable:{_LANE}",),
            {_LANE: "baseline_missing"},
            None,
            "UNAVAILABLE",
            id="2-no-baseline",
        ),
        pytest.param(
            2,
            (f"lane:unavailable:{_LANE}",),
            {},
            None,
            "UNAVAILABLE",
            id="2-not-compared",
        ),
        pytest.param(
            2,
            (f"lane:unavailable:{_LANE}", f"lane:unavailable:{_OTHER_LANE}"),
            {_LANE: "baseline_scope_id"},
            None,
            "UNAVAILABLE",
            id="2-refused-beside-not-compared",
        ),
        pytest.param(
            2,
            (f"lane:unavailable:{_LANE}",),
            {_LANE: "baseline_missing"},
            "integrity_failed",
            "REFUSED",
            id="2-refused-file",
        ),
        pytest.param(
            2,
            (f"lane:unavailable:{_LANE}",),
            {_LANE: "baseline_missing"},
            "missing",
            "UNAVAILABLE",
            id="2-no-baseline-file",
        ),
        pytest.param(5, ("gate crashed",), {}, None, "ERROR", id="5-crash"),
        pytest.param(7, (), {}, None, "ERROR", id="7-outside-contract"),
    ],
)
def test_the_gate_label_names_the_gate_outcome(
    gate_exit_code: int,
    gate_reasons: tuple[str, ...],
    lane_reasons: dict[str, str],
    file_status: str | None,
    label: str,
) -> None:
    document = _with_lane_trust(
        _report_document(gate_exit_code=gate_exit_code, gate_reasons=gate_reasons),
        lane_reasons,
        file_status=file_status,
    )

    assert _gate_labels(document) == (label, label)


def test_a_missing_evaluation_is_labelled_unavailable() -> None:
    assert _gate_labels({}) == ("UNAVAILABLE", "UNAVAILABLE")
