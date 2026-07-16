# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError

import pytest

from codeclone.analysis import _module_walk as module_walk_mod
from codeclone.analysis import security_surfaces as security_surfaces_mod
from codeclone.analysis.security_surfaces import project_security_surfaces
from codeclone.contracts import SEMANTIC_EVENT_VERSION
from codeclone.models import FactRef, SemanticEvent
from codeclone.qualnames import QualnameCollector
from codeclone.semantics import events as semantic_events_mod
from codeclone.semantics.events import SemanticEventCollector, event_counter_key
from tests._ast_metrics_helpers import module_registry_context


def _events(source: str) -> tuple[SemanticEvent, ...]:
    identity, registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )
    tree = ast.parse(source)
    collector = QualnameCollector()
    collector.visit(tree)
    return module_walk_mod._collect_module_walk_data(
        tree=tree,
        source=identity,
        registry=registry,
        collector=collector,
        collect_referenced_names=True,
    ).semantic_events


def test_semantic_event_stream_is_deterministic_and_covers_core_kinds() -> None:
    source = """
import subprocess

class Result:
    pass

def build(value: str) -> Result:
    result = Result()
    result.value = value
    subprocess.run(["echo", value])
    return result
"""
    first = _events(source)
    second = _events(source)

    assert first == second
    assert {event.kind for event in first} >= {
        "assign",
        "construct",
        "field_write",
        "return_value",
        "security_observation",
    }
    assert [event.event_id for event in first] == [event.event_id for event in second]
    assert project_security_surfaces(first) == project_security_surfaces(second)


def test_type_checking_branch_does_not_emit_runtime_events() -> None:
    events = _events(
        """
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import yaml
else:
    import subprocess
"""
    )
    surfaces = project_security_surfaces(events)
    assert tuple(item.evidence_symbol for item in surfaces) == ("subprocess",)


def test_semantic_event_models_are_frozen_and_versioned() -> None:
    events = _events("value = 1\n")
    assert SEMANTIC_EVENT_VERSION == "1"
    assert event_counter_key("security_observation") == (
        "events_by_kind.security_observation"
    )
    assert events
    field_name = "subject"
    with pytest.raises(FrozenInstanceError):
        setattr(events[0], field_name, "changed")
    assert FactRef(kind="const", ref="stable").ref == "stable"


def test_semantic_event_edge_inputs_and_missing_locations_are_typed() -> None:
    assert semantic_events_mod._input_ref(ast.Constant(value=b"raw")).ref == (
        "bytes_length:3"
    )
    assert semantic_events_mod._input_ref(ast.Constant(value=...)).ref == "ellipsis"

    collector = SemanticEventCollector(
        module_name="pkg.mod",
        filepath="pkg/mod.py",
        top_level_class_names=frozenset(),
    )
    collector.observe(
        ast.Assign(
            targets=[ast.Name(id="value", ctx=ast.Store())],
            value=ast.Constant(value=1),
        ),
        scope=(),
        callable_depth=0,
        class_depth=0,
        guards=(),
    )
    collector.observe(
        ast.Import(names=[ast.alias(name=" ", asname=None)]),
        scope=(),
        callable_depth=0,
        class_depth=0,
        guards=(),
    )
    collector._register_import_alias(bound_name="", imported_name="pkg")
    collector._emit_security(
        category="process_boundary",
        capability="subprocess_run",
        node=ast.Name(id="missing_line", ctx=ast.Load()),
        qualname="pkg.mod",
        location_scope="module",
        classification_mode="exact_call",
        evidence_kind="call",
        evidence_symbol="subprocess.run",
        guards=(),
    )
    assert collector.events == ()


def test_semantic_call_classification_and_keyword_modes_cover_closed_kinds() -> None:
    events = _events(
        """
from pkg import check_compatibility, publish_event, resolve_module_identity

def run() -> None:
    check_compatibility()
    resolve_module_identity()
    publish_event()
    open("artifact.txt", encoding="utf-8", mode="w")
    open("readonly.txt", encoding="utf-8")
"""
    )
    assert {event.kind for event in events} >= {
        "compatibility_check",
        "publish_event",
        "resolve_identity",
        "security_observation",
    }


def test_security_projection_rejects_unknown_closed_values() -> None:
    with pytest.raises(ValueError, match="category"):
        security_surfaces_mod._category("unknown")
    with pytest.raises(ValueError, match="location scope"):
        security_surfaces_mod._location_scope("unknown")
    with pytest.raises(ValueError, match="classification mode"):
        security_surfaces_mod._classification_mode("unknown")
    with pytest.raises(ValueError, match="evidence kind"):
        security_surfaces_mod._evidence_kind("unknown")
