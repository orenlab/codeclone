# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from codeclone.models import ObservabilityConfig
from codeclone.observability import bootstrap, record_counter, shutdown, span
from codeclone.observability.vocabulary import (
    COUNTER_KEYS,
    OBSERVER_VOCABULARY_VERSION,
    PARK_REASONS,
    PARKED_COUNTER_KEYS,
    PARKED_SPAN_NAMES,
    SPAN_NAMES,
    ObservabilityVocabularyError,
)

_ROOT = Path(__file__).resolve().parents[1]

_EMIT_CALLS = frozenset(
    {"span", "record_elapsed_span", "add_counter", "set_counter", "record_counter"}
)
# The observability package both declares the vocabulary and reads it back.
# These modules consume names — a literal here is a *consumer*, never proof
# that anything emits it, and counting them would make the reverse test hollow.
_VOCABULARY_CONSUMERS = frozenset(
    {
        "codeclone/observability/vocabulary.py",
        "codeclone/observability/query.py",
        "codeclone/observability/views.py",
        "codeclone/observability/render_html.py",
        "codeclone/observability/render_json.py",
        "codeclone/observability/analysis_phases.py",
        "codeclone/observability/store/reader.py",
        "codeclone/observability/store/writer.py",
        "codeclone/observability/store/schema.py",
    }
)
# Modules that carry counter names in a mapping which a *different* module
# feeds to set_counter. They emit by construction even though the call is
# elsewhere, so their literals count.
_COUNTER_CARRIERS = frozenset(
    {
        "codeclone/analysis/phase_ledger.py",
        "codeclone/semantics/events.py",
    }
)
# Names built at runtime rather than written literally, each verified against
# its generator: server.py f"mcp.{tool_name}", rebuild.py
# f"memory.semantic.source.{source.name()}", phase_ledger.py f"phase_{key}_us".
_GENERATED_NAMES = (
    re.compile(r"^mcp\.(?!run_store\.)[a-z_]+$"),
    re.compile(r"^memory\.semantic\.source\.[a-z_]+$"),
    re.compile(r"^phase_[a-z_]+_us$"),
)


def _emits_telemetry(tree: ast.AST) -> bool:
    return any(
        _call_name(node) in _EMIT_CALLS
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    )


def _emitted_literals() -> dict[str, str]:
    """Every string literal in a module that can emit telemetry -> first site."""
    literals: dict[str, str] = {}
    for path in sorted((_ROOT / "codeclone").rglob("*.py")):
        relative = path.relative_to(_ROOT).as_posix()
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        produces = relative not in _VOCABULARY_CONSUMERS and (
            relative in _COUNTER_CARRIERS or _emits_telemetry(tree)
        )
        if not produces:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.setdefault(node.value, f"{relative}:{node.lineno}")
    return literals


def _is_emitted(name: str, literals: dict[str, str]) -> bool:
    return name in literals or any(pattern.match(name) for pattern in _GENERATED_NAMES)


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


def test_every_declared_name_is_emitted_or_explicitly_parked() -> None:
    """The other direction: every declared name is emitted, or parked.

    ``test_production_literal_observer_calls_use_closed_vocabulary`` asserts
    emitted ⊆ declared, which stays green for a name nothing ever emits. That is
    how 15 span names and 53 counter keys came to be declared, test-pinned, and
    wired to nothing — including the whole ``run_store_*`` family, exactly the
    telemetry that would have shown one agent evicting another agent's run.
    A name with no emit site is a claim this build cannot honour: wire it, or
    park it in the vocabulary with the reason it cannot be wired.
    """
    literals = _emitted_literals()
    unwired = sorted(
        name
        for name in SPAN_NAMES
        if not _is_emitted(name, literals) and name not in PARKED_SPAN_NAMES
    ) + sorted(
        key
        for key in COUNTER_KEYS
        if not _is_emitted(key, literals) and key not in PARKED_COUNTER_KEYS
    )
    assert unwired == []


def test_parked_names_are_declared_reasoned_and_still_unwired() -> None:
    """Parking is a standing claim, and it has to keep being true.

    A parked name that acquires an emit site must leave the registry, or the
    parking list slowly becomes a second, silent vocabulary of things nobody
    checks. Parking a name that is not declared at all is equally wrong.
    """
    literals = _emitted_literals()
    assert set(PARKED_SPAN_NAMES) <= SPAN_NAMES
    assert set(PARKED_COUNTER_KEYS) <= COUNTER_KEYS
    assert set(PARKED_SPAN_NAMES.values()) <= set(PARK_REASONS)
    assert set(PARKED_COUNTER_KEYS.values()) <= set(PARK_REASONS)
    wired_but_parked = sorted(
        name
        for name in (*PARKED_SPAN_NAMES, *PARKED_COUNTER_KEYS)
        if _is_emitted(name, literals)
    )
    assert wired_but_parked == []


def test_the_run_store_telemetry_is_wired_not_parked() -> None:
    """The gap the reverse test exists for, pinned by name.

    Session run-store eviction between subagents was invisible three times in
    one day while these names sat in the vocabulary. Parking them later would
    re-open that blind zone quietly; this fails if anyone tries.
    """
    literals = _emitted_literals()
    for name in (
        "mcp.run_store.register",
        "mcp.run_store.resolve_artifact",
        "run_store_runs_evicted",
        "run_store_runs_retained",
        "run_store_selector_hits",
        "run_store_selector_misses",
        "run_store_artifact_bytes",
        "run_store_artifacts_missing",
        "run_store_artifacts_drifted",
        "run_store_artifacts_retained",
        "cache_profile_hit",
        "cache_profile_miss",
        "hygiene.git.status",
        "hygiene.git.rev_parse",
    ):
        assert _is_emitted(name, literals), name
        assert name not in PARKED_SPAN_NAMES
        assert name not in PARKED_COUNTER_KEYS
