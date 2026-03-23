import ast
import os
import signal
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import cast

import pytest

from codeclone import extractor
from codeclone.errors import ParseError
from codeclone.metrics import find_unused
from codeclone.models import BlockUnit, ModuleDep, SegmentUnit
from codeclone.normalize import NormalizationConfig


def extract_units_from_source(
    *,
    source: str,
    filepath: str,
    module_name: str,
    cfg: NormalizationConfig,
    min_loc: int,
    min_stmt: int,
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
        )
    )
    return units, blocks, segments


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

    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(signal, "getsignal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal, "signal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal, "setitimer", lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, "resource", _DummyResource)

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

    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(signal, "getsignal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal, "signal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal, "setitimer", lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, "resource", _DummyResource)

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

    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(signal, "getsignal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal, "signal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal, "setitimer", lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, "resource", _DummyResource)

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

    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(signal, "getsignal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal, "signal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal, "setitimer", lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, "resource", _DummyResource)

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

    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(signal, "getsignal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal, "signal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal, "setitimer", lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, "resource", _DummyResource)

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
    tree = ast.parse(src)
    collector = extractor._QualnameCollector()
    collector.visit(tree)
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
    tree = ast.parse(src)
    collector = extractor._QualnameCollector()
    collector.visit(tree)
    walk = extractor._collect_module_walk_data(
        tree=tree,
        module_name="pkg.mod",
        collector=collector,
        collect_referenced_names=True,
    )
    assert "pkg.mod:Service.hook" in walk.referenced_qualnames
    assert "pkg.helpers:tools" in walk.referenced_qualnames
    assert "pkg.helpers:decorate" not in walk.referenced_qualnames


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
    tree = ast.parse(src)
    collector = extractor._QualnameCollector()
    collector.visit(tree)
    walk = extractor._collect_module_walk_data(
        tree=tree,
        module_name="pkg.mod",
        collector=collector,
        collect_referenced_names=True,
    )
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
    )

    assert units
    assert blocks == []
    assert segments


def test_extract_generates_blocks_without_segments_when_only_block_gate_met() -> None:
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
    )

    assert units
    assert blocks
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
