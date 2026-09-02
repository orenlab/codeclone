# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

import ast
import dataclasses
import hashlib
import json
import os
import signal
import sys
import textwrap
import tokenize
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import pytest

import codeclone.analysis._module_walk as module_walk_mod
import codeclone.analysis.ast_helpers as ast_helpers_mod
import codeclone.analysis.parser as parser_mod
import codeclone.analysis.reachability as reachability_mod
import codeclone.analysis.units as units_mod
from codeclone import contracts, qualnames, ui_messages
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.contracts.errors import ParseError
from codeclone.metrics.dead_code import classify_liveness, find_unused
from codeclone.models import (
    BlockUnit,
    ClassMetrics,
    DeadCandidate,
    FileMetrics,
    FunctionRelationshipFacts,
    ModuleDep,
    ModuleRegistryHandle,
    PackagePrefix,
    RuntimeReachabilityFact,
    SegmentUnit,
    SourceStats,
    StructuralFindingGroup,
    Unit,
)
from codeclone.qualnames import FunctionNode, QualnameCollector
from tests._ast_metrics_helpers import (
    build_test_module_registry,
    module_registry_context,
)

_DETECT_FUSION_CORPUS_FILES = (
    "tests/fixtures/analytics/helpers.py",
    "tests/fixtures/golden_project/alpha.py",
    "tests/fixtures/golden_project/beta.py",
    "tests/fixtures/golden_v2/clone_metrics_cycle/pkg/a.py",
    "tests/fixtures/golden_v2/clone_metrics_cycle/pkg/app.py",
    "tests/fixtures/golden_v2/clone_metrics_cycle/pkg/b.py",
    "tests/fixtures/golden_v2/pyproject_defaults/pkg/one.py",
    "tests/fixtures/golden_v2/pyproject_defaults/pkg/two.py",
    "tests/fixtures/golden_v2/test_only_usage/pkg/consumer.py",
    "tests/fixtures/golden_v2/test_only_usage/pkg/core.py",
    "tests/fixtures/golden_v2/test_only_usage/pkg/main.py",
    "tests/fixtures/golden_v2/test_only_usage/pkg/tests/fixture_core.py",
    "tests/fixtures/semantic_authority/compatibility_checkers.py",
    "tests/fixtures/semantic_authority/dual_artifact_writers.py",
    "tests/fixtures/semantic_authority/module_identity_producers.py",
    "tests/fixtures/semantic_authority/volatile_run_identity.py",
    "tests/fixtures/wire_corpus/core_syntax.py",
    "tests/fixtures/wire_corpus/modern_syntax.py",
    "tests/fixtures/wire_corpus/pattern_syntax.py",
)
# Repinned under maintainer sanction for the 39Y rule-3 re-home: the payload
# canonicalizes dataclasses.asdict over metrics.class_metrics wholesale, so the
# three ratified ClassMetrics fields (base_names, has_unresolved_external_base,
# decorator_evidenced_methods) are digest-visible although no detect-fusion
# output changed — rebuilding the payload with exactly those three keys popped
# reproduces ebfb095c… byte-exact. The canonicalization is deliberately not
# narrowed; the guard stays whole-fact.
#
# Repinned again under maintainer sanction for 39Y Y6 (CBO imported-domain edge
# lane). The delta is confined to the `cbo` / `coupled_classes` fields of
# exactly three classes, each a genuine imported-domain edge the old rule could
# not see: clone_metrics_cycle pkg.a:ServiceA -> ('ServiceB',),
# pkg.b:ServiceB -> ('ServiceA',), and semantic_authority
# dual_artifact_writers:JsonWriter -> ('Mapping', 'Path'). Proof: restoring
# those three rows to cbo=0 / coupled_classes=() reproduces 84ce80a1… byte-exact
# — so no other row moved and no edge was lost anywhere in the corpus.
#
# Repinned again for 39Y rule-3 defect 2 (self-dispatch as decision-table row-1
# evidence), same whole-fact canonicalization as the first repin above: the new
# ClassMetrics field `self_dispatched_methods` is digest-visible although no
# detect-fusion output changed. Proof: rebuilding the payload with exactly that
# one key popped reproduces 98d15d32… byte-exact, so the delta is the added key
# and nothing else in the corpus moved.
#
# Repinned again for 39Y item 2 (maintainer ruling 2026-07-30: an imported
# collaborator counts only on proven class resolution; `Call.func` syntax is
# not evidence). Two sanctioned deltas, both confined:
#   1. the new ClassMetrics field `instantiation_candidates` is digest-visible;
#   2. exactly one class row loses a file-scope edge — clone_metrics_cycle
#      pkg.a:ServiceA, whose only edge was the unresolved call `ServiceB()`.
#      It is not a lost edge: the project fold re-earns it against the class
#      index, which is why golden_v2/clone_metrics_cycle is unchanged.
# Proof: popping that one key and re-applying the dead syntax rule (every
# candidate label counted as an edge) reproduces d7498815… byte-exact, so
# nothing else in the corpus moved. Exactly one row carries a candidate at all.
_DETECT_FUSION_CORPUS_DIGEST = (
    "63f6d558fb022b6b922dba188a115cb5eafcae5cc4b0fff85c64f2d9cde13106"
)


def _extract_source(
    *,
    source: str,
    filepath: str,
    module_name: str,
    cfg: NormalizationConfig,
    min_loc: int,
    min_stmt: int,
    block_min_loc: int = 20,
    block_min_stmt: int = 8,
    segment_min_loc: int = 20,
    segment_min_stmt: int = 10,
    collect_structural_findings: bool = True,
    module_registry: ModuleRegistryHandle | None = None,
) -> tuple[
    list[Unit],
    list[BlockUnit],
    list[SegmentUnit],
    SourceStats,
    FileMetrics,
    list[StructuralFindingGroup],
]:
    if module_registry is None:
        identity, registry = module_registry_context(
            filepath=filepath,
            module_name=module_name,
        )
    else:
        registry = module_registry
        identity = registry.entries_by_path[filepath].identity
    return units_mod.extract_units_and_stats_from_source(
        source=source,
        filepath=filepath,
        identity=identity,
        registry=registry,
        cfg=cfg,
        min_loc=min_loc,
        min_stmt=min_stmt,
        block_min_loc=block_min_loc,
        block_min_stmt=block_min_stmt,
        segment_min_loc=segment_min_loc,
        segment_min_stmt=segment_min_stmt,
        collect_structural_findings=collect_structural_findings,
    )


def extract_units_from_source(
    *,
    source: str,
    filepath: str,
    module_name: str,
    cfg: NormalizationConfig,
    min_loc: int,
    min_stmt: int,
    block_min_loc: int = 20,
    block_min_stmt: int = 8,
    segment_min_loc: int = 20,
    segment_min_stmt: int = 10,
) -> tuple[
    list[Unit],
    list[BlockUnit],
    list[SegmentUnit],
]:
    units, blocks, segments, _source_stats, _file_metrics, _sf = _extract_source(
        source=source,
        filepath=filepath,
        module_name=module_name,
        cfg=cfg,
        min_loc=min_loc,
        min_stmt=min_stmt,
        block_min_loc=block_min_loc,
        block_min_stmt=block_min_stmt,
        segment_min_loc=segment_min_loc,
        segment_min_stmt=segment_min_stmt,
    )
    return units, blocks, segments


def _parse_tree_and_collector(
    source: str,
) -> tuple[ast.Module, QualnameCollector]:
    tree = ast.parse(source)
    collector = QualnameCollector()
    collector.visit(tree)
    return tree, collector


def _collect_module_walk(
    source: str,
    *,
    filepath: str | None = None,
    module_name: str | None = "pkg.mod",
    collect_referenced_names: bool = True,
) -> tuple[ast.Module, QualnameCollector, module_walk_mod._ModuleWalkResult]:
    if filepath is None:
        assert module_name is not None
        filepath = f"{module_name.replace('.', '/')}.py"
    identity, registry = module_registry_context(
        filepath=filepath,
        module_name=module_name,
    )
    tree, collector = _parse_tree_and_collector(source)
    walk = module_walk_mod._collect_module_walk_data(
        tree=tree,
        source=identity,
        registry=registry,
        collector=collector,
        collect_referenced_names=collect_referenced_names,
    )
    return tree, collector, walk


