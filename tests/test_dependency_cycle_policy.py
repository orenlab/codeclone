# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Cycle POLICY: the kind reaches every layer that decides, not just the prose.

The cycle-honesty wave classified cycles by binding time but wired the result
only into the suggestion text and the ``cycle_details`` payload. Health, the
``--fail-cycles`` gate, novelty gating, the baseline lane, and the summary all
kept reading one undifferentiated count, so the product called a cycle a
"warning" and then scored it and failed the build exactly as if it were fatal.

These pins hold the split at each deciding layer:

* the gate fails on import cycles only;
* health prices the two kinds through two separate constants;
* the baseline remembers each cycle's kind, so a kind change across runs is
  neither "new" nor "unchanged";
* this layer does NOT move any score — the deferred penalty is deliberately
  equal to the import penalty, and the seam exists to be calibrated later
  under the project's score-change law.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from codeclone.baseline._metrics_baseline_payload import snapshot_from_project_metrics
from codeclone.baseline.diff import diff_metrics
from codeclone.baseline.metrics_baseline import MetricsBaseline
from codeclone.baseline.metrics_baseline import _snapshot as reconstruct_snapshot
from codeclone.contracts import (
    HEALTH_DEPENDENCY_CYCLE_PENALTY,
    HEALTH_DEPENDENCY_DEFERRED_CYCLE_PENALTY,
)
from codeclone.metrics import health as health_mod
from codeclone.metrics.health import HealthInputs, compute_health
from codeclone.models import (
    DependencyCycleDetail,
    DependencyCycleFact,
    DependencyCycleKind,
    HealthScore,
    MetricsDiff,
    MetricsSnapshot,
    ProjectMetrics,
    cycle_kind_counts,
)
from codeclone.report.document.metrics import (
    _cycle_kind_count as document_cycle_kind_count,
)

# ---------------------------------------------------------------------------
# Fixture trees: one import-time cycle, one deferred-only cycle
# ---------------------------------------------------------------------------

_IMPORT_CYCLE_TREE = {
    "alpha.py": """
import beta


def alpha_value() -> str:
    return f"alpha:{beta.BETA_TOKEN}"


ALPHA_TOKEN = "alpha"
""",
    "beta.py": """
import alpha


def beta_value() -> str:
    return f"beta:{alpha.ALPHA_TOKEN}"


BETA_TOKEN = "beta"
""",
}

# The same two modules, the same cycle, closed only by function-local imports.
# Nothing here can fail at import time, which is the whole point.
_DEFERRED_CYCLE_TREE = {
    "alpha.py": """
ALPHA_TOKEN = "alpha"


def alpha_value() -> str:
    import beta

    return f"alpha:{beta.BETA_TOKEN}"
""",
    "beta.py": """
BETA_TOKEN = "beta"


def beta_value() -> str:
    import alpha

    return f"beta:{alpha.ALPHA_TOKEN}"
""",
}


#: Baseline update and gating both require a stable canonical scope id.
_SCOPE_ID = "0192f3aa-6c51-7b28-9d44-1ea5c07b6f39"


