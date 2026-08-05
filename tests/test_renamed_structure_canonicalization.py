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
