# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import hashlib

import pytest

import codeclone.findings.design.instance_methods as instance_methods_mod
from codeclone.domain.findings import (
    DESIGN_KIND_INSTANCE_INDEPENDENT_METHOD,
    IIM_CLASSIFICATION_CANDIDATE,
    IIM_CLASSIFICATION_DECORATED_CONTEXT,
    IIM_CLASSIFICATION_DUNDER_PROTOCOL,
    IIM_CLASSIFICATION_INTERFACE_CONTRACT,
    IIM_CLASSIFICATION_NOOP_STUB,
    IIM_CLASSIFICATION_OVERRIDE_CONTEXT,
    IIM_CLASSIFICATION_PROPERTY_LIKE,
)
from codeclone.findings.design import (
    DesignFindingSignature,
    InstanceIndependentMethodOccurrence,
    collect_instance_independent_methods,
    group_instance_independent_methods,
)

from .ast_test_helpers import parse_class_first_member


def _collect(
    source: str,
    *,
    file_path: str = "pkg/module.py",
) -> tuple[InstanceIndependentMethodOccurrence, ...]:
    tree = ast.parse(source)
    return collect_instance_independent_methods(tree=tree, file_path=file_path)


def _classification(source: str) -> str | None:
    occurrences = _collect(source)
    if not occurrences:
        return None
    assert len(occurrences) == 1
    return occurrences[0].classification


# --- methods that are NOT instance-independent (no finding) -----------------

_NO_FINDING_SOURCES = {
    "reads_self_attr": "def helper(self, value):\n        return self.base + value",
    "writes_self_attr": "def helper(self, value):\n        self.cache = value",
    "augmented_assign_self": "def helper(self, value):\n        self.total += value",
    "deletes_self_attr": "def helper(self):\n        del self.cache",
    "calls_self_helper": "def helper(self, value):\n        return self.compute(value)",
    "returns_bare_self": "def chain(self):\n        return self",
    "zero_arg_super": "def close(self):\n        return super().close()",
    "explicit_super_with_self": "def close(self):\n        return super(A, self).x()",
    "nested_closure_reads_self": (
        "def make(self):\n"
        "        def check(value):\n"
        "            return value in self.allowed\n\n"
        "        return check"
    ),
    "nested_lambda_reads_self": (
        "def make(self):\n        return lambda value: value in self.allowed"
    ),
    "staticmethod_skipped": (
        "@staticmethod\n    def helper(value):\n        return value"
    ),
    "classmethod_skipped": (
        "@classmethod\n    def make(cls, value):\n        return value"
    ),
    "overload_skipped": "@overload\n    def helper(self, value):\n        ...",
    "non_self_first_arg": "def helper(cls, value):\n        return value",
}


@pytest.mark.parametrize("body", sorted(_NO_FINDING_SOURCES.values()))
def test_methods_that_use_receiver_or_are_skipped_emit_no_finding(body: str) -> None:
    assert _classification(f"class A(Base):\n    {body}\n") is None


# --- classification of instance-independent methods -------------------------

