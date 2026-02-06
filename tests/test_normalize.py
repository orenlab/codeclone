import ast
from typing import Any, cast

import pytest

import codeclone.normalize as normalize_mod
from codeclone.meta_markers import CFG_META_PREFIX
from codeclone.normalize import (
    NormalizationConfig,
    normalized_ast_dump,
    normalized_ast_dump_from_list,
)


@pytest.mark.parametrize(
    ("src1", "src2"),
    [
        (
            """
def f():
    x = 1
    return x
""",
            """
def f():
    y = 2
    return y
""",
        ),
        (
            '''
def f():
    """doc"""
    x = 1
    return x
''',
            """
def f():
    x = 1
    return x
""",
        ),
    ],
    ids=["ignore_var_names", "drop_docstring"],
)
def test_normalization_equivalent_sources(src1: str, src2: str) -> None:
    cfg = NormalizationConfig()
    a1 = ast.parse(src1).body[0]
    a2 = ast.parse(src2).body[0]
    assert normalized_ast_dump(a1, cfg) == normalized_ast_dump(a2, cfg)


def test_normalization_type_annotations_removed() -> None:
    src1 = """
def f(x: int) -> int:
    return x
"""
    src2 = """
def f(x):
    return x
"""
    cfg = NormalizationConfig()
    a1 = ast.parse(src1).body[0]
    a2 = ast.parse(src2).body[0]
    assert normalized_ast_dump(a1, cfg) == normalized_ast_dump(a2, cfg)


def test_normalization_attributes_and_constants() -> None:
    src1 = """
def f():
    obj.attr = 123
"""
    src2 = """
def f():
    x.y = 999
"""
    cfg = NormalizationConfig()
    a1 = ast.parse(src1).body[0]
    a2 = ast.parse(src2).body[0]
    assert normalized_ast_dump(a1, cfg) == normalized_ast_dump(a2, cfg)


def test_normalization_augassign_equivalence() -> None:
    src1 = """
def f():
    x += 1
"""
    src2 = """
def f():
    x = x + 1
"""
    cfg = NormalizationConfig()
    a1 = ast.parse(src1).body[0]
    a2 = ast.parse(src2).body[0]
    assert normalized_ast_dump(a1, cfg) == normalized_ast_dump(a2, cfg)


def test_normalization_augassign_target_without_ctx() -> None:
    node = ast.AugAssign(
        target=cast(Any, ast.Constant(value=1)),
        op=ast.Add(),
        value=ast.Constant(value=2),
    )
    node.lineno = 1
    node.col_offset = 0
    cfg = NormalizationConfig()
    dump = normalized_ast_dump_from_list([node], cfg)
    assert "Assign" in dump


def test_normalization_unary_non_not_preserved() -> None:
    src = """
def f(x):
    return -x
"""
    cfg = NormalizationConfig(normalize_names=False)
    node = ast.parse(src).body[0]
    dump = normalized_ast_dump(node, cfg)
    assert "UnaryOp" in dump


def test_normalization_not_non_compare_preserved() -> None:
    src = """
def f(x):
    return not x
"""
    cfg = NormalizationConfig(normalize_names=False)
    node = ast.parse(src).body[0]
    dump = normalized_ast_dump(node, cfg)
    assert "Not" in dump


def test_normalization_commutative_binop_reorders() -> None:
    src1 = """
def f():
    return 1 + 2
"""
    src2 = """
def f():
    return 2 + 1
"""
    cfg = NormalizationConfig(normalize_constants=False)
    a1 = ast.parse(src1).body[0]
    a2 = ast.parse(src2).body[0]
    assert normalized_ast_dump(a1, cfg) == normalized_ast_dump(a2, cfg)


def test_normalization_commutative_name_operands_not_reordered() -> None:
    src1 = """
def f():
    return a + b
"""
    src2 = """
def f():
    return b + a
"""
    cfg = NormalizationConfig(
        normalize_names=False,
        normalize_attributes=False,
        normalize_constants=False,
    )
    a1 = ast.parse(src1).body[0]
    a2 = ast.parse(src2).body[0]
    assert normalized_ast_dump(a1, cfg) != normalized_ast_dump(a2, cfg)


def test_normalization_commutative_binop_side_effects_not_reordered() -> None:
    src1 = """
def f():
    return foo() + bar()
"""
    src2 = """
def f():
    return bar() + foo()
"""
    cfg = NormalizationConfig(
        normalize_names=False,
        normalize_attributes=False,
        normalize_constants=False,
    )
    a1 = ast.parse(src1).body[0]
    a2 = ast.parse(src2).body[0]
    assert normalized_ast_dump(a1, cfg) != normalized_ast_dump(a2, cfg)


def test_normalization_preserves_call_target_names() -> None:
    src1 = """
def f(x):
    return load_user(x)
"""
    src2 = """
def f(x):
    return delete_user(x)
"""
    cfg = NormalizationConfig()
    a1 = ast.parse(src1).body[0]
    a2 = ast.parse(src2).body[0]
    assert normalized_ast_dump(a1, cfg) != normalized_ast_dump(a2, cfg)


def test_normalization_preserves_call_target_attributes() -> None:
    src1 = """
def f():
    return svc.load_user()
"""
    src2 = """
def f():
    return svc.delete_user()
"""
    cfg = NormalizationConfig()
    a1 = ast.parse(src1).body[0]
    a2 = ast.parse(src2).body[0]
    assert normalized_ast_dump(a1, cfg) != normalized_ast_dump(a2, cfg)


def test_normalization_call_keyword_values_are_visited() -> None:
    src1 = """
def f():
    x = 1
    return process(payload=x)
"""
    src2 = """
def f():
    y = 2
    return process(payload=y)
"""
    cfg = NormalizationConfig()
    a1 = ast.parse(src1).body[0]
    a2 = ast.parse(src2).body[0]
    assert normalized_ast_dump(a1, cfg) == normalized_ast_dump(a2, cfg)


