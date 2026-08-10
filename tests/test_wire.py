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
import unittest.mock
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


def test_wire_field_check_is_precomputed_per_node_type() -> None:
    """The allowed-field set is a pure function of the node type.

    The field check runs on every emitted node - 1.86M times over this
    repository - and rebuilt ``frozenset(fields) | _EXCLUDED_FIELDS`` on each
    call: two allocations to re-derive a per-type constant. The table asserted
    here is that constant, computed once at import.

    The entry also carries the node type's own ``_fields`` tuple by identity.
    An instance may shadow ``_fields`` (see
    ``test_unknown_node_and_field_fail_closed``), so the precomputed answer is
    valid only while the instance still reads the class attribute; the identity
    check is what keeps that refusal path alive.
    """

    for node_type, expected_fields in wire_module._WIRE_FIELDS.items():
        live_allowed = frozenset(expected_fields) | wire_module._EXCLUDED_FIELDS
        live_unknown = tuple(
            field for field in node_type._fields if field not in live_allowed
        )
        entry = wire_module._WIRE_FIELD_CHECK[node_type]
        fields, allowed, class_fields, unknown = entry
        assert fields == expected_fields
        assert allowed == live_allowed
        assert class_fields is node_type._fields
        assert unknown == live_unknown


def test_wire_field_check_reuses_one_entry_per_type() -> None:
    """Two emits of the same node type must not build two allowed-sets."""

    first = wire_module._WIRE_FIELD_CHECK[ast.Call]
    second = wire_module._WIRE_FIELD_CHECK[ast.Call]
    assert first is second
    assert first[1] is second[1]


def test_wire_contract_is_read_through_one_lookup() -> None:
    """Both emit paths admit a node through the same single-lookup helper.

    The type resolution, the field tuple and the whitelist refusal used to be
    written out at both emit sites - five identical lines that CodeClone's own
    block-clone gate flagged the moment one of them was touched. Reading them
    from one helper keeps the two paths from drifting, and from duplicating.
    """

    call = ast.parse("f(1)").body[0]
    assert isinstance(call, ast.Expr)
    node_type, fields = wire_module._wire_contract(call.value)
    assert node_type is ast.Call
    assert fields == wire_module._WIRE_FIELDS[ast.Call]

    source = inspect.getsource(wire_module)
    assert source.count("unsupported AST node:") == 1


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


def _module_wire(source: str, cfg: NormalizationConfig | None = None) -> str:
    tree = ast.parse(source, type_comments=True)
    return emit_wire(tree, cfg or _DEFAULT_CONFIG, bindings_for_tree(tree))


def test_build_wire_fields_skips_names_that_are_not_ast_types() -> None:
    """Spec names that do not resolve to AST classes are dropped, not crashed on."""

    with unittest.mock.patch.dict(
        wire_module._WIRE_FIELD_SPECS,
        {"NotARealAstNode": ("value",), "walk": ("target",)},
    ):
        rebuilt = wire_module._build_wire_fields()
    names = {node_type.__name__ for node_type in rebuilt}
    assert "NotARealAstNode" not in names
    assert "walk" not in names
    assert ast.Module in rebuilt


def test_type_ignore_tag_text_does_not_split_module_wire() -> None:
    """`# type: ignore[x]` and bare `# type: ignore` emit one masked tag."""

    tagged = _module_wire("x = 1  # type: ignore[assignment]\n")
    bare = _module_wire("x = 1  # type: ignore\n")
    assert tagged == bare
    assert "_CONST_" in tagged
    assert "assignment" not in tagged


def test_star_import_alias_survives_as_star_marker() -> None:
    wire = _source_wire("from os import *")
    assert "_STAR_" in wire
    assert wire != _source_wire("from os import path")


def test_emit_identifier_rejects_non_identifier_text() -> None:
    with pytest.raises(WireUnsupportedNode, match="unsafe identifier"):
        wire_module._emit_identifier("not an identifier!")


def test_emit_value_rejects_unsupported_field_payload() -> None:
    tree = ast.parse("x = 1")
    with pytest.raises(WireUnsupportedNode, match="unsupported value for field tag"):
        wire_module._emit_value(
            3.5,
            _DEFAULT_CONFIG,
            field="tag",
            bindings=bindings_for_tree(tree),
        )


def test_capture_name_is_kept_when_names_are_not_normalized() -> None:
    cfg = NormalizationConfig(normalize_names=False)
    source = (
        "def f(v):\n"
        "    match v:\n"
        "        case captured_name:\n"
        "            return captured_name\n"
    )
    tree = ast.parse(source)
    wire = emit_wire(tree.body[0], cfg, bindings_for_tree(tree))
    assert "captured_name" in wire
    default_wire = _function_wire(source)
    assert "captured_name" not in default_wire


def test_capture_name_must_be_a_string() -> None:
    with pytest.raises(WireUnsupportedNode, match="capture name is not a string"):
        wire_module._emit_capture_name(17, _DEFAULT_CONFIG)


