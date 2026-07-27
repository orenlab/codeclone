# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from codeclone.models import (
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
    baseline_trust: TrustVector | None = None,
    gate_exit_code: int = 0,
    gate_reasons: tuple[str, ...] = (),
) -> dict[str, object]:
    """Build the sole canonical report-v3 fixture shape used by report tests."""

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
        baseline_container=None,
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
