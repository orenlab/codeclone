# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from uuid import UUID

from codeclone.baseline.container import build_container
from codeclone.metrics.health import HealthInputs, compute_health, health_report_fields
from codeclone.models import (
    BaselineContainerV3,
    GroupMapLike,
    StructuralFindingGroup,
    Suggestion,
    SuppressedCloneGroup,
    TrustVector,
)
from codeclone.observations.projection import build_observation_bundle
from codeclone.report.document.builder import (
    build_report_document as _build_report_document_v3,
)
from codeclone.report.gates.evaluator import (
    GateResult,
    MetricGateConfig,
    evaluate_gates,
)
from codeclone.utils.mapping_paths import section

from ._ast_metrics_helpers import module_registry_context

REPEATED_STMT_HASH = "0e8579f84e518d186950d012c9944a40cb872332"

REPEATED_ASSERT_SOURCE = (
    "def f(html):\n"
    "    assert 'a' in html\n"
    "    assert 'b' in html\n"
    "    assert 'c' in html\n"
    "    assert 'd' in html\n"
)


def repeated_block_group_key(*, block_size: int = 4) -> str:
    return "|".join([REPEATED_STMT_HASH] * block_size)


def write_repeated_assert_source(path: Path) -> Path:
    path.write_text(REPEATED_ASSERT_SOURCE, "utf-8")
    return path


def health_family_for_population(*, found: int, analyzed: int) -> dict[str, object]:
    """The health metrics family exactly as its owner projects it.

    The population string is never typed by hand by a caller: ``compute_health``
    owns the tri-state and ``health_report_fields`` owns its projection, so a
    rename or a re-classification in that owner reaches the tests instead of
    being shadowed by a literal in each of them.
    """

    return health_report_fields(
        compute_health(
            HealthInputs(
                files_found=found,
                files_analyzed_or_cached=analyzed,
                function_clone_groups=0,
                block_clone_groups=0,
                complexity_avg=0.0,
                complexity_max=0,
                high_risk_functions=0,
                elevated_complexity_functions=0,
                complexity_function_population=0,
                coupling_avg=0.0,
                coupling_max=0,
                high_risk_classes=0,
                elevated_coupling_classes=0,
                coupling_class_population=0,
                cohesion_avg=0.0,
                low_cohesion_classes=0,
                import_dependency_cycles=0,
                deferred_dependency_cycles=0,
                dependency_max_depth=0,
                dependency_avg_depth=0.0,
                dependency_p95_depth=0,
                dead_code_items=0,
            )
        )
    )


def single_module_baseline_container(scope_id: UUID) -> BaselineContainerV3:
    """A real published-shape container, for the baseline states that need one.

    ``baseline.state`` is ``missing`` whenever no container exists, so the
    ``trusted``/``untrusted`` half of that projection is unreachable without
    this.
    """

    _source, registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )
    bundle = build_observation_bundle(scan_root=Path("."), module_registry=registry)
    return build_container(bundle, scope_id)


GATE_POLICY_GENERATED_AT = "2026-08-13T10:00:00Z"


def _gate_policy_health_family() -> dict[str, object]:
    """A health family carrying real debt, so a threshold can bracket it.

    A defect-free fixture scores 100 and leaves no room above it for a strict
    threshold, which would make two policies agree and any pin resting on
    their disagreement vacuous. No caller types the score: it is read back off
    the built document, so a recalibration moves the fixture with the metric.
    """

    return health_report_fields(
        compute_health(
            HealthInputs(
                files_found=10,
                files_analyzed_or_cached=10,
                function_clone_groups=4,
                block_clone_groups=3,
                complexity_avg=12.0,
                complexity_max=45,
                high_risk_functions=6,
                elevated_complexity_functions=9,
                complexity_function_population=40,
                coupling_avg=9.0,
                coupling_max=30,
                high_risk_classes=4,
                elevated_coupling_classes=6,
                coupling_class_population=20,
                cohesion_avg=0.2,
                low_cohesion_classes=7,
                import_dependency_cycles=3,
                deferred_dependency_cycles=1,
                dependency_max_depth=9,
                dependency_avg_depth=4.0,
                dependency_p95_depth=8,
                dead_code_items=25,
            )
        )
    )


