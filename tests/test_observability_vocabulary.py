# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import functools
from pathlib import Path

import pytest

from codeclone.analysis.phase_ledger import (
    MODULE_PASSES_SUBPHASE_US_COUNTER_SUFFIXES,
    PHASE_US_COUNTER_SUFFIXES,
)
from codeclone.models import ObservabilityConfig
from codeclone.observability import bootstrap, record_counter, shutdown, span
from codeclone.observability.vocabulary import (
    _MCP_TOOL_NAMES,
    COUNTER_KEYS,
    OBSERVER_PLANE_OPERATIONS,
    OBSERVER_VOCABULARY_VERSION,
    PARK_REASONS,
    PARKED_COUNTER_KEYS,
    PARKED_SPAN_NAMES,
    PLANE_OBSERVER,
    SPAN_NAMES,
    ObservabilityVocabularyError,
    resolve_operation_plane,
)

_ROOT = Path(__file__).resolve().parents[1]
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


def _walk_functions(tree: ast.AST) -> list[ast.FunctionDef]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]


@functools.cache
def _emit_calls() -> frozenset[str]:
    """The emit entry points, read off the functions that validate a name.

    A hand-written tuple of "calls that emit" is the same class of record as
    the vocabulary it polices: add an emit function, forget the tuple, and
    every module that uses only the new one drops out of the reverse scan
    while it stays green. An entry point is instead defined by what it does —
    it hands one of its own arguments to a vocabulary validator. The
    ``validate_counter_key("spans_dropped")`` bookkeeping inside
    ``_append_span`` passes a literal, not an argument, and is correctly not
    an entry point.
    """
    path = _ROOT / "codeclone" / "observability" / "runtime.py"
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    validators = {"validate_span_name", "validate_counter_key"}
    names: set[str] = set()
    for node in _walk_functions(tree):
        parameters = {argument.arg for argument in node.args.args} | {
            argument.arg for argument in node.args.kwonlyargs
        }
        validated = (
            argument
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and _call_name(call) in validators
            for argument in call.args
        )
        if any(
            isinstance(argument, ast.Name) and argument.id in parameters
            for argument in validated
        ):
            names.add(node.name)
    return frozenset(names)


