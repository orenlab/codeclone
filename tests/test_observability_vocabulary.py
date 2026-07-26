# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from codeclone.models import ObservabilityConfig
from codeclone.observability import bootstrap, record_counter, shutdown, span
from codeclone.observability.vocabulary import (
    COUNTER_KEYS,
    OBSERVER_VOCABULARY_VERSION,
    SPAN_NAMES,
    ObservabilityVocabularyError,
)

_ROOT = Path(__file__).resolve().parents[1]


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _literal_argument(call: ast.Call, *, keyword: str) -> str | None:
    for item in call.keywords:
        if item.arg == keyword and isinstance(item.value, ast.Constant):
            return item.value.value if isinstance(item.value.value, str) else None
    if call.args and isinstance(call.args[0], ast.Constant):
        value = call.args[0].value
        return value if isinstance(value, str) else None
    return None


def test_unknown_vocabulary_rejected_while_disabled() -> None:
    bootstrap(ObservabilityConfig(enabled=False))
    try:
        with (
            pytest.raises(ObservabilityVocabularyError, match="span name"),
            span(name="not.reviewed"),
        ):
            pass
        with (
            span(name="pipeline.process") as inert,
            pytest.raises(ObservabilityVocabularyError, match="counter key"),
        ):
            inert.set_counter("not_reviewed", 1)
        with pytest.raises(ObservabilityVocabularyError, match="counter key"):
            record_counter("not_reviewed")
    finally:
        shutdown()


def test_vocabulary_version_and_phase39_stage_inventory() -> None:
    assert OBSERVER_VOCABULARY_VERSION == "3"
    assert {
        "semantics.events",
        "config.resolve",
        "manifest.build",
        "registry.build",
        "cache.backend.prune",
        "baseline.container.publish",
        "report.render",
        "mcp.run_store.register",
        "memory.identity.migrate",
        "release.phase39.matrix",
    } <= SPAN_NAMES
    assert "spans_dropped" in COUNTER_KEYS
    assert "events_by_kind.security_observation" in COUNTER_KEYS
    assert "report_novelty_unavailable" in COUNTER_KEYS


def test_production_literal_observer_calls_use_closed_vocabulary() -> None:
    violations: list[str] = []
    for path in sorted((_ROOT / "codeclone").rglob("*.py")):
        source = path.read_text("utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name in {"span", "record_elapsed_span"}:
                literal = _literal_argument(node, keyword="name")
                if literal is not None and literal not in SPAN_NAMES:
                    violations.append(
                        f"{path.relative_to(_ROOT)}:{node.lineno}:{literal}"
                    )
            if name in {"add_counter", "set_counter", "record_counter"}:
                literal = _literal_argument(node, keyword="key")
                if literal is not None and literal not in COUNTER_KEYS:
                    violations.append(
                        f"{path.relative_to(_ROOT)}:{node.lineno}:{literal}"
                    )
        assert 'set_counter(f"' not in source
    assert violations == []
