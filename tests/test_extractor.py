import ast
import os
import signal
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest

from codeclone import extractor
from codeclone.errors import ParseError
from codeclone.extractor import extract_units_from_source
from codeclone.normalize import NormalizationConfig


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