@functools.cache
def _index_source_names() -> frozenset[str]:
    """The lane names ``memory.semantic.source.*`` is built from.

    rebuild.py spells the span ``f"memory.semantic.source.{source.name()}"``,
    so the generator's domain is what the IndexSource implementations return
    from ``name()`` — read from them, not approximated by a prefix pattern.
    """
    path = _ROOT / "codeclone" / "memory" / "semantic" / "sources.py"
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    name_methods = (
        member
        for declaration in ast.walk(tree)
        if isinstance(declaration, ast.ClassDef)
        for member in declaration.body
        if isinstance(member, ast.FunctionDef) and member.name == "name"
    )
    return frozenset(
        node.value.value
        for member in name_methods
        for node in ast.walk(member)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


@functools.cache
def _generated_names() -> frozenset[str]:
    """Names built at runtime, enumerated from the generators that build them.

    These used to be three regexes, and a regex is not a generator: the
    ``^mcp\\.[a-z_]+$`` pattern blessed every conceivable tool name, so the one
    family whose members are minted from a live registry was the one family
    this scan could not police. Each entry here is the generator's actual
    domain — the declared tool names, the IndexSource lane names, the analysis
    phase keys — so a declared name the generator cannot produce is unwired.
    """
    return frozenset(
        {f"mcp.{name}" for name in _MCP_TOOL_NAMES}
        | {f"memory.semantic.source.{name}" for name in _index_source_names()}
        | set(PHASE_US_COUNTER_SUFFIXES)
        | set(MODULE_PASSES_SUBPHASE_US_COUNTER_SUFFIXES)
    )


@functools.cache
def _mcp_tools_that_read_the_observability_store() -> frozenset[str]:
    """The MCP handlers that ARE the instrument, read off what they import.

    A tool belongs to the observer plane because it reads the observability
    read model, not because someone remembered to list it. The handler name is
    the tool name, so the operation name it will be recorded under is
    ``mcp.{handler}`` — the same string server.py builds.
    """
    surface = _ROOT / "codeclone" / "surfaces" / "mcp"
    handlers: set[str] = set()
    for path in sorted(surface.rglob("*.py")):
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        handlers.update(
            node.name
            for node in _walk_functions(tree)
            for inner in ast.walk(node)
            if isinstance(inner, ast.ImportFrom)
            and (inner.module or "").endswith("observability.query")
        )
    return frozenset(handlers)


def _emits_telemetry(tree: ast.AST) -> bool:
    return any(
        _call_name(node) in _emit_calls()
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
    return name in literals or name in _generated_names()


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


def test_observer_plane_claims_only_the_tools_that_read_the_store() -> None:
    """Over-claiming the observer plane hides runtime work from its own window.

    The plane split exists so the instrument cannot evict the evidence it just
    pointed at. Marking an ordinary tool as instrument moves real runtime
    operations into the observer window, where nobody looks for them — the
    same blindness as the eviction it was built to stop, from the other side.
    """
    instrument = _mcp_tools_that_read_the_observability_store()
    assert instrument, "no MCP tool was found reading the observability store"
    over_claimed = sorted(
        set(OBSERVER_PLANE_OPERATIONS) - {f"mcp.{name}" for name in instrument}
    )
    assert over_claimed == []


def test_every_store_reading_tool_is_marked_observer_plane() -> None:
    """Under-claiming it is the incident the plane split was built for.

    ``query_platform_observability`` is itself an instrumented MCP tool, so
    while it counted as runtime, reading the instrument consumed the window
    holding the evidence. A second reader added later and left unmarked
    re-opens exactly that, so the mark is derived from what the handlers do —
    reach the observability read model — not from a list kept beside them.
    """
    instrument = _mcp_tools_that_read_the_observability_store()
    assert instrument, "no MCP tool was found reading the observability store"
    for tool_name in sorted(instrument):
        operation_name = f"mcp.{tool_name}"
        assert operation_name in OBSERVER_PLANE_OPERATIONS, operation_name
        assert resolve_operation_plane(operation_name) == PLANE_OBSERVER


def test_generated_name_families_are_read_from_their_generators() -> None:
    """Each runtime-built family is exactly its generator's domain.

    A prefix or pattern would be satisfied by any plausible-looking member, so
    a name whose generator can never produce it would pass as instrumented.
    Re-deriving each family from the thing that mints it is what makes the
    reverse scan mean something for names no module writes literally.
    """
    sources = _index_source_names()
    assert sources, "no IndexSource declared a name, so no lane was compared"
    assert {
        name for name in SPAN_NAMES if name.startswith("memory.semantic.source.")
    } == {f"memory.semantic.source.{name}" for name in sources}

    phases = set(PHASE_US_COUNTER_SUFFIXES)
    assert phases, "the analysis phase ledger declared no phase, so none matched"
    assert {
        key for key in COUNTER_KEYS if key.startswith("phase_") and key.endswith("_us")
    } == phases

    subphases = set(MODULE_PASSES_SUBPHASE_US_COUNTER_SUFFIXES)
    assert subphases, "the ledger declared no module-pass subphase"
    assert subphases <= COUNTER_KEYS


def test_the_reverse_scan_still_looks_at_real_modules_and_real_emit_calls() -> None:
    """The scan's own inputs are records too, and they rot the same way.

    An excluded path that no longer exists excludes nothing; a carrier path
    that no longer exists carries nothing; an empty set of emit entry points
    would make every module look inert. Each failure leaves the reverse scan
    green while it checks less than it claims, which is the shape of defect
    this whole file exists to prevent.
    """
    missing = sorted(
        path
        for path in (*_VOCABULARY_CONSUMERS, *_COUNTER_CARRIERS)
        if not (_ROOT / path).is_file()
    )
    assert missing == []
    assert _emit_calls(), "no emit entry point was found, so every module looks inert"
    assert "span" in _emit_calls()
    assert "record_counter" in _emit_calls()
    literals = _emitted_literals()
    assert literals, "the emit scan found no module that emits anything"
