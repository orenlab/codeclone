# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

import ast
from textwrap import dedent

import pytest

from codeclone.analysis.cfg import CFG, CFGBuilder
from codeclone.analysis.cfg_model import CFG as CFGModel
from codeclone.analysis.cfg_model import Block
from codeclone.analysis.fingerprint import _cfg_fingerprint_and_complexity
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.meta_markers import CFG_META_PREFIX
from tests._ast_helpers import fix_missing_single_function
from tests._ast_metrics_helpers import bindings_for_function_node


def build_cfg_from_source(source: str) -> CFG:
    func_node = ast.parse(dedent(source)).body[0]

    assert isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)), (
        "Expected first top-level statement to be a function"
    )

    return CFGBuilder().build(
        func_node.name,
        func_node,
        NormalizationConfig(),
        bindings_for_function_node(func_node),
    )


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
    return _cfg_fingerprint_and_complexity(
        func, cfg, qualname, bindings_for_function_node(func)
    )[1]


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


def _cfg_contains_statement(cfg: CFG, stmt_type: type[ast.stmt]) -> bool:
    return any(
        any(isinstance(stmt, stmt_type) for stmt in block.statements)
        for block in cfg.blocks
    )


def _handler_predecessors_from_source(source: str) -> list[Block]:
    cfg = build_cfg_from_source(source)
    handler_blocks = [
        block
        for block in cfg.blocks
        if any(
            (meta := _const_meta_value(stmt)) is not None
            and meta.startswith(f"{CFG_META_PREFIX}TRY_HANDLER_TYPE:")
            for stmt in block.statements
        )
    ]
    assert len(handler_blocks) == 1
    handler_block = handler_blocks[0]
    return [block for block in cfg.blocks if handler_block in block.successors]


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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            """
    def f(a, b):
        while a or b:
            x = 1
    """,
            """
Block 0 -> [2]
Block 1 -> []
Block 2 -> [3, 5]
  Expr(value=Name(id='a', ctx=Load()))
Block 3 -> [2]
  Assign(targets=[Name(id='x', ctx=Store())], value=Constant(value=1))
Block 4 -> [1]
Block 5 -> [3, 4]
  Expr(value=Name(id='b', ctx=Load()))
""",
            id="while_boolop_or",
        ),
        pytest.param(
            """
    def f():
        while True:
            a = 1
    """,
            # 39Y Y9 norm: a literal loop guard emits only the edge it admits,
            # so ``while True`` no longer pretends the loop can fall through.
            # Block 4 is the exit path the loop never takes and is now
            # unreachable by structure, which is the true shape.
            """
Block 0 -> [2]
Block 1 -> []
Block 2 -> [3]
  Expr(value=Constant(value=True))
Block 3 -> [2]
  Assign(targets=[Name(id='a', ctx=Store())], value=Constant(value=1))
Block 4 -> [1]
""",
            id="while_loop",
        ),
        pytest.param(
            """
    def f():
        for i in range(10):
            a = 1
    """,
            """
Block 0 -> [2]
Block 1 -> []
Block 2 -> [3, 4]
  Expr(value=Call(func=Name(id='range', ctx=Load()), args=[Constant(value=10)]))
Block 3 -> [2]
  Assign(targets=[Name(id='a', ctx=Store())], value=Constant(value=1))
Block 4 -> [1]
""",
            id="for_loop",
        ),
    ],
)
def test_cfg_loop_shapes(source: str, expected: str) -> None:
    cfg_str = cfg_to_str(build_cfg_from_source(source))
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


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            """
    def f(x):
        if x > 0:
            return 1
        return 2
    """,
            id="if_return",
        ),
        pytest.param(
            """
    def f():
        try:
            x = 1
        except ValueError:
            pass
        else:
            return 1
    """,
            id="try_else_return",
        ),
        pytest.param(
            """
    def f():
        try:
            return 1
        except ValueError:
            pass
    """,
            id="try_body_return",
        ),
        pytest.param(
            """
    def f(x):
        if x:
            return 1
        else:
            return 2
    """,
            id="if_else_return",
        ),
        pytest.param(
            """
    def f():
        while True:
            return 1
    """,
            id="while_return",
        ),
        pytest.param(
            """
    def f():
        for i in range(3):
            return i
    """,
            id="for_return",
        ),
        pytest.param(
            """
    def f():
        with open(\"x\", \"w\") as f:
            return 1
    """,
            id="with_return",
        ),
        pytest.param(
            """
    def f():
        try:
            x = 1
        except:
            return 2
    """,
            id="bare_except_return",
        ),
    ],
)
def test_cfg_detects_return_blocks(source: str) -> None:
    cfg = build_cfg_from_source(source)
    assert _cfg_contains_statement(cfg, ast.Return)