def build_gate_policy_report_document(
    *,
    fail_health: int = -1,
    report_generated_at_utc: str = GATE_POLICY_GENERATED_AT,
) -> dict[str, object]:
    """One observed tree, gated at ``fail_health``, evaluated for real.

    Everything below the evaluation tier is a function of the tree and the
    baseline, so two documents from this builder differ only where the gate
    policy differs -- which is what makes them usable for asking what an
    identity is allowed to depend on.

    The verdict is not typed by the caller: the document is built once with
    the requested policy, handed to the gate owner, and rebuilt carrying the
    result that owner returned. A fixture that wrote its own exit code would
    pin its opinion of the gate rather than the gate.
    """

    gate_config = MetricGateConfig(
        fail_complexity=-1,
        fail_coupling=-1,
        fail_cohesion=-1,
        fail_cycles=False,
        fail_dead_code=False,
        fail_health=fail_health,
        fail_on_new_metrics=False,
    )
    metrics = {"health": _gate_policy_health_family()}
    meta = {"report_generated_at_utc": report_generated_at_utc}

    def _build(gate_result: GateResult) -> dict[str, object]:
        _source, registry = module_registry_context(
            filepath="pkg/module.py",
            module_name="pkg.module",
        )
        return _build_report_document_v3(
            func_groups={},
            block_groups={},
            segment_groups={},
            observation_bundle=build_observation_bundle(
                scan_root=Path("."), module_registry=registry
            ),
            baseline_container=None,
            baseline_trust=None,
            gate_config=gate_config,
            gate_result=gate_result,
            metrics=metrics,
            meta=meta,
        )

    unevaluated = _build(GateResult(exit_code=0, reasons=()))
    return _build(evaluate_gates(report_document=unevaluated, config=gate_config))


def build_gate_policy_disagreement_pair() -> tuple[
    dict[str, object], dict[str, object]
]:
    """Two documents over one tree whose gate verdicts genuinely disagree.

    Every surface that names a run needs this same arrangement to ask what an
    identity may depend on, and each surface writing it out again is how the
    CLI pin came to be a copy of the MCP pin. It lives here once.

    The self-checks are part of the fixture, not of any one surface's pin:
    they are what makes an accidental pass impossible. The pair must sit in
    the middle of the score range so a strict and a lenient threshold can
    bracket it, must actually answer differently, must carry a real gate
    reason rather than a silent refusal, and must agree on every tier below
    ``evaluation`` -- same tree, same baseline, policy the only difference.
    """

    probe = build_gate_policy_report_document()
    score = _gate_policy_health_score(probe)
    assert 10 <= score <= 90, "fixture must leave room on both sides of the score"

    lenient = build_gate_policy_report_document(fail_health=score - 10)
    strict = build_gate_policy_report_document(fail_health=score + 10)

    assert _gate_policy_exit_code(lenient) == 0
    assert _gate_policy_exit_code(strict) != 0
    assert _gate_policy_gate_reasons(strict)

    for tier in ("observation", "analysis_facts", "comparison"):
        assert _gate_policy_digest(lenient, tier) == _gate_policy_digest(
            strict, tier
        ), tier

    return lenient, strict


def _gate_policy_digest(document: Mapping[str, object], tier: str) -> str:
    value = section(document, f"integrity.digests.{tier}").get("value")
    assert isinstance(value, str) and value
    return value


def _gate_policy_health_score(document: Mapping[str, object]) -> int:
    score = section(document, "metrics.families.health.summary").get("score")
    assert isinstance(score, int)
    return score


def _gate_policy_exit_code(document: Mapping[str, object]) -> int:
    exit_code = section(document, "evaluation.outcome").get("exit_code")
    assert isinstance(exit_code, int)
    return exit_code


def _gate_policy_gate_reasons(document: Mapping[str, object]) -> list[object]:
    reasons = section(document, "evaluation.outcome").get("reasons")
    assert isinstance(reasons, list)
    return reasons


