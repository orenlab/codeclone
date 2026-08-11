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
from codeclone.report.gates.evaluator import GateResult, MetricGateConfig

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
    """

    _source, registry = module_registry_context(
        filepath="pkg/module.py",
        module_name="pkg.module",
    )
    observation_bundle = build_observation_bundle(
        scan_root=Path("."), module_registry=registry
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
    """

    return build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        metrics={
            "coverage_join": {"summary": {}, "items": []},
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
