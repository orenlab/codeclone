import ast

from codeclone.normalize import NormalizationConfig, normalized_ast_dump


def test_normalization_ignores_variable_names():
    src1 = """
def f():
    x = 1
    return x
"""
    src2 = """
def f():
    y = 2
    return y
"""

    cfg = NormalizationConfig()
    a1 = ast.parse(src1).body[0]
    a2 = ast.parse(src2).body[0]

    assert normalized_ast_dump(a1, cfg) == normalized_ast_dump(a2, cfg)
