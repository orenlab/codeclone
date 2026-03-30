# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

import ast
import os
import signal
import sys
import tokenize
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import cast

import pytest

from codeclone import extractor
from codeclone.errors import ParseError
from codeclone.metrics import find_unused
from codeclone.models import BlockUnit, ClassMetrics, ModuleDep, SegmentUnit
from codeclone.normalize import NormalizationConfig


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
    list[extractor.Unit],
    list[BlockUnit],
    list[SegmentUnit],
]:
    units, blocks, segments, _source_stats, _file_metrics, _sf = (
        extractor.extract_units_and_stats_from_source(
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
    )
    return units, blocks, segments


def _parse_tree_and_collector(
    source: str,
) -> tuple[ast.Module, extractor._QualnameCollector]:
    tree = ast.parse(source)
    collector = extractor._QualnameCollector()
    collector.visit(tree)
    return tree, collector


def _collect_module_walk(
    source: str,
    *,
    module_name: str = "pkg.mod",
    collect_referenced_names: bool = True,
) -> tuple[ast.Module, extractor._QualnameCollector, extractor._ModuleWalkResult]:
    tree, collector = _parse_tree_and_collector(source)
    walk = extractor._collect_module_walk_data(
        tree=tree,
        module_name=module_name,
        collector=collector,
        collect_referenced_names=collect_referenced_names,
    )
    return tree, collector, walk


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
    assert extractor._source_tokens('"""') == ()


def test_declaration_token_index_returns_none_when_start_token_is_missing() -> None:
    tokens = extractor._source_tokens("value = 1\n")
    assert (
        extractor._declaration_token_index(
            source_tokens=tokens,
            start_line=1,
            start_col=0,
            declaration_token="def",
        )
        is None
    )


def test_declaration_token_index_uses_prebuilt_index() -> None:
    tokens = extractor._source_tokens("async def demo():\n    return 1\n")
    token_index = extractor._build_declaration_token_index(tokens)

    assert (
        extractor._declaration_token_index(
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
    assert extractor._declaration_token_name(async_node) == "async"

    tokens = extractor._source_tokens("def demo():\n    return 1\n")
    assert (
        extractor._declaration_token_index(
            source_tokens=tokens,
            start_line=1,
            start_col=0,
            declaration_token="def",
        )
        == 0
    )

    nested_tokens = extractor._source_tokens(
        "def demo(arg: tuple[int, int]) -> tuple[int, int]:\n    return arg\n"
    )
    assert (
        extractor._scan_declaration_colon_line(
            source_tokens=nested_tokens,
            start_index=0,
        )
        == 1
    )

    default_tokens = extractor._source_tokens(
        "def demo(arg=(1, [2])):\n    return arg\n"
    )
    assert (
        extractor._scan_declaration_colon_line(
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
        extractor._scan_declaration_colon_line(
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
        extractor._scan_declaration_colon_line(
            source_tokens=unmatched_close_tokens,
            start_index=0,
        )
        is None
    )


def test_scan_declaration_colon_line_returns_none_when_header_is_incomplete() -> None:
    tokens = extractor._source_tokens("def broken\n")
    assert (
        extractor._scan_declaration_colon_line(
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
    assert extractor._declaration_end_line(node, source_tokens=()) == 2


def test_declaration_end_line_returns_zero_for_invalid_start_line() -> None:
    node = ast.parse(
        """
def broken():
    return 1
"""
    ).body[0]
    assert isinstance(node, ast.FunctionDef)
    node.lineno = 0
    assert extractor._declaration_end_line(node, source_tokens=()) == 0


def test_declaration_fallback_helpers_cover_empty_and_same_line_bodies() -> None:
    empty_body_node = ast.parse(
        """
def demo():
    return 1
"""
    ).body[0]
    assert isinstance(empty_body_node, ast.FunctionDef)
    empty_body_node.body = []
    assert extractor._fallback_declaration_end_line(empty_body_node, start_line=2) == 2

    inline_body_node = ast.parse(
        """
def demo():
    return 1
"""
    ).body[0]
    assert isinstance(inline_body_node, ast.FunctionDef)
    inline_body_node.body[0].lineno = 2
    assert extractor._fallback_declaration_end_line(inline_body_node, start_line=2) == 2

    no_colon_tokens = (
        tokenize.TokenInfo(tokenize.NAME, "def", (2, 0), (2, 3), "def demo"),
        tokenize.TokenInfo(tokenize.NAME, "demo", (2, 4), (2, 8), "def demo"),
    )
    assert (
        extractor._declaration_end_line(
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


def test_extract_units_skips_suppression_tokenization_without_directives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        extractor,
        "_source_tokens",
        lambda _source: (_ for _ in ()).throw(
            AssertionError("_source_tokens should not be called")
        ),
    )

    units, blocks, segments = extract_units_from_source(
        source="""
def foo():
    a = 1
    return a
""",
        filepath="x.py",
        module_name="mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )

    assert len(units) == 1
    assert blocks == []
    assert segments == []


def test_extract_units_skips_suppression_tokenization_for_leading_only_directives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        extractor,
        "_source_tokens",
        lambda _source: (_ for _ in ()).throw(
            AssertionError("_source_tokens should not be called")
        ),
    )

    units, blocks, segments = extract_units_from_source(
        source="""
# codeclone: ignore[dead-code]
def foo():
    a = 1
    return a
""",
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
    original_source_tokens = extractor._source_tokens

    def _record_tokens(source: str) -> tuple[tokenize.TokenInfo, ...]:
        nonlocal calls
        calls += 1
        return original_source_tokens(source)

    monkeypatch.setattr(extractor, "_source_tokens", _record_tokens)

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
    _units, _blocks, _segments, _source_stats, _file_metrics, sf = (
        extractor.extract_units_and_stats_from_source(
            source=src,
            filepath="x.py",
            module_name="mod",
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
            collect_structural_findings=False,
        )
    )
    assert sf == []


def test_parse_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def _boom(_timeout_s: int) -> Iterator[None]:
        raise extractor._ParseTimeoutError("AST parsing timeout")
        if False:
            yield

    monkeypatch.setattr(extractor, "_parse_limits", _boom)

    with pytest.raises(ParseError, match="AST parsing timeout"):
        extractor._parse_with_limits("x = 1", 1)


def test_parse_limits_no_timeout() -> None:
    with extractor._parse_limits(0):
        tree = extractor._parse_with_limits("x = 1", 0)
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

    with extractor._parse_limits(1):
        tree = extractor._parse_with_limits("x = 1", 1)
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

    with extractor._parse_limits(5):
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

    with extractor._parse_limits(5):
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

    with extractor._parse_limits(5):
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

    with extractor._parse_limits(5):
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
    with extractor._parse_limits(5):
        pass


def test_resolve_import_target_absolute_and_relative() -> None:
    absolute = ast.ImportFrom(module="pkg.util", names=[], level=0)
    assert extractor._resolve_import_target("root.mod.sub", absolute) == "pkg.util"

    relative = ast.ImportFrom(module="helpers", names=[], level=1)
    assert (
        extractor._resolve_import_target("root.mod.sub", relative) == "root.mod.helpers"
    )

    relative_no_module = ast.ImportFrom(module=None, names=[], level=2)
    assert (
        extractor._resolve_import_target("root.mod.sub", relative_no_module) == "root"
    )


def test_collect_module_walk_data_imports_and_references() -> None:
    tree = ast.parse(
        """
import os as operating_system
import json
from .pkg import utils
from .. import parent

value = obj.attr
foo()
obj.method()
""".strip()
    )
    collector = extractor._QualnameCollector()
    collector.visit(tree)
    walk = extractor._collect_module_walk_data(
        tree=tree,
        module_name="root.mod.sub",
        collector=collector,
        collect_referenced_names=True,
    )
    assert walk.import_names == frozenset({"operating_system", "json", "root"})
    assert walk.module_deps == (
        ModuleDep(
            source="root.mod.sub",
            target="json",
            import_type="import",
            line=2,
        ),
        ModuleDep(
            source="root.mod.sub",
            target="os",
            import_type="import",
            line=1,
        ),
        ModuleDep(
            source="root.mod.sub",
            target="root",
            import_type="from_import",
            line=4,
        ),
        ModuleDep(
            source="root.mod.sub",
            target="root.mod.pkg",
            import_type="from_import",
            line=3,
        ),
    )
    assert walk.referenced_names == frozenset({"obj", "attr", "foo", "method"})


def test_collect_module_walk_data_edge_branches() -> None:
    tree = ast.parse("from .... import parent")
    collector = extractor._QualnameCollector()
    collector.visit(tree)
    walk = extractor._collect_module_walk_data(
        tree=tree,
        module_name="pkg.mod",
        collector=collector,
        collect_referenced_names=True,
    )
    assert walk.import_names == frozenset()
    assert walk.module_deps == ()
    assert walk.referenced_names == frozenset()

    lambda_call_tree = ast.parse("(lambda x: x)(1)")
    lambda_collector = extractor._QualnameCollector()
    lambda_collector.visit(lambda_call_tree)
    lambda_walk = extractor._collect_module_walk_data(
        tree=lambda_call_tree,
        module_name="pkg.mod",
        collector=lambda_collector,
        collect_referenced_names=True,
    )
    assert lambda_walk.referenced_names == frozenset({"x"})


def test_collect_module_walk_data_without_referenced_name_collection() -> None:
    tree = ast.parse(
        """
import os as operating_system
from .pkg import utils
from .... import parent
""".strip()
    )
    collector = extractor._QualnameCollector()
    collector.visit(tree)
    walk = extractor._collect_module_walk_data(
        tree=tree,
        module_name="root.mod.sub",
        collector=collector,
        collect_referenced_names=False,
    )
    assert walk.import_names == frozenset({"operating_system", "root"})
    assert walk.module_deps == (
        ModuleDep(
            source="root.mod.sub",
            target="os",
            import_type="import",
            line=1,
        ),
        ModuleDep(
            source="root.mod.sub",
            target="root.mod.pkg",
            import_type="from_import",
            line=2,
        ),
    )
    assert walk.referenced_names == frozenset()


def test_module_walk_helpers_cover_import_and_reference_branches() -> None:
    state = extractor._ModuleWalkState()
    import_node = cast(
        ast.Import,
        ast.parse("import typing_extensions as te").body[0],
    )
    extractor._collect_import_node(
        node=import_node,
        module_name="pkg.mod",
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
    extractor._collect_import_from_node(
        node=import_from_node,
        module_name="pkg.mod",
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
    extractor._collect_import_from_node(
        node=unresolved_import,
        module_name="pkg.mod",
        state=state,
        collect_referenced_names=True,
    )
    assert "parent" not in state.imported_symbol_bindings

    name_node = cast(ast.Name, ast.parse("value", mode="eval").body)
    attr_node = cast(ast.Attribute, ast.parse("obj.attr", mode="eval").body)
    extractor._collect_load_reference_node(node=name_node, state=state)
    extractor._collect_load_reference_node(node=attr_node, state=state)
    extractor._collect_load_reference_node(
        node=cast(ast.Constant, ast.parse("1", mode="eval").body),
        state=state,
    )
    assert "value" in state.referenced_names
    assert "attr" in state.referenced_names


def test_dotted_expr_protocol_detection_and_runtime_candidate_edges() -> None:
    dotted_expr = ast.parse("pkg.helpers.decorate", mode="eval").body
    assert extractor._dotted_expr_name(dotted_expr) == "pkg.helpers.decorate"
    assert extractor._dotted_expr_name(ast.parse("custom()", mode="eval").body) is None

    tree = ast.parse(
        """
import typing_extensions as te

class A(te.Protocol):
    pass

class B(te.Protocol[int]):
    pass
""".strip()
    )
    collector = extractor._QualnameCollector()
    collector.visit(tree)
    walk = extractor._collect_module_walk_data(
        tree=tree,
        module_name="pkg.mod",
        collector=collector,
        collect_referenced_names=True,
    )
    protocol_symbol_aliases = walk.protocol_symbol_aliases
    protocol_module_aliases = walk.protocol_module_aliases
    assert "te" in protocol_module_aliases
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    class_a, class_b = classes
    assert extractor._is_protocol_class(
        class_a,
        protocol_symbol_aliases=protocol_symbol_aliases,
        protocol_module_aliases=protocol_module_aliases,
    )
    assert not extractor._is_protocol_class(
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
    assert extractor._is_non_runtime_candidate(runtime_candidate)


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
    state = extractor._ModuleWalkState()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            extractor._collect_import_node(
                node=node,
                module_name="pkg.mod",
                state=state,
                collect_referenced_names=True,
            )
        elif isinstance(node, ast.ImportFrom):
            extractor._collect_import_from_node(
                node=node,
                module_name="pkg.mod",
                state=state,
                collect_referenced_names=True,
            )
        else:
            extractor._collect_load_reference_node(node=node, state=state)

    resolved = extractor._resolve_referenced_qualnames(
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
    assert extractor._dotted_expr_name(expr) is None

    protocol_class = ast.parse(
        """
class Demo(Unknown, alias.Protocol):
    pass
"""
    ).body[0]
    assert isinstance(protocol_class, ast.ClassDef)
    assert (
        extractor._is_protocol_class(
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
    assert extractor._eligible_unit_shape(bad_span_node, min_loc=1, min_stmt=1) is None

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
        extractor._collect_declaration_targets(
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
    monkeypatch.setattr(extractor, "_source_tokens", lambda _source: ())
    suppression_index = extractor._build_suppression_index_for_source(
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
    _, _, _, _, test_metrics, _ = extractor.extract_units_and_stats_from_source(
        source=src,
        filepath="pkg/tests/test_usage.py",
        module_name="pkg.tests.test_usage",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    _, _, _, _, regular_metrics, _ = extractor.extract_units_and_stats_from_source(
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
    _, _, _, _, file_metrics, _ = extractor.extract_units_and_stats_from_source(
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

    _, _, _, _, prod_metrics, _ = extractor.extract_units_and_stats_from_source(
        source=src_prod,
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    _, _, _, _, test_metrics, _ = extractor.extract_units_and_stats_from_source(
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


def test_dead_code_skips_module_pep562_hooks() -> None:
    src = """
def __getattr__(name: str):
    raise AttributeError(name)

def __dir__():
    return ["demo"]

def orphan():
    return 1
"""
    _, _, _, _, file_metrics, _ = extractor.extract_units_and_stats_from_source(
        source=src,
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    dead = find_unused(
        definitions=file_metrics.dead_candidates,
        referenced_names=file_metrics.referenced_names,
        referenced_qualnames=file_metrics.referenced_qualnames,
    )
    assert tuple(item.qualname for item in dead) == ("pkg.mod:orphan",)


def test_dead_code_applies_inline_suppression_per_declaration() -> None:
    src = """
# codeclone: ignore[dead-code]
def runtime_hook():
    return 1

def orphan():
    return 2
"""
    _, _, _, _, file_metrics, _ = extractor.extract_units_and_stats_from_source(
        source=src,
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    dead = find_unused(
        definitions=file_metrics.dead_candidates,
        referenced_names=file_metrics.referenced_names,
        referenced_qualnames=file_metrics.referenced_qualnames,
    )
    assert tuple(item.qualname for item in dead) == ("pkg.mod:orphan",)


def test_dead_code_suppression_binding_is_scoped_to_target_symbol() -> None:
    src = """
class Service:  # codeclone: ignore[dead-code]
    # codeclone: ignore[dead-code]
    def hook(self):
        return 1

    def alive(self):
        return 2
"""
    _, _, _, _, file_metrics, _ = extractor.extract_units_and_stats_from_source(
        source=src,
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    dead = find_unused(
        definitions=file_metrics.dead_candidates,
        referenced_names=file_metrics.referenced_names,
        referenced_qualnames=file_metrics.referenced_qualnames,
    )
    assert tuple(item.qualname for item in dead) == ("pkg.mod:Service.alive",)


def test_dead_code_binds_inline_suppression_on_multiline_decorated_method() -> None:
    src = """
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
"""
    _, _, _, _, file_metrics, _ = extractor.extract_units_and_stats_from_source(
        source=src,
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    dead = find_unused(
        definitions=file_metrics.dead_candidates,
        referenced_names=file_metrics.referenced_names,
        referenced_qualnames=file_metrics.referenced_qualnames,
    )
    assert tuple(item.qualname for item in dead) == ("pkg.mod:Settings.orphan",)


def test_dead_code_binds_inline_suppression_on_multiline_header_start_line() -> None:
    src = """
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
"""
    _, _, _, _, file_metrics, _ = extractor.extract_units_and_stats_from_source(
        source=src,
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    dead = find_unused(
        definitions=file_metrics.dead_candidates,
        referenced_names=file_metrics.referenced_names,
        referenced_qualnames=file_metrics.referenced_qualnames,
    )
    assert tuple(item.qualname for item in dead) == ("pkg.mod:Settings.orphan",)


def test_collect_dead_candidates_and_extract_skip_classes_without_lineno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = extractor._QualnameCollector()
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
    dead = extractor._collect_dead_candidates(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        collector=collector,
    )
    assert all(item.qualname != "pkg.mod:Broken" for item in dead)

    class _CollectorNoClassMetrics:
        def __init__(self) -> None:
            self.units: list[tuple[str, extractor.FunctionNode]] = []
            self.class_nodes = [("Broken", broken_class)]
            self.function_count = 0
            self.method_count = 0
            self.class_count = 1

        def visit(self, _tree: ast.AST) -> None:
            return None

    monkeypatch.setattr(extractor, "_QualnameCollector", _CollectorNoClassMetrics)
    _, _, _, _, file_metrics, _ = extractor.extract_units_and_stats_from_source(
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
    _, _, _, _, file_metrics, _ = extractor.extract_units_and_stats_from_source(
        source=src,
        filepath="pkg/cli.py",
        module_name="pkg.cli",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )
    assert "pkg.runtime:run" in file_metrics.referenced_qualnames
    assert "pkg.helpers:decorate" in file_metrics.referenced_qualnames


def test_collect_dead_candidates_skips_protocol_and_stub_like_symbols() -> None:
    src = """
from abc import abstractmethod
from typing import Protocol, overload

class _Reader(Protocol):
    def read(self) -> str: ...

class _Base:
    @abstractmethod
    def parse(self) -> str:
        raise NotImplementedError

@overload
def parse_value(value: int) -> str: ...

def parse_value(value: object) -> str:
    return str(value)
    """
    _tree, collector, walk = _collect_module_walk(src)
    dead = extractor._collect_dead_candidates(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        collector=collector,
        protocol_symbol_aliases=walk.protocol_symbol_aliases,
        protocol_module_aliases=walk.protocol_module_aliases,
    )
    qualnames = {item.qualname for item in dead}
    assert "pkg.mod:_Reader.read" not in qualnames
    assert "pkg.mod:_Base.parse" not in qualnames
    assert "pkg.mod:parse_value" in qualnames


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
    assert units == []
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

    # -- function-level: min_loc boundary --

    def test_function_excluded_below_min_loc(self) -> None:
        src = self._make_func(stmt_count=6, lines_per_stmt=1)  # 7 lines
        units, _, _ = extract_units_from_source(
            source=src,
            filepath="x.py",
            module_name="m",
            cfg=NormalizationConfig(),
            min_loc=10,
            min_stmt=1,
        )
        assert units == []

    def test_function_included_at_min_loc(self) -> None:
        src = self._make_func(stmt_count=6, lines_per_stmt=2)  # 13 lines
        units, _, _ = extract_units_from_source(
            source=src,
            filepath="x.py",
            module_name="m",
            cfg=NormalizationConfig(),
            min_loc=10,
            min_stmt=1,
        )
        assert len(units) == 1

    # -- function-level: min_stmt boundary --

    def test_function_excluded_below_min_stmt(self) -> None:
        src = self._make_func(stmt_count=5, lines_per_stmt=3)  # 16 lines, 5 stmts
        units, _, _ = extract_units_from_source(
            source=src,
            filepath="x.py",
            module_name="m",
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=6,
        )
        assert units == []

    def test_function_included_at_min_stmt(self) -> None:
        src = self._make_func(stmt_count=6, lines_per_stmt=3)  # 19 lines, 6 stmts
        units, _, _ = extract_units_from_source(
            source=src,
            filepath="x.py",
            module_name="m",
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=6,
        )
        assert len(units) == 1

    # -- block gate boundary --

    def test_blocks_excluded_below_block_min_loc(self) -> None:
        src = self._make_func(stmt_count=10, lines_per_stmt=1)  # 11 lines, 10 stmts
        _, blocks, _ = extract_units_from_source(
            source=src,
            filepath="x.py",
            module_name="m",
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
            block_min_loc=20,
            block_min_stmt=8,
        )
        assert blocks == []

    def test_blocks_included_at_block_min_loc(self) -> None:
        src = self._make_func(stmt_count=10, lines_per_stmt=2)  # 21 lines, 10 stmts
        _, blocks, _ = extract_units_from_source(
            source=src,
            filepath="x.py",
            module_name="m",
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
            block_min_loc=20,
            block_min_stmt=8,
        )
        assert blocks

    def test_blocks_excluded_below_block_min_stmt(self) -> None:
        src = self._make_func(stmt_count=7, lines_per_stmt=4)  # 29 lines, 7 stmts
        _, blocks, _ = extract_units_from_source(
            source=src,
            filepath="x.py",
            module_name="m",
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
            block_min_loc=20,
            block_min_stmt=8,
        )
        assert blocks == []

    def test_blocks_included_at_block_min_stmt(self) -> None:
        src = self._make_func(stmt_count=8, lines_per_stmt=3)  # 25 lines, 8 stmts
        _, blocks, _ = extract_units_from_source(
            source=src,
            filepath="x.py",
            module_name="m",
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
            block_min_loc=20,
            block_min_stmt=8,
        )
        assert blocks

    # -- segment gate boundary --

    def test_segments_excluded_below_segment_min_loc(self) -> None:
        src = self._make_func(stmt_count=12, lines_per_stmt=1)  # 13 lines, 12 stmts
        _, _, segments = extract_units_from_source(
            source=src,
            filepath="x.py",
            module_name="m",
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
            segment_min_loc=20,
            segment_min_stmt=10,
        )
        assert segments == []

    def test_segments_included_at_segment_min_loc(self) -> None:
        src = self._make_func(stmt_count=12, lines_per_stmt=2)  # 25 lines, 12 stmts
        _, _, segments = extract_units_from_source(
            source=src,
            filepath="x.py",
            module_name="m",
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
            segment_min_loc=20,
            segment_min_stmt=10,
        )
        assert segments

    def test_segments_excluded_below_segment_min_stmt(self) -> None:
        src = self._make_func(stmt_count=9, lines_per_stmt=3)  # 28 lines, 9 stmts
        _, _, segments = extract_units_from_source(
            source=src,
            filepath="x.py",
            module_name="m",
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
            segment_min_loc=20,
            segment_min_stmt=10,
        )
        assert segments == []

    def test_segments_included_at_segment_min_stmt(self) -> None:
        src = self._make_func(stmt_count=10, lines_per_stmt=3)  # 31 lines, 10 stmts
        _, _, segments = extract_units_from_source(
            source=src,
            filepath="x.py",
            module_name="m",
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
            segment_min_loc=20,
            segment_min_stmt=10,
        )
        assert segments

    # -- boilerplate still excluded --

    def test_short_boilerplate_excluded_with_new_defaults(self) -> None:
        """3-line trivial function stays out even with lowered thresholds."""
        src = "def f():\n    x = 1\n    return x\n"
        units, blocks, segments = extract_units_from_source(
            source=src,
            filepath="x.py",
            module_name="m",
            cfg=NormalizationConfig(),
            min_loc=10,
            min_stmt=6,
        )
        assert units == []
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

    def _fake_fingerprint(
        _node: ast.FunctionDef | ast.AsyncFunctionDef,
        _cfg: NormalizationConfig,
        _qualname: str,
    ) -> tuple[str, int]:
        return "f" * 40, 1

    def _fake_extract_segments(
        _node: ast.FunctionDef | ast.AsyncFunctionDef,
        filepath: str,
        qualname: str,
        cfg: NormalizationConfig,
        window_size: int = 6,
        max_segments: int = 60,
        *,
        precomputed_hashes: list[str] | None = None,
    ) -> list[object]:
        del filepath, qualname, cfg, window_size, max_segments
        captured_hashes["value"] = precomputed_hashes
        return []

    monkeypatch.setattr(extractor, "_parse_with_limits", _fake_parse)
    monkeypatch.setattr(extractor, "_stmt_count", lambda _node: 12)
    monkeypatch.setattr(extractor, "_cfg_fingerprint_and_complexity", _fake_fingerprint)
    monkeypatch.setattr(extractor, "extract_segments", _fake_extract_segments)

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

    monkeypatch.setattr(extractor, "_parse_with_limits", _fake_parse)
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
        extractor._parse_with_limits("x = 1", 1)