_CLASSIFIED_SOURCES = {
    "plain_method": (
        "class A:\n    def helper(self, value):\n        return value + 1\n",
        IIM_CLASSIFICATION_CANDIDATE,
    ),
    "async_method": (
        "class A:\n    async def helper(self, value):\n        return value * 2\n",
        IIM_CLASSIFICATION_CANDIDATE,
    ),
    "global_state_only": (
        "import os\n\nclass A:\n"
        "    def helper(self, value):\n        return os.environ.get(value)\n",
        IIM_CLASSIFICATION_CANDIDATE,
    ),
    "nested_self_param_shadows": (
        "class A:\n    def builder(self, items):\n"
        "        def render(self, value):\n            return self.format(value)\n\n"
        "        return render\n",
        IIM_CLASSIFICATION_CANDIDATE,
    ),
    "final_decorator": (
        "class A:\n    @final\n    def handle(self, value):\n        return value\n",
        IIM_CLASSIFICATION_CANDIDATE,
    ),
    "property_like": (
        'class A:\n    @property\n    def name(self):\n        return "x"\n',
        IIM_CLASSIFICATION_PROPERTY_LIKE,
    ),
    "setter_like": (
        "class A:\n    @name.setter\n"
        "    def name(self, value):\n        return value\n",
        IIM_CLASSIFICATION_PROPERTY_LIKE,
    ),
    "dunder": (
        "class A:\n    def __eq__(self, other):\n        return True\n",
        IIM_CLASSIFICATION_DUNDER_PROTOCOL,
    ),
    "noop_pass": (
        "class A:\n    def hook(self):\n        pass\n",
        IIM_CLASSIFICATION_NOOP_STUB,
    ),
    "noop_ellipsis": (
        "class A:\n    def hook(self):\n        ...\n",
        IIM_CLASSIFICATION_NOOP_STUB,
    ),
    "noop_not_implemented": (
        "class A:\n    def hook(self):\n        raise NotImplementedError()\n",
        IIM_CLASSIFICATION_NOOP_STUB,
    ),
    "docstring_only": (
        'class A:\n    def hook(self):\n        """Documented but empty."""\n',
        IIM_CLASSIFICATION_NOOP_STUB,
    ),
    "protocol_base": (
        "class A(Protocol):\n    def handle(self, value):\n        return value\n",
        IIM_CLASSIFICATION_INTERFACE_CONTRACT,
    ),
    "abc_base": (
        "class A(ABC):\n    def handle(self, value):\n        return value\n",
        IIM_CLASSIFICATION_INTERFACE_CONTRACT,
    ),
    "abstractmethod": (
        "class A:\n    @abstractmethod\n"
        "    def handle(self, value):\n        return value\n",
        IIM_CLASSIFICATION_INTERFACE_CONTRACT,
    ),
    "override": (
        "class A:\n    @override\n    def handle(self, value):\n        return value\n",
        IIM_CLASSIFICATION_OVERRIDE_CONTEXT,
    ),
    "typing_override": (
        "class A:\n    @typing.override\n"
        "    def handle(self, value):\n        return value\n",
        IIM_CLASSIFICATION_OVERRIDE_CONTEXT,
    ),
    "unknown_decorator": (
        "class A:\n    @register_handler\n"
        "    def handle(self, value):\n        return value\n",
        IIM_CLASSIFICATION_DECORATED_CONTEXT,
    ),
    # Precedence: property_like (rank 3) wins over interface_contract (rank 5).
    "abstract_property": (
        "class A(ABC):\n    @property\n    @abstractmethod\n"
        '    def name(self):\n        return "x"\n',
        IIM_CLASSIFICATION_PROPERTY_LIKE,
    ),
    # Precedence: dunder_protocol (rank 4) wins over decorated_context (rank 7).
    "decorated_dunder": (
        "class A:\n    @register_handler\n"
        "    def __call__(self, value):\n        return value\n",
        IIM_CLASSIFICATION_DUNDER_PROTOCOL,
    ),
}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(src, exp, id=name)
        for name, (src, exp) in _CLASSIFIED_SOURCES.items()
    ],
)
def test_method_classification(source: str, expected: str) -> None:
    assert _classification(source) == expected


# --- nested class receiver isolation ----------------------------------------


def test_nested_class_method_self_does_not_count_as_outer_receiver() -> None:
    occurrences = _collect(
        "class Outer:\n"
        "    def build(self):\n"
        "        class Inner:\n"
        "            def run(self):\n"
        "                return self.value\n\n"
        "        return Inner\n"
    )
    classifications = {occ.method_qualname: occ.classification for occ in occurrences}
    # Outer.build never reads its own receiver -> candidate; Inner.run reads its
    # own receiver -> not emitted.
    assert classifications == {"Outer.build": IIM_CLASSIFICATION_CANDIDATE}


# --- grouping + signatures --------------------------------------------------


def test_grouping_splits_production_and_context_counts() -> None:
    occurrences = _collect(
        "class Mixin:\n"
        "    def alpha(self, value):\n        return value\n\n"
        "    def beta(self, value):\n        return value + 1\n\n"
        "    @register_handler\n"
        "    def gamma(self, value):\n        return value\n\n"
        "    @property\n"
        '    def name(self):\n        return "x"\n'
    )
    groups = group_instance_independent_methods(occurrences)
    assert len(groups) == 1
    group = groups[0]
    assert group.finding_kind == DESIGN_KIND_INSTANCE_INDEPENDENT_METHOD
    assert group.class_qualname == "Mixin"
    # gamma -> decorated_context (context), name -> property_like (suppressed).
    assert group.signature == DesignFindingSignature(
        candidate_count=2,
        production_candidate_count=2,
        test_candidate_count=0,
        context_count=1,
        suppressed_count=1,
    )


def test_grouping_marks_test_candidates_by_source_path() -> None:
    occurrences = _collect(
        "class Helper:\n    def util(self, value):\n        return value\n",
        file_path="tests/test_thing.py",
    )
    groups = group_instance_independent_methods(
        occurrences,
        test_paths=frozenset({"tests/test_thing.py"}),
    )
    assert groups[0].signature == DesignFindingSignature(
        candidate_count=1,
        production_candidate_count=0,
        test_candidate_count=1,
        context_count=0,
        suppressed_count=0,
    )


