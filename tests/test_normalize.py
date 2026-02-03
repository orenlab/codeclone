import ast

from codeclone.normalize import NormalizationConfig, normalized_ast_dump


def test_normalization_ignores_variable_names() -> None:
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


def test_normalization_docstring_removed() -> None:
    src1 = '''
def f():
    """doc"""
    x = 1
    return x
'''
    src2 = """
def f():
    x = 1
    return x
"""
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
