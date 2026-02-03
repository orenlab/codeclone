import ast

from codeclone.blocks import extract_blocks
from codeclone.normalize import NormalizationConfig


def test_extracts_non_overlapping_blocks() -> None:
    src = """
def f():
    a = 1
    b = 2
    c = 3
    d = 4
    e = 5
    f = 6
"""

    func = ast.parse(src).body[0]

    blocks = extract_blocks(
        func,
        filepath="x.py",
        qualname="mod:f",
        cfg=NormalizationConfig(),
        block_size=4,
        max_blocks=10,
    )

    # With MIN_LINE_DISTANCE filtering we expect <= 2 blocks
    assert len(blocks) <= 2
    for b in blocks:
        assert b.size == 4


def test_extract_blocks_empty_or_short() -> None:
    short = ast.parse(
        """
def f():
    a = 1
"""
    ).body[0]
    blocks = extract_blocks(
        short,
        filepath="x.py",
        qualname="mod:f",
        cfg=NormalizationConfig(),
        block_size=4,
        max_blocks=10,
    )
    assert blocks == []

    assign = ast.parse("x = 1").body[0]
    blocks2 = extract_blocks(
        assign,
        filepath="x.py",
        qualname="mod:assign",
        cfg=NormalizationConfig(),
        block_size=1,
        max_blocks=10,
    )
    assert blocks2 == []


def test_extract_blocks_missing_lineno_skips() -> None:
    func = ast.parse(
        """
def f():
    a = 1
    b = 2
    c = 3
    d = 4
"""
    ).body[0]
    assert isinstance(func, ast.FunctionDef)
    func.body[0].lineno = 0
    blocks = extract_blocks(
        func,
        filepath="x.py",
        qualname="mod:f",
        cfg=NormalizationConfig(),
        block_size=4,
        max_blocks=10,
    )
    assert blocks == []


def test_extract_blocks_max_blocks_limit() -> None:
    func = ast.parse(
        """
def f():
    a = 1
    b = 2
    c = 3
    d = 4
    e = 5
    f = 6
"""
    ).body[0]
    blocks = extract_blocks(
        func,
        filepath="x.py",
        qualname="mod:f",
        cfg=NormalizationConfig(),
        block_size=2,
        max_blocks=1,
    )
    assert len(blocks) == 1
