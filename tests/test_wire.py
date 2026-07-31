# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

from codeclone.analysis import wire as wire_module
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.wire import WireUnsupportedNode, emit_wire, emit_wire_seq
from codeclone.contracts import WIRE_VERSION
from tests._ast_metrics_helpers import bindings_for_tree

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_ROOT = _REPO_ROOT / "tests" / "fixtures" / "wire_corpus"
_FIXTURE_NAMES = ("core_syntax.py", "pattern_syntax.py", "modern_syntax.py")
_DEFAULT_CONFIG = NormalizationConfig()


def _fixture_is_supported(name: str) -> bool:
    return name != "modern_syntax.py" or sys.version_info >= (3, 11)


def _fixture_tree(name: str) -> ast.Module:
    source = (_FIXTURE_ROOT / name).read_text(encoding="utf-8")
    if name == "modern_syntax.py":
        container = ast.parse(source, filename=name)
        assignment = container.body[0]
        assert isinstance(assignment, ast.Assign)
        assert isinstance(assignment.value, ast.Constant)
        assert isinstance(assignment.value.value, str)
        source = assignment.value.value
    return ast.parse(source, filename=name, type_comments=True)


def _source_wire(source: str) -> str:
    tree = ast.parse(source)
    return emit_wire_seq(tree.body, _DEFAULT_CONFIG, bindings_for_tree(tree))


def _function_wire(source: str) -> str:
    """Wire of a complete function definition, read in its own scope."""

    tree = ast.parse(source)
    return emit_wire(tree.body[0], _DEFAULT_CONFIG, bindings_for_tree(tree))


def _goldens() -> dict[str, str]:
    raw = json.loads((_FIXTURE_ROOT / "goldens.json").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    result: dict[str, str] = {}
    for name, wire in raw.items():
        assert isinstance(name, str)
        assert isinstance(wire, str)
        result[name] = wire
    return result


def test_wire_version_is_frozen() -> None:
    assert WIRE_VERSION == "2"
    assert wire_module.WIRE_VERSION == WIRE_VERSION


@pytest.mark.parametrize("fixture_name", _FIXTURE_NAMES)
def test_cross_version_fixture_golden(fixture_name: str) -> None:
    if not _fixture_is_supported(fixture_name):
        pytest.skip("fixture requires Python 3.11 except-star grammar")
    expected = _goldens()[fixture_name]
    tree = _fixture_tree(fixture_name)
    assert emit_wire(tree, _DEFAULT_CONFIG, bindings_for_tree(tree)) == expected


@pytest.mark.parametrize("fixture_name", _FIXTURE_NAMES)
def test_emitter_is_read_only(fixture_name: str) -> None:
    if not _fixture_is_supported(fixture_name):
        pytest.skip("fixture requires Python 3.11 except-star grammar")
    tree = _fixture_tree(fixture_name)
    before = ast.dump(tree, annotate_fields=True, include_attributes=True)
    emit_wire(tree, _DEFAULT_CONFIG, bindings_for_tree(tree))
    after = ast.dump(tree, annotate_fields=True, include_attributes=True)
    assert after == before


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("value += 1", "value = value + 1"),
        ("result = not (item in values)", "result = item not in values"),
        (
            "match subject:\n    case 1:\n        pass",
            "match subject:\n    case 2:\n        pass",
        ),
        (
            "match subject:\n    case captured:\n        pass",
            "match subject:\n    case renamed:\n        pass",
        ),
    ],
)
def test_equivalent_sources_share_wire(left: str, right: str) -> None:
    assert _source_wire(left) == _source_wire(right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (
            "def f(left, right):\n    result = right + left",
            "def f(left, right):\n    result = left + right",
        ),
        (
            "def f(source):\n    first = source",
            "def f(source):\n    second = source",
        ),
    ],
    ids=["commutative_local_operands", "local_target_rename"],
)
def test_local_name_renames_share_wire(left: str, right: str) -> None:
    """Locals normalize, so renaming them cannot move the wire.

    These rows live inside a function on purpose. The same statements at module
    scope bind globals, and two differently named globals are two different
    symbols — the wire says so, and must.
    """

    assert _function_wire(left) == _function_wire(right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("result = alpha()", "result = beta()"),
        (
            "match subject:\n    case Alpha(1):\n        pass",
            "match subject:\n    case Beta(1):\n        pass",
        ),
    ],
)
def test_semantically_distinct_symbols_keep_distinct_wires(
    left: str, right: str
) -> None:
    assert _source_wire(left) != _source_wire(right)