def _write_tree(root: Path, tree: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, source in tree.items():
        (root / name).write_text(source.lstrip(), encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'[tool.codeclone]\nbaseline_scope_id = "{_SCOPE_ID}"\n',
        encoding="utf-8",
    )
    return root


#: The CLI is SPAWNED, never imported. This module's pins live at the metrics
#: and baseline layer (ring 2); importing the CLI surface would make the whole
#: module a ring-4 test reaching into ring-2 internals, which the architecture
#: boundary ratchet rejects — correctly. Same pattern as the baseline lane
#: degradation suite.
_CLI_ENTRY = "from codeclone.surfaces.cli.workflow import main; main()"


def _run_cli(
    tmp_path: Path,
    tree: dict[str, str],
    *,
    extra_args: tuple[str, ...] = (),
    tree_name: str = "project",
) -> tuple[int, dict[str, object], Path]:
    """Run the real CLI over a generated tree and return its exit code."""

    project_root = _write_tree(tmp_path / tree_name, tree)
    report_path = tmp_path / f"{tree_name}-report.json"
    baseline_path = tmp_path / f"{tree_name}-baseline.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _CLI_ENTRY,
            str(project_root),
            "--baseline",
            str(baseline_path),
            "--cache-path",
            str(tmp_path / f"{tree_name}-cache.json"),
            "--json",
            str(report_path),
            "--no-skip-metrics",
            "--no-progress",
            *extra_args,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert report_path.exists(), completed.stdout + completed.stderr
    payload = json.loads(report_path.read_text("utf-8"))
    assert isinstance(payload, dict)
    return completed.returncode, payload, baseline_path


def _dependencies_summary(payload: dict[str, object]) -> dict[str, object]:
    metrics = payload.get("metrics")
    assert isinstance(metrics, dict)
    families = metrics.get("families")
    assert isinstance(families, dict)
    dependencies = families.get("dependencies")
    assert isinstance(dependencies, dict)
    summary = dependencies.get("summary")
    assert isinstance(summary, dict)
    return summary


# ---------------------------------------------------------------------------
# Gate: --fail-cycles fires on import cycles only
# ---------------------------------------------------------------------------


def test_import_cycle_fails_the_cycle_gate(tmp_path: Path) -> None:
    code, payload, _baseline = _run_cli(
        tmp_path,
        _IMPORT_CYCLE_TREE,
        extra_args=("--fail-cycles",),
        tree_name="import_cycle",
    )
    summary = _dependencies_summary(payload)

    assert summary["cycles"] == 1
    assert summary["import_cycles"] == 1
    assert summary["deferred_cycles"] == 0
    assert code == 3, "an import-time cycle must still fail --fail-cycles"


def test_deferred_only_cycle_does_not_fail_the_cycle_gate(tmp_path: Path) -> None:
    """The defect, inverted: a warning must not fail the build like a fatal.

    The cycle is still reported — it is real — but it cannot crash an import,
    so it cannot carry an import-time verdict.
    """

    code, payload, _baseline = _run_cli(
        tmp_path,
        _DEFERRED_CYCLE_TREE,
        extra_args=("--fail-cycles",),
        tree_name="deferred_cycle",
    )
    summary = _dependencies_summary(payload)

    assert summary["cycles"] == 1, "the deferred cycle must stay VISIBLE"
    assert summary["import_cycles"] == 0
    assert summary["deferred_cycles"] == 1
    assert code == 0, "a deferred-only cycle must not fail --fail-cycles"


def test_reported_cycle_total_is_the_sum_of_the_two_kinds(tmp_path: Path) -> None:
    """The split partitions the total — no cycle is dropped or double-counted."""

    for name, tree in (
        ("total_import", _IMPORT_CYCLE_TREE),
        ("total_deferred", _DEFERRED_CYCLE_TREE),
    ):
        _code, payload, _baseline = _run_cli(
            tmp_path,
            tree,
            tree_name=name,
        )
        summary = _dependencies_summary(payload)
        assert summary["cycles"] == (
            int(str(summary["import_cycles"])) + int(str(summary["deferred_cycles"]))
        ), name


# ---------------------------------------------------------------------------
# Health: consumes the split, and this layer moves no score
# ---------------------------------------------------------------------------


def _health_inputs(*, import_cycles: int, deferred_cycles: int) -> HealthInputs:
    """A neutral repository whose only debt is the cycles under test."""

    return HealthInputs(
        files_found=10,
        files_analyzed_or_cached=10,
        function_clone_groups=0,
        block_clone_groups=0,
        complexity_avg=1.0,
        complexity_max=1,
        high_risk_functions=0,
        elevated_complexity_functions=0,
        complexity_function_population=10,
        coupling_avg=0.0,
        coupling_max=0,
        high_risk_classes=0,
        elevated_coupling_classes=0,
        coupling_class_population=10,
        cohesion_avg=1.0,
        low_cohesion_classes=0,
        import_dependency_cycles=import_cycles,
        deferred_dependency_cycles=deferred_cycles,
        dependency_max_depth=0,
        dependency_avg_depth=0.0,
        dependency_p95_depth=0,
        dead_code_items=0,
    )


def _dependency_score(*, import_cycles: int, deferred_cycles: int) -> int:
    return compute_health(
        _health_inputs(
            import_cycles=import_cycles,
            deferred_cycles=deferred_cycles,
        )
    ).dimensions["dependencies"]


@pytest.mark.parametrize(
    ("import_cycles", "deferred_cycles"),
    [(0, 0), (1, 0), (0, 1), (2, 0), (0, 2), (1, 1), (2, 1)],
)
def test_dependency_score_re_derives_from_both_penalty_constants(
    import_cycles: int,
    deferred_cycles: int,
) -> None:
    """Pin the DERIVATION RULE, not a literal score.

    Re-deriving from the two constants keeps the pin alive if either is
    recalibrated later, and reds immediately if a term is dropped or if one
    kind stops reaching the formula.
    """

    expected = max(
        0,
        100
        - import_cycles * HEALTH_DEPENDENCY_CYCLE_PENALTY
        - deferred_cycles * HEALTH_DEPENDENCY_DEFERRED_CYCLE_PENALTY,
    )
    assert (
        _dependency_score(
            import_cycles=import_cycles,
            deferred_cycles=deferred_cycles,
        )
        == expected
    )


def test_each_cycle_kind_is_wired_to_its_own_penalty_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two terms are distinguishable ONLY when the constants differ.

    Both constants are 25 today by design, so a formula that charged deferred
    cycles at the import rate — or fed one count into the other's term — would
    be numerically invisible and every other test here would stay green. That
    is exactly the hollow-test shape this pin exists to kill: it drives the
    deferred constant to a different value so the seam becomes observable, and
    then checks each count moves only its OWN term.
    """

    monkeypatch.setattr(health_mod, "HEALTH_DEPENDENCY_DEFERRED_CYCLE_PENALTY", 4)

    # One deferred cycle costs the deferred rate, not the import rate.
    assert _dependency_score(import_cycles=0, deferred_cycles=1) == 96
    # One import cycle still costs the import rate.
    assert _dependency_score(import_cycles=1, deferred_cycles=0) == 100 - (
        HEALTH_DEPENDENCY_CYCLE_PENALTY
    )
    # The terms are additive and independent, so swapping the two counts
    # produces a DIFFERENT score once the rates differ.
    assert _dependency_score(import_cycles=2, deferred_cycles=1) == 46
    assert _dependency_score(import_cycles=1, deferred_cycles=2) == 67


def test_this_layer_does_not_move_health_for_import_cycles() -> None:
    """Behaviour preservation: import-cycle scoring is identical to pre-split.

    Before the split the dimension was ``100 - cycles * 25`` for every cycle.
    A repository whose cycles are all import cycles must therefore score
    exactly what it scored before, to the point.
    """

    for cycles in range(5):
        pre_split_score = max(0, 100 - cycles * 25)
        assert _dependency_score(import_cycles=cycles, deferred_cycles=0) == (
            pre_split_score
        )


def test_deferred_penalty_is_a_behaviour_preserving_candidate() -> None:
    """The seam is calibratable but NOT yet calibrated.

    Layer 1 creates the separate constant; choosing its real value is a
    separate task that must pass an independent blind external benchmark. If
    this equality is ever broken, that benchmark must exist — and this pin is
    where the next agent is told so.
    """

    assert (
        HEALTH_DEPENDENCY_DEFERRED_CYCLE_PENALTY == HEALTH_DEPENDENCY_CYCLE_PENALTY
    ), (
        "The deferred penalty is a CANDIDATE deliberately equal to the import "
        "penalty so this layer moves no user-facing score. Changing it is a "
        "score change governed by the project's score-change law: it requires "
        "an independent blind benchmark over frozen external repositories, "
        "not a self-repo re-fit."
    )


def test_health_is_identical_for_a_deferred_cycle_at_the_candidate_value() -> None:
    """Whole-score proof, not just the dimension: no repository moves today."""

    assert (
        compute_health(_health_inputs(import_cycles=1, deferred_cycles=0)).total
        == compute_health(_health_inputs(import_cycles=0, deferred_cycles=1)).total
    )


# ---------------------------------------------------------------------------
# Baseline: the kind survives across runs, and a kind change is not "unchanged"
# ---------------------------------------------------------------------------


def _snapshot(*facts: DependencyCycleFact) -> MetricsSnapshot:
    return MetricsSnapshot(
        max_complexity=0,
        high_risk_functions=(),
        max_coupling=0,
        high_coupling_classes=(),
        max_cohesion=0,
        low_cohesion_classes=(),
        dependency_cycles=facts,
        dependency_max_depth=0,
        dead_code_items=(),
        health_score=100,
        health_grade="A",
    )


def _diff(
    baseline: tuple[DependencyCycleFact, ...],
    current: tuple[DependencyCycleFact, ...],
) -> MetricsDiff:
    return diff_metrics(
        baseline_snapshot=_snapshot(*baseline),
        current_snapshot=_snapshot(*current),
        baseline_api_surface=None,
        current_api_surface=None,
    )


_AB = ("alpha", "beta")


def _reconstructed_cycle_kinds(
    tmp_path: Path,
    tree: dict[str, str],
    *,
    tree_name: str,
) -> list[tuple[str, ...]]:
    """Write a real baseline, then reconstruct its snapshot from the lanes.

    The whole round trip, through the actual container: analyse, persist the
    dependency lane, read it back, and rebuild the cycle facts from the stored
    rows alone. Nothing about the kind is carried in memory between the two
    halves — if the lane cannot answer, this returns the wrong kind.
    """

    _code, _payload, baseline_path = _run_cli(
        tmp_path,
        tree,
        extra_args=("--update-baseline",),
        tree_name=tree_name,
    )
    baseline = MetricsBaseline(baseline_path)
    baseline.load()
    assert baseline.container is not None
    snapshot = reconstruct_snapshot(baseline.container)
    return [(*fact.modules, fact.kind) for fact in snapshot.dependency_cycles]


def test_baseline_lane_round_trips_the_deferred_cycle_kind(tmp_path: Path) -> None:
    """The stored lane must reconstruct the KIND, not just the members.

    This is the fact the baseline used to lose: the reconstruction dropped
    each row's binding, so every remembered cycle came back critical.
    """

    assert _reconstructed_cycle_kinds(
        tmp_path,
        _DEFERRED_CYCLE_TREE,
        tree_name="roundtrip_deferred",
    ) == [("alpha", "beta", "deferred_cycle")]


def test_baseline_lane_round_trips_the_import_cycle_kind(tmp_path: Path) -> None:
    """The opposite direction: a real import cycle must not be softened."""

    assert _reconstructed_cycle_kinds(
        tmp_path,
        _IMPORT_CYCLE_TREE,
        tree_name="roundtrip_import",
    ) == [("alpha", "beta", "import_cycle")]


def test_a_new_import_cycle_is_distinguishable_from_a_new_deferred_one() -> None:
    new_import = _diff((), (DependencyCycleFact(modules=_AB, kind="import_cycle"),))
    new_deferred = _diff((), (DependencyCycleFact(modules=_AB, kind="deferred_cycle"),))

    # Both are visible as new cycles.
    assert new_import.new_cycles == (_AB,)
    assert new_deferred.new_cycles == (_AB,)
    # Only one of them gates.
    assert new_import.new_import_cycles == (_AB,)
    assert new_import.new_deferred_cycles == ()
    assert new_deferred.new_import_cycles == ()
    assert new_deferred.new_deferred_cycles == (_AB,)


def test_deferred_hardening_into_an_import_cycle_is_not_unchanged() -> None:
    """A crash risk appeared where there was none — the count did not move."""

    diff = _diff(
        (DependencyCycleFact(modules=_AB, kind="deferred_cycle"),),
        (DependencyCycleFact(modules=_AB, kind="import_cycle"),),
    )

    assert diff.new_cycles == (), "the members already cycled, so not 'new'"
    assert [
        (change.modules, change.previous_kind, change.current_kind)
        for change in diff.cycle_kind_changes
    ] == [(_AB, "deferred_cycle", "import_cycle")]
    # It gates: an import cycle exists now and did not before.
    assert diff.new_import_cycles == (_AB,)


def test_repairing_an_import_cycle_into_a_deferred_one_is_not_unchanged() -> None:
    """The opposite transition: visible as a change, and it must NOT gate."""

    diff = _diff(
        (DependencyCycleFact(modules=_AB, kind="import_cycle"),),
        (DependencyCycleFact(modules=_AB, kind="deferred_cycle"),),
    )

    assert diff.new_cycles == ()
    assert [
        (change.modules, change.previous_kind, change.current_kind)
        for change in diff.cycle_kind_changes
    ] == [(_AB, "import_cycle", "deferred_cycle")]
    assert diff.new_import_cycles == (), "a repair must never fail a build"
    assert diff.new_deferred_cycles == ()


def _project_metrics_with_cycles(
    *,
    details: tuple[DependencyCycleDetail, ...],
    cycles: tuple[tuple[str, ...], ...],
) -> ProjectMetrics:
    return ProjectMetrics(
        complexity_avg=0.0,
        complexity_max=0,
        high_risk_functions=(),
        coupling_avg=0.0,
        coupling_max=0,
        high_risk_classes=(),
        cohesion_avg=0.0,
        cohesion_max=0,
        low_cohesion_classes=(),
        dependency_modules=2,
        dependency_edges=2,
        dependency_edge_list=(),
        dependency_cycles=cycles,
        dependency_max_depth=1,
        dependency_longest_chains=(),
        dead_code=(),
        health=HealthScore(total=100, grade="A", dimensions={"dependencies": 100}),
        dependency_cycle_details=details,
    )


def test_current_run_snapshot_carries_the_kind_into_the_diff() -> None:
    """The CURRENT side of a baseline diff must not forget the kind either.

    ``snapshot_from_project_metrics`` builds the current-run snapshot that
    every baseline comparison is measured against. If it stamped one kind on
    every cycle, a brand-new DEFERRED cycle would arrive at the gate wearing
    an import label and fail a build that must pass — the original defect,
    re-entering through the diff instead of through health.
    """

    deferred = snapshot_from_project_metrics(
        _project_metrics_with_cycles(
            cycles=(_AB,),
            details=(
                DependencyCycleDetail(
                    modules=_AB,
                    kind="deferred_cycle",
                    member_paths=("alpha.py", "beta.py"),
                ),
            ),
        )
    )
    assert [fact.kind for fact in deferred.dependency_cycles] == ["deferred_cycle"]

    imported = snapshot_from_project_metrics(
        _project_metrics_with_cycles(
            cycles=(_AB,),
            details=(
                DependencyCycleDetail(
                    modules=_AB,
                    kind="import_cycle",
                    member_paths=("alpha.py", "beta.py"),
                ),
            ),
        )
    )
    assert [fact.kind for fact in imported.dependency_cycles] == ["import_cycle"]


def test_a_new_deferred_cycle_does_not_gate_through_the_current_snapshot() -> None:
    """End of the chain: ProjectMetrics -> snapshot -> diff -> gate lane.

    Pinned through the real snapshot builder rather than a hand-made
    ``DependencyCycleFact``, so a regression anywhere along that chain — not
    only in the diff — turns this red.
    """

    current = snapshot_from_project_metrics(
        _project_metrics_with_cycles(
            cycles=(_AB,),
            details=(
                DependencyCycleDetail(
                    modules=_AB,
                    kind="deferred_cycle",
                    member_paths=("alpha.py", "beta.py"),
                ),
            ),
        )
    )
    diff = diff_metrics(
        baseline_snapshot=_snapshot(),
        current_snapshot=current,
        baseline_api_surface=None,
        current_api_surface=None,
    )

    assert diff.new_cycles == (_AB,), "still visible"
    assert diff.new_deferred_cycles == (_AB,)
    assert diff.new_import_cycles == (), "a new deferred cycle must not gate"


def test_missing_cycle_details_fall_back_to_the_critical_reading() -> None:
    """An unclassified cycle counts as import — never silently downgraded.

    Details are aligned with cycles by index; when they are absent the
    classification was never recorded. Reading that as "deferred" would drop a
    real crash risk out of both health and the gate.
    """

    snapshot = snapshot_from_project_metrics(
        _project_metrics_with_cycles(cycles=(_AB,), details=())
    )
    assert [fact.kind for fact in snapshot.dependency_cycles] == ["import_cycle"]

    counts = cycle_kind_counts(cycles=(_AB,), details=())
    assert (counts.import_cycles, counts.deferred_cycles) == (1, 0)
    assert counts.total == 1


def test_report_document_applies_the_same_fallback_as_the_metrics_layer() -> None:
    """The document keeps its own copy of the fallback, so pin it too.

    Proving the guard is REACHABLE matters as much as its value: a report
    payload that carries cycles without ``cycle_details`` — an older document,
    or a surface that omits the detail rows — lands exactly here. Without an
    input that trips it, the branch would be untested theatre.
    """

    misaligned: list[dict[str, object]] = []
    assert (
        document_cycle_kind_count(misaligned, kind="import_cycle", cycles_total=2) == 2
    )
    assert (
        document_cycle_kind_count(misaligned, kind="deferred_cycle", cycles_total=2)
        == 0
    )

    # Aligned details are counted honestly, per kind.
    aligned: list[dict[str, object]] = [
        {"kind": "import_cycle"},
        {"kind": "deferred_cycle"},
        {"kind": "deferred_cycle"},
    ]
    assert document_cycle_kind_count(aligned, kind="import_cycle", cycles_total=3) == 1
    assert (
        document_cycle_kind_count(aligned, kind="deferred_cycle", cycles_total=3) == 2
    )


def test_an_unchanged_cycle_reports_no_movement_at_all() -> None:
    """The control case both transition pins are measured against."""

    kinds: tuple[DependencyCycleKind, ...] = ("import_cycle", "deferred_cycle")
    for kind in kinds:
        fact = DependencyCycleFact(modules=_AB, kind=kind)
        diff = _diff((fact,), (fact,))
        assert diff.new_cycles == (), kind
        assert diff.new_import_cycles == (), kind
        assert diff.new_deferred_cycles == (), kind
        assert diff.cycle_kind_changes == (), kind