def build_test_report_document(
    *,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
    meta: Mapping[str, object] | None = None,
    inventory: Mapping[str, object] | None = None,
    block_facts: Mapping[str, Mapping[str, str]] | None = None,
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
    new_segment_group_keys: Collection[str] | None = None,
    suppressed_clone_groups: Sequence[SuppressedCloneGroup] | None = None,
    metrics: Mapping[str, object] | None = None,
    suggestions: Sequence[Suggestion] | None = None,
    structural_findings: Sequence[StructuralFindingGroup] | None = None,
    baseline_container: BaselineContainerV3 | None = None,
    baseline_trust: TrustVector | None = None,
    observed_function_clone_keys: Sequence[str] = (),
    observed_block_clone_keys: Sequence[str] = (),
    gate_exit_code: int = 0,
    gate_reasons: tuple[str, ...] = (),
) -> dict[str, object]:
    """Build the sole canonical report-v3 fixture shape used by report tests.

    ``baseline_container`` defaults to ``None``, which is the container-less
    run every existing caller wants and which the builder projects as
    ``baseline.state == "missing"``. Pass a real container when the test needs
    the other two states: ``trusted``/``untrusted`` are only reachable when a
    container exists, and a test that hand-writes the state string instead
    would be pinning its own guess rather than the builder's projection.

    ``observed_*_clone_keys`` populate the observation bundle's structural
    facts, which is where ``baseline.sorted_novelty_facts`` draws its identities
    from. Left empty -- as every earlier caller left them -- that projection has
    nothing to classify, so its novelty decision was exercised by no test at all
    and a mutation of it survived. Pass the group keys to reach it.
    """

    _source, registry = module_registry_context(
        filepath="pkg/module.py",
        module_name="pkg.module",
    )
    observation_bundle = build_observation_bundle(
        scan_root=Path("."),
        module_registry=registry,
        function_clone_keys=observed_function_clone_keys,
        block_clone_keys=observed_block_clone_keys,
    )
    gate_config = MetricGateConfig(
        fail_complexity=-1,
        fail_coupling=-1,
        fail_cohesion=-1,
        fail_cycles=False,
        fail_dead_code=False,
        fail_health=-1,
        fail_on_new_metrics=False,
    )
    return _build_report_document_v3(
        observation_bundle=observation_bundle,
        baseline_container=baseline_container,
        baseline_trust=baseline_trust,
        gate_config=gate_config,
        gate_result=GateResult(exit_code=gate_exit_code, reasons=gate_reasons),
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        meta=meta,
        inventory=inventory,
        block_facts=block_facts,
        new_function_group_keys=new_function_group_keys,
        new_block_group_keys=new_block_group_keys,
        new_segment_group_keys=new_segment_group_keys,
        suppressed_clone_groups=suppressed_clone_groups,
        metrics=metrics,
        suggestions=suggestions,
        structural_findings=structural_findings,
    )


def build_maximal_report_document() -> dict[str, object]:
    """The canonical fixture with every optional section populated.

    A default run omits the metric families that depend on run mode --
    ``coverage_join`` needs joined coverage, ``semantic_authority`` needs
    authority analysis -- and omits the suppressed-clone group. All three are
    part of the schema, so a consumer reading them is reading a key the report
    carries. Callers that check consumer reads against a document need this
    shape, not a default one, or a conditional section reads as a withdrawn key.

    Two more sections are optional in the same way and were missing here. The
    analysis profile is emitted only when all six thresholds are declared, and
    ``health.summary.dimensions`` is filled only when the health family carries
    a measurement -- so the Overview's threshold line and the Dependencies
    panel's health figure both read keys a thinner fixture does not carry. The
    document is the reference for "what a consumer may read", so a gap in it
    reads as a defect in the consumer.
    """

    return build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={
            "analysis_profile": {
                "min_loc": 6,
                "min_stmt": 4,
                "block_min_loc": 20,
                "block_min_stmt": 8,
                "segment_min_loc": 20,
                "segment_min_stmt": 10,
            },
        },
        metrics={
            "coverage_join": {"summary": {}, "items": []},
            "health": health_family_for_population(found=10, analyzed=10),
            "semantic_authority": {"summary": {}, "items": []},
        },
        suppressed_clone_groups=(
            SuppressedCloneGroup(
                kind="function",
                group_key="golden-group",
                items=(
                    {
                        "qualname": "tests.fixtures.golden.a:run",
                        "filepath": "/root/tests/fixtures/golden_project/a.py",
                        "start_line": 10,
                        "end_line": 12,
                        "loc": 3,
                        "stmt_count": 2,
                        "fingerprint": "fp-a",
                        "loc_bucket": "0-19",
                    },
                ),
                matched_patterns=("tests/fixtures/golden_*",),
                suppression_rule="golden_fixture",
                suppression_source="project_config",
            ),
        ),
    )
