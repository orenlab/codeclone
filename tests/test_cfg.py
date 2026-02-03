import ast
from textwrap import dedent

import pytest

from codeclone.cfg import CFG, CFGBuilder


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
            dumped = ast.dump(stmt)
            # Normalize across Python versions (empty Call keywords may be shown)
            dumped = dumped.replace(", keywords=[]", "")
            lines.append(f"  {dumped}")
    return "\n".join(lines)


def test_cfg_if_else() -> None:
    source = """
    def f(a):
        if a > 0:
            x = 1
        else:
            x = 2
    """
    cfg_str = cfg_to_str(build_cfg_from_source(source))
    expected = "\n".join(
        [
            "Block 0 -> [2, 3]",
            "  Expr(value=Compare(left=Name(id='a', ctx=Load()), ops=[Gt()], "
            "comparators=[Constant(value=0)]))",
            "Block 1 -> []",
            "Block 2 -> [4]",
            "  Assign(targets=[Name(id='x', ctx=Store())], value=Constant(value=1))",
            "Block 3 -> [4]",
            "  Assign(targets=[Name(id='x', ctx=Store())], value=Constant(value=2))",
            "Block 4 -> [1]",
            "",
        ]
    )
    assert cfg_str.strip() == dedent(expected).strip()


def test_cfg_while_loop() -> None:
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


def test_cfg_for_loop() -> None:
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


def test_cfg_break_continue() -> None:
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


def test_cfg_if_with_return() -> None:
    source = """
    def f(x):
        if x > 0:
            return 1
        return 2
    """
    cfg = build_cfg_from_source(source)
    assert any(
        any(isinstance(stmt, ast.Return) for stmt in block.statements)
        for block in cfg.blocks
    )


def test_cfg_raise_statement() -> None:
    source = """
    def f():
        raise ValueError("x")
        x = 1
    """
    cfg = build_cfg_from_source(source)
    exits = [
        b for b in cfg.blocks if any(isinstance(s, ast.Raise) for s in b.statements)
    ]
    assert len(exits) == 1


def test_cfg_async_for() -> None:
    source = """
    async def f():
        async for i in a:
            x = i
    """
    cfg = build_cfg_from_source(source)
    assert len(cfg.blocks) >= 4


def test_cfg_try_finally() -> None:
    source = """
    def f():
        try:
            x = 1
        except ValueError:
            y = 2
        finally:
            z = 3
    """
    cfg = build_cfg_from_source(source)
    # Entry -> TryBody -> Handler/Finally
    # Just ensure we traversed it and have blocks
    assert len(cfg.blocks) > 3


def test_cfg_try_else() -> None:
    source = """
    def f():
        try:
            x = 1
        except ValueError:
            pass
        else:
            y = 2
    """
    cfg = build_cfg_from_source(source)
    has_else_assign = False
    for block in cfg.blocks:
        for stmt in block.statements:
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "y" for t in stmt.targets
            ):
                has_else_assign = True
    assert has_else_assign


def test_cfg_try_return_in_body() -> None:
    source = """
    def f():
        try:
            return 1
        except ValueError:
            pass
    """
    cfg = build_cfg_from_source(source)
    assert any(
        any(isinstance(stmt, ast.Return) for stmt in block.statements)
        for block in cfg.blocks
    )


def test_cfg_if_else_returns() -> None:
    source = """
    def f(x):
        if x:
            return 1
        else:
            return 2
    """
    cfg = build_cfg_from_source(source)
    assert any(
        any(isinstance(stmt, ast.Return) for stmt in block.statements)
        for block in cfg.blocks
    )


def test_cfg_while_return() -> None:
    source = """
    def f():
        while True:
            return 1
    """
    cfg = build_cfg_from_source(source)
    assert any(
        any(isinstance(stmt, ast.Return) for stmt in block.statements)
        for block in cfg.blocks
    )


def test_cfg_for_return() -> None:
    source = """
    def f():
        for i in range(3):
            return i
    """
    cfg = build_cfg_from_source(source)
    assert any(
        any(isinstance(stmt, ast.Return) for stmt in block.statements)
        for block in cfg.blocks
    )


def test_cfg_with_return() -> None:
    source = """
    def f():
        with open(\"x\", \"w\") as f:
            return 1
    """
    cfg = build_cfg_from_source(source)
    assert any(
        any(isinstance(stmt, ast.Return) for stmt in block.statements)
        for block in cfg.blocks
    )


def test_cfg_try_handler_no_type() -> None:
    source = """
    def f():
        try:
            x = 1
        except:
            return 2
    """
    cfg = build_cfg_from_source(source)
    assert any(
        any(isinstance(stmt, ast.Return) for stmt in block.statements)
        for block in cfg.blocks
    )


def test_cfg_with() -> None:
    source = """
    def f():
        with open("x") as f:
            read()
    """
    cfg = build_cfg_from_source(source)
    assert len(cfg.blocks) >= 3


def test_cfg_match() -> None:
    source = """
    def f(x):
        match x:
            case 1:
                return 1
            case _:
                return 2
    """
    try:
        cfg = build_cfg_from_source(source)
        assert len(cfg.blocks) >= 3
    except SyntaxError:
        # Python < 3.10
        pass


def test_cfg_try_handler_linking() -> None:
    """Test that statements inside try block are linked to handlers."""
    code = """
    def f():
        try:
            x = 1
            y = 2
        except ValueError:
            pass
    """
    func = ast.parse(dedent(code)).body[0]
    assert isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef))
    builder = CFGBuilder()
    cfg = builder.build("f", func)

    handler_blocks = [
        b
        for b in cfg.blocks
        if any(
            isinstance(s, ast.Expr)
            and isinstance(s.value, ast.Name)
            and s.value.id == "ValueError"
            for s in b.statements
        )
    ]

    assert len(handler_blocks) == 1
    handler_block = handler_blocks[0]

    predecessors = [b for b in cfg.blocks if handler_block in b.successors]

    has_assignment = False
    for pred in predecessors:
        for stmt in pred.statements:
            if isinstance(stmt, ast.Assign):
                has_assignment = True

    assert has_assignment, "Handler should be reachable from assignment block"


def test_cfg_try_star() -> None:
    code = """
    def f():
        try:
            x = 1
        except* ValueError:
            pass
    """
    try:
        func = ast.parse(dedent(code)).body[0]
    except SyntaxError:
        pytest.skip("TryStar not supported")

    assert isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef))
    cfg = CFGBuilder().build("f", func)
    assert len(cfg.blocks) >= 3


def test_cfg_match_pattern() -> None:
    """Test that match pattern is recorded in CFG."""
    code = """
    def f(x):
        match x:
            case [1, 2]:
                pass
            case {"a": 1}:
                pass
    """
    try:
        func = ast.parse(dedent(code)).body[0]
    except SyntaxError:
        pytest.skip("SyntaxError parsing match (old python?)")

    assert isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef))
    builder = CFGBuilder()
    cfg = builder.build("f", func)

    patterns_found = []
    for block in cfg.blocks:
        for stmt in block.statements:
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                val = stmt.value.value
                if isinstance(val, str) and val.startswith("PATTERN:"):
                    patterns_found.append(val)

    assert len(patterns_found) == 2
    assert "MatchSequence" in patterns_found[0]
    assert "MatchMapping" in patterns_found[1]