@pytest.mark.parametrize(
    ("source", "minimum_blocks"),
    [
        pytest.param(
            """
    async def f():
        async for i in a:
            x = i
    """,
            4,
            id="async_for",
        ),
        pytest.param(
            """
    def f():
        with open("x") as f:
            read()
    """,
            3,
            id="with",
        ),
    ],
)
def test_cfg_constructs_produce_expected_minimum_blocks(
    source: str,
    minimum_blocks: int,
) -> None:
    cfg = build_cfg_from_source(source)
    assert len(cfg.blocks) >= minimum_blocks


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
    cfg = builder.build(
        "f", func, NormalizationConfig(), bindings_for_function_node(func)
    )

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


# ``test_cfg_try_handler_linking_skips_safe_statements`` stood here. It pinned
# the ``_stmt_can_raise`` guess — "safe assignments should not link to
# handlers" — which is precisely the behaviour ruled a defect in 39Y Y9: the
# predicate also judged ``import`` safe, leaving plainly-reachable handler
# bodies with no predecessor and producing false unreachable findings. The norm
# dispatches from the region entry instead, so the refusal this test encoded no
# longer describes correct behaviour. Its coverage moves, strictly stronger, to
# ``test_norm_d1_one_dispatch_edge_per_handler`` (every handler reachable) and
# ``test_norm_d2_unmatched_exception_leaves_the_region``.


def test_cfg_try_handler_is_reachable_from_the_region_entry() -> None:
    """The replacement predicate: dispatch does not depend on the statement."""

    code = """
    def f():
        try:
            x = 1
            y = 2
        except ValueError:
            pass
    """
    predecessors = _handler_predecessors_from_source(code)
    assert predecessors, "a handler must be reachable regardless of the body"


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
    cfg = CFGBuilder().build(
        "f", func, NormalizationConfig(), bindings_for_function_node(func)
    )
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
    predecessors = _handler_predecessors_from_source(code)
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
    cfg = CFGBuilder().build(
        "f", func, NormalizationConfig(), bindings_for_function_node(func)
    )
    assert len(cfg.blocks) >= 3


def test_cfg_try_star_branch_with_distinct_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import codeclone.analysis.cfg as cfg_module

    class _DistinctTryStar:
        def __init__(self) -> None:
            self.body: list[ast.stmt] = [ast.Pass()]
            self.handlers: list[ast.ExceptHandler] = []
            self.orelse: list[ast.stmt] = []
            self.finalbody: list[ast.stmt] = []

    monkeypatch.setattr(cfg_module, "TryStar", _DistinctTryStar)
    from codeclone.analysis.cfg_model import CFG

    node = _DistinctTryStar()
    builder = CFGBuilder()
    builder.cfg = CFG("f")
    builder.current = builder.cfg.entry
    builder._visit(node)  # type: ignore[arg-type]
    assert len(builder.cfg.blocks) >= 2


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
    cfg = builder.build(
        "f", func, NormalizationConfig(), bindings_for_function_node(func)
    )

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
    func = fix_missing_single_function(fn)
    cfg = CFGBuilder().build(
        "f", func, NormalizationConfig(), bindings_for_function_node(func)
    )
    assert len(cfg.blocks) >= 3


# ===========================================================================
# 39Y Y9 norm CFG — one graph, one truth
# ===========================================================================
#
# The condemned first implementation kept unreachable statements in a side
# channel beside ``cfg.blocks`` and answered three false-positive classes with
# abstention flags. Both were ruled crutches. Under the norm the graph itself
# carries the truth: post-terminator statements are real blocks with no
# incoming edges, and exception/suppression flow is modelled by conservative
# edges instead of being excluded from judgement.
#
# Reachability over-approximation is the honest direction for a dead-code
# detector: it under-approximates findings.