def test_normalization_preserves_attribute_call_target_with_call_value() -> None:
    src1 = """
def f():
    return factory_a().run()
"""
    src2 = """
def f():
    return factory_b().run()
"""
    cfg = NormalizationConfig()
    a1 = ast.parse(src1).body[0]
    a2 = ast.parse(src2).body[0]
    assert normalized_ast_dump(a1, cfg) != normalized_ast_dump(a2, cfg)


def test_normalization_non_name_non_attribute_call_target() -> None:
    src1 = """
def f():
    handlers = [run]
    return handlers[0]()
"""
    src2 = """
def f():
    callbacks = [run]
    return callbacks[0]()
"""
    cfg = NormalizationConfig()
    a1 = ast.parse(src1).body[0]
    a2 = ast.parse(src2).body[0]
    assert normalized_ast_dump(a1, cfg) == normalized_ast_dump(a2, cfg)


def test_commutative_operand_recursive_and_constant_guards() -> None:
    nested = ast.parse("(1 + 2) + 3", mode="eval").body
    assert isinstance(nested, ast.BinOp)
    assert normalize_mod._is_proven_commutative_operand(nested, ast.Add())
    assert not normalize_mod._is_proven_commutative_constant(True, ast.BitOr())
    assert not normalize_mod._is_proven_commutative_constant("x", ast.Add())
    assert not normalize_mod._is_proven_commutative_constant(1, ast.Sub())


def test_normalization_preserves_semantic_marker_names() -> None:
    fn = ast.FunctionDef(
        name="f",
        args=ast.arguments(
            posonlyargs=[],
            args=[],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        ),
        body=[
            ast.Expr(
                value=ast.Name(
                    id=f"{CFG_META_PREFIX}MATCH_PATTERN:MatchValue(Constant(value=1))",
                    ctx=ast.Load(),
                )
            )
        ],
        decorator_list=[],
    )
    module = ast.Module(body=[fn], type_ignores=[])
    module = ast.fix_missing_locations(module)
    node = module.body[0]
    assert isinstance(node, ast.FunctionDef)
    cfg = NormalizationConfig()
    dump = normalized_ast_dump(node, cfg)
    assert f"{CFG_META_PREFIX}MATCH_PATTERN:MatchValue(Constant(value=1))" in dump


def test_normalization_non_commutative_binop_not_reordered() -> None:
    src1 = """
def f():
    return a - b
"""
    src2 = """
def f():
    return b - a
"""
    cfg = NormalizationConfig(normalize_names=False)
    a1 = ast.parse(src1).body[0]
    a2 = ast.parse(src2).body[0]
    assert normalized_ast_dump(a1, cfg) != normalized_ast_dump(a2, cfg)


def test_normalization_not_in_and_is_not_equivalence() -> None:
    src1 = """
def f(x, y):
    return not (x in y)
"""
    src2 = """
def f(x, y):
    return x not in y
"""
    src3 = """
def f(x, y):
    return not (x is y)
"""
    src4 = """
def f(x, y):
    return x is not y
"""
    cfg = NormalizationConfig(normalize_names=False)
    a1 = ast.parse(src1).body[0]
    a2 = ast.parse(src2).body[0]
    a3 = ast.parse(src3).body[0]
    a4 = ast.parse(src4).body[0]
    assert normalized_ast_dump(a1, cfg) == normalized_ast_dump(a2, cfg)
    assert normalized_ast_dump(a3, cfg) == normalized_ast_dump(a4, cfg)


def test_normalization_no_demorgan() -> None:
    src1 = """
def f(x, y):
    return not (x == y)
"""
    src2 = """
def f(x, y):
    return x != y
"""
    cfg = NormalizationConfig(normalize_names=False)
    a1 = ast.parse(src1).body[0]
    a2 = ast.parse(src2).body[0]
    assert normalized_ast_dump(a1, cfg) != normalized_ast_dump(a2, cfg)


def test_normalization_flags_false_preserve_details() -> None:
    src = """
def f(x: int, /, y: int, *, z: int, **k: int) -> int:
    \"\"\"doc\"\"\"
    obj.my_attr = 123
    return x
"""
    cfg = NormalizationConfig(
        ignore_docstrings=False,
        ignore_type_annotations=False,
        normalize_attributes=False,
        normalize_constants=False,
        normalize_names=False,
    )
    node = ast.parse(src).body[0]
    dump = normalized_ast_dump(node, cfg)
    assert "my_attr" in dump
    assert "123" in dump
    assert "doc" in dump
    assert "id='x'" in dump
    assert "id='int'" in dump


def test_normalization_type_annotations_posonly_kwonly_vararg() -> None:
    src = """
def f(a: int, /, b: int, *args: int, c: int, **kwargs: int) -> int:
    return a
"""
    cfg = NormalizationConfig()
    node = ast.parse(src).body[0]
    dump = normalized_ast_dump(node, cfg)
    assert isinstance(dump, str)


def test_normalization_names_constants_attributes_disabled() -> None:
    src = """
def f():
    obj.attr = 7
    return obj.attr
"""
    cfg = NormalizationConfig(
        normalize_names=False,
        normalize_attributes=False,
        normalize_constants=False,
    )
    node = ast.parse(src).body[0]
    dump = normalized_ast_dump(node, cfg)
    assert "attr" in dump
    assert "7" in dump


def test_normalization_async_function() -> None:
    src = """
async def af(x):
    return x
"""
    cfg = NormalizationConfig()
    node = ast.parse(src).body[0]
    dump = normalized_ast_dump(node, cfg)
    assert isinstance(dump, str)
