# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import subprocess
import sys
from dataclasses import FrozenInstanceError, asdict

import pytest

from codeclone.analysis import _module_walk as module_walk_mod
from codeclone.analysis.fingerprint import _cfg_fingerprint_and_complexity
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.units import extract_units_and_stats_from_source
from codeclone.findings.clones.grouping import clone_eligible_units
from codeclone.models import FunctionContractSummary
from codeclone.qualnames import QualnameCollector
from codeclone.semantics.flow import summarize_function_contract
from tests._ast_metrics_helpers import (
    bindings_for_function_node,
    module_registry_context,
)


def _summary(source: str) -> FunctionContractSummary:
    identity, registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )
    tree = ast.parse(source)
    collector = QualnameCollector()
    collector.visit(tree)
    assert len(collector.units) == 1
    local_name, node = collector.units[0]
    walk = module_walk_mod._collect_module_walk_data(
        tree=tree,
        source=identity,
        registry=registry,
        collector=collector,
        collect_referenced_names=True,
    )
    function = f"pkg.mod:{local_name}"
    graph, _fingerprint, _complexity = _cfg_fingerprint_and_complexity(
        node,
        NormalizationConfig(),
        function,
        bindings_for_function_node(node),
    )
    return summarize_function_contract(
        function=function,
        node=node,
        graph=graph,
        events=walk.semantic_events,
    )


def test_local_flow_resolves_parameter_assignments_and_returns() -> None:
    summary = _summary("def flow(value):\n    copied = value\n    return copied\n")

    assert summary.function == "pkg.mod:flow"
    assert summary.unresolved_flow is False
    assert summary.param_flows == (
        ("value", "pkg.mod:flow#000001"),
        ("value", "pkg.mod:flow#000002"),
    )
    assert summary.returns == (summary.events[0].output,)
    assert all(event.resolution == "resolved" for event in summary.events)


def test_local_flow_reuses_call_output_and_parameter_lineage() -> None:
    summary = _summary(
        "class Result:\n"
        "    pass\n"
        "\n"
        "def build(value):\n"
        "    result = Result(value)\n"
        "    return result\n"
    )

    assert summary.unresolved_flow is False
    assert ("value", "pkg.mod:build#000001") in summary.param_flows
    assert ("value", "pkg.mod:build#000002") in summary.param_flows
    assert summary.returns == (summary.events[0].output,)


def test_dynamic_and_branch_ambiguous_flow_is_unavailable_not_guessed() -> None:
    dynamic = _summary("def choose(value):\n    return globals()[value]\n")
    branch = _summary(
        "def choose(flag, value):\n"
        "    if flag:\n"
        "        result = value\n"
        "    return result\n"
    )
    callback = _summary("def choose(callback, value):\n    return callback(value)\n")

    assert dynamic.unresolved_flow is True
    assert dynamic.returns[0].kind == "unresolved"
    assert branch.unresolved_flow is True
    assert branch.returns[0].kind == "unresolved"
    assert callback.unresolved_flow is True


def test_flow_summary_is_deterministic_and_frozen() -> None:
    source = "def flow(value):\n    copied = value\n    return copied\n"
    first = _summary(source)
    second = _summary(source)

    assert first == second
    field_name = "unresolved_flow"
    with pytest.raises(FrozenInstanceError):
        setattr(first, field_name, True)


def test_flow_summary_is_stable_across_processes() -> None:
    script = """
import dataclasses
import json
from tests.test_semantic_flow import _summary

summary = _summary("def flow(value):\\n    copied = value\\n    return copied\\n")
print(json.dumps(dataclasses.asdict(summary), sort_keys=True, separators=(",", ":")))
"""
    outputs = tuple(
        subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        for _ in range(3)
    )

    assert outputs[0] == outputs[1] == outputs[2]


def test_every_function_is_summarized_below_clone_threshold() -> None:
    identity, registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )
    units, _blocks, _segments, _stats, metrics, _findings = (
        extract_units_and_stats_from_source(
            source="def tiny(value):\n    return value\n",
            filepath="pkg/mod.py",
            identity=identity,
            registry=registry,
            cfg=NormalizationConfig(),
            min_loc=100,
            min_stmt=100,
        )
    )

    # Far below the clone floors the function is not a clone unit, yet both
    # its semantic summary and its metric fact exist (39Y Y5).
    assert (
        clone_eligible_units(
            [asdict(unit) for unit in units],
            min_loc=100,
            min_stmt=100,
        )
        == []
    )
    assert [unit.qualname for unit in units] == ["pkg.mod:tiny"]
    assert tuple(
        summary.function
        for summary in metrics.semantic_facts.function_contract_summaries
    ) == ("pkg.mod:tiny",)


def test_double_star_call_keywords_are_dynamic_flow() -> None:
    summary = _summary(
        "def apply(kw):\n    return helper.apply(**kw)\n",
    )
    assert summary.unresolved_flow is True
    assert summary.returns[0].kind == "unresolved"


def test_assign_event_without_output_marks_flow_unresolved() -> None:
    """A synthesized assign event with no output fact cannot resolve; the
    summary must abstain instead of inventing lineage."""

    from codeclone.models import SemanticEvent

    source = "def flow(value):\n    copied = value\n    return copied\n"
    tree = ast.parse(source)
    collector = QualnameCollector()
    collector.visit(tree)
    local_name, node = collector.units[0]
    function = f"pkg.mod:{local_name}"
    graph, _fingerprint, _complexity = _cfg_fingerprint_and_complexity(
        node,
        NormalizationConfig(),
        function,
        bindings_for_function_node(node),
    )
    broken = SemanticEvent(
        event_id=f"{function}#000001",
        kind="assign",
        subject="copied",
        inputs=(),
        output=None,
        guards=(),
        location=("pkg/mod.py", 2),
        resolution="resolved",
    )
    summary = summarize_function_contract(
        function=function,
        node=node,
        graph=graph,
        events=(broken,),
    )
    assert summary.unresolved_flow is True