def _dead_qualnames_from_source(
    source: str,
    *,
    filepath: str = "pkg/mod.py",
    module_name: str = "pkg.mod",
) -> tuple[str, ...]:
    _, _, _, _, file_metrics, _ = _extract_source(
        source=source,
        filepath=filepath,
        module_name=module_name,
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    dead = find_unused(
        definitions=file_metrics.dead_candidates,
        referenced_names=file_metrics.referenced_names,
        referenced_qualnames=file_metrics.referenced_qualnames,
        runtime_reachability=file_metrics.runtime_reachability,
        class_metrics=file_metrics.class_metrics,
    )
    return tuple(item.qualname for item in dead)


def _runtime_reachability_by_target(source: str) -> dict[str, RuntimeReachabilityFact]:
    """Runtime-reachability facts keyed by target qualname."""
    return {
        fact.target_qualname: fact for fact in _runtime_reachability_from_source(source)
    }


def _liveness_status_by_qualname(
    source: str,
    *,
    filepath: str = "pkg/mod.py",
    module_name: str = "pkg.mod",
) -> dict[str, str]:
    """Tri-state liveness status for every dead candidate in ``source``.

    The statuses are the 39Y rule-3 contract: ``live``, ``dead``, and
    ``unresolved_external_override`` - honest abstention on a method whose
    owning class inherits from a base the analysis root cannot see.
    """
    _, _, _, _, file_metrics, _ = _extract_source(
        source=source,
        filepath=filepath,
        module_name=module_name,
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    result = classify_liveness(
        definitions=file_metrics.dead_candidates,
        referenced_names=file_metrics.referenced_names,
        referenced_qualnames=file_metrics.referenced_qualnames,
        runtime_reachability=file_metrics.runtime_reachability,
        class_metrics=file_metrics.class_metrics,
    )
    statuses = {
        candidate.qualname: "live" for candidate in file_metrics.dead_candidates
    }
    statuses.update({item.qualname: "dead" for item in result.dead_items})
    statuses.update(
        {
            item.qualname: "unresolved_external_override"
            for item in result.unresolved_overrides
        }
    )
    return statuses


def _file_metrics_from_source(
    source: str,
    *,
    filepath: str,
    module_name: str,
) -> FileMetrics:
    _, _, _, _, file_metrics, _ = _extract_source(
        source=source,
        filepath=filepath,
        module_name=module_name,
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    return file_metrics


def _dead_qualnames_from_metrics(
    definitions: FileMetrics,
    *references: FileMetrics,
) -> set[str]:
    referenced_names: set[str] = set()
    referenced_qualnames: set[str] = set()
    for file_metrics in (definitions, *references):
        referenced_names.update(file_metrics.referenced_names)
        referenced_qualnames.update(file_metrics.referenced_qualnames)

    return {
        item.qualname
        for item in find_unused(
            definitions=definitions.dead_candidates,
            referenced_names=frozenset(referenced_names),
            referenced_qualnames=frozenset(referenced_qualnames),
        )
    }


def _runtime_reachability_from_source(
    source: str,
    *,
    filepath: str = "pkg/mod.py",
    module_name: str = "pkg.mod",
) -> tuple[RuntimeReachabilityFact, ...]:
    _, _, _, _, file_metrics, _ = _extract_source(
        source=source,
        filepath=filepath,
        module_name=module_name,
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    return file_metrics.runtime_reachability


def test_detect_fusion_preserves_fixture_corpus_outputs() -> None:
    root = Path(__file__).parent.parent
    payload: dict[str, object] = {}
    for filepath in _DETECT_FUSION_CORPUS_FILES:
        source = (root / filepath).read_text(encoding="utf-8")
        module_path = filepath.removesuffix(".py")
        if module_path.endswith("/__init__"):
            module_path = module_path[: -len("/__init__")]
        _, _, _, _, metrics, _ = _extract_source(
            source=source,
            filepath=filepath,
            module_name=module_path.replace("/", "."),
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
        )
        payload[filepath] = {
            "runtime_reachability": [
                dataclasses.asdict(item) for item in metrics.runtime_reachability
            ],
            "class_metrics": [
                dataclasses.asdict(item) for item in metrics.class_metrics
            ],
            "security_surfaces": [
                dataclasses.asdict(item) for item in metrics.security_surfaces
            ],
        }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()

    assert hashlib.sha256(canonical).hexdigest() == _DETECT_FUSION_CORPUS_DIGEST


def test_extracts_function_unit() -> None:
    src = """

def foo():
    a = 1
    b = 2
    return a + b
"""

    units, blocks, segments = extract_units_from_source(
        source=src,
        filepath="x.py",
        module_name="mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )

    assert len(units) == 1
    u = units[0]
    assert u.qualname == "mod:foo"
    assert u.loc >= 3
    assert blocks == []
    assert segments == []


def test_source_tokens_returns_empty_on_tokenize_error() -> None:
    assert parser_mod._source_tokens('"""') == ()


def test_declaration_token_index_returns_none_when_start_token_is_missing() -> None:
    tokens = parser_mod._source_tokens("value = 1\n")
    assert (
        parser_mod._declaration_token_index(
            source_tokens=tokens,
            start_line=1,
            start_col=0,
            declaration_token="def",
        )
        is None
    )


def test_declaration_token_index_uses_prebuilt_index() -> None:
    tokens = parser_mod._source_tokens("async def demo():\n    return 1\n")
    token_index = parser_mod._build_declaration_token_index(tokens)

    assert (
        parser_mod._declaration_token_index(
            source_tokens=tokens,
            start_line=1,
            start_col=0,
            declaration_token="async",
            source_token_index=token_index,
        )
        == 0
    )


def test_declaration_helpers_cover_async_found_tokens_and_eof_scan() -> None:
    async_node = ast.parse(
        """
async def demo():
    return 1
"""
    ).body[0]
    assert isinstance(async_node, ast.AsyncFunctionDef)
    assert parser_mod._declaration_token_name(async_node) == "async"

    tokens = parser_mod._source_tokens("def demo():\n    return 1\n")
    assert (
        parser_mod._declaration_token_index(
            source_tokens=tokens,
            start_line=1,
            start_col=0,
            declaration_token="def",
        )
        == 0
    )

    nested_tokens = parser_mod._source_tokens(
        "def demo(arg: tuple[int, int]) -> tuple[int, int]:\n    return arg\n"
    )
    assert (
        parser_mod._scan_declaration_colon_line(
            source_tokens=nested_tokens,
            start_index=0,
        )
        == 1
    )

    default_tokens = parser_mod._source_tokens(
        "def demo(arg=(1, [2])):\n    return arg\n"
    )
    assert (
        parser_mod._scan_declaration_colon_line(
            source_tokens=default_tokens,
            start_index=0,
        )
        == 1
    )

    eof_tokens = (
        tokenize.TokenInfo(tokenize.NAME, "def", (1, 0), (1, 3), "def demo("),
        tokenize.TokenInfo(tokenize.NAME, "demo", (1, 4), (1, 8), "def demo("),
        tokenize.TokenInfo(tokenize.OP, "(", (1, 8), (1, 9), "def demo("),
    )
    assert (
        parser_mod._scan_declaration_colon_line(
            source_tokens=eof_tokens,
            start_index=0,
        )
        is None
    )

    unmatched_close_tokens = (
        tokenize.TokenInfo(tokenize.NAME, "def", (1, 0), (1, 3), "def demo)"),
        tokenize.TokenInfo(tokenize.OP, ")", (1, 8), (1, 9), "def demo)"),
    )
    assert (
        parser_mod._scan_declaration_colon_line(
            source_tokens=unmatched_close_tokens,
            start_index=0,
        )
        is None
    )


def test_scan_declaration_colon_line_returns_none_when_header_is_incomplete() -> None:
    tokens = parser_mod._source_tokens("def broken\n")
    assert (
        parser_mod._scan_declaration_colon_line(
            source_tokens=tokens,
            start_index=0,
        )
        is None
    )


def test_declaration_end_line_falls_back_without_tokens() -> None:
    node = ast.parse(
        """
class Demo:
    pass
"""
    ).body[0]
    assert isinstance(node, ast.ClassDef)
    assert parser_mod._declaration_end_line(node, source_tokens=()) == 2


def test_declaration_end_line_returns_zero_for_invalid_start_line() -> None:
    node = ast.parse(
        """
def broken():
    return 1
"""
    ).body[0]
    assert isinstance(node, ast.FunctionDef)
    node.lineno = 0
    assert parser_mod._declaration_end_line(node, source_tokens=()) == 0


def test_declaration_fallback_helpers_cover_empty_and_same_line_bodies() -> None:
    empty_body_node = ast.parse(
        """
def demo():
    return 1
"""
    ).body[0]
    assert isinstance(empty_body_node, ast.FunctionDef)
    empty_body_node.body = []
    assert parser_mod._fallback_declaration_end_line(empty_body_node, start_line=2) == 2

    inline_body_node = ast.parse(
        """
def demo():
    return 1
"""
    ).body[0]
    assert isinstance(inline_body_node, ast.FunctionDef)
    inline_body_node.body[0].lineno = 2
    assert (
        parser_mod._fallback_declaration_end_line(inline_body_node, start_line=2) == 2
    )

    no_colon_tokens = (
        tokenize.TokenInfo(tokenize.NAME, "def", (2, 0), (2, 3), "def demo"),
        tokenize.TokenInfo(tokenize.NAME, "demo", (2, 4), (2, 8), "def demo"),
    )
    assert (
        parser_mod._declaration_end_line(
            inline_body_node,
            source_tokens=no_colon_tokens,
        )
        == 2
    )


def test_init_function_is_ignored_for_blocks() -> None:
    src = """
class A:
    def __init__(self):
        x = 1
        y = 2
        z = 3
        w = 4
"""

    units, blocks, segments = extract_units_from_source(
        source=src,
        filepath="x.py",
        module_name="mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )

    assert len(units) == 1
    assert blocks == []
    assert segments == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            """
def foo():
    a = 1
    return a
""",
            id="without_directives",
        ),
        pytest.param(
            """
# codeclone: ignore[dead-code]
def foo():
    a = 1
    return a
""",
            id="leading_only_directive",
        ),
    ],
)
def test_extract_units_skips_suppression_tokenization_without_inline_directives(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    monkeypatch.setattr(
        module_walk_mod,
        "_source_tokens",
        lambda _source: (_ for _ in ()).throw(
            AssertionError("_source_tokens should not be called")
        ),
    )

    units, blocks, segments = extract_units_from_source(
        source=source,
        filepath="x.py",
        module_name="mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )

    assert len(units) == 1
    assert blocks == []
    assert segments == []


def test_extract_units_tokenizes_when_inline_suppressions_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original_source_tokens = cast(
        "Callable[[str], tuple[tokenize.TokenInfo, ...]]",
        module_walk_mod.__dict__["_source_tokens"],
    )

    def _record_tokens(source: str) -> tuple[tokenize.TokenInfo, ...]:
        nonlocal calls
        calls += 1
        return original_source_tokens(source)

    monkeypatch.setattr(module_walk_mod, "_source_tokens", _record_tokens)

    units, blocks, segments = extract_units_from_source(
        source="""
def foo(  # codeclone: ignore[dead-code]
    value: int,
) -> int:
    return value
""",
        filepath="x.py",
        module_name="mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )

    assert calls == 1
    assert len(units) == 1
    assert blocks == []
    assert segments == []


def test_extract_units_can_skip_structural_findings() -> None:
    src = """
def foo(x):
    a = 1
    b = 2
    c = 3
    d = 4
    e = 5
    if x == 1:
        log("a")
        value = x + 1
        return value
    elif x == 2:
        log("b")
        value = x + 2
        return value
    return a + b + c + d + e
"""
    _units, _blocks, _segments, _source_stats, _file_metrics, sf = _extract_source(
        source=src,
        filepath="x.py",
        module_name="mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
        collect_structural_findings=False,
    )
    assert sf == []


def test_parse_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def _boom(_timeout_s: int) -> Iterator[None]:
        raise parser_mod._ParseTimeoutError("AST parsing timeout")
        if False:
            yield

    monkeypatch.setattr(parser_mod, "_parse_limits", _boom)

    with pytest.raises(ParseError, match="AST parsing timeout"):
        parser_mod._parse_with_limits("x = 1", 1)


def test_parse_limits_no_timeout() -> None:
    with parser_mod._parse_limits(0):
        tree = parser_mod._parse_with_limits("x = 1", 0)
    assert tree is not None


def _patch_posix_parse_limits(
    monkeypatch: pytest.MonkeyPatch, resource_module: object
) -> None:
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(signal, "getsignal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal, "signal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal, "setitimer", lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, "resource", resource_module)


def test_parse_limits_resource_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DummyResource:
        RLIMIT_CPU = 0
        RLIM_INFINITY = 10**9

        @staticmethod
        def getrlimit(_key: int) -> tuple[int, int]:
            raise RuntimeError("nope")

        @staticmethod
        def setrlimit(_key: int, _val: tuple[int, int]) -> None:
            return None

    _patch_posix_parse_limits(monkeypatch, _DummyResource)

    with parser_mod._parse_limits(1):
        tree = parser_mod._parse_with_limits("x = 1", 1)
    assert tree is not None


def test_parse_limits_never_lowers_hard_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []

    class _DummyResource:
        RLIMIT_CPU = 0
        RLIM_INFINITY = 10**9

        @staticmethod
        def getrlimit(_key: int) -> tuple[int, int]:
            return (_DummyResource.RLIM_INFINITY, _DummyResource.RLIM_INFINITY)

        @staticmethod
        def setrlimit(_key: int, val: tuple[int, int]) -> None:
            calls.append(val)
            # Simulate a system where changing hard limit would fail.
            assert val[1] == _DummyResource.RLIM_INFINITY

    _patch_posix_parse_limits(monkeypatch, _DummyResource)

    with parser_mod._parse_limits(5):
        pass

    assert calls
    # First set lowers only soft limit, hard stays unchanged.
    assert calls[0] == (5, _DummyResource.RLIM_INFINITY)
    # Final restore returns to original limits.
    assert calls[-1] == (
        _DummyResource.RLIM_INFINITY,
        _DummyResource.RLIM_INFINITY,
    )


def test_parse_limits_accounts_for_consumed_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []

    class _DummyUsage:
        ru_utime = 7.2
        ru_stime = 0.3

    class _DummyResource:
        RLIMIT_CPU = 0
        RLIM_INFINITY = 10**9
        RUSAGE_SELF = 0

        @staticmethod
        def getrlimit(_key: int) -> tuple[int, int]:
            return (_DummyResource.RLIM_INFINITY, _DummyResource.RLIM_INFINITY)

        @staticmethod
        def setrlimit(_key: int, val: tuple[int, int]) -> None:
            calls.append(val)

        @staticmethod
        def getrusage(_who: int) -> _DummyUsage:
            return _DummyUsage()

    _patch_posix_parse_limits(monkeypatch, _DummyResource)

    with parser_mod._parse_limits(5):
        pass

    assert calls
    # ceil(7.5) + timeout(5) == 13
    assert calls[0] == (13, _DummyResource.RLIM_INFINITY)
    assert calls[-1] == (
        _DummyResource.RLIM_INFINITY,
        _DummyResource.RLIM_INFINITY,
    )


def test_parse_limits_raises_too_low_soft_limit_for_consumed_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []

    class _DummyUsage:
        ru_utime = 10.0
        ru_stime = 0.0

    class _DummyResource:
        RLIMIT_CPU = 0
        RLIM_INFINITY = 10**9
        RUSAGE_SELF = 0

        @staticmethod
        def getrlimit(_key: int) -> tuple[int, int]:
            return (2, 20)

        @staticmethod
        def setrlimit(_key: int, val: tuple[int, int]) -> None:
            calls.append(val)

        @staticmethod
        def getrusage(_who: int) -> _DummyUsage:
            return _DummyUsage()

    _patch_posix_parse_limits(monkeypatch, _DummyResource)

    with parser_mod._parse_limits(5):
        pass

    # Raised from 2 to ceil(10)+5 to avoid immediate SIGXCPU.
    assert calls[0] == (15, 20)
    assert calls[-1] == (2, 20)


def test_parse_limits_uses_finite_soft_limit_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []

    class _DummyResource:
        RLIMIT_CPU = 0
        RLIM_INFINITY = 10**9

        @staticmethod
        def getrlimit(_key: int) -> tuple[int, int]:
            return (20, 20)

        @staticmethod
        def setrlimit(_key: int, val: tuple[int, int]) -> None:
            calls.append(val)

    _patch_posix_parse_limits(monkeypatch, _DummyResource)

    with parser_mod._parse_limits(5):
        pass

    # Finite soft limits are never lowered.
    assert calls[0] == (20, 20)
    assert calls[-1] == (20, 20)


def test_parse_limits_restore_failure_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _DummyResource:
        RLIMIT_CPU = 0
        RLIM_INFINITY = 10**9
        _calls = 0

        @staticmethod
        def getrlimit(_key: int) -> tuple[int, int]:
            return (_DummyResource.RLIM_INFINITY, _DummyResource.RLIM_INFINITY)

        @staticmethod
        def setrlimit(_key: int, _val: tuple[int, int]) -> None:
            _DummyResource._calls += 1
            if _DummyResource._calls >= 2:
                raise RuntimeError("restore denied")

    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(signal, "getsignal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal, "signal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal, "setitimer", lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, "resource", _DummyResource)

    # Should not raise even if restoring old limits fails.
    with parser_mod._parse_limits(5):
        pass


def test_resolve_import_observation_absolute_and_relative() -> None:
    identity, registry = module_registry_context(
        filepath="root/mod/sub.py",
        module_name="root.mod.sub",
    )
    absolute = ast.ImportFrom(module="pkg.util", names=[], level=0)
    assert (
        module_walk_mod.resolve_import_observation(
            identity, absolute, registry
        ).resolved_target
        == "pkg.util"
    )

    relative = ast.ImportFrom(module="helpers", names=[], level=1)
    assert (
        module_walk_mod.resolve_import_observation(
            identity, relative, registry
        ).resolved_target
        == "root.mod.helpers"
    )

    relative_no_module = ast.ImportFrom(module=None, names=[], level=2)
    assert (
        module_walk_mod.resolve_import_observation(
            identity, relative_no_module, registry
        ).resolved_target
        == "root"
    )


@pytest.mark.parametrize(
    (
        "filepath",
        "module_name",
        "level",
        "requested_module",
        "requested_names",
        "inventory_modules",
        "expected_targets",
        "expected_resolutions",
    ),
    (
        (
            "pkg/__init__.py",
            "pkg",
            1,
            None,
            ("x",),
            ("pkg.x",),
            ("pkg", "pkg.x"),
            ("analyzed", "analyzed"),
        ),
        (
            "pkg/__init__.py",
            "pkg",
            1,
            "sibling",
            ("value",),
            ("pkg.sibling",),
            ("pkg.sibling",),
            ("analyzed",),
        ),
        (
            # A relative star import expands only the named siblings; the
            # `*` alias itself contributes no expansion row.
            "pkg/__init__.py",
            "pkg",
            1,
            None,
            ("*", "x"),
            ("pkg.x",),
            ("pkg", "pkg.x"),
            ("analyzed", "analyzed"),
        ),
        (
            "pkg/mod.py",
            "pkg.mod",
            1,
            None,
            ("x",),
            ("pkg.x",),
            ("pkg", "pkg.x"),
            ("external", "analyzed"),
        ),
        (
            "pkg/mod.py",
            "pkg.mod",
            1,
            "sibling",
            ("value",),
            ("pkg.sibling",),
            ("pkg.sibling",),
            ("analyzed",),
        ),
        (
            "pkg/mod.py",
            "pkg.mod",
            2,
            None,
            ("outside",),
            (),
            (None,),
            ("unresolved_relative",),
        ),
        (
            "scripts/tool.py",
            None,
            1,
            "sibling",
            ("value",),
            (),
            (None,),
            ("unresolved_relative",),
        ),
        (
            "tool.py",
            "tool",
            1,
            None,
            ("sibling",),
            (),
            (None,),
            ("unresolved_relative",),
        ),
    ),
)
def test_relative_import_decision_table(
    filepath: str,
    module_name: str | None,
    level: int,
    requested_module: str | None,
    requested_names: tuple[str, ...],
    inventory_modules: tuple[str, ...],
    expected_targets: tuple[str | None, ...],
    expected_resolutions: tuple[str, ...],
) -> None:
    identity, registry = module_registry_context(
        filepath=filepath,
        module_name=module_name,
        inventory_modules=inventory_modules,
    )
    node = ast.ImportFrom(
        module=requested_module,
        names=[ast.alias(name=name) for name in requested_names],
        level=level,
    )

    observations = module_walk_mod._import_from_observations(
        identity,
        node,
        registry,
    )

    assert tuple(item.resolved_target for item in observations) == expected_targets
    assert tuple(item.resolution for item in observations) == expected_resolutions


def test_import_resolution_distinguishes_excluded_internal_target() -> None:
    identity, registry = module_registry_context(
        filepath="pkg/live.py",
        module_name="pkg.live",
        known_internal_modules=("migrations.old",),
    )
    observation = module_walk_mod.resolve_import_observation(
        identity,
        ast.ImportFrom(
            module="migrations.old",
            names=[ast.alias(name="upgrade")],
            level=0,
        ),
        registry,
    )

    assert observation.resolution == "known_internal_not_analyzed"
    assert observation.resolved_target == "migrations.old"


def test_non_importable_source_dependencies_remain_path_keyed() -> None:
    _tree, _collector, walk = _collect_module_walk(
        "from .sibling import value",
        filepath="scripts/not-a-module.py",
        module_name=None,
    )

    assert walk.module_deps[0].source == "scripts/not-a-module.py"
    assert walk.module_deps[0].target == ""
    assert walk.module_deps[0].resolution == "unresolved_relative"


def test_flat_and_src_relative_fixture_graphs_match_identity_golden() -> None:
    fixture_root = Path("tests/fixtures/module_identity/relative")

    def _dependency_rows(
        root: Path,
        *,
        source_roots: tuple[str, ...],
    ) -> list[dict[str, object]]:
        registry = build_test_module_registry(
            root=root,
            source_roots=source_roots,
        )
        rows: list[dict[str, object]] = []
        for relative_path, entry in registry.entries_by_path.items():
            tree = ast.parse((root / relative_path).read_text("utf-8"))
            collector = QualnameCollector()
            collector.visit(tree)
            walk = module_walk_mod._collect_module_walk_data(
                tree=tree,
                source=entry.identity,
                registry=registry,
                collector=collector,
                collect_referenced_names=True,
            )
            rows.extend(
                {
                    "inventory_expansion": dep.inventory_expansion,
                    "resolution": dep.resolution,
                    "source": dep.source,
                    "target": dep.target,
                }
                for dep in walk.module_deps
            )
        return sorted(
            rows,
            key=lambda row: (
                str(row["source"]),
                str(row["target"]),
                bool(row["inventory_expansion"]),
            ),
        )

    expected = json.loads(
        (fixture_root / "golden_dependencies.json").read_text("utf-8")
    )
    flat = _dependency_rows(fixture_root / "flat", source_roots=(".",))
    src = _dependency_rows(fixture_root / "src_layout", source_roots=("src",))

    assert flat == expected
    assert src == expected


def test_collect_module_walk_data_imports_and_references() -> None:
    _tree, _collector, walk = _collect_module_walk(
        """
import os as operating_system
import json
from .pkg import utils
from .. import parent

value = obj.attr
foo()
obj.method()
""".strip(),
        module_name="root.mod.sub",
    )
    assert walk.import_names == frozenset({"operating_system", "json", "root"})
    assert walk.module_deps == (
        ModuleDep(
            source="root.mod.sub",
            target="json",
            import_type="import",
            line=2,
            requested_module="json",
            candidate_targets=("json",),
        ),
        ModuleDep(
            source="root.mod.sub",
            target="os",
            import_type="import",
            line=1,
            requested_module="os",
            candidate_targets=("os",),
        ),
        ModuleDep(
            source="root.mod.sub",
            target="root",
            import_type="from_import",
            line=4,
            level=2,
            requested_names=("parent",),
            candidate_targets=("root",),
        ),
        ModuleDep(
            source="root.mod.sub",
            target="root.mod.pkg",
            import_type="from_import",
            line=3,
            level=1,
            requested_module="pkg",
            requested_names=("utils",),
            candidate_targets=("root.mod.pkg",),
        ),
    )
    assert walk.referenced_names == frozenset({"obj", "attr", "foo", "method"})


def test_collect_module_walk_data_edge_branches() -> None:
    _tree, _collector, walk = _collect_module_walk(
        "from .... import parent",
        module_name="pkg.mod",
    )
    assert walk.import_names == frozenset()
    assert walk.module_deps == (
        ModuleDep(
            source="pkg.mod",
            target="",
            import_type="from_import",
            line=1,
            resolution="unresolved_relative",
            level=4,
            requested_names=("parent",),
        ),
    )
    assert walk.referenced_names == frozenset()

    _lambda_tree, _lambda_collector, lambda_walk = _collect_module_walk(
        "(lambda x: x)(1)",
        module_name="pkg.mod",
    )
    assert lambda_walk.referenced_names == frozenset({"x"})


def test_collect_module_walk_data_without_referenced_name_collection() -> None:
    _tree, _collector, walk = _collect_module_walk(
        """
import os as operating_system
from .pkg import utils
from .... import parent
""".strip(),
        module_name="root.mod.sub",
        collect_referenced_names=False,
    )
    assert walk.import_names == frozenset({"operating_system", "root"})
    assert walk.module_deps == (
        ModuleDep(
            source="root.mod.sub",
            target="",
            import_type="from_import",
            line=3,
            resolution="unresolved_relative",
            level=4,
            requested_names=("parent",),
        ),
        ModuleDep(
            source="root.mod.sub",
            target="os",
            import_type="import",
            line=1,
            requested_module="os",
            candidate_targets=("os",),
        ),
        ModuleDep(
            source="root.mod.sub",
            target="root.mod.pkg",
            import_type="from_import",
            line=2,
            level=1,
            requested_module="pkg",
            requested_names=("utils",),
            candidate_targets=("root.mod.pkg",),
        ),
    )
    assert walk.referenced_names == frozenset()


def test_module_walk_helpers_cover_import_and_reference_branches() -> None:
    state = module_walk_mod._ModuleWalkState()
    identity, registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )
    import_node = cast(
        ast.Import,
        ast.parse("import typing_extensions as te").body[0],
    )
    module_walk_mod._collect_import_node(
        node=import_node,
        source=identity,
        registry=registry,
        state=state,
        collect_referenced_names=False,
    )
    assert "te" in state.import_names
    assert "te" in state.protocol_module_aliases
    assert state.imported_module_aliases == {}

    import_from_node = cast(
        ast.ImportFrom,
        ast.parse("from typing import Protocol as Proto, Thing as Alias").body[0],
    )
    module_walk_mod._collect_import_from_node(
        node=import_from_node,
        source=identity,
        registry=registry,
        state=state,
        collect_referenced_names=True,
    )
    assert "Proto" in state.protocol_symbol_aliases
    assert state.imported_symbol_bindings["Alias"] == {"typing:Thing"}

    unresolved_import = ast.ImportFrom(
        module=None,
        names=[ast.alias(name="parent", asname=None)],
        level=4,
    )
    module_walk_mod._collect_import_from_node(
        node=unresolved_import,
        source=identity,
        registry=registry,
        state=state,
        collect_referenced_names=True,
    )
    assert "parent" not in state.imported_symbol_bindings

    name_node = cast(ast.Name, ast.parse("value", mode="eval").body)
    attr_node = cast(ast.Attribute, ast.parse("obj.attr", mode="eval").body)
    module_walk_mod._collect_load_reference_node(node=name_node, state=state)
    module_walk_mod._collect_load_reference_node(node=attr_node, state=state)
    module_walk_mod._collect_load_reference_node(
        node=cast(ast.Constant, ast.parse("1", mode="eval").body),
        state=state,
    )
    assert "value" in state.referenced_names
    assert "attr" in state.referenced_names


def test_dotted_expr_protocol_detection_and_runtime_candidate_edges() -> None:
    dotted_expr = ast.parse("pkg.helpers.decorate", mode="eval").body
    assert module_walk_mod._dotted_expr_name(dotted_expr) == "pkg.helpers.decorate"
    assert (
        module_walk_mod._dotted_expr_name(ast.parse("custom()", mode="eval").body)
        is None
    )

    protocol_source = """
import typing_extensions as te

class A(te.Protocol):
    pass

class B(te.Protocol[int]):
    pass
""".strip()
    tree, _collector, walk = _collect_module_walk(
        protocol_source,
        module_name="pkg.mod",
    )
    protocol_symbol_aliases = walk.protocol_symbol_aliases
    protocol_module_aliases = walk.protocol_module_aliases
    assert "te" in protocol_module_aliases
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    class_a, class_b = classes
    assert module_walk_mod._is_protocol_class(
        class_a,
        protocol_symbol_aliases=protocol_symbol_aliases,
        protocol_module_aliases=protocol_module_aliases,
    )
    assert module_walk_mod._is_protocol_class(
        class_b,
        protocol_symbol_aliases=protocol_symbol_aliases,
        protocol_module_aliases=protocol_module_aliases,
    )

    runtime_candidate = ast.parse(
        """
@trace()
@custom
@overload
def f(x):
    return x
""".strip()
    ).body[0]
    assert isinstance(runtime_candidate, ast.FunctionDef)
    assert module_walk_mod._is_non_runtime_candidate(runtime_candidate)

    dynamic_decorator_candidate = ast.parse(
        """
@(lambda fn: fn)
def dynamic():
    return None
""".strip()
    ).body[0]
    assert isinstance(dynamic_decorator_candidate, ast.FunctionDef)
    assert not module_walk_mod._is_non_runtime_candidate(dynamic_decorator_candidate)

    dotted_overload_candidate = ast.parse(
        """
@typing.overload
def typed(value):
    return value
""".strip()
    ).body[0]
    assert isinstance(dotted_overload_candidate, ast.FunctionDef)
    assert module_walk_mod._is_non_runtime_candidate(dotted_overload_candidate)


def test_resolve_referenced_qualnames_covers_module_class_and_attr_branches() -> None:
    src = """
from pkg.runtime import handler as imported_handler
import pkg.helpers as helpers

class Service:
    def hook(self) -> int:
        return 1

value = imported_handler()
decorator = helpers.decorate
method = Service.hook
unknown = Missing.hook
dynamic = factory().attr
"""
    tree, collector = _parse_tree_and_collector(src)
    state = module_walk_mod._ModuleWalkState()
    identity, registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            module_walk_mod._collect_import_node(
                node=node,
                source=identity,
                registry=registry,
                state=state,
                collect_referenced_names=True,
            )
        elif isinstance(node, ast.ImportFrom):
            module_walk_mod._collect_import_from_node(
                node=node,
                source=identity,
                registry=registry,
                state=state,
                collect_referenced_names=True,
            )
        else:
            module_walk_mod._collect_load_reference_node(node=node, state=state)

    resolved = module_walk_mod._resolve_referenced_qualnames(
        module_name="pkg.mod",
        collector=collector,
        state=state,
    )
    assert "pkg.runtime:handler" in resolved
    assert "pkg.helpers:decorate" in resolved
    assert "pkg.mod:Service.hook" in resolved
    assert all("Missing.hook" not in qualname for qualname in resolved)
    assert all(not qualname.endswith(":attr") for qualname in resolved)


def test_collect_referenced_qualnames_edge_cases() -> None:
    src = """
from .... import hidden
from pkg.runtime import *
import pkg.helpers as helpers

class Service:
    def hook(self) -> int:
        return 1

value = helpers.tools.decorate(1)
handler = Service.hook
    """
    _tree, _collector, walk = _collect_module_walk(src)
    assert "pkg.mod:Service.hook" in walk.referenced_qualnames
    assert "pkg.helpers:tools" in walk.referenced_qualnames
    assert "pkg.helpers:decorate" not in walk.referenced_qualnames


def test_extractor_private_helper_branches_cover_invalid_protocol_and_declarations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expr = ast.Attribute(
        value=ast.Call(
            func=ast.Name(id="factory", ctx=ast.Load()),
            args=[],
            keywords=[],
        ),
        attr="method",
        ctx=ast.Load(),
    )
    assert module_walk_mod._dotted_expr_name(expr) is None

    protocol_class = ast.parse(
        """
class Demo(Unknown, alias.Protocol):
    pass
"""
    ).body[0]
    assert isinstance(protocol_class, ast.ClassDef)
    assert (
        module_walk_mod._is_protocol_class(
            protocol_class,
            protocol_symbol_aliases=frozenset({"Protocol"}),
            protocol_module_aliases=frozenset({"typing"}),
        )
        is False
    )

    bad_span_node = ast.parse(
        """
def demo():
    return 1
"""
    ).body[0]
    assert isinstance(bad_span_node, ast.FunctionDef)
    bad_span_node.lineno = 3
    bad_span_node.end_lineno = 2
    assert units_mod._unit_shape(bad_span_node) is None

    _, missing_method_collector, missing_method_walk = _collect_module_walk(
        """
class Service:
    def real(self) -> int:
        return 1

handler = Service.missing
"""
    )
    assert "pkg.mod:Service.missing" not in missing_method_walk.referenced_qualnames
    assert missing_method_collector.class_nodes[0][0] == "Service"

    _, declaration_collector = _parse_tree_and_collector(
        """
class Demo:
    def work(self) -> int:
        return 1
"""
    )
    declaration_collector.units[0][1].end_lineno = 0
    declaration_collector.class_nodes[0][1].end_lineno = 0
    assert (
        module_walk_mod._collect_declaration_targets(
            filepath="pkg/mod.py",
            module_name="pkg.mod",
            collector=declaration_collector,
        )
        == ()
    )

    suppression_source = """
def demo():  # codeclone: ignore[dead-code]
    return 1
"""
    _, suppression_collector = _parse_tree_and_collector(suppression_source)
    monkeypatch.setattr(module_walk_mod, "_source_tokens", lambda _source: ())
    suppression_index = module_walk_mod._build_suppression_index_for_source(
        source=suppression_source,
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        collector=suppression_collector,
    )
    assert tuple(suppression_index.values()) == (("dead-code",),)


def test_extract_stats_drops_referenced_names_for_test_filepaths() -> None:
    src = """
from pkg.mod import live

live()
"""
    _, _, _, _, test_metrics, _ = _extract_source(
        source=src,
        filepath="pkg/tests/test_usage.py",
        module_name="pkg.tests.test_usage",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    _, _, _, _, regular_metrics, _ = _extract_source(
        source=src,
        filepath="pkg/usage.py",
        module_name="pkg.usage",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )

    assert test_metrics.referenced_names == frozenset()
    assert "live" in regular_metrics.referenced_names


def test_extract_stats_keeps_class_cohesion_metrics_after_unit_fingerprinting() -> None:
    src = """
class Service:
    def __init__(self):
        self.path = "x"
        self.data = {}

    def load(self):
        if self.path:
            return self.data
        return {}

    def save(self):
        if self.path:
            self.data["saved"] = True
        return self.data

    def verify(self):
        return bool(self.path) and bool(self.data)

    @staticmethod
    def make():
        return Service()
"""
    _, _, _, _, file_metrics, _ = _extract_source(
        source=src,
        filepath="pkg/service.py",
        module_name="pkg.service",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )

    assert file_metrics.class_metrics == (
        ClassMetrics(
            qualname="pkg.service:Service",
            filepath="pkg/service.py",
            start_line=2,
            end_line=22,
            cbo=0,
            lcom4=2,
            method_count=5,
            instance_var_count=2,
            risk_coupling="low",
            risk_cohesion="medium",
        ),
    )


def test_extract_protocol_class_excludes_stub_methods_from_lcom4() -> None:
    src = """
from typing import Protocol

class Reader(Protocol):
    def read(self) -> str: ...

    def write(self, data: str) -> None: ...

    def close(self) -> None: ...
"""
    _, _, _, _, file_metrics, _ = _extract_source(
        source=src,
        filepath="pkg/reader.py",
        module_name="pkg.reader",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )

    assert file_metrics.class_metrics == (
        ClassMetrics(
            qualname="pkg.reader:Reader",
            filepath="pkg/reader.py",
            start_line=4,
            end_line=9,
            cbo=0,
            lcom4=1,
            method_count=3,
            instance_var_count=0,
            risk_coupling="low",
            risk_cohesion="low",
            # typing.Protocol is outside the analysis root, so the rule-3
            # opacity flag is set. It changes no dead-code verdict here:
            # protocol stub methods are already non-actionable by their own
            # rule, which runs before the abstention branch.
            base_names=("Protocol",),
            has_unresolved_external_base=True,
        ),
    )


@pytest.mark.parametrize(
    ("source", "filepath", "module_name", "lcom4", "method_count", "risk"),
    (
        pytest.param(
            """
from pydantic import BaseModel, field_validator

class Config(BaseModel):
    name: str
    value: int

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: int) -> int:
        return value

    def describe(self) -> str:
        return self.name
""".strip(),
            "pkg/config.py",
            "pkg.config",
            1,
            3,
            "low",
            id="field_validators_ignored",
        ),
        pytest.param(
            """
from pydantic import BaseModel, computed_field

class Item(BaseModel):
    first: str
    second: str

    @computed_field
    @property
    def left(self) -> str:
        return self.first

    @computed_field
    @property
    def right(self) -> str:
        return self.second

    def unrelated(self) -> int:
        return 1
""".strip(),
            "pkg/item.py",
            "pkg.item",
            3,
            3,
            "medium",
            id="computed_field_in_graph",
        ),
    ),
)
def test_extract_pydantic_cohesion_exclusions(
    source: str,
    filepath: str,
    module_name: str,
    lcom4: int,
    method_count: int,
    risk: str,
) -> None:
    _, _, _, _, file_metrics, _ = _extract_source(
        source=source,
        filepath=filepath,
        module_name=module_name,
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    assert len(file_metrics.class_metrics) == 1
    metric = file_metrics.class_metrics[0]
    assert metric.lcom4 == lcom4
    assert metric.method_count == method_count
    assert metric.risk_cohesion == risk


def test_extract_ignores_dynamic_pydantic_decorator_for_cohesion() -> None:
    source = """
import pydantic
from pydantic import BaseModel

class Item(BaseModel):
    value: int

    @getattr(pydantic, "field_validator")("value")
    @classmethod
    def validate_value(cls, value: int) -> int:
        return value

    def used(self) -> int:
        return self.value
""".strip()
    _, _, _, _, file_metrics, _ = _extract_source(
        source=source,
        filepath="pkg/item.py",
        module_name="pkg.item",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    assert len(file_metrics.class_metrics) == 1
    assert file_metrics.class_metrics[0].method_count == 2
    # Dynamic decorator names are not resolved; validator stays in the cohesion graph.
    assert file_metrics.class_metrics[0].lcom4 == 2


def test_dead_code_marks_symbol_dead_when_referenced_only_by_tests() -> None:
    src_prod = """
def orphan():
    return 1
"""
    src_test = """
from pkg.mod import orphan

def test_orphan_usage():
    assert orphan() == 1
"""

    _, _, _, _, prod_metrics, _ = _extract_source(
        source=src_prod,
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    _, _, _, _, test_metrics, _ = _extract_source(
        source=src_test,
        filepath="pkg/tests/test_mod.py",
        module_name="pkg.tests.test_mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )

    dead = find_unused(
        definitions=prod_metrics.dead_candidates,
        referenced_names=(
            prod_metrics.referenced_names | test_metrics.referenced_names
        ),
    )
    assert dead and dead[0].qualname == "pkg.mod:orphan"


def test_dead_code_distinguishes_test_only_reference_from_unreferenced() -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "liveness_policy"
    ground_truth = json.loads((fixture_root / "ground_truth.json").read_text())
    expected_by_symbol = {
        case["symbol"]: case["expected"]
        for case in ground_truth["cases"]
        if case["path"].startswith("liveprobe/")
    }
    # The whole liveprobe acceptance set, not just the production module.
    assert len(expected_by_symbol) == 7

    metrics_by_module: dict[str, FileMetrics] = {}
    for relative_path, module_name in (
        ("liveprobe/src/liveprobe/__init__.py", "liveprobe"),
        ("liveprobe/src/liveprobe/api.py", "liveprobe.api"),
        ("liveprobe/src/liveprobe/framework.py", "liveprobe.framework"),
        ("liveprobe/src/liveprobe/production.py", "liveprobe.production"),
        ("liveprobe/src/liveprobe/main.py", "liveprobe.main"),
        ("liveprobe/tests/test_production.py", "liveprobe.tests.test_production"),
    ):
        _, _, _, _, metrics, _ = _extract_source(
            source=(fixture_root / relative_path).read_text(),
            filepath=relative_path,
            module_name=module_name,
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
        )
        metrics_by_module[module_name] = metrics

    test_module = metrics_by_module["liveprobe.tests.test_production"]
    dead = find_unused(
        definitions=tuple(
            candidate
            for metrics in metrics_by_module.values()
            for candidate in metrics.dead_candidates
        ),
        referenced_names=frozenset().union(
            *(metrics.referenced_names for metrics in metrics_by_module.values())
        ),
        referenced_qualnames=frozenset().union(
            *(metrics.referenced_qualnames for metrics in metrics_by_module.values())
        ),
        function_relationship_facts=(
            *reversed(test_module.function_relationship_facts),
            *test_module.function_relationship_facts,
        ),
    )
    dead_by_symbol = {item.qualname.rsplit(":", 1)[-1]: item for item in dead}

    # All seven ground-truth symbols, live and dead alike.
    assert {symbol: symbol not in dead_by_symbol for symbol in expected_by_symbol} == {
        symbol: expected["live"] for symbol, expected in expected_by_symbol.items()
    }

    for symbol, expected in expected_by_symbol.items():
        if expected["live"]:
            continue
        assert dead_by_symbol[symbol].reason == expected["reason"]

    test_only = dead_by_symbol["test_only_helper"]
    assert test_only.reason == "test_only_reference"
    assert test_only.test_reference_sources == (
        "liveprobe.tests.test_production:test_helper_for_historical_behavior",
    )
    assert dead_by_symbol["unused_private"].test_reference_sources == ()
    assert dead_by_symbol["run"].test_reference_sources == ()
    # Declared generation of the liveness policy. It stays "2": that
    # generation was introduced after the last release and has never
    # shipped, so this wave refined its definition in place rather than
    # spending a number no artifact carries.
    assert contracts.LIVENESS_POLICY_VERSION == "2"


def test_extraction_uses_module_identity_for_test_named_package_trees() -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "source_kind"
    source = """
def helper() -> str:
    return "ready"

result = helper()
"""
    package_path = "src/example/testing/helpers.py"
    package_registry = build_test_module_registry(
        root=fixture_root / "in_package",
        source_roots=("src",),
    )
    *_, package_metrics, _findings = _extract_source(
        source=source,
        filepath=package_path,
        module_name="example.testing.helpers",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
        module_registry=package_registry,
    )
    assert "helper" in package_metrics.referenced_names

    test_path = "testing/case.py"
    test_registry = build_test_module_registry(root=fixture_root / "repo_root")
    *_, test_metrics, _findings = _extract_source(
        source=source,
        filepath=test_path,
        module_name="testing.helpers",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
        module_registry=test_registry,
    )
    assert test_metrics.referenced_names == frozenset()


def test_package_export_chain_roots_only_exported_symbols() -> None:
    """The __all__ / package re-export chain is owned by the module walk.

    A symbol exported only through the package ``__init__`` chain, with no
    other reference anywhere, must come out live; its non-exported sibling in
    the same module must stay dead. Public methods of an exported class are
    deliberately NOT rooted here - that extension is owned by
    ``codeclone.core.entrypoints`` and pinned by its own contract test.
    """
    fixture_root = Path(__file__).parent / "fixtures" / "liveness_policy"
    ground_truth = json.loads((fixture_root / "ground_truth.json").read_text())
    registry = build_test_module_registry(root=fixture_root)

    for package_module, api_path, api_module in (
        ("distillations", "distillations/api.py", "distillations.api"),
        (
            "distillations_renamed",
            "distillations_renamed/api.py",
            "distillations_renamed.api",
        ),
    ):
        expected_by_symbol = {
            case["symbol"]: case["expected"]
            for case in ground_truth["cases"]
            if case["path"] == api_path
        }
        referenced_names: set[str] = set()
        referenced_qualnames: set[str] = set()
        dead_candidates: list[DeadCandidate] = []
        for relative_path, module_name in (
            (f"{package_module}/__init__.py", package_module),
            (api_path, api_module),
        ):
            _, _, _, _, metrics, _ = _extract_source(
                source=(fixture_root / relative_path).read_text(),
                filepath=relative_path,
                module_name=module_name,
                cfg=NormalizationConfig(),
                min_loc=1,
                min_stmt=1,
                module_registry=registry,
            )
            referenced_names |= set(metrics.referenced_names)
            referenced_qualnames |= set(metrics.referenced_qualnames)
            dead_candidates.extend(metrics.dead_candidates)

        dead = {
            item.qualname
            for item in find_unused(
                definitions=tuple(dead_candidates),
                referenced_names=frozenset(referenced_names),
                referenced_qualnames=frozenset(referenced_qualnames),
            )
        }

        exported_function = next(
            symbol
            for symbol, expected in expected_by_symbol.items()
            if expected["live"] and "." not in symbol
        )
        # Exported only through the package __init__ re-export + __all__.
        assert f"{api_module}:{exported_function}" in referenced_qualnames
        assert f"{api_module}:{exported_function}" not in dead
        # The non-exported sibling in the same module stays dead.
        non_exported = next(
            symbol
            for symbol, expected in expected_by_symbol.items()
            if not expected["live"]
        )
        assert f"{api_module}:{non_exported}" not in referenced_qualnames
        assert f"{api_module}:{non_exported}" in dead
        # Methods are not rooted by the walk; core.entrypoints owns that step.
        exported_method = next(
            symbol
            for symbol, expected in expected_by_symbol.items()
            if expected["live"] and "." in symbol
        )
        assert f"{api_module}:{exported_method}" not in referenced_qualnames


def test_external_decorators_define_liveness_roots() -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "liveness_policy"
    ground_truth = json.loads((fixture_root / "ground_truth.json").read_text())
    registry = build_test_module_registry(root=fixture_root)
    for relative_path, module_name in (
        ("distillations/roots.py", "distillations.roots"),
        ("distillations_renamed/roots.py", "distillations_renamed.roots"),
    ):
        expected_by_symbol = {
            case["symbol"]: case["expected"]
            for case in ground_truth["cases"]
            if case["path"] == relative_path and "live" in case["expected"]
        }
        source = (fixture_root / relative_path).read_text()
        _, _, _, _, metrics, _ = _extract_source(
            source=source,
            filepath=relative_path,
            module_name=module_name,
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
            module_registry=registry,
        )

        dead = find_unused(
            definitions=metrics.dead_candidates,
            referenced_names=metrics.referenced_names,
            referenced_qualnames=metrics.referenced_qualnames,
            runtime_reachability=metrics.runtime_reachability,
        )
        dead_symbols = {item.qualname.removeprefix(f"{module_name}:") for item in dead}
        tree, collector = _parse_tree_and_collector(source)
        walk = module_walk_mod._collect_module_walk_data(
            tree=tree,
            source=registry.entries_by_path[relative_path].identity,
            registry=registry,
            collector=collector,
            collect_referenced_names=True,
        )
        evidence_by_symbol = {
            qualname.removeprefix(f"{module_name}:"): reason
            for qualname, reason in walk.liveness_root_reasons
        }
        for symbol, expected in expected_by_symbol.items():
            assert (symbol not in dead_symbols) is expected["live"]
            if expected["reason"] == "external_decorator":
                assert evidence_by_symbol[symbol] == expected["reason"]


def test_explicit_reexport_is_a_life_proof_without_all() -> None:
    """Policy v2: `from x import y as y` alone livens its exact target.

    Two INDEPENDENT proofs exist for an imported symbol - the PEP 484
    explicit re-export spelling and static ``__all__`` membership - and
    either suffices. This pins the first proof standing alone: the package
    carries no ``__all__`` and the ``as``-same-name import in the package
    ``__init__`` is the only reference to ``fetch_snapshot``. Negative twins
    pin the boundaries: a renaming import (``as manifest_alias``) is NOT an
    explicit re-export by itself, and a ``TYPE_CHECKING``-guarded
    ``as``-same-name import must not liven a runtime symbol.
    """
    fixture_root = Path(__file__).parent / "fixtures" / "liveness_policy"
    registry = build_test_module_registry(root=fixture_root)
    referenced_names: set[str] = set()
    referenced_qualnames: set[str] = set()
    dead_candidates: list[DeadCandidate] = []
    for relative_path, module_name in (
        ("reexports/__init__.py", "reexports"),
        ("reexports/impl.py", "reexports.impl"),
    ):
        _, _, _, _, metrics, _ = _extract_source(
            source=(fixture_root / relative_path).read_text(),
            filepath=relative_path,
            module_name=module_name,
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
            module_registry=registry,
        )
        referenced_names |= set(metrics.referenced_names)
        referenced_qualnames |= set(metrics.referenced_qualnames)
        dead_candidates.extend(metrics.dead_candidates)

    dead = {
        item.qualname
        for item in find_unused(
            definitions=tuple(dead_candidates),
            referenced_names=frozenset(referenced_names),
            referenced_qualnames=frozenset(referenced_qualnames),
        )
    }
    # The explicit re-export livens its exact resolved target.
    assert "reexports.impl:fetch_snapshot" in referenced_qualnames
    assert "reexports.impl:fetch_snapshot" not in dead
    # A renaming import alone is not an explicit re-export.
    assert "reexports.impl:parse_manifest" in dead
    # A TYPE_CHECKING-guarded re-export must not liven a runtime symbol.
    assert "reexports.impl:annotate_frame" in dead
    # The never-imported sibling stays dead.
    assert "reexports.impl:orphan_helper" in dead


def test_dynamic_all_is_unresolved_not_a_heuristic() -> None:
    """A computed ``__all__`` proves nothing and never degrades to a guess.

    Static membership is the only ``__all__`` proof. A dynamically built
    ``__all__`` (here a call expression) stays UNRESOLVED: its would-be
    member gains no liveness from it. There is no abstention idiom for
    export chains - the symbol simply remains dead-eligible under the
    ordinary evidence rules.
    """
    fixture_root = Path(__file__).parent / "fixtures" / "liveness_policy"
    registry = build_test_module_registry(root=fixture_root)
    relative_path = "reexports/dynamic_registry.py"
    module_name = "reexports.dynamic_registry"
    _, _, _, _, metrics, _ = _extract_source(
        source=(fixture_root / relative_path).read_text(),
        filepath=relative_path,
        module_name=module_name,
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
        module_registry=registry,
    )
    dead = {
        item.qualname
        for item in find_unused(
            definitions=metrics.dead_candidates,
            referenced_names=metrics.referenced_names,
            referenced_qualnames=metrics.referenced_qualnames,
        )
    }
    assert f"{module_name}:would_be_member" not in metrics.referenced_qualnames
    assert f"{module_name}:would_be_member" in dead


def test_resolved_hook_markers_are_independent_liveness_roots() -> None:
    """Policy v2: a resolved pluggy marker decorator roots its function.

    ``resolved @hookspec`` livens a declaration and ``resolved @hookimpl``
    livens an implementation - two INDEPENDENT roots, never a pair: the spec
    module has no impl and the impl module has no spec. The root fires on
    the PROVEN marker binding (the decorator expression resolves to
    ``pluggy.HookspecMarker`` / ``pluggy.HookimplMarker`` through module
    -level assignments and import aliases), covering the bare, call-wrapped
    and assignment-chain alias forms. Negative twins: a user's own decorator
    NAMED ``hookspec`` is not magic, and a same-shape marker built from a
    non-pluggy factory does not root.
    """
    fixture_root = Path(__file__).parent / "fixtures" / "liveness_policy"
    registry = build_test_module_registry(root=fixture_root)
    marker_rooted = {
        "plugin_hooks/contract.py": (
            "plugin_hooks.contract",
            {"demo_setting_loaded": True, "demo_resolve_backend": True},
        ),
        "plugin_hooks/integration.py": (
            "plugin_hooks.integration",
            {
                "demo_render_panel": True,
                "demo_flush_cache": True,
                "demo_publish_summary": True,
            },
        ),
        "plugin_hooks/lookalike.py": (
            "plugin_hooks.lookalike",
            {"tracked_report": False},
        ),
        "plugin_hooks/vendor_masquerade.py": (
            "plugin_hooks.vendor_masquerade",
            {"shadow_contract": False},
        ),
    }
    for relative_path, (module_name, expected_by_symbol) in marker_rooted.items():
        source = (fixture_root / relative_path).read_text()
        _, _, _, _, metrics, _ = _extract_source(
            source=source,
            filepath=relative_path,
            module_name=module_name,
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
            module_registry=registry,
        )
        dead = find_unused(
            definitions=metrics.dead_candidates,
            referenced_names=metrics.referenced_names,
            referenced_qualnames=metrics.referenced_qualnames,
            runtime_reachability=metrics.runtime_reachability,
        )
        dead_symbols = {item.qualname.removeprefix(f"{module_name}:") for item in dead}
        for symbol, live in expected_by_symbol.items():
            assert (symbol not in dead_symbols) is live, (relative_path, symbol)

        tree, collector = _parse_tree_and_collector(source)
        walk = module_walk_mod._collect_module_walk_data(
            tree=tree,
            source=registry.entries_by_path[relative_path].identity,
            registry=registry,
            collector=collector,
            collect_referenced_names=True,
        )
        evidence_by_symbol = {
            qualname.removeprefix(f"{module_name}:"): reason
            for qualname, reason in walk.liveness_root_reasons
        }
        for symbol, live in expected_by_symbol.items():
            if live:
                assert evidence_by_symbol[symbol] == "external_decorator", (
                    relative_path,
                    symbol,
                )
            else:
                assert symbol not in evidence_by_symbol, (relative_path, symbol)


def test_tri_state_liveness_abstains_on_unresolved_external_bases() -> None:
    """Rule 3: an opaque base yields abstention, never name-only revival.

    The maintainer's decision table (39Y brief §6) proven on six fixtures: a
    call naming the declaring class roots the method; an unevidenced public
    method abstains; a name collision proven only on an unrelated local class
    must NOT revive the external-base method; a name-mangled private stays
    ordinary dead-eligible code; a ``self`` call inside the declaring class is
    itself a proven receiver and roots its target; and the same bare name
    self-called from an UNRELATED class does not.
    """
    fixture_root = Path(__file__).parent / "fixtures" / "liveness_policy"
    ground_truth = json.loads((fixture_root / "ground_truth.json").read_text())
    registry = build_test_module_registry(root=fixture_root)

    for relative_path, module_name in (
        ("distillations/roots.py", "distillations.roots"),
        ("distillations_renamed/roots.py", "distillations_renamed.roots"),
    ):
        expected_by_symbol = {
            case["symbol"]: case["expected"]["status"]
            for case in ground_truth["cases"]
            if case["path"] == relative_path and "status" in case["expected"]
        }
        assert len(expected_by_symbol) == 8

        _, _, _, _, metrics, _ = _extract_source(
            source=(fixture_root / relative_path).read_text(),
            filepath=relative_path,
            module_name=module_name,
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
            module_registry=registry,
        )
        result = classify_liveness(
            definitions=metrics.dead_candidates,
            referenced_names=metrics.referenced_names,
            referenced_qualnames=metrics.referenced_qualnames,
            runtime_reachability=metrics.runtime_reachability,
            class_metrics=metrics.class_metrics,
        )

        def local(qualname: str, *, prefix: str = f"{module_name}:") -> str:
            return qualname.removeprefix(prefix)

        statuses = {
            local(candidate.qualname): "live" for candidate in metrics.dead_candidates
        }
        statuses.update({local(item.qualname): "dead" for item in result.dead_items})
        statuses.update(
            {
                local(item.qualname): "unresolved_external_override"
                for item in result.unresolved_overrides
            }
        )

        assert {
            symbol: statuses[symbol] for symbol in expected_by_symbol
        } == expected_by_symbol

        # The collision axes stated directly: exactly two abstaining methods
        # share their bare name with a symbol proven live on an unrelated
        # receiver, and neither shared name rescued them above. One collides
        # through an explicit local-class call (LocalStore.get), the other
        # through an unrelated class's self-dispatch.
        colliding = [
            symbol
            for symbol, status in expected_by_symbol.items()
            if status == "unresolved_external_override"
            and symbol.rpartition(".")[2] in metrics.referenced_names
        ]
        assert len(colliding) == 2


def test_self_dispatch_is_row_one_evidence_for_opaque_base_methods() -> None:
    """A ``self`` call inside the declaring class proves the receiver type.

    Decision-table row 1 asks for a resolved reference whose receiver type is
    proven. ``self`` inside a class body is exactly that: it can only ever bind
    an instance of the declaring class or a subclass, so the call is
    method-specific evidence and never a bare-name match. Without this the
    engine over-abstained on ordinary private helpers of any class with an
    external base.

    The negative twin holds by construction rather than by a second rule: the
    walk records a self-call only when the called attribute is itself a method
    of the class being walked, so ``UnrelatedDispatcher``'s self-call cannot
    reach ``SharedNameHandler``.
    """
    source = """
from external_protocol import Handler

class SelfDispatchHandler(Handler):
    def collect(self, payload):
        return self._gather(payload)

    def _gather(self, payload):
        return payload.strip()

class SharedNameHandler(Handler):
    def _gather(self, payload):
        return payload

class UnrelatedDispatcher:
    def drive(self, payload):
        return self._gather(payload)

    def _gather(self, payload):
        return payload.lower()
"""

    statuses = _liveness_status_by_qualname(source)

    assert statuses["pkg.mod:SelfDispatchHandler._gather"] == "live"
    # No evidence of its own: the caller still abstains.
    assert statuses["pkg.mod:SelfDispatchHandler.collect"] == (
        "unresolved_external_override"
    )
    # Negative twin: an unrelated class's self-call shares the bare name and
    # must not revive this method.
    assert statuses["pkg.mod:SharedNameHandler._gather"] == (
        "unresolved_external_override"
    )


@pytest.mark.parametrize(
    ("source", "expected_dead"),
    [
        pytest.param(
            """
def __getattr__(name: str):
    raise AttributeError(name)

def __dir__():
    return ["demo"]

def orphan():
    return 1
""",
            ("pkg.mod:orphan",),
            id="skip_pep562_hooks",
        ),
        pytest.param(
            """
# codeclone: ignore[dead-code]
def runtime_hook():
    return 1

def orphan():
    return 2
""",
            ("pkg.mod:orphan",),
            id="inline_suppression_per_declaration",
        ),
        pytest.param(
            """
class Service:  # codeclone: ignore[dead-code]
    # codeclone: ignore[dead-code]
    def hook(self):
        return 1

    def alive(self):
        return 2
""",
            ("pkg.mod:Service.alive",),
            id="suppression_binding_scoped_to_target",
        ),
        pytest.param(
            """
class Settings:  # codeclone: ignore[dead-code]
    @validator("field")
    @classmethod
    def validate_config_version(
        cls,
        value: str | None,
    ) -> str | None:  # codeclone: ignore[dead-code]
        return value

    def orphan(self) -> int:
        return 1
""",
            ("pkg.mod:Settings.orphan",),
            id="decorated_method_end_line",
        ),
        pytest.param(
            """
class Settings:  # codeclone: ignore[dead-code]
    @field_validator("trusted_proxy_ips", "additional_telegram_ip_ranges")
    @classmethod
    def validate_trusted_proxy_ips(  # codeclone: ignore[dead-code]
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        return value

    @model_validator(mode="before")
    @classmethod
    def migrate_config_if_needed(  # codeclone: ignore[dead-code]
        cls,
        values: dict[str, object],
    ) -> dict[str, object]:
        return values

    def orphan(self) -> int:
        return 1
""",
            ("pkg.mod:Settings.orphan",),
            id="multiline_header_start_line",
        ),
    ],
)
def test_dead_code_respects_runtime_hooks_and_inline_suppressions(
    source: str,
    expected_dead: tuple[str, ...],
) -> None:
    assert _dead_qualnames_from_source(source) == expected_dead


def test_dead_code_uses_fastapi_route_and_dependency_reachability() -> None:
    source = """
from fastapi import APIRouter, Depends

router = APIRouter()

def require_user():
    return "user"

@router.get("/items", dependencies=[Depends(require_user)])
def list_items(current_user=Depends(require_user)):
    return [current_user]

@fake.get("/items")
def fake_handler():
    return []

def orphan():
    return 1
"""

    assert _dead_qualnames_from_source(source) == (
        "pkg.mod:fake_handler",
        "pkg.mod:orphan",
    )


def test_dead_code_uses_fastapi_annotated_dependency_reachability() -> None:
    source = """
from typing import Annotated
from fastapi import APIRouter, Depends, Security

router = APIRouter()

def require_user():
    return "user"

def require_token():
    return "token"

def require_extra():
    return "extra"

def require_kwargs():
    return "kwargs"

@router.get("/items")
def list_items(
    current_user: Annotated[str, Depends(require_user)],
    *extra: Annotated[str, Depends(require_extra)],
    token: Annotated[str, Security(dependency=require_token)],
    optional: list[str] | None = None,
    broken: Annotated[str] | None = None,
    **kwargs: Annotated[str, Depends(require_kwargs)],
):
    return [current_user, token, extra, optional, broken, kwargs]

def orphan():
    return 1
"""

    assert _dead_qualnames_from_source(source) == ("pkg.mod:orphan",)


def test_runtime_reachability_helper_symbol_edges() -> None:
    tree = ast.parse(
        """
if TYPE_CHECKING:
    pass

if typing.TYPE_CHECKING:
    pass

target = loader()[name]
"""
    )
    guarded_if = cast(ast.If, tree.body[0])
    typing_guarded_if = cast(ast.If, tree.body[1])
    subscript_value = cast(ast.Assign, tree.body[2]).value

    assert ast_helpers_mod.is_type_checking_guard(guarded_if.test) is True
    assert ast_helpers_mod.is_type_checking_guard(typing_guarded_if.test) is True
    assert reachability_mod._dotted_name(subscript_value) == "loader"
    assert reachability_mod._resolve_symbol(ast.Constant(value=1), {}) is None


def test_runtime_binding_collect_first_arg_object_requires_args() -> None:
    visitor = reachability_mod._RuntimeBindingVisitor()
    visitor.objects["app"] = "aiohttp_app"
    stmt = ast.parse("app.add_routes()").body[0]
    assert isinstance(stmt, ast.Expr)
    call = stmt.value
    assert isinstance(call, ast.Call)
    visitor._collect_runtime_registration(call)
    assert visitor.included_routers == set()


@pytest.mark.parametrize(
    ("fixture_name", "expected_confidence"),
    (
        pytest.param("import_before_use.py", "high", id="import_before_use"),
        pytest.param("use_before_import.py", "medium", id="use_before_import"),
    ),
)
def test_runtime_binding_resolves_only_preceding_imports(
    fixture_name: str,
    expected_confidence: str,
) -> None:
    fixture = Path(__file__).parent / "fixtures" / "detect_fusion" / fixture_name
    facts = _runtime_reachability_from_source(fixture.read_text(encoding="utf-8"))

    assert [(fact.target_qualname, fact.confidence) for fact in facts] == [
        ("pkg.mod:view", expected_confidence)
    ]


def test_runtime_reachability_internal_guards_stay_safe() -> None:
    empty_collector = QualnameCollector()
    visitor = reachability_mod._RuntimeReachabilityVisitor(
        module_name="pkg.mod",
        filepath="pkg/mod.py",
        collector=empty_collector,
        aliases={
            "containers": "dependency_injector.containers",
            "providers": "dependency_injector.providers",
        },
        runtime_objects={},
        included_routers=set(),
        route_decorator_factories={},
    )
    tree = ast.parse(
        """
def unindexed_function():
    return None

class Container(containers.DeclarativeContainer):
    service = providers.Factory(Service)
"""
    )

    visitor.visit(tree)
    visitor._emit(
        target=reachability_mod._Target(
            qualname="pkg.mod:missing",
            start_line=0,
            end_line=0,
            kind="function",
        ),
        framework="fastapi",
        edge_kind="registers_handler",
        confidence="high",
        evidence="manual guard",
        evidence_symbol="manual",
        source_qualname="pkg.mod",
    )

    assert visitor.facts == []

    # Non-handler statements contribute nothing when replayed.
    visitor._apply_handler_node(ast.Pass())
    assert visitor.facts == []

    # A factory recorded with a non-route method claims nothing (fail closed).
    corrupt = reachability_mod._RuntimeReachabilityVisitor(
        module_name="pkg.mod",
        filepath="pkg/mod.py",
        collector=empty_collector,
        aliases={},
        runtime_objects={},
        included_routers=set(),
        route_decorator_factories={
            "weird": reachability_mod._RouteDecoratorFactory(
                obj_name="app",
                obj_kind="fastapi_app",
                method="not_a_route_method",
            )
        },
    )
    decorator = ast.parse("weird", mode="eval").body
    assert corrupt._route_registration(decorator) is None


def test_runtime_reachability_covers_fastapi_aliases_and_dependency_edges() -> None:
    source = """
from typing_extensions import Annotated as Ann
from fastapi import APIRouter as Router, Depends as Inject, FastAPI

router = Router()
also_router = Router()
app = FastAPI()
app.include_router(router)
app.include_router(router=also_router)

def require_user():
    return "user"

def require_token():
    return "token"

def require_session():
    return "session"

@router.post("/items", dependencies=Inject(require_user))
async def create_item(token=Inject(dependency=require_token)):
    return token

@router.get("/annotated")
def annotated_dependency(token: Ann[str, Inject(require_session)]):
    return token

@also_router.websocket("/ws")
def websocket_endpoint():
    return None
"""

    facts = _runtime_reachability_from_source(source)
    by_target = {(fact.target_qualname, fact.edge_kind): fact for fact in facts}

    assert by_target[("pkg.mod:create_item", "registers_handler")].confidence == (
        "high"
    )
    assert by_target[("pkg.mod:require_user", "declares_dependency")].evidence == (
        "dependency registration"
    )
    assert by_target[
        ("pkg.mod:require_token", "declares_dependency")
    ].evidence_symbol == ("fastapi.Depends")
    assert by_target[
        ("pkg.mod:annotated_dependency", "registers_handler")
    ].confidence == ("high")
    assert by_target[
        ("pkg.mod:require_session", "declares_dependency")
    ].evidence_symbol == ("fastapi.Depends")
    assert by_target[
        ("pkg.mod:websocket_endpoint", "registers_handler")
    ].confidence == ("high")


def test_dead_code_uses_fastapi_route_decorator_factory_reachability() -> None:
    source = """
from typing import cast
from fastapi import APIRouter, status

router = APIRouter()

def _typed_get(*args: object, **kwargs: object):
    route_get = cast(object, router.get)
    return route_get(*args, **kwargs)

@_typed_get("", status_code=status.HTTP_200_OK)
async def get_system_metrics():
    return {}

def orphan():
    return 1
"""

    assert _dead_qualnames_from_source(source) == ("pkg.mod:orphan",)
    by_target = _runtime_reachability_by_target(source)

    assert by_target["pkg.mod:get_system_metrics"].framework == "fastapi"
    assert by_target["pkg.mod:get_system_metrics"].evidence == (
        "route decorator factory"
    )
    assert by_target["pkg.mod:get_system_metrics"].evidence_symbol == "_typed_get"


def test_dead_code_uses_aiogram_router_observer_reachability() -> None:
    source = """
from aiogram import F, Dispatcher, Router
from aiogram.filters import Command

router = Router()
dp = Dispatcher()
not_router = object()

def get_router():
    return router

@router.message(Command("start"))
async def cmd_start(message):
    return message

@router.callback_query(F.data.startswith("docker:container:"))
async def show_container_detail(callback):
    return callback

@dp.inline_query()
async def inline_search(query):
    return query

@not_router.message()
async def fake_message(message):
    return message

def orphan():
    return 1
"""

    assert _dead_qualnames_from_source(source) == (
        "pkg.mod:get_router",
        "pkg.mod:fake_message",
        "pkg.mod:orphan",
    )
    observed = {
        fact.target_qualname: (fact.framework, fact.evidence_symbol, fact.confidence)
        for fact in _runtime_reachability_from_source(source)
    }
    assert {
        key: observed[key]
        for key in (
            "pkg.mod:cmd_start",
            "pkg.mod:show_container_detail",
            "pkg.mod:inline_search",
        )
    } == {
        "pkg.mod:cmd_start": ("aiogram", "router.message", "medium"),
        "pkg.mod:show_container_detail": (
            "aiogram",
            "router.callback_query",
            "medium",
        ),
        "pkg.mod:inline_search": ("aiogram", "dp.inline_query", "high"),
    }
    assert "pkg.mod:fake_message" not in observed


def test_dead_code_uses_flask_and_aiohttp_route_reachability() -> None:
    source = """
from aiohttp import web
from flask import Blueprint, Flask

app = Flask(__name__)
bp = Blueprint("api", __name__)
aio_routes = web.RouteTableDef()
aio_app = web.Application()
other = object()

app.register_blueprint(bp)
aio_app.add_routes(aio_routes)

@app.route("/")
def flask_index():
    return "ok"

@bp.get("/items")
def flask_items():
    return "items"

@aio_routes.post("/items")
async def aio_items(request):
    return request

@other.route("/")
def fake_route():
    return "fake"

def orphan():
    return 1
"""

    assert _dead_qualnames_from_source(source) == (
        "pkg.mod:fake_route",
        "pkg.mod:orphan",
    )
    observed = {
        fact.target_qualname: (fact.framework, fact.confidence)
        for fact in _runtime_reachability_from_source(source)
    }
    assert observed == {
        "pkg.mod:flask_index": ("flask", "high"),
        "pkg.mod:flask_items": ("flask", "high"),
        "pkg.mod:aio_items": ("aiohttp", "high"),
    }


def test_dead_code_uses_starlette_base_http_middleware_dispatch_hook() -> None:
    source = """
from starlette.middleware.base import BaseHTTPMiddleware as MiddlewareBase

class SecurityAuditMiddleware(MiddlewareBase):
    async def dispatch(self, request, call_next):
        return await call_next(request)

    async def helper(self):
        return None

class PlainMiddleware:
    async def dispatch(self, request, call_next):
        return await call_next(request)

def orphan():
    return 1
"""

    # SUPERSEDED by the tri-state contract (EM mem-f12ffef4): this assertion
    # used to require SecurityAuditMiddleware.helper to be dead. Its owner
    # inherits an unresolved external base, so an unevidenced public method now
    # abstains rather than being claimed dead. The class itself still dies, and
    # base-less PlainMiddleware is the untouched negative control.
    assert _dead_qualnames_from_source(source) == (
        "pkg.mod:SecurityAuditMiddleware",
        "pkg.mod:PlainMiddleware",
        "pkg.mod:PlainMiddleware.dispatch",
        "pkg.mod:orphan",
    )
    assert (
        _liveness_status_by_qualname(source)["pkg.mod:SecurityAuditMiddleware.helper"]
        == "unresolved_external_override"
    )
    by_target = _runtime_reachability_by_target(source)
    assert by_target["pkg.mod:SecurityAuditMiddleware.dispatch"].framework == (
        "starlette"
    )
    assert (
        by_target["pkg.mod:SecurityAuditMiddleware.dispatch"].evidence_symbol
        == "BaseHTTPMiddleware.dispatch"
    )
    assert "pkg.mod:PlainMiddleware.dispatch" not in by_target


def test_dead_code_uses_sqlalchemy_type_decorator_runtime_hooks() -> None:
    source = """
from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator

class OrjsonJSON(TypeDecorator[object]):
    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        return value

    def helper(self):
        return None
"""

    dead = set(_dead_qualnames_from_source(source))

    assert "pkg.mod:OrjsonJSON.process_bind_param" not in dead
    assert "pkg.mod:OrjsonJSON.process_result_value" not in dead
    # SUPERSEDED by the tri-state contract (EM mem-f12ffef4): this assertion
    # used to require OrjsonJSON.helper to be dead. TypeDecorator is an
    # unresolved external base, so the unevidenced helper abstains instead.
    assert "pkg.mod:OrjsonJSON.helper" not in dead
    assert _liveness_status_by_qualname(source)["pkg.mod:OrjsonJSON.helper"] == (
        "unresolved_external_override"
    )
    by_target = _runtime_reachability_by_target(source)
    assert by_target["pkg.mod:OrjsonJSON.process_bind_param"].framework == (
        "sqlalchemy"
    )
    assert by_target["pkg.mod:OrjsonJSON.process_result_value"].edge_kind == (
        "runtime_hook"
    )


def test_dead_code_uses_extended_framework_runtime_reachability() -> None:
    source = """
from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic.json_schema import GenerateJsonSchema as _GenerateJsonSchema

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    return None

@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    return request

@app.middleware("http")
async def audit_middleware(request, call_next):
    return await call_next(request)

class CustomJsonSchema(_GenerateJsonSchema):
    def bytes_schema(self, schema):
        return {"type": "string", "format": "base64"}

    def schema_helper(self):
        return None

class CustomRoute(APIRoute):
    def get_path(self, scope):
        return scope["path"]

    async def get_response(self, path, scope):
        return path

    def route_helper(self):
        return None

class CustomApp(FastAPI):
    def build_middleware_stack(self):
        return super().build_middleware_stack()

    def app_helper(self):
        return None

def orphan():
    return 1
"""

    dead = set(_dead_qualnames_from_source(source))
    assert {
        "pkg.mod:startup_event",
        "pkg.mod:value_error_handler",
        "pkg.mod:audit_middleware",
        "pkg.mod:CustomJsonSchema.bytes_schema",
        "pkg.mod:CustomRoute.get_path",
        "pkg.mod:CustomRoute.get_response",
        "pkg.mod:CustomApp.build_middleware_stack",
    }.isdisjoint(dead)
    assert dead >= {"pkg.mod:orphan"}
    # SUPERSEDED by the tri-state contract (EM mem-f12ffef4): these three
    # helpers used to be asserted dead. Each hangs off an unresolved external
    # framework base, so all three abstain together.
    statuses = _liveness_status_by_qualname(source)
    assert {
        statuses["pkg.mod:CustomJsonSchema.schema_helper"],
        statuses["pkg.mod:CustomRoute.route_helper"],
        statuses["pkg.mod:CustomApp.app_helper"],
    } == {"unresolved_external_override"}
    by_target = _runtime_reachability_by_target(source)
    by_evidence = {
        (fact.target_qualname, fact.evidence_symbol): fact
        for fact in _runtime_reachability_from_source(source)
    }
    assert by_evidence[("pkg.mod:startup_event", "app.on_event")].framework == "fastapi"
    assert by_evidence[("pkg.mod:audit_middleware", "app.middleware")].confidence == (
        "high"
    )
    assert by_target["pkg.mod:CustomJsonSchema.bytes_schema"].framework == "pydantic"
    assert by_target["pkg.mod:CustomRoute.get_path"].edge_kind == "runtime_hook"
    assert by_target["pkg.mod:CustomApp.build_middleware_stack"].evidence_symbol == (
        "FastAPI.build_middleware_stack"
    )


def test_runtime_reachability_ignores_type_checking_only_frameworks() -> None:
    source = """
from typing import TYPE_CHECKING
from fastapi import APIRouter

router = APIRouter()

if TYPE_CHECKING:
    from fastapi import Depends as Inject

def dep():
    return 1

@router.get("/items")
def view(value=Inject(dep)):
    return value
"""

    facts = _runtime_reachability_from_source(source)

    assert [fact.target_qualname for fact in facts] == ["pkg.mod:view"]


def test_runtime_reachability_covers_binding_edge_cases() -> None:
    source = """
from . import relative_import
from framework import *
from fastapi import APIRouter, Depends, FastAPI

router = APIRouter()
app = FastAPI()
other = object()
app.attr = FastAPI()
ann_only: FastAPI

FastAPI.include_router(router)
app.include_router(42)
app.include_router(router=42)
app.include_router(prefix="/api")
other.include_router(router)

def dep():
    return 1

@router.get
def bare_route_decorator():
    return 1

@router.get("/name", name="items")
def named_route():
    return 2

@router.get("/bad-dependencies", dependencies=dependency_list)
def dependency_list_route():
    return 3

@router.get("/empty-dependency")
def empty_dependency(value=Depends()):
    return value

@router.get("/kw-dependency")
def keyword_dependency(value=Depends(dep, use_cache=False)):
    return value
"""

    facts = _runtime_reachability_from_source(source)
    by_target = {(fact.target_qualname, fact.edge_kind): fact for fact in facts}

    assert by_target[("pkg.mod:bare_route_decorator", "registers_handler")]
    assert by_target[("pkg.mod:named_route", "registers_handler")]
    assert by_target[("pkg.mod:dependency_list_route", "registers_handler")]
    assert by_target[("pkg.mod:empty_dependency", "registers_handler")]
    assert by_target[("pkg.mod:keyword_dependency", "registers_handler")]
    assert by_target[("pkg.mod:dep", "declares_dependency")].evidence_symbol == (
        "fastapi.Depends"
    )


def test_dead_code_uses_django_urlpattern_reachability() -> None:
    source = """
from django.urls import path

class ItemView:
    def get(self, request):
        return request

    def helper(self):
        return 1

def list_items(request):
    return request

urlpatterns = [
    path("items/", list_items),
    path("items/<int:item_id>/", ItemView.as_view()),
]

def orphan():
    return 1
"""

    assert _dead_qualnames_from_source(source) == (
        "pkg.mod:ItemView.helper",
        "pkg.mod:orphan",
    )


def test_runtime_reachability_covers_django_re_path_and_urlpattern_concat() -> None:
    source = """
from django.urls import path, re_path

def home(request):
    return request

def search(request):
    return request

urlpatterns = [
    object(),
    path("home/", home),
] + (
    re_path(r"^search/$", search),
    re_path(r"^broken/$"),
)
"""

    facts = _runtime_reachability_from_source(source)

    assert [fact.target_qualname for fact in facts] == [
        "pkg.mod:home",
        "pkg.mod:search",
    ]
    assert {fact.evidence_symbol for fact in facts} == {
        "django.urls.path",
        "django.urls.re_path",
    }


def test_runtime_reachability_ignores_unresolved_django_url_entries() -> None:
    source = """
from django.urls import path

def local_view(request):
    return request

urlpatterns = make_patterns()
urlpatterns = [
    "not a call",
    path("missing/"),
    path("external/", external.view),
    path("local/", local_view),
]
"""

    facts = _runtime_reachability_from_source(source)

    assert [fact.target_qualname for fact in facts] == ["pkg.mod:local_view"]


def test_dead_code_uses_dependency_injector_provider_reachability() -> None:
    source = """
from dependency_injector import containers, providers

class Service:
    pass

class Unused:
    pass

class Container(containers.DeclarativeContainer):
    service = providers.Factory(Service)
"""

    assert _dead_qualnames_from_source(source) == ("pkg.mod:Unused",)


def test_runtime_reachability_covers_di_annassign_and_invalid_provider() -> None:
    source = """
from dependency_injector import containers, providers

class Service:
    pass

class Repository:
    pass

class Container(containers.DeclarativeContainer):
    config = object()
    missing = providers.Factory()
    raw = object
    service: object = providers.Singleton(Service)
    repository = providers.Factory(Repository)
    (tuple_provider,) = providers.Factory(Service)
    literal = providers.Factory(1)

    def helper(self):
        return None
"""

    facts = _runtime_reachability_from_source(source)
    provider_targets = {
        fact.target_qualname: fact
        for fact in facts
        if fact.evidence == "Dependency Injector provider"
    }

    assert sorted(provider_targets) == [
        "pkg.mod:Repository",
        "pkg.mod:Service",
    ]
    assert provider_targets["pkg.mod:Service"].source_qualname == (
        "pkg.mod:Container.service"
    )


def test_dead_code_uses_cli_and_task_registration_reachability() -> None:
    source = """
import click
import typer
from celery import Celery, shared_task

cli = typer.Typer()
celery_app = Celery("demo")

@cli.command()
def run_typer():
    return 1

@click.command()
def run_click():
    return 2

@celery_app.task
def run_task():
    return 3

@shared_task
def run_shared_task():
    return 4

def orphan():
    return 5
"""

    assert _dead_qualnames_from_source(source) == ("pkg.mod:orphan",)


def test_runtime_reachability_rejects_invalid_router_methods_and_cast_factory() -> None:
    source = """
from typing import cast
from starlette.routing import Router

router = Router()

def _short_cast():
    return cast(object)

def _invalid_factory(*args, **kwargs):
    return router.not_a_route(*args, **kwargs)

@router.not_a_route("/bad")
def invalid_direct(request):
    return request

@_short_cast()
def short_cast_handler(request):
    return request

@_invalid_factory("/factory-bad")
def invalid_factory_handler(request):
    return request
"""

    by_target = _runtime_reachability_by_target(source)
    assert "pkg.mod:invalid_direct" not in by_target
    assert "pkg.mod:short_cast_handler" not in by_target
    assert "pkg.mod:invalid_factory_handler" not in by_target


def test_runtime_reachability_covers_starlette_click_group_and_celery_aliases() -> None:
    source = """
import click
from celery import Celery as CeleryApp
from starlette.applications import Starlette
from starlette.routing import Router

app: Starlette = Starlette()
router = Router()
worker = CeleryApp("demo")
not_worker = object()
group = click.Group()

@app.route("/home")
def home(request):
    return request

@router.route("/internal")
def internal(request):
    return request

@click.group()
def cli():
    return None

@cli.callback()
def configure_cli():
    return None

@group.command()
def grouped_command():
    return None

@worker.task()
def run_task():
    return None

@not_worker.task()
def not_registered_task():
    return None
"""

    by_target = _runtime_reachability_by_target(source)

    assert by_target["pkg.mod:home"].framework == "starlette"
    assert by_target["pkg.mod:home"].confidence == "high"
    assert by_target["pkg.mod:internal"].confidence == "medium"
    assert by_target["pkg.mod:cli"].framework == "click"
    assert by_target["pkg.mod:configure_cli"].evidence_symbol == "cli.callback"
    assert by_target["pkg.mod:grouped_command"].evidence_symbol == "group.command"
    assert by_target["pkg.mod:run_task"].framework == "celery"
    assert "pkg.mod:not_registered_task" not in by_target


def test_collect_dead_candidates_and_extract_skip_classes_without_lineno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = QualnameCollector()
    collector.visit(
        ast.parse(
            """
def used():
    return 1
""".strip()
        )
    )
    broken_class = ast.ClassDef(
        name="Broken",
        bases=[],
        keywords=[],
        body=[],
        decorator_list=[],
    )
    broken_class.lineno = 0
    broken_class.end_lineno = 0
    collector.class_nodes.append(("Broken", broken_class))
    dead = module_walk_mod._collect_dead_candidates(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        collector=collector,
    )
    assert all(item.qualname != "pkg.mod:Broken" for item in dead)

    class _CollectorNoClassMetrics:
        def __init__(self) -> None:
            self.units: list[tuple[str, FunctionNode]] = []
            self.class_nodes = [("Broken", broken_class)]
            self.function_count = 0
            self.method_count = 0
            self.class_count = 1

        def visit(self, _tree: ast.AST) -> None:
            return None

    monkeypatch.setattr(qualnames, "QualnameCollector", _CollectorNoClassMetrics)
    _, _, _, _, file_metrics, _ = _extract_source(
        source="class Broken:\n    pass\n",
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    assert file_metrics.class_metrics == ()


def test_extract_collects_referenced_qualnames_for_import_aliases() -> None:
    src = """
from pkg.runtime import run as _run_impl
import pkg.helpers as helpers

def wrapper():
    value = _run_impl()
    return helpers.decorate(value)
"""
    _, _, _, _, file_metrics, _ = _extract_source(
        source=src,
        filepath="pkg/cli.py",
        module_name="pkg.cli",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    assert "pkg.runtime:run" in file_metrics.referenced_qualnames
    assert "pkg.helpers:decorate" in file_metrics.referenced_qualnames


def test_extract_collects_cross_module_relationships_by_caller() -> None:
    source = """
from pkg.runtime import run as imported_run
from pkg.handlers import handler
import pkg.helpers as helpers

def source(value):
    callback = handler
    imported_run()
    helpers.decorate(value)
    factory()()
    return callback
"""
    _, _, _, _, file_metrics, _ = _extract_source(
        source=source,
        filepath="pkg/module.py",
        module_name="pkg.module",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )

    assert len(file_metrics.function_relationship_facts) == 1
    facts = file_metrics.function_relationship_facts[0]
    assert facts.source_qualname == "pkg.module:source"
    resolved = {
        (record.relation_kind, record.target_qualname, record.resolution_rule)
        for record in facts.relationships
        if record.resolution_status == "resolved"
    }
    assert (
        "call",
        "pkg.runtime:run",
        "imported_symbol",
    ) in resolved
    assert (
        "call",
        "pkg.helpers:decorate",
        "imported_module_attribute",
    ) in resolved
    assert (
        "reference",
        "pkg.handlers:handler",
        "imported_symbol",
    ) in resolved
    unresolved_calls = [
        record
        for record in facts.relationships
        if record.resolution_status == "unresolved"
    ]
    assert unresolved_calls
    assert all(record.relation_kind == "call" for record in unresolved_calls)
    assert all(record.origin_lane == "production" for record in facts.relationships)


def test_relationship_resolution_guards_caller_local_shadowing() -> None:
    source = """
from pkg.runtime import run

def by_parameter(run):
    return run()

def by_assignment():
    run = lambda: 1
    return run()

def by_nested_definition():
    def run():
        return 1
    return run()

def by_local_import():
    from pkg.other import run
    return run()
"""
    _, _, _, _, file_metrics, _ = _extract_source(
        source=source,
        filepath="pkg/module.py",
        module_name="pkg.module",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )

    records = [
        record
        for facts in file_metrics.function_relationship_facts
        for record in facts.relationships
        if record.expression == "run"
    ]
    assert len(records) == 4
    assert all(record.relation_kind == "call" for record in records)
    assert all(record.resolution_status == "unresolved" for record in records)
    assert all(record.target_qualname is None for record in records)
    assert all(record.resolution_rule == "local_shadowing" for record in records)


def test_relationship_import_index_is_module_scoped_and_conservative() -> None:
    tree = ast.parse(
        """
import pkg.alpha as alpha
import pkg.one as duplicate
import pkg.two as duplicate
from pkg.handlers import handler
from pkg.other import handler
from pkg.runtime import *
from .... import hidden

shadowed = 1

def declared():
    import pkg.local as leaked
    return leaked.run()

try:
    value = 1
except Exception as captured:
    value = 2

match value:
    case {"name": matched}:
        pass
"""
    )

    identity, registry = module_registry_context(
        filepath="pkg/module.py",
        module_name="pkg.module",
    )
    index = module_walk_mod._collect_relationship_import_index(
        tree=tree,
        source=identity,
        registry=registry,
    )

    assert index.module_bindings["alpha"] == frozenset({"pkg.alpha"})
    assert index.module_bindings["duplicate"] == frozenset({"pkg.one", "pkg.two"})
    assert index.symbol_bindings["handler"] == frozenset(
        {"pkg.handlers:handler", "pkg.other:handler"}
    )
    assert "leaked" not in index.module_bindings
    assert {"shadowed", "declared", "captured", "matched"} <= set(
        index.module_shadowed_names
    )
    assert module_walk_mod._collect_relationship_import_index(
        tree=ast.Constant(value=1),
        source=identity,
        registry=registry,
    ) == module_walk_mod._RelationshipImportIndex({}, {}, frozenset())


def test_relationship_caller_bindings_cover_python_scope_forms() -> None:
    outer = ast.parse(
        """
def outer():
    inherited = 1

    def inner(posonly, /, regular, *args, kwonly, **kwargs):
        global global_name
        nonlocal inherited
        global_name = 1
        inherited = 2
        local = 3
        for item in ():
            pass
        with resource() as opened:
            pass
        try:
            pass
        except Exception as captured:
            pass
        match regular:
            case {"name": matched}:
                pass
        import pkg.local as local_module
        from pkg.runtime import handler
        def nested():
            return None
        class Inner:
            pass
        return local
"""
    ).body[0]
    assert isinstance(outer, ast.FunctionDef)
    inner = outer.body[1]
    assert isinstance(inner, ast.FunctionDef)

    bindings, _scope_nodes = module_walk_mod._walk_relationship_function_scope(inner)

    assert {
        "posonly",
        "regular",
        "args",
        "kwonly",
        "kwargs",
        "local",
        "item",
        "opened",
        "captured",
        "matched",
        "local_module",
        "handler",
        "nested",
        "Inner",
    } <= set(bindings)
    assert "global_name" not in bindings
    assert "inherited" not in bindings
    assert module_walk_mod._first_parameter_name(inner) == "posonly"
    no_args = ast.parse("def empty():\n    return None\n").body[0]
    assert isinstance(no_args, ast.FunctionDef)
    assert module_walk_mod._first_parameter_name(no_args) is None


def test_relationship_expression_resolution_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imports = module_walk_mod._RelationshipImportIndex(
        symbol_bindings={
            "handler": frozenset({"pkg.handlers:handler"}),
            "ambiguous": frozenset({"pkg.one:run", "pkg.two:run"}),
            "shadowed": frozenset({"pkg.runtime:shadowed"}),
        },
        module_bindings={
            "helpers": frozenset({"pkg.helpers"}),
            "modules": frozenset({"pkg.one", "pkg.two"}),
        },
        module_shadowed_names=frozenset({"shadowed"}),
    )

    def resolve(
        expression: str,
        *,
        caller_bindings: frozenset[str] = frozenset(),
        local_method_qualnames: frozenset[str] = frozenset({"pkg.module:Service.hook"}),
        enclosing_class_local: str | None = None,
        receiver_name: str | None = None,
    ) -> tuple[str | None, str]:
        node = ast.parse(expression, mode="eval").body
        assert isinstance(node, ast.expr)
        return module_walk_mod._resolve_relationship_expression(
            node,
            module_name="pkg.module",
            imports=imports,
            caller_bindings=caller_bindings,
            top_level_function_names=frozenset({"local_function"}),
            top_level_class_names=frozenset({"Service"}),
            local_method_qualnames=local_method_qualnames,
            enclosing_class_local=enclosing_class_local,
            receiver_name=receiver_name,
        )

    assert resolve("handler") == ("pkg.handlers:handler", "imported_symbol")
    assert resolve("handler", caller_bindings=frozenset({"handler"})) == (
        None,
        "local_shadowing",
    )
    assert resolve("shadowed") == (None, "local_shadowing")
    assert resolve("ambiguous") == (None, "ambiguous_import")
    # same-module function (6c): resolved unless caller-shadowed.
    assert resolve("local_function") == (
        "pkg.module:local_function",
        "same_module_function",
    )
    assert resolve("Service") == (
        "pkg.module:Service",
        "same_module_class",
    )
    assert resolve(
        "local_function",
        caller_bindings=frozenset({"local_function"}),
    ) == (None, "unresolved_name")
    assert resolve("unknown") == (None, "unresolved_name")
    assert resolve("helpers.decorate") == (
        "pkg.helpers:decorate",
        "imported_module_attribute",
    )
    assert resolve(
        "helpers.decorate",
        caller_bindings=frozenset({"helpers"}),
    ) == (None, "local_shadowing")
    assert resolve("modules.run") == (None, "ambiguous_import")
    # same-module class method (6c): resolved only when the method exists and the
    # class name is not locally shadowed.
    assert resolve("Service.hook") == (
        "pkg.module:Service.hook",
        "same_module_class_method",
    )
    assert resolve("Service.missing") == (None, "unresolved_dynamic")
    assert resolve(
        "Service.hook",
        caller_bindings=frozenset({"Service"}),
    ) == (None, "unresolved_dynamic")
    # self/cls receiver method (6c): resolved against the enclosing class, keyed
    # on the actual first-parameter name, only when the method exists.
    assert resolve(
        "receiver.hook",
        enclosing_class_local="Service",
        receiver_name="receiver",
    ) == ("pkg.module:Service.hook", "self_or_cls_method")
    assert resolve(
        "receiver.missing",
        enclosing_class_local="Service",
        receiver_name="receiver",
    ) == (None, "unresolved_dynamic")
    assert resolve("factory().hook") == (None, "unresolved_dynamic")
    assert module_walk_mod._single_relationship_target(
        None,
        resolved_rule="unused",
    ) == (None, "unresolved_name")

    expression = ast.Name(id="handler", ctx=ast.Load())
    monkeypatch.setattr(
        ast,
        "unparse",
        lambda _node: (_ for _ in ()).throw(ValueError("broken")),
    )
    assert module_walk_mod._relationship_expression(expression) is None
    record = module_walk_mod._relationship_record(
        relation_kind="call",
        origin_lane="production",
        source_qualname="pkg.module:source",
        target_qualname=None,
        filepath="pkg/module.py",
        node=expression,
        resolution_rule="unresolved_name",
    )
    assert record.line == 1
    assert record.resolution_status == "unresolved"


def _function_relationship_facts_for(
    source: str, source_qualname: str
) -> FunctionRelationshipFacts:
    _, _, _, _, file_metrics, _ = _extract_source(
        source=source,
        filepath="pkg/module.py",
        module_name="pkg.module",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    return next(
        facts
        for facts in file_metrics.function_relationship_facts
        if facts.source_qualname == source_qualname
    )


def test_relationship_collection_resolves_intra_module_and_self() -> None:
    source = """
def local_function():
    return 1

class Service:
    def hook(self):
        return 1

    def caller(receiver):
        local_function()
        Service.hook()
        receiver.hook()
        factory().hook()
"""
    caller = _function_relationship_facts_for(source, "pkg.module:Service.caller")
    resolved = {
        record.resolution_rule: record.target_qualname
        for record in caller.relationships
        if record.relation_kind == "call" and record.resolution_status == "resolved"
    }
    # receiver.hook() resolves on the actual first-parameter name (not a hardcoded
    # "self"); Service.hook() and receiver.hook() reach the same method via
    # different rules.
    assert resolved == {
        "same_module_function": "pkg.module:local_function",
        "same_module_class_method": "pkg.module:Service.hook",
        "self_or_cls_method": "pkg.module:Service.hook",
    }
    assert any(
        record.resolution_rule == "unresolved_dynamic"
        and record.resolution_status == "unresolved"
        for record in caller.relationships
    )


@pytest.mark.parametrize(
    ("source", "source_qualname"),
    [
        pytest.param(
            """
class Service:
    def hook(self):
        return 1

    @staticmethod
    def build(item):
        return item.hook()
""",
            "pkg.module:Service.build",
            id="staticmethod_first_param",
        ),
        pytest.param(
            """
class Service:
    def hook(self):
        return 1

def helper(self):
    return self.hook()
""",
            "pkg.module:helper",
            id="top_level_self_param",
        ),
    ],
)
def test_relationship_non_receiver_first_parameter_stays_unresolved(
    source: str, source_qualname: str
) -> None:
    # A staticmethod's first parameter and a top-level function's parameter named
    # self are ordinary values, not receivers — self/cls resolution must not fire
    # even though a Service.hook method exists.
    facts = _function_relationship_facts_for(source, source_qualname)
    assert all(
        record.resolution_status == "unresolved" for record in facts.relationships
    )


def test_relationship_classmethod_receiver_resolves_to_same_class() -> None:
    source = """
class Service:
    def hook(self):
        return 1

    @classmethod
    def make(cls):
        return cls.hook()
"""
    make = _function_relationship_facts_for(source, "pkg.module:Service.make")
    assert any(
        record.target_qualname == "pkg.module:Service.hook"
        and record.resolution_rule == "self_or_cls_method"
        for record in make.relationships
    )


def test_test_relationship_lane_does_not_feed_flat_reachability() -> None:
    source = """
from prod import only_used_by_test

def test_it():
    assert only_used_by_test() == 1
"""
    _, _, _, _, file_metrics, _ = _extract_source(
        source=source,
        filepath="tests/test_prod.py",
        module_name="tests.test_prod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )

    assert file_metrics.referenced_qualnames == frozenset()
    records = file_metrics.function_relationship_facts[0].relationships
    assert any(
        record.target_qualname == "prod:only_used_by_test"
        and record.origin_lane == "test"
        and record.resolution_status == "resolved"
        for record in records
    )


def test_extract_collects_referenced_qualnames_for_module_all_exports() -> None:
    source = """
__all__ = ["PublicClass"] + ("public_func",)
__all__: list[str] = ["TypedPublic"]
__all__: tuple[str, ...]
__all__ += ["AugmentedPublic"]
__all__.append("AlsoPublic")
__all__.extend(["exported_later"])
__all__.append(object())
__all__.extend([["NestedInvalid"]])

class PublicClass:
    pass

class TypedPublic:
    pass

class AugmentedPublic:
    pass

class AlsoPublic:
    pass

class Internal:
    def public_func(self):
        return 1

def public_func():
    return 2

def exported_later():
    return 3

def internal_func():
    __all__ = ["NestedOnly"]
    return 4

def NestedOnly():
    return 5

def NestedInvalid():
    return 6
"""
    dead = set(_dead_qualnames_from_source(source))

    exported = {
        "pkg.mod:PublicClass",
        "pkg.mod:TypedPublic",
        "pkg.mod:AugmentedPublic",
        "pkg.mod:AlsoPublic",
        "pkg.mod:public_func",
        "pkg.mod:exported_later",
    }
    still_dead = {
        "pkg.mod:Internal",
        "pkg.mod:Internal.public_func",
        "pkg.mod:internal_func",
        "pkg.mod:NestedOnly",
        "pkg.mod:NestedInvalid",
    }
    assert dead.isdisjoint(exported)
    assert still_dead <= dead

    state = module_walk_mod._ModuleWalkState()
    module_walk_mod._collect_module_all_exports(ast.Pass(), state)
    assert state.exported_names == set()


def test_module_walk_export_and_dynamic_getattr_helpers_cover_safe_edges() -> None:
    invalid_exports = cast(
        ast.Assign,
        ast.parse('_EXPORTS = {"Good": "pkg.good", 42: "bad", "Bad": object()}').body[
            0
        ],
    )
    assert module_walk_mod._string_mapping_from_literal_dict(ast.Pass()) == {}
    assert module_walk_mod._string_mapping_from_literal_dict(invalid_exports.value) == {
        "Good": "pkg.good"
    }
    assert module_walk_mod._literal_getattr_name(ast.Pass()) is None
    assert (
        module_walk_mod._literal_getattr_name(
            ast.parse("getattr(obj)", mode="eval").body
        )
        is None
    )
    assert (
        module_walk_mod._literal_getattr_name(
            ast.parse('getattr(obj, "not-valid")', mode="eval").body
        )
        is None
    )
    assert module_walk_mod._collect_dynamic_getattr_names(ast.Pass()) == set()

    tree = ast.parse(
        """
class Runtime:
    def dispatch(self) -> object | None:
        first = second = getattr(self, "multi_lookup", None)
        annotated: object = getattr(self, "annotated_lookup", None)
        ignored = getattr(self, "not-valid", None)
        if callable(first):
            first()
        if callable(annotated):
            annotated()

        def nested() -> None:
            hidden = getattr(self, "nested_lookup", None)
            if callable(hidden):
                hidden()

        class Inner:
            def method(self) -> None:
                inner = getattr(self, "inner_lookup", None)
                if callable(inner):
                    inner()

        return second
"""
    )
    assert module_walk_mod._collect_dynamic_getattr_names(tree) == {
        "annotated_lookup",
        "multi_lookup",
    }


def test_extract_resolves_public_reexports_to_source_symbols() -> None:
    sources = {
        "common": (
            "pkg/common.py",
            "pkg.common",
            """
class MetricValueDTO:
    pass
""",
        ),
        "reexport": (
            "pkg/__init__.py",
            "pkg",
            """
from pkg.common import MetricValueDTO

__all__ = ["MetricValueDTO"]
""",
        ),
        "handlers": (
            "pkg/handlers.py",
            "pkg.handlers",
            """
class ListContainersHandler:
    pass
""",
        ),
        "lazy_exports": (
            "pkg/__init__.py",
            "pkg",
            """
__all__ = ["ListContainersHandler"]

_EXPORTS = {
    "ListContainersHandler": "pkg.handlers",
}

def __getattr__(name: str):
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(name)
    module = __import__(module_path, fromlist=[name])
    value = getattr(module, name)
    globals()[name] = value
    return value
""",
        ),
    }
    metrics = {
        name: _file_metrics_from_source(
            source=source,
            filepath=filepath,
            module_name=module_name,
        )
        for name, (filepath, module_name, source) in sources.items()
    }

    dead_reexports = _dead_qualnames_from_metrics(
        metrics["common"],
        metrics["reexport"],
    )
    dead_lazy = _dead_qualnames_from_metrics(
        metrics["handlers"],
        metrics["lazy_exports"],
    )
    assert "pkg.common:MetricValueDTO" not in dead_reexports
    assert "pkg.handlers:ListContainersHandler" not in dead_lazy


def test_extract_treats_guarded_dynamic_getattr_call_as_runtime_reference() -> None:
    source = """
class Repository:
    def find_latest_artifact_by_format(self, expected_format: str) -> object | None:
        return None

class BootstrapService:
    def __init__(self, repository: object) -> None:
        self._repository = repository

    async def bootstrap(self) -> object | None:
        finder = getattr(self._repository, "find_latest_artifact_by_format", None)
        if not callable(finder):
            return None
        return await finder("onnx")
"""
    dead = set(_dead_qualnames_from_source(source))
    assert "pkg.mod:Repository.find_latest_artifact_by_format" not in dead


def test_extract_ignores_uncalled_dynamic_getattr_probe() -> None:
    source = """
class Repository:
    def find_latest_artifact_by_format(self, expected_format: str) -> object | None:
        return None

class BootstrapService:
    def probe(self) -> bool:
        finder = getattr(self, "find_latest_artifact_by_format", None)
        return callable(finder)
"""
    dead = set(_dead_qualnames_from_source(source))
    assert "pkg.mod:Repository.find_latest_artifact_by_format" in dead


def test_collect_dead_candidates_skips_protocol_and_stub_like_symbols() -> None:
    src = """
from abc import abstractmethod
from typing import Protocol, TypeVar, overload

T = TypeVar("T")

class _Reader(Protocol):
    def read(self) -> str: ...

class _Box(Protocol[T]):
    def get(self) -> T: ...

class _Base:
    @abstractmethod
    def parse(self) -> str:
        raise NotImplementedError

class _DynamicBase(factory()):
    def hook(self) -> str:
        return "runtime"

@overload
def parse_value(value: int) -> str: ...

def parse_value(value: object) -> str:
    return str(value)
    """
    _tree, collector, walk = _collect_module_walk(src)
    dead = module_walk_mod._collect_dead_candidates(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        collector=collector,
        protocol_symbol_aliases=walk.protocol_symbol_aliases,
        protocol_module_aliases=walk.protocol_module_aliases,
    )
    qualnames = {item.qualname for item in dead}
    type_only = {
        "pkg.mod:_Reader",
        "pkg.mod:_Reader.read",
        "pkg.mod:_Box",
        "pkg.mod:_Box.get",
        "pkg.mod:_Base.parse",
    }
    assert qualnames.isdisjoint(type_only)
    assert "pkg.mod:parse_value" in qualnames


def test_collect_dead_candidates_skips_pydantic_hooks_and_dataclass_post_init() -> None:
    source = """
from dataclasses import dataclass
from pydantic import BaseModel, computed_field, field_validator as validate_field
from pydantic.v1 import validator as legacy_validator
import pydantic as pyd

class User(BaseModel):
    @validate_field("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return value

    @pyd.model_validator(mode="after")
    def validate_model(self):
        return self

    @computed_field
    @property
    def display_name(self) -> str:
        return "user"

    @legacy_validator("legacy")
    def validate_legacy(cls, value: str) -> str:
        return value

class Plain:
    def validate_name(self) -> str:
        return "unused"

@dataclass
class Config:
    name: str

    def __post_init__(self) -> None:
        self.name = self.name.strip()

    def helper(self) -> None:
        return None
"""
    _tree, collector, walk = _collect_module_walk(source)
    candidates = module_walk_mod._collect_dead_candidates(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        collector=collector,
        protocol_symbol_aliases=walk.protocol_symbol_aliases,
        protocol_module_aliases=walk.protocol_module_aliases,
        non_runtime_decorator_aliases=walk.non_runtime_decorator_aliases,
        pydantic_module_aliases=walk.pydantic_module_aliases,
    )
    candidate_qualnames = {item.qualname for item in candidates}

    pydantic_hooks = {
        "pkg.mod:User.validate_name",
        "pkg.mod:User.validate_model",
        "pkg.mod:User.display_name",
        "pkg.mod:User.validate_legacy",
    }
    assert candidate_qualnames.isdisjoint(pydantic_hooks)
    assert "pkg.mod:Plain.validate_name" in candidate_qualnames
    assert "pkg.mod:Config.helper" in set(_dead_qualnames_from_source(source))
    assert "pkg.mod:Config.__post_init__" not in set(
        _dead_qualnames_from_source(source)
    )


def test_dead_code_skips_pydantic_field_validators_without_direct_calls() -> None:
    source = """
from typing import Any
from pydantic import BaseModel, Field, field_validator

class AllowedAction(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    parameters: dict[str, Any] | None = Field(default=None)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("parameters")
    @classmethod
    def validate_parameters(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        return value
"""
    assert _dead_qualnames_from_source(source) == ("pkg.mod:AllowedAction",)


def test_dead_code_keeps_explicitly_inherited_abc_base_live() -> None:
    source = """
from abc import ABC, abstractmethod

class _Base(ABC):
    @abstractmethod
    def parse(self) -> str:
        raise NotImplementedError

class _Impl(_Base):
    def parse(self) -> str:
        return "ok"
"""
    qualnames = set(_dead_qualnames_from_source(source))
    assert "pkg.mod:_Base" not in qualnames
    assert "pkg.mod:_Base.parse" not in qualnames
    assert "pkg.mod:_Impl" in qualnames
    assert "pkg.mod:_Impl.parse" in qualnames
    # Explicit rule-3 boundary: _Impl's DIRECT base _Base is local, so the
    # unresolved-external-base predicate never fires and the override stays
    # plainly dead. Abstention must not leak through a local base whose own
    # base happens to be external.
    assert _liveness_status_by_qualname(source)["pkg.mod:_Impl.parse"] == "dead"


def test_extract_syntax_error() -> None:
    with pytest.raises(ParseError):
        extract_units_from_source(
            source="def f(:\n    pass",
            filepath="x.py",
            module_name="mod",
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
        )


def test_extract_respects_min_loc_min_stmt() -> None:
    src = """

def f():
    x = 1
"""
    units, blocks, segments = extract_units_from_source(
        source=src,
        filepath="x.py",
        module_name="mod",
        cfg=NormalizationConfig(),
        min_loc=10,
        min_stmt=10,
    )
    # 39Y Y5: the floors are a clone-lane predicate. The function below them
    # keeps its metric fact and produces no clone-lane artifact.
    assert [unit.qualname for unit in units] == ["mod:f"]
    assert blocks == []
    assert segments == []


def test_extract_block_units_generated() -> None:
    body_lines = "\n".join([f"    x{i} = {i}" for i in range(50)])
    src = f"""

def f():
{body_lines}
"""
    units, blocks, segments = extract_units_from_source(
        source=src,
        filepath="x.py",
        module_name="mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    assert units
    assert blocks
    assert segments


def test_extract_async_function() -> None:
    src = """
async def af():
    return 1
"""
    units, blocks, segments = extract_units_from_source(
        source=src,
        filepath="x.py",
        module_name="mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    assert len(units) == 1
    assert blocks == []
    assert segments == []


def test_extract_handles_long_line() -> None:
    long_line = 'x = "1" * 10000'
    src = f"""
def f():
    {long_line}
"""
    units, blocks, segments = extract_units_from_source(
        source=src,
        filepath="x.py",
        module_name="mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    assert units
    assert blocks == []
    assert segments == []


def test_extract_generates_segments_without_blocks_when_only_segment_gate_met() -> None:
    """Function with 12 stmts in ~36 lines: passes segment gate but not block gate."""
    lines = ["def f():"]
    for i in range(12):
        lines.append(f"    x{i} = {i}")
        lines.append("")
        lines.append("")
    src = "\n".join(lines)

    units, blocks, segments = extract_units_from_source(
        source=src,
        filepath="x.py",
        module_name="mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
        # segment gate passes (loc=37 >= 20, stmt=12 >= 10)
        segment_min_loc=20,
        segment_min_stmt=10,
        # block gate fails (stmt=12 < 15)
        block_min_loc=20,
        block_min_stmt=15,
    )

    assert units
    assert blocks == []
    assert segments


def test_extract_generates_blocks_without_segments_when_only_block_gate_met() -> None:
    """Function with 10 stmts in ~50 lines: passes block gate but not segment gate."""
    lines = ["def f():"]
    for i in range(10):
        lines.append(f"    x{i} = {i}")
        lines.append("")
        lines.append("")
        lines.append("")
        lines.append("")
    src = "\n".join(lines)

    units, blocks, segments = extract_units_from_source(
        source=src,
        filepath="x.py",
        module_name="mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
        # block gate passes (loc=51 >= 20, stmt=10 >= 8)
        block_min_loc=20,
        block_min_stmt=8,
        # segment gate fails (stmt=10 < 12)
        segment_min_loc=20,
        segment_min_stmt=12,
    )

    assert units
    assert blocks
    assert segments == []


class TestAdmissionThresholdBoundaries:
    """Verify function/block/segment admission gates at exact boundaries."""

    @staticmethod
    def _make_func(stmt_count: int, lines_per_stmt: int = 1) -> str:
        """Build a function with configurable statement count and per-statement LOC."""
        lines = ["def f():"]
        for i in range(stmt_count):
            lines.append(f"    x{i} = {i}")
            # pad with blank lines to inflate LOC
            lines.extend([""] * (lines_per_stmt - 1))
        return "\n".join(lines)

    def _extract_with_thresholds(
        self,
        *,
        stmt_count: int,
        lines_per_stmt: int,
        **thresholds: int,
    ) -> tuple[list[Unit], list[BlockUnit], list[SegmentUnit]]:
        return extract_units_from_source(
            source=self._make_func(
                stmt_count=stmt_count,
                lines_per_stmt=lines_per_stmt,
            ),
            filepath="x.py",
            module_name="m",
            cfg=NormalizationConfig(),
            min_loc=thresholds.get("min_loc", 1),
            min_stmt=thresholds.get("min_stmt", 1),
            block_min_loc=thresholds.get("block_min_loc", 20),
            block_min_stmt=thresholds.get("block_min_stmt", 8),
            segment_min_loc=thresholds.get("segment_min_loc", 20),
            segment_min_stmt=thresholds.get("segment_min_stmt", 10),
        )

    # -- function-level: min_loc boundary --

    @pytest.mark.parametrize(
        ("stmt_count", "lines_per_stmt", "thresholds", "expected_count"),
        [
            pytest.param(6, 1, {"min_loc": 10}, 0, id="excluded_below_min_loc"),
            pytest.param(6, 2, {"min_loc": 10}, 1, id="included_at_min_loc"),
            pytest.param(5, 3, {"min_stmt": 6}, 0, id="excluded_below_min_stmt"),
            pytest.param(6, 3, {"min_stmt": 6}, 1, id="included_at_min_stmt"),
        ],
    )
    def test_function_admission_thresholds(
        self,
        stmt_count: int,
        lines_per_stmt: int,
        thresholds: dict[str, int],
        expected_count: int,
    ) -> None:
        # Block floors are dropped below the unit floors so that clone-lane
        # admission is observable: an admitted unit of this size always yields
        # blocks, a rejected one must yield none (39Y Y5).
        units, blocks, _ = self._extract_with_thresholds(
            stmt_count=stmt_count,
            lines_per_stmt=lines_per_stmt,
            block_min_loc=1,
            block_min_stmt=1,
            **thresholds,
        )
        # The metric fact exists at every floor; the boundary verified here is
        # admission to the clone lane.
        assert len(units) == 1
        assert bool(blocks) is bool(expected_count)

    # -- block gate boundary --

    @pytest.mark.parametrize(
        ("kind", "stmt_count", "lines_per_stmt", "expected_present"),
        [
            pytest.param(
                "blocks",
                10,
                1,
                False,
                id="excluded_below_block_min_loc",
            ),
            pytest.param(
                "blocks",
                10,
                2,
                True,
                id="included_at_block_min_loc",
            ),
            pytest.param(
                "blocks",
                7,
                4,
                False,
                id="excluded_below_block_min_stmt",
            ),
            pytest.param(
                "blocks",
                8,
                3,
                True,
                id="included_at_block_min_stmt",
            ),
            pytest.param(
                "segments",
                12,
                1,
                False,
                id="excluded_below_segment_min_loc",
            ),
            pytest.param(
                "segments",
                12,
                2,
                True,
                id="included_at_segment_min_loc",
            ),
            pytest.param(
                "segments",
                9,
                3,
                False,
                id="excluded_below_segment_min_stmt",
            ),
            pytest.param(
                "segments",
                10,
                3,
                True,
                id="included_at_segment_min_stmt",
            ),
        ],
    )
    def test_non_function_admission_thresholds(
        self,
        kind: str,
        stmt_count: int,
        lines_per_stmt: int,
        expected_present: bool,
    ) -> None:
        _, blocks, segments = self._extract_with_thresholds(
            stmt_count=stmt_count,
            lines_per_stmt=lines_per_stmt,
        )
        extracted = blocks if kind == "blocks" else segments
        assert bool(extracted) is expected_present

    # -- boilerplate still excluded --

    def test_short_boilerplate_excluded_with_new_defaults(self) -> None:
        """3-line trivial function stays out of the clone lane."""
        src = "def f():\n    x = 1\n    return x\n"
        units, blocks, segments = extract_units_from_source(
            source=src,
            filepath="x.py",
            module_name="m",
            cfg=NormalizationConfig(),
            min_loc=10,
            min_stmt=6,
            block_min_loc=1,
            block_min_stmt=1,
            segment_min_loc=1,
            segment_min_stmt=1,
        )
        # The unit floors dominate the block/segment floors: the metric fact
        # exists, the clone-lane artifacts do not (39Y Y5).
        assert len(units) == 1
        assert blocks == []
        assert segments == []


def test_extract_handles_non_list_function_body_for_hash_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = ["def f():"]
    for i in range(12):
        lines.append(f"    x{i} = {i}")
        lines.append("")
        lines.append("")
    tree = ast.parse("\n".join(lines))
    func = tree.body[0]
    assert isinstance(func, ast.FunctionDef)
    func.body = tuple(func.body)  # type: ignore[assignment]

    captured_hashes: dict[str, object] = {}

    def _fake_parse(_source: str, _timeout_s: int) -> ast.AST:
        return tree

    helper_name = "_cfg_fingerprint_and_complexity"
    real_fingerprint = getattr(units_mod, helper_name)

    def _fake_fingerprint(
        _node: ast.FunctionDef | ast.AsyncFunctionDef,
        _cfg: NormalizationConfig,
        _qualname: str,
        _bindings: object,
        *,
        phase_ledger: object,
    ) -> tuple[object, str, int]:
        del phase_ledger
        graph, _fingerprint, _complexity = real_fingerprint(
            _node,
            _cfg,
            _qualname,
            _bindings,
        )
        return graph, "f" * 64, 1

    def _fake_extract_segments(
        _node: ast.FunctionDef | ast.AsyncFunctionDef,
        filepath: str,
        qualname: str,
        cfg: NormalizationConfig,
        bindings: object = None,
        window_size: int = 6,
        max_segments: int = 60,
        *,
        precomputed_hashes: list[str] | None = None,
    ) -> list[object]:
        del filepath, qualname, cfg, bindings, window_size, max_segments
        captured_hashes["value"] = precomputed_hashes
        return []

    monkeypatch.setattr(units_mod, "_parse_with_limits", _fake_parse)
    monkeypatch.setattr(units_mod, "_stmt_count", lambda _node: 12)
    monkeypatch.setattr(units_mod, "_cfg_fingerprint_and_complexity", _fake_fingerprint)
    monkeypatch.setattr(units_mod, "extract_segments", _fake_extract_segments)

    units, blocks, segments = extract_units_from_source(
        source="def f():\n    pass\n",
        filepath="x.py",
        module_name="mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )

    assert len(units) == 1
    assert blocks == []
    assert segments == []
    assert captured_hashes["value"] is None


def test_extract_skips_invalid_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    tree = ast.parse(
        """
def f():
    return 1
"""
    )
    func = tree.body[0]
    assert isinstance(func, ast.FunctionDef)
    func.end_lineno = 0

    def _fake_parse(_source: str, _timeout_s: int) -> ast.AST:
        return tree

    monkeypatch.setattr(units_mod, "_parse_with_limits", _fake_parse)
    units, blocks, segments = extract_units_from_source(
        source="def f():\n    return 1\n",
        filepath="x.py",
        module_name="mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    assert units == []
    assert blocks == []
    assert segments == []


def test_extract_distinguishes_call_targets() -> None:
    src = """
def load(x):
    return load_user(x)

def delete(x):
    return delete_user(x)
"""
    units, _, _ = extract_units_from_source(
        source=src,
        filepath="x.py",
        module_name="mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    fps = {u.qualname: u.fingerprint for u in units}
    assert fps["mod:load"] != fps["mod:delete"]


def test_parse_limits_triggers_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_signal(_sig: int, handler: Callable[[int, object], None] | None) -> None:
        if callable(handler):
            handler(_sig, None)
        return None

    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(signal, "getsignal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal, "signal", _fake_signal)
    monkeypatch.setattr(signal, "setitimer", lambda *_args, **_kwargs: None)

    with pytest.raises(ParseError, match="AST parsing timeout"):
        parser_mod._parse_with_limits("x = 1", 1)


def test_runtime_reachability_cast_alias_arity_gates_factory_assignment() -> None:
    """A one-argument ``cast`` alias cannot prove a route factory; the
    two-argument form can."""

    source = """
from typing import cast
from fastapi import FastAPI

app = FastAPI()

def broken_factory(*args, **kwargs):
    bad = cast(app.get)
    return bad("/broken")

def good_factory(*args, **kwargs):
    good = cast(object, app.get)
    return good("/good")

@broken_factory
def broken_handler(request):
    return request

@good_factory
def good_handler(request):
    return request
"""

    by_target = _runtime_reachability_by_target(source)
    good = by_target["pkg.mod:good_handler"]
    assert good.framework == "fastapi"
    assert good.evidence == "route decorator factory"
    assert "pkg.mod:broken_handler" not in by_target


def test_runtime_reachability_first_arg_registration_requires_a_named_object() -> None:
    """A `register_blueprint` argument with no dotted name proves no inclusion;
    a named blueprint argument upgrades its routes to high confidence."""

    dynamic = """
from flask import Blueprint, Flask

def make_blueprint():
    return Blueprint("dyn", __name__)

app = Flask(__name__)
bp = Blueprint("bp", __name__)

@bp.route("/named")
def named_handler():
    return "n"

app.register_blueprint(bp or make_blueprint())
"""
    named = dynamic.replace(
        "app.register_blueprint(bp or make_blueprint())",
        "app.register_blueprint(bp)",
    )

    dynamic_fact = _runtime_reachability_by_target(dynamic)["pkg.mod:named_handler"]
    named_fact = _runtime_reachability_by_target(named)["pkg.mod:named_handler"]
    assert dynamic_fact.confidence == "medium"
    assert named_fact.confidence == "high"


def test_runtime_reachability_skips_type_checking_module_blocks() -> None:
    source = """
from typing import TYPE_CHECKING
from fastapi import FastAPI

app = FastAPI()
FEATURE = True

if TYPE_CHECKING:
    @app.get("/typing-only")
    def typing_only_handler():
        return 0

if FEATURE:
    @app.get("/gated")
    def gated_handler():
        return 1
"""

    by_target = _runtime_reachability_by_target(source)
    assert "pkg.mod:typing_only_handler" not in by_target
    assert by_target["pkg.mod:gated_handler"].framework == "fastapi"


def test_runtime_reachability_covers_async_route_handlers() -> None:
    source = """
from fastapi import FastAPI

app = FastAPI()

@app.get("/async")
async def async_handler():
    return 1
"""

    fact = _runtime_reachability_by_target(source)["pkg.mod:async_handler"]
    assert fact.framework == "fastapi"
    assert fact.confidence == "high"


def test_runtime_reachability_starlette_route_subclass_hooks() -> None:
    """A plain Starlette ``Route`` subclass emits starlette hook facts for its
    overridden hook methods only."""

    source = """
from starlette.routing import Route

class TracingRoute(Route):
    async def handle(self, scope):
        return scope

    def matches(self, scope):
        return super().matches(scope)

    def unrelated(self):
        return None
"""

    by_target = _runtime_reachability_by_target(source)
    fact = by_target["pkg.mod:TracingRoute.matches"]
    assert fact.framework == "starlette"
    assert "Route" in fact.evidence_symbol
    assert by_target["pkg.mod:TracingRoute.handle"].framework == "starlette"
    assert "pkg.mod:TracingRoute.unrelated" not in by_target


def test_runtime_reachability_guarded_nested_route_classes() -> None:
    """A Route subclass nested under `if TYPE_CHECKING:` inside a class body
    emits no hook facts; one under a plain `if` does."""

    source = """
from typing import TYPE_CHECKING

from starlette.routing import Route

class Outer:
    if TYPE_CHECKING:
        class TypedRoute(Route):
            def matches(self, scope):
                return scope
    if True:
        class RealRoute(Route):
            def matches(self, scope):
                return scope
"""

    by_target = _runtime_reachability_by_target(source)
    assert "pkg.mod:Outer.RealRoute.matches" in by_target
    assert "pkg.mod:Outer.TypedRoute.matches" not in by_target


def test_runtime_binding_visitor_type_checking_dispatch_is_guarded() -> None:
    """`visit_If` itself refuses TYPE_CHECKING blocks: no runtime object is
    recorded from a guarded body even when the method is invoked directly."""

    visitor = reachability_mod._RuntimeBindingVisitor()
    visitor.visit(ast.parse("from fastapi import FastAPI\napp = FastAPI()\n"))
    assert visitor.objects == {"app": "fastapi_app"}

    guarded = ast.parse("if TYPE_CHECKING:\n    shadow = FastAPI()\n").body[0]
    assert isinstance(guarded, ast.If)
    visitor.visit_If(guarded)
    assert "shadow" not in visitor.objects

    plain = ast.parse("if enabled:\n    extra = FastAPI()\n").body[0]
    assert isinstance(plain, ast.If)
    visitor.visit_If(plain)
    assert visitor.objects.get("extra") == "fastapi_app"


def test_runtime_reachability_visitor_walk_respects_type_checking_guards() -> None:
    """The visitor's own tree walk skips TYPE_CHECKING subtrees, descends into
    plain conditional subtrees, and dispatches async handlers."""

    source = """
if TYPE_CHECKING:
    class TypedRoute(Route):
        def matches(self, scope):
            return scope

if FEATURE:
    class RealRoute(Route):
        def matches(self, scope):
            return scope

@app.get("/async-walked")
async def async_handler():
    return 1
"""
    tree, collector = _parse_tree_and_collector(source)
    visitor = reachability_mod._RuntimeReachabilityVisitor(
        module_name="pkg.mod",
        filepath="pkg/mod.py",
        collector=collector,
        aliases={"Route": "starlette.routing.Route"},
        runtime_objects={"app": "fastapi_app"},
        included_routers=set(),
        route_decorator_factories={},
    )
    visitor.visit(tree)

    qualnames = {fact.target_qualname for fact in visitor.facts}
    assert "pkg.mod:RealRoute.matches" in qualnames
    assert "pkg.mod:async_handler" in qualnames
    assert "pkg.mod:TypedRoute.matches" not in qualnames


def test_bare_namespace_package_import_classifies_by_prefix() -> None:
    """A target that is only a package prefix (no entry of its own) resolves
    through the prefix's contributing entries."""

    _identity, registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        inventory_modules=("pkg.other",),
    )
    prefixed = dataclasses.replace(
        registry,
        package_prefixes=(
            PackagePrefix(
                module="pkg",
                node_kind="namespace_package",
                mount_paths=(".",),
                contributing_paths=("pkg/mod.py", "pkg/other.py"),
            ),
        ),
    )
    assert module_walk_mod._classify_import_target("pkg", prefixed) == "analyzed"
    # A prefix that does not match the target must not swallow it.
    assert module_walk_mod._classify_import_target("elsewhere", prefixed) == "external"


def test_plain_self_package_import_resolves_as_analyzed() -> None:
    _tree, _collector, walk = _collect_module_walk(
        "import pkg.mod\n",
        module_name="pkg.mod",
    )
    (dep,) = walk.module_deps
    assert dep.resolution == "analyzed"
    assert walk.import_names == frozenset({"pkg"})


def test_extract_dynamic_getattr_binding_requires_name_targets() -> None:
    """A getattr result assigned to an attribute (not a plain name) proves no
    dynamic dispatch, so the probed method stays dead."""

    source = """
class Repository:
    def load_artifact(self) -> object | None:
        return None

class Service:
    def wire(self) -> object:
        budget: int = 3
        self.finder = getattr(Repository, "load_artifact", None)
        return self.finder(budget)
"""
    dead = set(_dead_qualnames_from_source(source))
    assert "pkg.mod:Repository.load_artifact" in dead


def test_override_decorator_is_row_two_liveness_evidence() -> None:
    """`@override` on a method of an externally based class is live evidence;
    an undecorated sibling still abstains."""

    source = """
from typing import override

from external_ui import ExternalBase

class Styled(ExternalBase):
    @override
    def render(self):
        return 1

    def helper(self):
        return 2
"""
    statuses = _liveness_status_by_qualname(source)
    assert statuses["pkg.mod:Styled.render"] == "live"
    assert statuses["pkg.mod:Styled.helper"] == "unresolved_external_override"


def test_conditional_base_expression_is_not_an_external_base() -> None:
    """A conditional base expression contributes no base name: alone it never
    triggers external-base abstention; adding a real external base does."""

    dynamic_only = """
FLAG = True

class BaseA:
    pass

class BaseB:
    pass

class Dynamic(BaseA if FLAG else BaseB):
    def probe(self):
        return 1
"""
    statuses = _liveness_status_by_qualname(dynamic_only)
    assert statuses["pkg.mod:Dynamic.probe"] == "dead"

    with_external = dynamic_only.replace(
        "class Dynamic(BaseA if FLAG else BaseB):",
        "class Dynamic(BaseA if FLAG else BaseB, external_ui.ExternalBase):",
    )
    statuses = _liveness_status_by_qualname("import external_ui\n" + with_external)
    assert statuses["pkg.mod:Dynamic.probe"] == "unresolved_external_override"


def test_neutral_cache_reuse_still_scans_structural_findings() -> None:
    """Threshold-neutral cache reuse must recompute structural findings for
    clone-eligible units instead of dropping them."""

    from codeclone.models import RehydratedCacheNeutral, SemanticFileFacts

    source = """
def fn(x):
    if x == 1:
        y = 1
        return y
    elif x == 2:
        y = 2
        return y
"""
    units, blocks, segments, stats, _metrics, findings = _extract_source(
        source=source,
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    assert [group.finding_kind for group in findings] == ["duplicated_branches"]

    neutral = RehydratedCacheNeutral(
        source_stats=stats,
        units=tuple(units),
        blocks=tuple(blocks),
        segments=tuple(segments),
        semantic_facts=SemanticFileFacts(),
    )
    identity, registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )
    r_units, _b, _s, _stats, _m, r_findings = (
        units_mod.extract_units_and_stats_from_source(
            source,
            "pkg/mod.py",
            identity,
            registry,
            NormalizationConfig(),
            1,
            1,
            collect_structural_findings=True,
            neutral_reuse=neutral,
        )
    )
    assert list(r_units) == list(units)
    assert [group.finding_kind for group in r_findings] == ["duplicated_branches"]


def test_stmt_floor_help_states_what_the_producer_measures() -> None:
    """The stmt floors count top-level body statements, not AST statements.

    ``_stmt_count`` is ``len(node.body)``, so only the outermost statements of a
    function body reach the floors. "AST statement count" names a different
    measurement, and a reader who applies it predicts the opposite eligibility
    verdict for the function below. The help string is therefore pinned to the
    producer's semantics rather than to a literal: the counts here are
    re-derived from the producer, and wording the producer contradicts is
    refused. The docs tables carry the same phrasing; this is their upstream.
    """

    source = textwrap.dedent(
        """\
        def wide(flag):
            if flag:
                a = 1
                b = 2
                c = 3
                d = 4
                e = 5
                f = 6
                return a + b + c + d + e + f
            return 0
        """
    )
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.FunctionDef)

    measured = units_mod._stmt_count(node)
    nested_total = sum(1 for child in ast.walk(node) if isinstance(child, ast.stmt)) - 1

    # What the floors apply to, versus what "AST statements" would name.
    assert measured == 2
    assert nested_total == 9
    assert measured < contracts.DEFAULT_MIN_STMT <= nested_total

    help_text = ui_messages.HELP_MIN_STMT.lower()
    assert "top-level" in help_text
    assert "ast statement" not in help_text
