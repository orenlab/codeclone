import ast
from textwrap import dedent

import pytest

from codeclone.cfg import CFG, CFGBuilder
from codeclone.cfg_model import CFG as CFGModel
from codeclone.cfg_model import Block
from codeclone.extractor import get_cfg_fingerprint
from codeclone.meta_markers import CFG_META_PREFIX
from codeclone.normalize import NormalizationConfig


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


def _const_meta_value(stmt: ast.stmt) -> str | None:
    if not isinstance(stmt, ast.Expr):
        return None
    if not isinstance(stmt.value, ast.Name):
        return None
    if not isinstance(stmt.value.id, str):
        return None
    return stmt.value.id


def _parse_function(
    source: str, *, skip_reason: str | None = None
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    try:
        module = ast.parse(dedent(source))
    except SyntaxError:
        if skip_reason:
            pytest.skip(skip_reason)
        raise
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    raise AssertionError("Expected at least one function in source")


def _cfg_fingerprint(
    source: str, qualname: str, *, skip_reason: str | None = None
) -> str:
    func = _parse_function(source, skip_reason=skip_reason)
    cfg = NormalizationConfig()
    return get_cfg_fingerprint(func, cfg, qualname)


def _assert_fingerprint_diff(
    source_a: str, source_b: str, *, skip_reason: str | None = None
) -> None:
    fp_a = _cfg_fingerprint(source_a, "m:f", skip_reason=skip_reason)
    fp_b = _cfg_fingerprint(source_b, "m:g", skip_reason=skip_reason)
    assert fp_a != fp_b


def _single_return_block(cfg: CFG) -> Block:
    return_blocks = [
        block
        for block in cfg.blocks
        if any(isinstance(stmt, ast.Return) for stmt in block.statements)
    ]
    assert len(return_blocks) == 1
    return return_blocks[0]


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


def test_cfg_if_with_boolop_and() -> None:
    source = """
    def f(a, b):
        if a and b:
            x = 1
        else:
            x = 2
    """
    cfg_str = cfg_to_str(build_cfg_from_source(source))
    expected = """
Block 0 -> [3, 5]
  Expr(value=Name(id='a', ctx=Load()))
Block 1 -> []
Block 2 -> [4]
  Assign(targets=[Name(id='x', ctx=Store())], value=Constant(value=1))
Block 3 -> [4]
  Assign(targets=[Name(id='x', ctx=Store())], value=Constant(value=2))
Block 4 -> [1]
Block 5 -> [2, 3]
  Expr(value=Name(id='b', ctx=Load()))
"""
    assert cfg_str.strip() == dedent(expected).strip()


def test_cfg_while_with_boolop_or() -> None:
    source = """
    def f(a, b):
        while a or b:
            x = 1
    """
    cfg_str = cfg_to_str(build_cfg_from_source(source))
    expected = """
Block 0 -> [2]
Block 1 -> []
Block 2 -> [3, 5]
  Expr(value=Name(id='a', ctx=Load()))
Block 3 -> [2]
  Assign(targets=[Name(id='x', ctx=Store())], value=Constant(value=1))
Block 4 -> [1]
Block 5 -> [3, 4]
  Expr(value=Name(id='b', ctx=Load()))
"""
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


def test_cfg_try_else_return_terminates() -> None:
    source = """
    def f():
        try:
            x = 1
        except ValueError:
            pass
        else:
            return 1
    """
    cfg = build_cfg_from_source(source)
    assert any(
        any(isinstance(stmt, ast.Return) for stmt in block.statements)
        for block in cfg.blocks
    )


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
    """Test that only potentially raising statements inside try link to handlers."""
    code = """
    def f():
        try:
            x = 1
            y = risky()
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
            (meta := _const_meta_value(s)) is not None
            and meta.startswith(f"{CFG_META_PREFIX}TRY_HANDLER_TYPE:")
            for s in b.statements
        )
    ]

    assert len(handler_blocks) == 1
    handler_block = handler_blocks[0]

    predecessors = [b for b in cfg.blocks if handler_block in b.successors]

    has_call = False
    for pred in predecessors:
        for stmt in pred.statements:
            if (
                isinstance(stmt, ast.Assign)
                and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Name)
                and stmt.value.func.id == "risky"
            ):
                has_call = True

    assert has_call, "Handler should be reachable from potentially raising block"


def test_cfg_try_handler_linking_skips_safe_statements() -> None:
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
    cfg = CFGBuilder().build("f", func)

    handler_blocks = [
        b
        for b in cfg.blocks
        if any(
            (meta := _const_meta_value(s)) is not None
            and meta.startswith(f"{CFG_META_PREFIX}TRY_HANDLER_TYPE:")
            for s in b.statements
        )
    ]

    assert len(handler_blocks) == 1
    handler_block = handler_blocks[0]

    predecessors = [b for b in cfg.blocks if handler_block in b.successors]

    has_assign_only = any(
        any(isinstance(stmt, ast.Assign) for stmt in pred.statements)
        for pred in predecessors
    )

    assert not has_assign_only, "Safe assignments should not link to handlers"


def test_cfg_try_body_breaks_after_termination() -> None:
    code = """
    def f():
        try:
            return 1
            x = 2
        except ValueError:
            pass
    """
    func = ast.parse(dedent(code)).body[0]
    assert isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef))
    cfg = CFGBuilder().build("f", func)
    assert any(
        any(isinstance(stmt, ast.Return) for stmt in block.statements)
        for block in cfg.blocks
    )


def test_cfg_try_handler_linking_for_raise() -> None:
    code = """
    def f():
        try:
            raise ValueError("x")
        except ValueError:
            pass
    """
    func = ast.parse(dedent(code)).body[0]
    assert isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef))
    cfg = CFGBuilder().build("f", func)

    handler_blocks = [
        b
        for b in cfg.blocks
        if any(
            (meta := _const_meta_value(s)) is not None
            and meta.startswith(f"{CFG_META_PREFIX}TRY_HANDLER_TYPE:")
            for s in b.statements
        )
    ]
    assert len(handler_blocks) == 1
    handler_block = handler_blocks[0]

    predecessors = [b for b in cfg.blocks if handler_block in b.successors]
    assert any(
        any(isinstance(stmt, ast.Raise) for stmt in pred.statements)
        for pred in predecessors
    )


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
            meta = _const_meta_value(stmt)
            if meta and meta.startswith(f"{CFG_META_PREFIX}MATCH_PATTERN:"):
                patterns_found.append(meta)

    assert len(patterns_found) == 2
    assert "MatchSequence" in patterns_found[0]
    assert "MatchMapping" in patterns_found[1]


@pytest.mark.parametrize(
    ("source_a", "source_b", "skip_reason"),
    [
        (
            """
    def f(x):
        match x:
            case 1 if cond():
                return 1
            case _:
                return 2
    """,
            """
    def f(x):
        match x:
            case 1:
                return 1
            case _:
                return 2
    """,
            "Match syntax is unavailable",
        ),
        (
            """
    def f(x):
        match x:
            case 1:
                return 1
            case _:
                return 2
    """,
            """
    def g(x):
        match x:
            case _:
                return 2
            case 1:
                return 1
    """,
            "Match syntax is unavailable",
        ),
        (
            """
    def f(x):
        try:
            return risky(x)
        except ValueError:
            return 1
        except Exception:
            return 2
    """,
            """
    def g(x):
        try:
            return risky(x)
        except Exception:
            return 2
        except ValueError:
            return 1
    """,
            None,
        ),
        (
            """
    def f(xs):
        for x in xs:
            pass
        else:
            y = 1
    """,
            """
    def f(xs):
        for x in xs:
            pass
    """,
            None,
        ),
        (
            """
    def f(flag):
        while flag:
            flag = False
        else:
            x = 1
    """,
            """
    def f(flag):
        while flag:
            flag = False
    """,
            None,
        ),
    ],
    ids=[
        "match_guard",
        "match_case_order",
        "try_handler_order",
        "for_else",
        "while_else",
    ],
)
def test_cfg_fingerprint_variants(
    source_a: str, source_b: str, skip_reason: str | None
) -> None:
    _assert_fingerprint_diff(source_a, source_b, skip_reason=skip_reason)


@pytest.mark.parametrize(
    ("keyword", "stmt_type"),
    [("break", ast.Break), ("continue", ast.Continue)],
    ids=["break", "continue"],
)
def test_cfg_loop_control_terminates_block(
    keyword: str, stmt_type: type[ast.stmt]
) -> None:
    source = f"""
    def f(xs):
        for x in xs:
            {keyword}
            y = 1
    """
    cfg = build_cfg_from_source(source)
    control_blocks = [
        block
        for block in cfg.blocks
        if any(isinstance(stmt, stmt_type) for stmt in block.statements)
    ]
    assert len(control_blocks) == 1
    control_block = control_blocks[0]
    assert control_block.is_terminated is True
    assert all(not isinstance(stmt, ast.Assign) for stmt in control_block.statements)


def test_cfg_break_skips_for_else_block() -> None:
    source = """
    def f(xs):
        for x in xs:
            break
        else:
            y = 1
    """
    cfg = build_cfg_from_source(source)
    break_blocks = [
        b
        for b in cfg.blocks
        if any(isinstance(stmt, ast.Break) for stmt in b.statements)
    ]
    else_blocks = [
        b
        for b in cfg.blocks
        if any(
            isinstance(stmt, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "y" for t in stmt.targets)
            for stmt in b.statements
        )
    ]
    assert len(break_blocks) == 1
    assert len(else_blocks) == 1
    assert else_blocks[0] not in break_blocks[0].successors


@pytest.mark.parametrize(
    "source",
    [
        """
    def f(flag):
        while flag:
            flag = False
        else:
            return 1
    """,
        """
    def f(xs):
        for x in xs:
            pass
        else:
            return 1
    """,
    ],
    ids=["while_else", "for_else"],
)
def test_cfg_loop_else_terminated_branch(source: str) -> None:
    cfg = build_cfg_from_source(source)
    return_block = _single_return_block(cfg)
    assert return_block.is_terminated is True
    assert cfg.exit in return_block.successors


def test_cfg_break_outside_loop_falls_back_to_exit() -> None:
    builder = CFGBuilder()
    builder.cfg = CFGModel("m:f")
    builder.current = builder.cfg.entry
    builder._visit_break(ast.Break())
    assert builder.current.is_terminated is True
    assert builder.cfg.exit in builder.current.successors


def test_cfg_continue_outside_loop_falls_back_to_exit() -> None:
    builder = CFGBuilder()
    builder.cfg = CFGModel("m:f")
    builder.current = builder.cfg.entry
    builder._visit_continue(ast.Continue())
    assert builder.current.is_terminated is True
    assert builder.cfg.exit in builder.current.successors


def test_cfg_match_with_empty_cases_ast() -> None:
    # Defensive coverage for the fallback branch when Match.cases is empty.
    match_stmt = ast.Match(subject=ast.Name(id="x", ctx=ast.Load()), cases=[])
    fn = ast.FunctionDef(
        name="f",
        args=ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg="x")],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        ),
        body=[match_stmt],
        decorator_list=[],
    )
    module = ast.Module(body=[fn], type_ignores=[])
    module = ast.fix_missing_locations(module)
    func = module.body[0]
    assert isinstance(func, ast.FunctionDef)
    cfg = CFGBuilder().build("f", func)
    assert len(cfg.blocks) >= 3