def test_group_finding_key_is_stable_sha1() -> None:
    occurrences = _collect(
        "class Mixin:\n    def alpha(self, value):\n        return value\n"
    )
    group = group_instance_independent_methods(occurrences)[0]
    expected = hashlib.sha1(
        b"design:instance_independent_method:v1\npkg/module.py\nMixin",
        usedforsecurity=False,
    ).hexdigest()
    assert group.finding_key == expected


def test_groups_order_by_candidate_count_then_path() -> None:
    occurrences = (
        *_collect(
            "class Small:\n    def a(self, v):\n        return v\n",
            file_path="pkg/a.py",
        ),
        *_collect(
            "class Big:\n"
            "    def a(self, v):\n        return v\n\n"
            "    def b(self, v):\n        return v\n",
            file_path="pkg/b.py",
        ),
    )
    groups = group_instance_independent_methods(occurrences)
    # Big (2 candidates) ranks before Small (1 candidate).
    assert [group.class_qualname for group in groups] == ["Big", "Small"]


def test_helper_edge_cases_cover_ast_branches() -> None:
    call_decorator = ast.parse("@cache(maxsize=1)\ndef f(): ...").body[0]
    assert isinstance(call_decorator, ast.FunctionDef)
    decorator = call_decorator.decorator_list[0]
    assert instance_methods_mod._simple_decorator_name(decorator) == "cache"

    name_decorator = ast.parse("@final\ndef f(): ...").body[0]
    assert isinstance(name_decorator, ast.FunctionDef)
    assert (
        instance_methods_mod._simple_decorator_name(name_decorator.decorator_list[0])
        == "final"
    )

    subscript_base = ast.parse("class A(Generic[T]): ...").body[0]
    assert isinstance(subscript_base, ast.ClassDef)
    assert instance_methods_mod._simple_base_name(subscript_base.bases[0]) == "Generic"

    metaclass_node = ast.parse("class A(metaclass=ABCMeta): ...").body[0]
    assert isinstance(metaclass_node, ast.ClassDef)
    assert instance_methods_mod._class_is_interface(metaclass_node, ()) is True

    kwonly = ast.parse("def helper(*, value):\n    return value\n").body[0]
    assert isinstance(kwonly, ast.FunctionDef)
    assert instance_methods_mod._first_positional_arg(kwonly) is None

    vararg_func = ast.parse(
        "def helper(self, *args, **kwargs):\n    return args\n"
    ).body[0]
    assert isinstance(vararg_func, ast.FunctionDef)
    names = instance_methods_mod._function_param_names(vararg_func)
    assert names == {"self", "args", "kwargs"}

    _async_class, method = parse_class_first_member(
        "class A:\n    async def helper(self):\n        return 1\n",
        ast.AsyncFunctionDef,
    )
    visitor = instance_methods_mod._ReceiverUseVisitor()
    visitor.visit(method)
    assert visitor.receiver_reads == 0

    _outer_class, outer_method = parse_class_first_member(
        "class Outer:\n"
        "    def build(self):\n"
        "        class Inner(Base):\n"
        "            pass\n",
        ast.FunctionDef,
    )
    visitor = instance_methods_mod._ReceiverUseVisitor()
    for statement in outer_method.body:
        visitor.visit(statement)

    class _NodeWithoutEndLine(ast.AST):
        pass

    assert instance_methods_mod._node_end_line(_NodeWithoutEndLine(), 9) == 9

    bare_raise = ast.parse("raise\n").body[0]
    assert isinstance(bare_raise, ast.Raise)
    assert instance_methods_mod._raises_not_implemented(bare_raise) is False


def test_grouping_counts_suppressed_classifications() -> None:
    occurrences = _collect("class Mixin:\n    def hook(self):\n        pass\n")
    groups = group_instance_independent_methods(occurrences)
    assert groups[0].signature.suppressed_count == 1
    assert groups[0].signature.candidate_count == 0


def test_occurrences_are_deterministically_ordered() -> None:
    occurrences = _collect(
        "class A:\n"
        "    def gamma(self, v):\n        return v\n\n"
        "    def alpha(self, v):\n        return v\n\n"
        "    def beta(self, v):\n        return v\n"
    )
    starts = [occ.start for occ in occurrences]
    assert starts == sorted(starts)


def test_decorator_and_base_name_helpers_ignore_non_names() -> None:
    import ast

    import codeclone.findings.design.instance_methods as instance_methods_mod

    assert instance_methods_mod._simple_decorator_name(ast.Constant(value=1)) == ""
    assert instance_methods_mod._simple_base_name(ast.Constant(value=1)) == ""
