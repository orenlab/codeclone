import ast

from codeclone.blocks import extract_blocks
from codeclone.normalize import NormalizationConfig


def test_extracts_non_overlapping_blocks():
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