def _reachable_ids(cfg: CFG) -> set[int]:
    seen = {cfg.entry.id}
    queue = [cfg.entry]
    while queue:
        block = queue.pop()
        for successor in block.successors:
            if successor.id not in seen:
                seen.add(successor.id)
                queue.append(successor)
    return seen


def _block_holding(cfg: CFG, text: str) -> Block:
    """The block whose statements contain ``text`` when unparsed."""

    matches = [
        block
        for block in cfg.blocks
        if any(text in ast.unparse(stmt) for stmt in block.statements)
    ]
    assert len(matches) == 1, f"expected exactly one block holding {text!r}"
    return matches[0]


def _weakly_connected_components(cfg: CFG) -> int:
    parent = {block.id: block.id for block in cfg.blocks}

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for block in cfg.blocks:
        for successor in block.successors:
            left, right = find(block.id), find(successor.id)
            if left != right:
                parent[left] = right
    return len({find(block.id) for block in cfg.blocks})


def _mccabe(cfg: CFG) -> int:
    edges = sum(len(block.successors) for block in cfg.blocks)
    nodes = len(cfg.blocks)
    return edges - nodes + 2 * _weakly_connected_components(cfg)


# ---------------------------------------------------------------------------
# Post-terminator statements are real blocks (replaces the side channel)
# ---------------------------------------------------------------------------


def test_norm_dead_tail_is_a_real_unreachable_block() -> None:
    """Strictly stronger than the old "stays out of the graph" assertion.

    The old implementation asserted the dead tail was ABSENT from every block
    and kept it in ``unreachable_regions``. The norm asserts the opposite and
    more: the statement is a real block, it carries no incoming edge, and plain
    reachability finds it without consulting any second structure.
    """

    cfg = build_cfg_from_source(
        """
        def after_return(value):
            return value
            value += 1
        """
    )
    dead = _block_holding(cfg, "value += 1")
    assert dead.id not in _reachable_ids(cfg)
    assert not any(dead in block.successors for block in cfg.blocks), (
        "an unreachable block must have no fabricated incoming edge"
    )


def test_norm_dead_tail_keeps_its_own_structure() -> None:
    """Unreachable code is analysed, not discarded: its branches are blocks."""

    cfg = build_cfg_from_source(
        """
        def dead_branching(value, flag):
            return value
            if flag:
                value += 1
            else:
                value -= 1
        """
    )
    reachable = _reachable_ids(cfg)
    assert _block_holding(cfg, "value += 1").id not in reachable
    assert _block_holding(cfg, "value -= 1").id not in reachable


# ---------------------------------------------------------------------------
# Norm edge decision table
# ---------------------------------------------------------------------------


def test_norm_d1_one_dispatch_edge_per_handler() -> None:
    """D1: the region entry reaches every handler, replacing _stmt_can_raise.

    The old predicate guessed which statements could raise and missed
    ``import``, which is how a plainly-reachable handler body ended up with no
    predecessor at all.
    """

    cfg = build_cfg_from_source(
        """
        def two_handlers():
            try:
                import psutil
            except ImportError:
                return None
            except ValueError:
                return 0
            return psutil
        """
    )
    reachable = _reachable_ids(cfg)
    assert _block_holding(cfg, "return None").id in reachable
    assert _block_holding(cfg, "return 0").id in reachable


def test_norm_d2_unmatched_exception_leaves_the_region() -> None:
    """D2: an exception matching no handler propagates out of the function."""

    cfg = build_cfg_from_source(
        """
        def only_value_error():
            try:
                risky()
            except ValueError:
                return 1
            return 2
        """
    )
    entry_of_region = _block_holding(cfg, "TRY_KIND")
    assert cfg.exit in entry_of_region.successors, (
        "an unmatched exception must be able to leave the function"
    )


def test_norm_f1_finally_runs_after_a_returning_body() -> None:
    """F1/F4: a ``finally`` is reachable even when the body always returns."""

    cfg = build_cfg_from_source(
        """
        def guarded(value):
            try:
                return value
            finally:
                cleanup()
        """
    )
    assert _block_holding(cfg, "cleanup()").id in _reachable_ids(cfg)


