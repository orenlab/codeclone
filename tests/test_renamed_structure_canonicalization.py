# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The ordinal-canonicalization pins behind the ``renamed_structure`` digest.

Four maintainer pins plus the call-chain rule, each asserted directly against
the digest rather than through the grouping layer:

1. LOCAL and ATTRIBUTE ordinals live in separate numbering spaces.
2. Binding identity is scope-qualified before ordinal assignment.
3. Repeated use of the same symbol receives the same ordinal.
4. ``a.x + b.x`` stays distinguishable from ``a.x + b.y``.

Chain rule: in ``obj.client.send()`` the root local and the intermediate
receiver attribute rename while the terminal callee stays literal, and the
chain length itself is structural.

Alpha-equivalence is by construction, which cuts both ways: parameters
correspond by declaration position, so ``x - y`` under ``f(x, y)`` is NOT a
renaming of ``y - x`` — a mapping that merely permutes names without
respecting binding sites would claim semantic equivalence the tier cannot
prove.
"""

from __future__ import annotations

import ast
import textwrap

import pytest

from codeclone.analysis.cfg import CFGBuilder
from codeclone.analysis.fingerprint import _cfg_fingerprint_and_complexity
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.renamed_structure import renamed_structure_fingerprint
from tests._ast_metrics_helpers import bindings_for_tree


def _function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"no function {name} in tree")


def _digest(source: str, function: str = "f") -> str:
    tree = ast.parse(textwrap.dedent(source))
    node = _function_node(tree, function)
    bindings = bindings_for_tree(tree).enter(node)
    cfg = NormalizationConfig()
    graph = CFGBuilder().build(function, node, cfg, bindings)
    return renamed_structure_fingerprint(graph, node, cfg, bindings)


def _exact_fingerprint(source: str, function: str = "f") -> str:
    tree = ast.parse(textwrap.dedent(source))
    node = _function_node(tree, function)
    bindings = bindings_for_tree(tree).enter(node)
    _graph, fingerprint, _complexity = _cfg_fingerprint_and_complexity(
        node, NormalizationConfig(), function, bindings
    )
    return fingerprint


def test_consistent_local_and_attribute_renames_match() -> None:
    left = """
    def f(records):
        total = 0
        for record in records:
            total += record.amount
        return total
    """
    right = """
    def f(entries):
        gathered = 0
        for entry in entries:
            gathered += entry.volume
        return gathered
    """
    assert _digest(left) == _digest(right)


def test_parameter_positions_anchor_alpha_equivalence() -> None:
    """Pin 3 corollary: ordinals respect binding sites, not name shuffles.

    ``x - y`` and ``y - x`` under the same signature differ semantically;
    a digest that merged them would publish a false equivalence.
    """

    left = "def f(x, y):\n    return x - y\n"
    right = "def f(x, y):\n    return y - x\n"
    assert _digest(left) != _digest(right)
    consistent = "def f(u, v):\n    return u - v\n"
    assert _digest(left) == _digest(consistent)


def test_repeated_symbol_shares_one_ordinal() -> None:
    """Pin 3, and the domain split from fp3: locals are ordinals, not erased."""

    doubled = "def f(a, b):\n    return a + a\n"
    mixed = "def f(a, b):\n    return a + b\n"
    # The strict exact tier erases locals to one token, so it merges these;
    # the renamed tier is alpha-equivalence and must keep them apart.
    assert _exact_fingerprint(doubled) == _exact_fingerprint(mixed)
    assert _digest(doubled) != _digest(mixed)


def test_local_and_attribute_spaces_are_separate() -> None:
    """Pin 1: the two ordinal spaces never bleed into each other."""

    left = "def f(p):\n    return p.cost + 1\n"
    renamed = "def f(q):\n    return q.price + 1\n"
    other_receiver = "def f(p, q):\n    return q.cost + 1\n"
    assert _digest(left) == _digest(renamed)
    assert _digest(left) != _digest(other_receiver)


def test_scope_qualified_bindings_keep_shadowing_distinct() -> None:
    """Pin 2: same name in two scopes is two identities; renaming one matches."""

    shadowing = """
    def f(items):
        out = [entry * 2 for entry in items]
        entry = len(out)
        return entry
    """
    inner_renamed = """
    def f(items):
        out = [row * 2 for row in items]
        entry = len(out)
        return entry
    """
    assert _digest(shadowing) == _digest(inner_renamed)


def test_equality_pattern_is_preserved() -> None:
    """Pin 4: same-attribute-on-two-receivers is not two attributes."""

    same_attribute = "def f(a, b):\n    return a.x + b.x\n"
    two_attributes = "def f(a, b):\n    return a.x + b.y\n"
    receivers_renamed = "def f(p, q):\n    return p.x + q.x\n"
    assert _digest(same_attribute) != _digest(two_attributes)
    assert _digest(same_attribute) == _digest(receivers_renamed)


def test_import_identity_is_rigid_under_aliasing() -> None:
    aliased = """
    import json as j

    def f(payload):
        return j.dumps(payload)
    """
    plain = """
    import json

    def f(payload):
        return json.dumps(payload)
    """
    other = """
    import pickle

    def f(payload):
        return pickle.dumps(payload)
    """
    assert _digest(aliased) == _digest(plain)
    assert _digest(aliased) != _digest(other)


def test_unknowable_names_default_rigid() -> None:
    """Refusal over approximation: an unprovable name never gets an ordinal."""

    left = "def f(v):\n    return SETTINGS.mode + v\n"
    other_root = "def f(v):\n    return CONFIG.mode + v\n"
    other_attribute = "def f(v):\n    return SETTINGS.level + v\n"
    assert _digest(left) != _digest(other_root)
    assert _digest(left) != _digest(other_attribute)


def test_callee_symbol_is_rigid_across_the_whole_unit() -> None:
    """One mapping per symbol: a callee name stays literal in field position."""

    callee_and_field = """
    class C:
        def f(self):
            self.emit()
            handler = self.emit
            return handler
    """
    field_renamed = """
    class C:
        def f(self):
            self.emit()
            handler = self.send
            return handler
    """
    reference = _digest(callee_and_field)
    assert reference != _digest(field_renamed)
    local_renamed = """
    class C:
        def f(self):
            self.emit()
            grabbed = self.emit
            return grabbed
    """
    assert reference == _digest(local_renamed)


def test_chain_rule_renames_receiver_and_keeps_terminal_callee() -> None:
    through_channel = """
    def f(gateway, note):
        receipt = gateway.channel.send(note)
        return receipt
    """
    through_pipe = """
    def f(hub, item):
        stamp = hub.pipe.send(item)
        return stamp
    """
    renamed_callee = """
    def f(gateway, note):
        receipt = gateway.channel.post(note)
        return receipt
    """
    shortened = """
    def f(gateway, note):
        receipt = gateway.send(note)
        return receipt
    """
    assert _digest(through_channel) == _digest(through_pipe)
    assert _digest(through_channel) != _digest(renamed_callee)
    assert _digest(through_channel) != _digest(shortened)


def test_digest_is_deterministic() -> None:
    source = """
    def f(records):
        kept = [record for record in records if record.active]
        total = 0
        for record in kept:
            total += record.amount
        return total
    """
    assert _digest(source) == _digest(source)


def test_canonicalization_never_mutates_the_tree() -> None:
    """fp3 reads the same AST; the canonical pass must be a pure read."""

    tree = ast.parse(
        "def f(self, items):\n"
        "    total = 0\n"
        "    for item in items:\n"
        "        total += item.amount\n"
        "    return total\n"
    )
    node = _function_node(tree, "f")
    bindings = bindings_for_tree(tree).enter(node)
    cfg = NormalizationConfig()
    graph = CFGBuilder().build("f", node, cfg, bindings)
    before = ast.dump(tree)
    renamed_structure_fingerprint(graph, node, cfg, bindings)
    assert ast.dump(tree) == before


def test_own_domain_never_collides_with_fp3() -> None:
    source = """
    def f(records):
        total = 0
        for record in records:
            total += record.amount
        return total
    """
    assert _digest(source) != _exact_fingerprint(source)


# Each row is ``(case, base, renamed, distinct)``. ``renamed`` is a consistent
# renaming of ``base`` and must share its digest; ``distinct`` differs
# structurally and must not. Both directions are asserted for every row, so an
# over-rigid canonicalizer fails the first assertion and an over-loose one
# fails the second. The rows are constructs the unit's own straight-line body
# cannot reach: inner scopes, pattern nodes, and the receiver shapes that
# decide whether an attribute is renameable at all.
_ALPHA_EQUIVALENCE_CASES: tuple[tuple[str, str, str, str], ...] = (
    (
        "nested_def",
        """
        def f(items):
            def scale(value):
                return value * value
            return [scale(item) for item in items]
        """,
        """
        def f(entries):
            def grow(amount):
                return amount * amount
            return [grow(entry) for entry in entries]
        """,
        """
        def f(items):
            def scale(value, factor):
                return factor * value
            return [scale(item, item) for item in items]
        """,
    ),
    (
        "lambda",
        """
        def f(rows):
            pick = lambda left, right: left - right
            return pick(rows, rows)
        """,
        """
        def f(cells):
            take = lambda first, second: first - second
            return take(cells, cells)
        """,
        """
        def f(rows):
            pick = lambda left, right: right - left
            return pick(rows, rows)
        """,
    ),
    (
        "nested_class",
        """
        def f(seed):
            class Holder:
                limit = seed
            return Holder
        """,
        """
        def f(start):
            class Keeper:
                bound = start
            return Keeper
        """,
        """
        def f(seed):
            class Holder:
                limit = seed
                extra = seed
            return Holder
        """,
    ),
    # A handler reaches the walker as a real ``ExceptHandler`` only from an
    # inner scope: the unit's own ``try`` is lowered into CFG blocks, so its
    # handler never becomes a block statement.
    (
        "nested_except_binding",
        """
        def f(source):
            def read(handle):
                try:
                    return handle.load()
                except ValueError as failure:
                    return failure
            return read(source)
        """,
        """
        def f(origin):
            def fetch(stream):
                try:
                    return stream.load()
                except ValueError as problem:
                    return problem
            return fetch(origin)
        """,
        """
        def f(source):
            def read(handle):
                try:
                    return handle.load()
                except TypeError as failure:
                    return failure
            return read(source)
        """,
    ),
    (
        "nested_match_captures",
        """
        def f(payload):
            def classify(event):
                match event:
                    case [head, *tail]:
                        return head, tail, head
                    case {"a": one, **rest}:
                        return one, rest, one
                    case _:
                        return None
            return classify(payload)
        """,
        """
        def f(payload):
            def sort(signal):
                match signal:
                    case [first, *others]:
                        return first, others, first
                    case {"a": single, **remainder}:
                        return single, remainder, single
                    case _:
                        return None
            return sort(payload)
        """,
        """
        def f(payload):
            def classify(event):
                match event:
                    case [head, *tail]:
                        return tail, head, head
                    case {"a": one, **rest}:
                        return one, rest, one
                    case _:
                        return None
            return classify(payload)
        """,
    ),
    # An ``as`` capture over a sub-pattern, against the same mapping with no
    # ``**rest``: the sub-pattern and the double-star are structure.
    (
        "nested_match_as_capture",
        """
        def f(payload):
            def read(event):
                match event:
                    case {"a": inner} as whole:
                        return inner, whole, inner
                    case _:
                        return None
            return read(payload)
        """,
        """
        def f(payload):
            def scan(signal):
                match signal:
                    case {"a": part} as entire:
                        return part, entire, part
                    case _:
                        return None
            return scan(payload)
        """,
        """
        def f(payload):
            def read(event):
                match event:
                    case {"a": inner}:
                        return inner, inner, inner
                    case _:
                        return None
            return read(payload)
        """,
    ),
    # The unit's OWN match arrives as ``__CC_META__`` markers that spell the
    # pattern shape with capture names already replaced by ``_VAR_``. So
    # renaming captures is invisible here while the shape still separates.
    (
        "top_level_match_marker",
        """
        def f(event):
            match event:
                case [head, *tail]:
                    return head, tail, head
                case _:
                    return None
        """,
        """
        def f(event):
            match event:
                case [first, *others]:
                    return first, others, first
                case _:
                    return None
        """,
        """
        def f(event):
            match event:
                case [head, extra]:
                    return head, extra, head
                case _:
                    return None
        """,
    ),
    (
        "dict_comprehension",
        """
        def f(pairs):
            return {pair.key: pair.value for pair in pairs}
        """,
        """
        def f(items):
            return {item.name: item.datum for item in items}
        """,
        """
        def f(pairs):
            return {pair.key: pair.key for pair in pairs}
        """,
    ),
    # ``{**base}`` stores ``None`` in ``Dict.keys`` -- the one list field the
    # walker recurses into that can hold something other than a node.
    (
        "dict_unpacking",
        """
        def f(base, extra):
            return {**base, "k": extra}
        """,
        """
        def f(origin, other):
            return {**origin, "k": other}
        """,
        """
        def f(base, extra):
            return {"k": extra}
        """,
    ),
    (
        "parameter_defaults",
        """
        def f(base):
            def apply(value=base, *, plain, scale=base):
                return value, plain, scale
            return apply
        """,
        """
        def f(seed):
            def run(amount=seed, *, bare, factor=seed):
                return amount, bare, factor
            return run
        """,
        """
        def f(base):
            def apply(value=base, *, plain, scale=value):
                return value, plain, scale
            return apply
        """,
    ),
    (
        "classmethod_receiver",
        """
        class C:
            @classmethod
            def f(cls, total):
                cls.registry = total
                return cls.registry
        """,
        """
        class C:
            @classmethod
            def f(cls, amount):
                cls.store = amount
                return cls.store
        """,
        """
        class C:
            @classmethod
            def f(cls, total):
                cls.registry = total
                return total
        """,
    ),
    (
        "subscript_receiver_is_rigid",
        """
        def f(self, rows):
            return self.items[0].label + rows.label
        """,
        """
        def f(self, cells):
            return self.items[0].label + cells.label
        """,
        """
        def f(self, rows):
            return self.items[0].other + rows.label
        """,
    ),
    # A renameable chain is walked link by link, and its length is emitted.
    (
        "receiver_chain_depth",
        """
        def f(obj):
            return obj.inner.leaf
        """,
        """
        def f(holder):
            return holder.middle.tip
        """,
        """
        def f(obj):
            return obj.leaf
        """,
    ),
)


@pytest.mark.parametrize(
    ("case", "base", "renamed", "distinct"),
    _ALPHA_EQUIVALENCE_CASES,
    ids=[row[0] for row in _ALPHA_EQUIVALENCE_CASES],
)
def test_canonicalization_is_alpha_equivalent_and_no_looser(
    case: str, base: str, renamed: str, distinct: str
) -> None:
    """One relation, asserted over every construct that can carry it."""

    assert _digest(base) == _digest(renamed), (
        f"{case}: a consistent renaming changed the digest"
    )
    assert _digest(base) != _digest(distinct), (
        f"{case}: a structural difference was absorbed into one digest"
    )


def test_global_stays_rigid_while_nonlocal_renames() -> None:
    """The two bound-name statements reach opposite rigidity verdicts.

    A ``global`` name has no provable local binding, so it stays literal and a
    renaming is a different unit. A ``nonlocal`` name resolves to a local of
    the enclosing scope, so it takes an ordinal and renames like any other.
    """

    global_base = """
    def f():
        global counter
        counter = counter + 1
        return counter
    """
    global_renamed = """
    def f():
        global tally
        tally = tally + 1
        return tally
    """
    nonlocal_base = """
    def f(seed):
        stored = seed
        def bump(step):
            nonlocal stored
            stored = stored + step
            return stored
        return bump
    """
    nonlocal_renamed = """
    def f(origin):
        kept = origin
        def raise_by(delta):
            nonlocal kept
            kept = kept + delta
            return kept
        return raise_by
    """
    assert _digest(global_base) != _digest(global_renamed)
    assert _digest(nonlocal_base) == _digest(nonlocal_renamed)


def _import_position_source(body: str, *, module: str, alias: str | None = None) -> str:
    """A unit whose body puts an import-rooted chain in one syntactic slot."""

    header = f"import {module}" if alias is None else f"import {module} as {alias}"
    return f"{header}\n\ndef f(rows):\n{body.format(root=alias or module)}"


# The syntactic slots in which a canonicalized child can REPLACE its copy
# rather than be rewritten in place. Replacement happens only where an
# import-rooted attribute chain collapses to a single identity node, so each
# slot below is the only route to its own replacement branch.
_IMPORT_COLLAPSE_POSITIONS: tuple[tuple[str, str], ...] = (
    ("bare_name", "    return {root}(rows)\n"),
    ("return_value", "    return {root}.dumps\n"),
    ("list_element", "    return [{root}.dumps, rows]\n"),
    ("comprehension_iterable", "    return [item for item in {root}.registry]\n"),
    ("comprehension_element", "    return [{root}.dumps for item in rows]\n"),
    ("comprehension_target", "    return [item for {root}.slot in rows]\n"),
    (
        "dict_comprehension_pair",
        "    return {{{root}.key: {root}.value for item in rows}}\n",
    ),
    ("lambda_body", "    return lambda: {root}.dumps\n"),
    (
        "decorator_and_defaults",
        "    @{root}.cache\n"
        "    def inner(value={root}.default, *, plain, kw={root}.other):\n"
        "        return value, plain, kw\n"
        "    return inner\n",
    ),
)


@pytest.mark.parametrize(
    ("position", "body"),
    _IMPORT_COLLAPSE_POSITIONS,
    ids=[row[0] for row in _IMPORT_COLLAPSE_POSITIONS],
)
def test_import_identity_is_rigid_in_every_syntactic_position(
    position: str, body: str
) -> None:
    """An imported chain is one rigid identity wherever it is written.

    The alias is the renaming that must NOT move the digest and the different
    module is the identity change that must. Running the pair through every
    slot is what proves the collapse is applied by position, rather than only
    where existing tests happened to put it.
    """

    plain = _import_position_source(body, module="json")
    aliased = _import_position_source(body, module="json", alias="codec")
    other = _import_position_source(body, module="pickle")
    assert _digest(plain) == _digest(aliased), (
        f"{position}: aliasing the import changed the digest"
    )
    assert _digest(plain) != _digest(other), (
        f"{position}: a different imported identity collapsed to one digest"
    )


def _nested_handler_source(clause: str, body: str) -> str:
    """A nested unit whose inner function carries one ``except`` clause."""

    return (
        "def f(source):\n"
        "    def read(handle):\n"
        "        try:\n"
        "            return handle.load()\n"
        f"        {clause}\n"
        f"            {body}\n"
        "    return read(source)\n"
    )


def test_except_clause_parts_are_each_structural() -> None:
    """A handler's caught type and bound name are independently optional.

    The type is an ordinary expression, so it can itself be an imported
    identity that must collapse; and dropping either the type or the binding
    is a shape change the digest has to carry.
    """

    imported = "import json\n\n" + _nested_handler_source(
        "except json.JSONDecodeError as failure:", "return failure"
    )
    imported_aliased = "import json as codec\n\n" + _nested_handler_source(
        "except codec.JSONDecodeError as problem:", "return problem"
    )
    imported_other = "import pickle\n\n" + _nested_handler_source(
        "except pickle.UnpicklingError as failure:", "return failure"
    )
    bare = _nested_handler_source("except:", "return None")
    typed = _nested_handler_source("except ValueError:", "return None")
    typed_and_bound = _nested_handler_source(
        "except ValueError as failure:", "return None"
    )
    assert _digest(imported) == _digest(imported_aliased)
    assert _digest(imported) != _digest(imported_other)
    assert _digest(bare) != _digest(typed)
    assert _digest(typed) != _digest(typed_and_bound)