def test_boolean_constants_survive_when_constants_are_not_normalized() -> None:
    cfg = NormalizationConfig(normalize_constants=False)
    true_wire = _module_wire("x = True", cfg)
    false_wire = _module_wire("x = False", cfg)
    none_wire = _module_wire("x = None", cfg)
    assert "True" in true_wire
    assert "False" in false_wire
    assert "None" in none_wire
    assert len({true_wire, false_wire, none_wire}) == 3


def test_non_literal_constant_is_rejected_when_not_normalized() -> None:
    cfg = NormalizationConfig(normalize_constants=False)
    with pytest.raises(WireUnsupportedNode, match="unsupported constant value"):
        wire_module._emit_constant(object(), cfg)


def test_commutative_constant_proof_is_scoped_to_the_operator_family() -> None:
    """Sub is filtered out before the proof; the proof itself still denies it."""

    assert wire_module._is_proven_commutative_constant(1, ast.Add()) is True
    assert wire_module._is_proven_commutative_constant(1, ast.Sub()) is False
    # Public surface: subtraction operands are never reordered.
    assert _source_wire("y = a - 1") != _source_wire("y = 1 - a")


@pytest.mark.skipif(sys.version_info < (3, 14), reason="t-strings require Python 3.14")
def test_interpolation_source_text_is_masked_in_template_strings() -> None:
    """Interpolation.str (the brace source text) is masked, so formatting-only
    differences inside braces do not split the wire."""

    spaced = _source_wire('x = t"{ name + tail }"')
    tight = _source_wire('x = t"{name+tail}"')
    assert spaced == tight


def _synthetic_lazy_import_wire(source: str, is_lazy: int) -> str:
    """Wire of ``source`` with the PEP 810 field present, on any interpreter.

    Python 3.15 parses ``is_lazy`` onto every ``Import``/``ImportFrom`` and
    extends the class field tuple. Older interpreters never produce the field,
    so the test constructs the same shape: the value in the instance dict and
    an instance-level ``_fields`` shadow that triggers the wire's rescan path.
    """

    tree = ast.parse(source)
    statement = tree.body[0]
    assert isinstance(statement, (ast.Import, ast.ImportFrom))
    object.__setattr__(statement, "is_lazy", is_lazy)
    if "is_lazy" not in statement._fields:
        object.__setattr__(statement, "_fields", (*statement._fields, "is_lazy"))
    return emit_wire_seq(tree.body, _DEFAULT_CONFIG, bindings_for_tree(tree))


@pytest.mark.parametrize(
    "source",
    ["import json", "from json import dumps"],
    ids=["import", "from_import"],
)
def test_eager_import_with_is_lazy_zero_shares_the_wire(source: str) -> None:
    """PEP 810 ``is_lazy=0`` is the eager default and must not move the wire."""

    baseline = _source_wire(source)
    assert "is_lazy" not in baseline
    assert _synthetic_lazy_import_wire(source, 0) == baseline


@pytest.mark.parametrize(
    "source",
    ["import json", "from json import dumps"],
    ids=["import", "from_import"],
)
def test_lazy_import_emits_an_explicit_marker(source: str) -> None:
    """PEP 810 ``is_lazy=1`` is new lexicon: emitted, and distinct from eager."""

    lazy = _synthetic_lazy_import_wire(source, 1)
    assert "is_lazy=1" in lazy
    assert lazy != _source_wire(source)


@pytest.mark.skipif(
    sys.version_info < (3, 15), reason="PEP 810 lazy imports require Python 3.15"
)
def test_lazy_import_live_parse_matches_the_synthetic_wire() -> None:
    assert _source_wire("lazy import json") == _synthetic_lazy_import_wire(
        "import json", 1
    )
    assert _source_wire("lazy from json import dumps") == _synthetic_lazy_import_wire(
        "from json import dumps", 1
    )


def _dict_unpacking_comprehension_wire() -> str:
    """Wire of the PEP 798 ``{**mapping for mapping in mappings}`` shape.

    Python 3.15 parses it as ``DictComp`` with ``value=None`` (mirroring the
    dict literal ``{**mapping}``, whose unpacking marker is a ``None`` key).
    Older interpreters cannot parse the source, so the shape is constructed.
    """

    tree = ast.parse("{mapping: mapping for mapping in mappings}")
    statement = tree.body[0]
    assert isinstance(statement, ast.Expr)
    comprehension = statement.value
    assert isinstance(comprehension, ast.DictComp)
    object.__setattr__(comprehension, "value", None)
    return emit_wire_seq(tree.body, _DEFAULT_CONFIG, bindings_for_tree(tree))


def test_dict_unpacking_comprehension_value_none_binds_and_emits() -> None:
    """The PEP 798 ``value=None`` shape must emit a wire, never crash raw."""

    wire = _dict_unpacking_comprehension_wire()
    assert wire.startswith("Expr(value=DictComp(")
    assert "value=None" in wire
    assert wire != _source_wire("{mapping: mapping for mapping in mappings}")


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="PEP 798 dict-unpacking comprehensions require Python 3.15",
)
def test_dict_unpacking_comprehension_live_parse_matches_the_synthetic_wire() -> None:
    assert (
        _source_wire("{**mapping for mapping in mappings}")
        == _dict_unpacking_comprehension_wire()
    )