def test_norm_f4_return_inside_try_routes_through_finally() -> None:
    """F4: the return does not jump straight to the exit past the finally."""

    cfg = build_cfg_from_source(
        """
        def guarded(value):
            try:
                return value
            finally:
                cleanup()
        """
    )
    returning = _block_holding(cfg, "return value")
    finally_block = _block_holding(cfg, "cleanup()")
    assert finally_block in returning.successors
    assert cfg.exit not in returning.successors, (
        "a return inside a protected region must not bypass its finally"
    )


def test_norm_f5_break_inside_try_routes_through_finally() -> None:
    """F5: ``break`` leaves the protected region and must run the finally."""

    cfg = build_cfg_from_source(
        """
        def looping(items):
            for item in items:
                try:
                    break
                finally:
                    cleanup()
            return items
        """
    )
    breaking = _block_holding(cfg, "break")
    finally_block = _block_holding(cfg, "cleanup()")
    assert finally_block in breaking.successors


def test_norm_f5_break_outside_any_finally_is_unaffected() -> None:
    """The mirror of F5: no finally in between means no routing at all."""

    cfg = build_cfg_from_source(
        """
        def looping(items):
            for item in items:
                break
            return items
        """
    )
    breaking = _block_holding(cfg, "break")
    assert not any(
        "cleanup" in ast.unparse(stmt)
        for block in breaking.successors
        for stmt in block.statements
    )


def test_norm_f6_finally_reaches_both_the_join_and_the_exit() -> None:
    """F6: a finally continues normally AND propagates the abrupt path."""

    cfg = build_cfg_from_source(
        """
        def guarded(value):
            try:
                risky()
            finally:
                cleanup()
            return value
        """
    )
    finally_block = _block_holding(cfg, "cleanup()")
    assert cfg.exit in finally_block.successors
    assert _block_holding(cfg, "return value") in finally_block.successors


def test_norm_w1_post_with_is_reachable_through_a_raising_body() -> None:
    """W1: ``__exit__`` may suppress, so the join is never provably dead."""

    cfg = build_cfg_from_source(
        """
        def expects_failure():
            with raises(ValueError):
                raise ValueError('nope')
            return 1
        """
    )
    assert _block_holding(cfg, "return 1").id in _reachable_ids(cfg)


# ---------------------------------------------------------------------------
# Literal conditions are graph facts, not a side channel
# ---------------------------------------------------------------------------


def test_norm_literal_false_branch_has_no_incoming_edge() -> None:
    cfg = build_cfg_from_source(
        """
        def disabled():
            if False:
                return 'never'
            return 'always'
        """
    )
    assert _block_holding(cfg, "return 'never'").id not in _reachable_ids(cfg)


def test_norm_name_bound_to_false_stays_reachable() -> None:
    """The restraint, now as a graph property: no value inference."""

    cfg = build_cfg_from_source(
        """
        def constant_binding(value):
            flag = False
            if flag:
                return value + 1
            return value
        """
    )
    assert _block_holding(cfg, "return value + 1").id in _reachable_ids(cfg)


def test_norm_while_true_leaves_the_following_statement_unreachable() -> None:
    """A literal loop guard is a source fact, and the graph now shows it."""

    cfg = build_cfg_from_source(
        """
        def forever():
            while True:
                work()
            return 1
        """
    )
    assert _block_holding(cfg, "return 1").id not in _reachable_ids(cfg)


# ---------------------------------------------------------------------------
# Complexity — ruling A, full McCabe over the extended graph
# ---------------------------------------------------------------------------


def _complexity_of(source: str) -> tuple[int, int]:
    """Return (reported complexity, independently recomputed E-N+2P)."""

    func_node = ast.parse(dedent(source)).body[0]
    assert isinstance(func_node, ast.FunctionDef)
    graph, _fingerprint, complexity = _cfg_fingerprint_and_complexity(
        func_node,
        NormalizationConfig(),
        func_node.name,
        bindings_for_function_node(func_node),
    )
    return complexity, _mccabe(graph)


