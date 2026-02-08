import ast

from codeclone.blocks import extract_segments
from codeclone.normalize import NormalizationConfig


def test_extract_segments_windows() -> None:
    src = """
def f():
    a = 1
    b = 2
    c = 3
"""
    func = ast.parse(src).body[0]
    assert isinstance(func, ast.FunctionDef)
    segments = extract_segments(
        func,
        filepath="x.py",
        qualname="mod:f",
        cfg=NormalizationConfig(),
        window_size=2,
        max_segments=10,
    )
    assert len(segments) == 2
    assert segments[0].size == 2


def test_extract_segments_short_function() -> None:
    src = """
def f():
    a = 1
"""
    func = ast.parse(src).body[0]
    assert isinstance(func, ast.FunctionDef)
    segments = extract_segments(
        func,
        filepath="x.py",
        qualname="mod:f",
        cfg=NormalizationConfig(),
        window_size=3,
        max_segments=10,
    )
    assert segments == []


def test_extract_segments_missing_lineno_and_max_limit() -> None:
    src = """
def f():
    a = 1
    b = 2
    c = 3
    d = 4
"""
    func = ast.parse(src).body[0]
    assert isinstance(func, ast.FunctionDef)
    func.body[0].lineno = 0
    segments = extract_segments(
        func,
        filepath="x.py",
        qualname="mod:f",
        cfg=NormalizationConfig(),
        window_size=2,
        max_segments=1,
    )
    assert len(segments) == 1


def test_extract_segments_signature_orderless() -> None:
    src1 = """
def f():
    a = 1
    b = 2
"""
    src2 = """
def f():
    b = 2
    a = 1
"""
    func1 = ast.parse(src1).body[0]
    func2 = ast.parse(src2).body[0]
    assert isinstance(func1, ast.FunctionDef)
    assert isinstance(func2, ast.FunctionDef)
    cfg = NormalizationConfig(
        normalize_names=False,
        normalize_attributes=False,
        normalize_constants=False,
    )
    seg1 = extract_segments(
        func1,
        filepath="x.py",
        qualname="mod:f",
        cfg=cfg,
        window_size=2,
        max_segments=10,
    )[0]
    seg2 = extract_segments(
        func2,
        filepath="x.py",
        qualname="mod:f",
        cfg=cfg,
        window_size=2,
        max_segments=10,
    )[0]
    assert seg1.segment_sig == seg2.segment_sig
    assert seg1.segment_hash != seg2.segment_hash
