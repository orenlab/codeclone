from codeclone.extractor import extract_units_from_source
from codeclone.normalize import NormalizationConfig


def test_extracts_function_unit():
    src = """
def foo():
    a = 1
    b = 2
    return a + b
"""

    units, blocks = extract_units_from_source(
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


def test_init_function_is_ignored_for_blocks():
    src = """
class A:
    def __init__(self):
        x = 1
        y = 2
        z = 3
        w = 4
"""

    units, blocks = extract_units_from_source(
        source=src,
        filepath="x.py",
        module_name="mod",
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
    )

    assert len(units) == 1
    assert blocks == []