@pytest.mark.parametrize(
    "source",
    [
        "def straight(value):\n    return value\n",
        "def branchy(value):\n    if value:\n        return 1\n    return 2\n",
        (
            "def guarded(value):\n"
            "    try:\n"
            "        return value\n"
            "    except ValueError:\n"
            "        return 0\n"
            "    finally:\n"
            "        cleanup()\n"
        ),
        "def dead(value):\n    return value\n    value += 1\n",
        (
            "def suppressing():\n"
            "    with raises(ValueError):\n"
            "        raise ValueError('x')\n"
            "    return 1\n"
        ),
    ],
)
def test_complexity_is_full_mccabe_over_the_extended_graph(source: str) -> None:
    """Ruling A: V(G) = E - N + 2P over the whole graph, every edge counted.

    No edge kind is excluded and no component is skipped; the reported value
    must equal the formula applied to the graph the fingerprint also sees.
    """

    reported, recomputed = _complexity_of(source)
    assert reported == recomputed


def test_each_handler_adds_one_path() -> None:
    """The textbook consequence of the dispatch edges, stated as a delta."""

    one, _ = _complexity_of(
        "def one_handler():\n"
        "    try:\n"
        "        risky()\n"
        "    except ValueError:\n"
        "        return 0\n"
        "    return 1\n"
    )
    two, _ = _complexity_of(
        "def two_handlers():\n"
        "    try:\n"
        "        risky()\n"
        "    except ValueError:\n"
        "        return 0\n"
        "    except TypeError:\n"
        "        return 2\n"
        "    return 1\n"
    )
    assert two == one + 1


def test_complexity_never_filters_by_edge_kind() -> None:
    """The back-door guard: dispatch/finally/suppress edges must all count.

    Reproducing pre-norm numbers by ignoring norm edges would recreate the
    second truth the redesign exists to remove, so a function whose only
    control flow is a handler must not report the complexity of a straight
    line.
    """

    guarded, _ = _complexity_of(
        "def guarded():\n"
        "    try:\n"
        "        risky()\n"
        "    except ValueError:\n"
        "        return 0\n"
        "    return 1\n"
    )
    straight, _ = _complexity_of("def straight():\n    return 1\n")
    assert guarded > straight


def test_cfg_try_star_rejects_malformed_field_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_try_star_parts` answers None for any field that is not the exact
    list shape, instead of crashing mid-build."""

    import codeclone.analysis.cfg as cfg_module

    class _DistinctTryStar:
        def __init__(self) -> None:
            self.body: object = [ast.Pass()]
            self.handlers: object = []
            self.orelse: object = []
            self.finalbody: object = []

    monkeypatch.setattr(cfg_module, "TryStar", _DistinctTryStar)

    well_formed = _DistinctTryStar()
    parts = cfg_module._try_star_parts(well_formed)  # type: ignore[arg-type]
    assert parts is not None
    body, handlers, orelse, finalbody = parts
    assert len(body) == 1 and handlers == [] and orelse == [] and finalbody == []

    non_list = _DistinctTryStar()
    non_list.body = "oops"
    assert cfg_module._try_star_parts(non_list) is None  # type: ignore[arg-type]

    wrong_item_type = _DistinctTryStar()
    wrong_item_type.handlers = [ast.Pass()]
    assert (
        cfg_module._try_star_parts(wrong_item_type) is None  # type: ignore[arg-type]
    )


def test_cfg_finally_that_always_raises_seals_the_join() -> None:
    """When every path through a ``finally`` terminates, the join block after
    the try gets no incoming edge; a benign ``finally`` feeds it."""

    def _reachable_ids(cfg: CFG) -> set[int]:
        seen: set[int] = set()
        stack = [cfg.entry]
        while stack:
            block = stack.pop()
            if block.id in seen:
                continue
            seen.add(block.id)
            stack.extend(block.successors)
        return seen

    def _tail_block_id(cfg: CFG) -> int:
        for block in cfg.blocks:
            for statement in block.statements:
                if isinstance(statement, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "tail"
                    for target in statement.targets
                ):
                    return block.id
        raise AssertionError("tail assignment block not found")

    raising = build_cfg_from_source(
        """
        def f():
            try:
                x = 1
            finally:
                raise RuntimeError("cleanup")
            tail = 2
        """
    )
    benign = build_cfg_from_source(
        """
        def f():
            try:
                x = 1
            finally:
                x = 2
            tail = 2
        """
    )
    assert _tail_block_id(raising) not in _reachable_ids(raising)
    assert _tail_block_id(benign) in _reachable_ids(benign)