@pytest.mark.parametrize("injected", ('"a|SUCCESSORS:0"', '"BLOCK[0]:"'))
def test_match_literal_injection_is_erased(injected: str) -> None:
    template = "match subject:\n    case {literal}:\n        pass"
    hostile = _source_wire(template.format(literal=injected))
    innocuous = _source_wire(template.format(literal='"ordinary"'))
    assert hostile == innocuous
    assert "SUCCESSORS" not in hostile
    assert "BLOCK" not in hostile


def test_match_value_dotted_symbol_is_preserved() -> None:
    alpha = _source_wire("match subject:\n    case Alpha.VALUE:\n        pass")
    beta = _source_wire("match subject:\n    case Beta.VALUE:\n        pass")
    assert alpha != beta
    assert "Alpha" in alpha


def test_try_star_has_a_distinct_node_name() -> None:
    if sys.version_info < (3, 11):
        pytest.skip("except-star grammar was introduced in Python 3.11")
    regular = _source_wire("try:\n    work()\nexcept ValueError:\n    recover()")
    grouped = _source_wire("try:\n    work()\nexcept* ValueError:\n    recover()")
    assert regular.startswith("Try(")
    assert grouped.startswith("TryStar(")
    assert regular != grouped


def test_unknown_node_and_field_fail_closed() -> None:
    class FutureNode(ast.AST):
        _fields = ()

    with pytest.raises(WireUnsupportedNode, match="FutureNode"):
        emit_wire(
            FutureNode(),
            _DEFAULT_CONFIG,
            bindings_for_tree(ast.Module(body=[], type_ignores=[])),
        )

    module = ast.parse("value")
    statement = module.body[0]
    assert isinstance(statement, ast.Expr)
    node = statement.value
    assert isinstance(node, ast.Name)
    object.__setattr__(node, "_fields", (*node._fields, "future_field"))
    with pytest.raises(WireUnsupportedNode, match="future_field"):
        emit_wire(node, _DEFAULT_CONFIG, bindings_for_tree(module))


def test_every_repository_function_body_is_supported() -> None:
    for path in sorted((_REPO_ROOT / "codeclone").rglob("*.py")):
        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path.relative_to(_REPO_ROOT)),
            type_comments=True,
        )
        bindings = bindings_for_tree(tree)
        functions = (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        for function in functions:
            emit_wire_seq(function.body, _DEFAULT_CONFIG, bindings.enter(function))


def test_subprocess_emission_is_deterministic() -> None:
    script = """
import ast
import pathlib
import sys
from codeclone.analysis.binding import build_module_bindings
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.wire import emit_wire

path = pathlib.Path(sys.argv[1])
tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
bindings = build_module_bindings(
    tree,
    resolve_from_import=lambda node: (node.module or "") if node.level == 0 else None,
)
sys.stdout.write(emit_wire(tree, NormalizationConfig(), bindings))
"""
    fixture = _FIXTURE_ROOT / "core_syntax.py"
    outputs = [
        subprocess.run(
            [sys.executable, "-c", script, str(fixture)],
            cwd=_REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        for _ in range(3)
    ]
    assert outputs[0] == outputs[1] == outputs[2]


def test_wire_module_has_no_mutating_or_stdlib_dump_path() -> None:
    source = inspect.getsource(wire_module)
    assert "ast.dump" not in source
    assert "deepcopy" not in source
    assert "NodeTransformer" not in source
