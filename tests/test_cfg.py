import ast
from textwrap import dedent

from codeclone.cfg import CFGBuilder, CFG


def build_cfg_from_source(source: str) -> CFG:
    func_node = ast.parse(dedent(source)).body[0]

    assert isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)), (
        "Expected first top-level statement to be a function"
    )

    return CFGBuilder().build(func_node.name, func_node)


def cfg_to_str(cfg: CFG) -> str:
    # Stable string representation of CFG
    lines: list[str] = []
    for block in sorted(cfg.blocks, key=lambda b: b.id):
        succ = sorted(s.id for s in block.successors)
        lines.append(f"Block {block.id} -> [{', '.join(map(str, succ))}]")
        for stmt in block.statements:
            lines.append(f"  {ast.dump(stmt)}")
    return "\n".join(lines)


def test_cfg_if_else():
    source = """
    def f(a):
        if a > 0:
            x = 1
        else:
            x = 2
    """
    cfg_str = cfg_to_str(build_cfg_from_source(source))
    expected = """
Block 0 -> [2, 3]
  Expr(value=Compare(left=Name(id='a', ctx=Load()), ops=[Gt()], comparators=[Constant(value=0)]))
Block 1 -> []
Block 2 -> [4]
  Assign(targets=[Name(id='x', ctx=Store())], value=Constant(value=1))
Block 3 -> [4]
  Assign(targets=[Name(id='x', ctx=Store())], value=Constant(value=2))
Block 4 -> [1]
"""
    assert cfg_str.strip() == dedent(expected).strip()


def test_cfg_while_loop():
    source = """
    def f():
        while True:
            a = 1
    """
    cfg_str = cfg_to_str(build_cfg_from_source(source))
    expected = """
Block 0 -> [2]
Block 1 -> []
Block 2 -> [3, 4]
  Expr(value=Constant(value=True))
Block 3 -> [2]
  Assign(targets=[Name(id='a', ctx=Store())], value=Constant(value=1))
Block 4 -> [1]
"""
    assert cfg_str.strip() == dedent(expected).strip()


def test_cfg_for_loop():
    source = """
    def f():
        for i in range(10):
            a = 1
    """
    cfg_str = cfg_to_str(build_cfg_from_source(source))
    expected = """
Block 0 -> [2]
Block 1 -> []
Block 2 -> [3, 4]
  Expr(value=Call(func=Name(id='range', ctx=Load()), args=[Constant(value=10)]))
Block 3 -> [2]
  Assign(targets=[Name(id='a', ctx=Store())], value=Constant(value=1))
Block 4 -> [1]
"""
    assert cfg_str.strip() == dedent(expected).strip()


def test_cfg_break_continue():
    source = """
    def f():
        for i in range(10):
            if i % 2 == 0:
                continue
            if i == 5:
                break
            print(i)
    """
    cfg = build_cfg_from_source(source)

    assert any(
        any(
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Name)
            and stmt.value.func.id == "range"
            for stmt in block.statements
        )
        for block in cfg.blocks
    )

    assert any(
        any(isinstance(stmt, ast.Continue) for stmt in block.statements)
        for block in cfg.blocks
    )

    assert any(
        any(isinstance(stmt, ast.Break) for stmt in block.statements)
        for block in cfg.blocks
    )

    assert any(
        any(
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Name)
            and stmt.value.func.id == "print"
            for stmt in block.statements
        )
        for block in cfg.blocks
    )

    for block in cfg.blocks:
        assert isinstance(block.successors, set)
