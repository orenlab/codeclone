# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Ordinal canonicalization behind the ``renamed_structure`` clone tier (Wave C).

Two units are a ``renamed_structure`` pair when there exists a bijective,
consistent renaming between them: local bindings may rename, attributes on
local/``self``/``cls`` receivers may rename, the mapping is one-to-one and the
same across the whole unit, and everything else — imported identities, proven
global names, terminal callees, attribute-chain length, CFG structure — stays
rigid. The tier is an exact match in its own digest domain: O(n) per unit,
alpha-equivalence by construction, no pairwise matcher and no similarity score.

The construction is a pure read of the same artifacts the exact tier already
produced. Each CFG block statement is deep-copied, the copy is rewritten in
lockstep with the original so that every symbol decision is resolved against
the original nodes' scope graph, and the rewritten copy is emitted through the
existing versioned wire with ``normalize_names=False`` — by then every name IS
its canonical spelling. fp3, the wire and the CFG are never modified and never
mutated (the mutation-free property is pinned by test).

The ordinal encoding, pin by pin:

1. *Separate spaces.* Renameable locals become ``_L{n}_`` and renameable
   attributes become ``_A{n}_``, from two independent counters.
2. *Scope-qualified identity.* A local's ordinal key is
   ``(binding scope token, name)`` via ``BindingContext.lookup_site``, so two
   bindings sharing a name in different scopes get distinct ordinals and
   shadowing is respected. Attribute ordinals key on the attribute name
   unit-wide — attributes have no scope of their own.
3. *First occurrence.* Repeated use of a symbol reuses its ordinal. Occurrence
   order is the walker's fixed walk order, with one deliberate anchor:
   parameters are seeded in declaration order when their scope is entered, so
   ordinals respect binding sites. ``x - y`` under ``f(x, y)`` is therefore
   NOT a renaming of ``y - x`` — a digest that merged them would publish a
   semantic equivalence the tier cannot prove.
4. *Equality pattern.* Attribute ordinals are per attribute NAME, never per
   ``receiver.attr`` pair, so ``a.x + b.x`` and ``a.x + b.y`` stay apart.

Call-chain rule (``obj.client.send()``): the root local renames, intermediate
receiver attributes rename, the terminal callee is literal, and the chain
length is structural because the ``Attribute`` nesting itself is emitted. A
callee name is one symbol with one image, so every attribute name that appears
as a terminal callee anywhere in the unit stays literal in every position.

Rigidity is the honest default. A name with no provable binding (builtins,
module-scope names, unresolved imports) stays literal, as does any attribute
whose receiver chain does not provably root at a local/``self``/``cls`` name —
``self.items[0].name`` freezes ``name`` because its receiver is a subscript,
not a proven renameable chain. An over-rigid tier under-reports; an over-loose
one lies. Canonical tokens share the wire's residual-collision class: a
literal global spelled ``_L0_`` could collide with an ordinal, exactly as a
global spelled ``_SELF_`` already can inside fp3.
"""

from __future__ import annotations

import ast
import hashlib
from copy import deepcopy
from typing import TYPE_CHECKING, Final, TypeVar, cast

from ..contracts import RENAMED_STRUCTURE_ALGORITHM_REVISION
from ..meta_markers import CFG_META_PREFIX
from .binding import EMPTY_BINDINGS, BindingContext
from .fingerprint import (
    _NEAR_MISS_BOUNDARY_PREFIX,
    _NEAR_MISS_TOKEN_HEX,
    _signature_token,
    sha256_hex,
)
from .normalizer import NormalizationConfig
from .wire import emit_wire

if TYPE_CHECKING:
    from ..models import BindingSite, NearMissElement
    from .cfg import CFG

__all__ = ["renamed_structure_artifacts", "renamed_structure_fingerprint"]

# The domain moves with the tier's algorithm revision for the same reason the
# fp3 domain moves with the fingerprint version: a digest must not keep its
# bytes across two incompatible generations of its own meaning.
_DOMAIN: Final = f"ccrs{RENAMED_STRUCTURE_ALGORITHM_REVISION}:fn\x00".encode()
# The statement-token domain of the near-miss renamed token domain (the CxB
# composition). It moves with the CANONICALIZATION revision, not the near-miss
# one: a token's bytes mean "this canonical spelling", so they must change
# exactly when the canonicalization rules do, while the near-miss algorithm
# revision governs what is computed over the tokens. Never comparable with
# the y8 statement tokens — the two domains never share an index.
_SEQUENCE_DOMAIN: Final = (
    f"ccnmrs{RENAMED_STRUCTURE_ALGORITHM_REVISION}:stmt\x00".encode()
)

_RENAMEABLE_RECEIVER_ROLES: Final = frozenset({"local", "self", "cls"})

_COMPREHENSION_TYPES: Final = (
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)

_TNode = TypeVar("_TNode", bound=ast.AST)


def renamed_structure_artifacts(
    graph: CFG,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> tuple[str, tuple[NearMissElement, ...]]:
    """Return the unit's ordinal-canonical digest and statement sequence.

    One canonicalization walk, two projections. The walk is the one the exact
    fingerprint already performs — the signature token, then blocks in sorted
    id order with their successor ids — so CFG structure is preserved
    identically. Only the statement wire differs: each statement is
    canonicalized as described in the module docstring before it meets the
    emitter. Nothing here feeds fp3, the baseline, or any gate.

    The digest is the ``renamed_structure`` tier's exact-match identity. The
    sequence is the near-miss tier's renamed token domain (the CxB
    composition): a ``near_miss_statement_sequence`` twin whose tokens hash
    the CANONICAL wire in ``_SEQUENCE_DOMAIN``, with one control-flow anchor
    per block exactly like the y8 twin, so the near-miss deletion index,
    budget and witness law run over it unchanged. Both projections come from
    the same walker because ordinal assignment is walk-global: computing them
    in separate walks would only repeat the deep-copy cost to reach identical
    tokens. Spans are the ORIGINAL statements' source lines — canonical
    spellings exist for comparison; evidence shows the user their real code.
    """

    walker = _Canonicalizer(rigid_attributes=_rigid_attribute_callees(node))
    walker.seed_parameters(node.args, None, bindings)
    wire_cfg = NormalizationConfig(
        ignore_docstrings=cfg.ignore_docstrings,
        # Annotation independence is part of the tier's law: a renaming pair
        # renames its type spellings too, so annotations never reach the wire
        # and are never canonicalized.
        ignore_type_annotations=True,
        normalize_constants=cfg.normalize_constants,
        # Every name in the canonical copy already IS its final spelling.
        normalize_names=False,
    )
    parts: list[str] = [_signature_token(node)]
    sequence: list[NearMissElement] = []
    for block in sorted(graph.blocks, key=lambda b: b.id):
        succ_ids = ",".join(
            str(s.id) for s in sorted(block.successors, key=lambda s: s.id)
        )
        wires = [
            emit_wire(
                walker.canonical_copy(statement, bindings),
                wire_cfg,
                EMPTY_BINDINGS,
            )
            for statement in block.statements
        ]
        parts.append(f"BLOCK[{block.id}]:{';'.join(wires)}|SUCCESSORS:{succ_ids}")
        sequence.append((f"{_NEAR_MISS_BOUNDARY_PREFIX}{block.id}>{succ_ids}", 0, 0))
        for statement, wire in zip(block.statements, wires, strict=True):
            token = hashlib.sha256(_SEQUENCE_DOMAIN + wire.encode("utf-8")).hexdigest()[
                :_NEAR_MISS_TOKEN_HEX
            ]
            start = int(getattr(statement, "lineno", 0) or 0)
            end = int(getattr(statement, "end_lineno", 0) or 0) or start
            sequence.append((token, start, end))
    return sha256_hex(_DOMAIN, "|".join(parts)), tuple(sequence)


def renamed_structure_fingerprint(
    graph: CFG,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    cfg: NormalizationConfig,
    bindings: BindingContext,
) -> str:
    """Return only the ordinal-canonical digest — see the artifacts producer."""

    digest, _sequence = renamed_structure_artifacts(graph, node, cfg, bindings)
    return digest


def _rigid_attribute_callees(node: ast.AST) -> frozenset[str]:
    """Every attribute name used as a terminal callee anywhere in the unit.

    The mapping is one-to-one and the same across the whole unit, and a
    terminal callee is rigid — so a symbol that is a callee anywhere has the
    identity image everywhere, including field positions. Collected receiver-
    independently: an import-rooted callee like ``json.dumps`` also freezes a
    same-named attribute on a renameable receiver, which is the over-rigid,
    honest reading of "one symbol, one image".
    """

    rigid: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            rigid.add(child.func.attr)
    return frozenset(rigid)


class _Canonicalizer:
    """One unit's canonicalization walk, holding the two ordinal spaces.

    A stateful AST walker in the mold of ``CFGBuilder``, not a data model:
    the ordinal maps grow as the walk discovers symbols, and every rewrite
    method reads them. ``orig`` nodes supply every decision — scope entry is
    keyed by original node identity, and roles come from the original scope
    graph — while the deep copies receive every mutation. The two trees are
    structurally identical by ``deepcopy``, so index-wise lockstep is exact
    and the casts below only restate that structural fact for the checker.
    """

    def __init__(self, *, rigid_attributes: frozenset[str]) -> None:
        self._rigid_attributes = rigid_attributes
        self._locals: dict[tuple[int, str], str] = {}
        self._attributes: dict[str, str] = {}

    def local_token(self, site: BindingSite, name: str) -> str:
        key = (site.scope_token, name)
        token = self._locals.get(key)
        if token is None:
            token = f"_L{len(self._locals)}_"
            self._locals[key] = token
        return token

    def attribute_token(self, name: str) -> str:
        token = self._attributes.get(name)
        if token is None:
            token = f"_A{len(self._attributes)}_"
            self._attributes[name] = token
        return token

    def canonical_copy(self, statement: ast.stmt, ctx: BindingContext) -> ast.AST:
        """Canonicalize one statement without touching the original tree."""

        duplicate = deepcopy(statement)
        return self._canonicalize(statement, duplicate, ctx)

    def _canonicalize(
        self,
        orig: ast.AST,
        copy_node: ast.AST,
        ctx: BindingContext,
    ) -> ast.AST:
        if isinstance(orig, ast.Name):
            return self._canonical_name(orig, cast("ast.Name", copy_node), ctx)
        if isinstance(orig, ast.Attribute):
            return self._canonical_attribute(
                orig, cast("ast.Attribute", copy_node), ctx, callee=False
            )
        if isinstance(orig, ast.Call):
            return self._canonical_call(orig, cast("ast.Call", copy_node), ctx)
        if isinstance(orig, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return self._canonical_function(
                orig,
                cast("ast.FunctionDef | ast.AsyncFunctionDef", copy_node),
                ctx,
            )
        if isinstance(orig, ast.Lambda):
            return self._canonical_lambda(orig, cast("ast.Lambda", copy_node), ctx)
        if isinstance(orig, ast.ClassDef):
            return self._canonical_class(orig, cast("ast.ClassDef", copy_node), ctx)
        if isinstance(orig, _COMPREHENSION_TYPES):
            return self._canonical_comprehension(orig, copy_node, ctx)
        if isinstance(orig, ast.ExceptHandler):
            return self._canonical_except_handler(
                orig, cast("ast.ExceptHandler", copy_node), ctx
            )
        if isinstance(orig, (ast.Global, ast.Nonlocal)):
            bound_copy = cast("ast.Global | ast.Nonlocal", copy_node)
            bound_copy.names = [
                self._canonical_bound_string(name, ctx) for name in orig.names
            ]
            return bound_copy
        if isinstance(orig, (ast.MatchAs, ast.MatchStar)):
            return self._canonical_capture(
                orig, cast("ast.MatchAs | ast.MatchStar", copy_node), ctx
            )
        if isinstance(orig, ast.MatchMapping):
            mapping_copy = cast("ast.MatchMapping", copy_node)
            self._canonical_children(orig, mapping_copy, ctx, skip=("rest",))
            if orig.rest is not None:
                mapping_copy.rest = self._canonical_bound_string(orig.rest, ctx)
            return mapping_copy
        return self._canonical_children(orig, copy_node, ctx)

    def _canonical_children(
        self,
        orig: ast.AST,
        copy_node: ast.AST,
        ctx: BindingContext,
        *,
        skip: tuple[str, ...] = (),
    ) -> ast.AST:
        """Recurse into child nodes in field order; strings stay untouched here.

        Annotations are skipped by name: the tier's wire always ignores them,
        and a signature annotation is evaluated in the enclosing scope this
        walk has already left behind. Never canonicalized, never emitted.
        """

        for field_name in orig._fields:
            if field_name in skip or field_name in ("annotation", "returns"):
                continue
            value = getattr(orig, field_name, None)
            if isinstance(value, ast.AST):
                copy_value = cast("ast.AST", getattr(copy_node, field_name))
                replacement = self._canonicalize(value, copy_value, ctx)
                if replacement is not copy_value:
                    setattr(copy_node, field_name, replacement)
            elif isinstance(value, list):
                copy_items = cast("list[object]", getattr(copy_node, field_name))
                for index, item in enumerate(value):
                    if isinstance(item, ast.AST):
                        copy_item = cast("ast.AST", copy_items[index])
                        replacement = self._canonicalize(item, copy_item, ctx)
                        if replacement is not copy_item:
                            copy_items[index] = replacement
        return copy_node

    def _canonical_name(
        self,
        orig: ast.Name,
        copy_node: ast.Name,
        ctx: BindingContext,
    ) -> ast.AST:
        name = orig.id
        if name.startswith(CFG_META_PREFIX):
            return copy_node
        site = ctx.lookup_site(name)
        if site is None:
            # No binding anywhere: unknowable, therefore rigid.
            return copy_node
        role = site.role
        if role == "self":
            copy_node.id = "_SELF_"
        elif role == "cls":
            copy_node.id = "_CLS_"
        elif role == "import":
            copy_node.id = site.identity
        elif role == "local":
            copy_node.id = self.local_token(site, name)
        # global_literal stays literal: proven and unknowable names alike.
        return copy_node

    def _canonical_attribute(
        self,
        orig: ast.Attribute,
        copy_node: ast.Attribute,
        ctx: BindingContext,
        *,
        callee: bool,
    ) -> ast.AST:
        dotted = _import_chain_identity(orig, ctx)
        if dotted is not None:
            # The same collapse the fp3 wire performs: an import-rooted chain
            # is one rigid identity whatever syntax reached it.
            return ast.Name(id=dotted, ctx=ast.Load())
        if (
            not callee
            and orig.attr not in self._rigid_attributes
            and _receiver_is_renameable(orig.value, ctx)
        ):
            copy_node.attr = self.attribute_token(orig.attr)
        replacement = self._canonicalize(orig.value, copy_node.value, ctx)
        if replacement is not copy_node.value:
            copy_node.value = cast("ast.expr", replacement)
        return copy_node

    def _canonical_call(
        self,
        orig: ast.Call,
        copy_node: ast.Call,
        ctx: BindingContext,
    ) -> ast.AST:
        if isinstance(orig.func, ast.Attribute):
            replacement = self._canonical_attribute(
                orig.func,
                cast("ast.Attribute", copy_node.func),
                ctx,
                callee=True,
            )
        else:
            replacement = self._canonicalize(orig.func, copy_node.func, ctx)
        if replacement is not copy_node.func:
            copy_node.func = cast("ast.expr", replacement)
        return self._canonical_children(orig, copy_node, ctx, skip=("func",))

    def _canonical_function(
        self,
        orig: ast.FunctionDef | ast.AsyncFunctionDef,
        copy_node: ast.FunctionDef | ast.AsyncFunctionDef,
        ctx: BindingContext,
    ) -> ast.AST:
        name_site = ctx.lookup_site(orig.name)
        if name_site is not None and name_site.role == "local":
            copy_node.name = self.local_token(name_site, orig.name)
        inner = ctx.enter(orig)
        self.seed_parameters(orig.args, copy_node.args, inner)
        # Decorators and defaults are evaluated where the definition is
        # written, so they canonicalize in the enclosing scope, mirroring the
        # wire.
        self._canonical_defaults(orig.args, copy_node.args, ctx)
        self._canonical_node_list(orig.decorator_list, copy_node.decorator_list, ctx)
        self._canonical_node_list(orig.body, copy_node.body, inner)
        return copy_node

    def _canonical_lambda(
        self,
        orig: ast.Lambda,
        copy_node: ast.Lambda,
        ctx: BindingContext,
    ) -> ast.AST:
        inner = ctx.enter(orig)
        self.seed_parameters(orig.args, copy_node.args, inner)
        self._canonical_defaults(orig.args, copy_node.args, ctx)
        replacement = self._canonicalize(orig.body, copy_node.body, inner)
        if replacement is not copy_node.body:
            copy_node.body = cast("ast.expr", replacement)
        return copy_node

    def _canonical_class(
        self,
        orig: ast.ClassDef,
        copy_node: ast.ClassDef,
        ctx: BindingContext,
    ) -> ast.AST:
        name_site = ctx.lookup_site(orig.name)
        if name_site is not None and name_site.role == "local":
            copy_node.name = self.local_token(name_site, orig.name)
        self._canonical_node_list(orig.bases, copy_node.bases, ctx)
        self._canonical_node_list(orig.keywords, copy_node.keywords, ctx)
        self._canonical_node_list(orig.decorator_list, copy_node.decorator_list, ctx)
        inner = ctx.enter(orig)
        self._canonical_node_list(orig.body, copy_node.body, inner)
        return copy_node

    def _canonical_comprehension(
        self,
        orig: ast.AST,
        copy_node: ast.AST,
        ctx: BindingContext,
    ) -> ast.AST:
        """Comprehension scoping mirrors the wire.

        The leftmost iterable is evaluated in the enclosing scope; targets,
        conditions, later iterables and the element expressions belong to the
        comprehension's own scope. The walk order — elements first, then
        generators — is the wire's emission order, so ordinal first-occurrence
        reads in emitted order.
        """

        inner = ctx.enter(orig)
        if isinstance(orig, ast.DictComp):
            dict_copy = cast("ast.DictComp", copy_node)
            key = self._canonicalize(orig.key, dict_copy.key, inner)
            if key is not dict_copy.key:
                dict_copy.key = cast("ast.expr", key)
            value = self._canonicalize(orig.value, dict_copy.value, inner)
            if value is not dict_copy.value:
                dict_copy.value = cast("ast.expr", value)
            generators = orig.generators
            copy_generators = dict_copy.generators
        else:
            element_orig = cast("ast.ListComp | ast.SetComp | ast.GeneratorExp", orig)
            element_copy = cast(
                "ast.ListComp | ast.SetComp | ast.GeneratorExp", copy_node
            )
            element = self._canonicalize(element_orig.elt, element_copy.elt, inner)
            if element is not element_copy.elt:
                element_copy.elt = cast("ast.expr", element)
            generators = element_orig.generators
            copy_generators = element_copy.generators
        for index, generator in enumerate(generators):
            copy_generator = copy_generators[index]
            target = self._canonicalize(generator.target, copy_generator.target, inner)
            if target is not copy_generator.target:
                copy_generator.target = cast("ast.expr", target)
            iter_ctx = ctx if index == 0 else inner
            iterator = self._canonicalize(generator.iter, copy_generator.iter, iter_ctx)
            if iterator is not copy_generator.iter:
                copy_generator.iter = cast("ast.expr", iterator)
            self._canonical_node_list(generator.ifs, copy_generator.ifs, inner)
        return copy_node

    def _canonical_except_handler(
        self,
        orig: ast.ExceptHandler,
        copy_node: ast.ExceptHandler,
        ctx: BindingContext,
    ) -> ast.AST:
        if orig.type is not None and copy_node.type is not None:
            replacement = self._canonicalize(orig.type, copy_node.type, ctx)
            if replacement is not copy_node.type:
                copy_node.type = cast("ast.expr", replacement)
        if orig.name is not None:
            copy_node.name = self._canonical_bound_string(orig.name, ctx)
        self._canonical_node_list(orig.body, copy_node.body, ctx)
        return copy_node

    def _canonical_capture(
        self,
        orig: ast.MatchAs | ast.MatchStar,
        copy_node: ast.MatchAs | ast.MatchStar,
        ctx: BindingContext,
    ) -> ast.AST:
        if (
            isinstance(orig, ast.MatchAs)
            and isinstance(copy_node, ast.MatchAs)
            and orig.pattern is not None
            and copy_node.pattern is not None
        ):
            replacement = self._canonicalize(orig.pattern, copy_node.pattern, ctx)
            if replacement is not copy_node.pattern:
                copy_node.pattern = cast("ast.pattern", replacement)
        if orig.name is not None:
            copy_node.name = self._canonical_bound_string(orig.name, ctx)
        return copy_node

    def _canonical_bound_string(self, name: str, ctx: BindingContext) -> str:
        """Canonicalize a raw-string binding occurrence by its resolved site."""

        site = ctx.lookup_site(name)
        if site is not None and site.role == "local":
            return self.local_token(site, name)
        return name

    def _canonical_node_list(
        self,
        originals: list[_TNode],
        copies: list[_TNode],
        ctx: BindingContext,
    ) -> None:
        for index, item in enumerate(originals):
            replacement = self._canonicalize(item, copies[index], ctx)
            if replacement is not copies[index]:
                copies[index] = cast("_TNode", replacement)

    def seed_parameters(
        self,
        args: ast.arguments,
        copy_args: ast.arguments | None,
        inner: BindingContext,
    ) -> None:
        """Assign parameter ordinals at scope entry, in declaration order.

        Parameter names inside the unit body resolve through the scope graph,
        but a parameter's first *occurrence* is its declaration — seeding here
        anchors ordinal order to binding position instead of use order, which
        is what keeps ``x - y`` and ``y - x`` apart. ``copy_args`` is ``None``
        for the unit's own signature: the CFG carries only body statements, so
        there is no copy to rewrite at the top level.
        """

        copy_parameters = (
            _declared_parameters(copy_args) if copy_args is not None else None
        )
        for index, argument in enumerate(_declared_parameters(args)):
            site = inner.lookup_site(argument.arg)
            if site is None:
                continue
            role = site.role
            if role == "self":
                token = "_SELF_"
            elif role == "cls":
                token = "_CLS_"
            elif role == "local":
                token = self.local_token(site, argument.arg)
            else:
                continue
            if copy_parameters is not None:
                copy_parameters[index].arg = token

    def _canonical_defaults(
        self,
        args: ast.arguments,
        copy_args: ast.arguments,
        ctx: BindingContext,
    ) -> None:
        for index, default in enumerate(args.defaults):
            replacement = self._canonicalize(default, copy_args.defaults[index], ctx)
            if replacement is not copy_args.defaults[index]:
                copy_args.defaults[index] = cast("ast.expr", replacement)
        for index, kw_default in enumerate(args.kw_defaults):
            if kw_default is None:
                continue
            copy_default = copy_args.kw_defaults[index]
            if copy_default is None:
                continue
            replacement = self._canonicalize(kw_default, copy_default, ctx)
            if replacement is not copy_default:
                copy_args.kw_defaults[index] = cast("ast.expr", replacement)


def _import_chain_identity(node: ast.Attribute, ctx: BindingContext) -> str | None:
    attributes: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        attributes.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name) or current.id.startswith(CFG_META_PREFIX):
        return None
    site = ctx.lookup_site(current.id)
    if site is None or site.role != "import":
        return None
    attributes.reverse()
    return ".".join((site.identity, *attributes))


def _receiver_is_renameable(expr: ast.expr, ctx: BindingContext) -> bool:
    """Whether an attribute's receiver chain provably roots at a renameable name.

    Only pure ``Attribute`` links count as a chain: a subscript, call or any
    other expression between the attribute and its root makes the attribute
    rigid — refusal over approximation.
    """

    current = expr
    while isinstance(current, ast.Attribute):
        current = current.value
    if not isinstance(current, ast.Name) or current.id.startswith(CFG_META_PREFIX):
        return False
    site = ctx.lookup_site(current.id)
    return site is not None and site.role in _RENAMEABLE_RECEIVER_ROLES


def _declared_parameters(args: ast.arguments) -> tuple[ast.arg, ...]:
    """Parameters in source-declaration order — the pin-3 seeding anchor."""

    optional_star = (args.vararg,)
    optional_kw = (args.kwarg,)
    return (
        *args.posonlyargs,
        *args.args,
        *(argument for argument in optional_star if argument is not None),
        *args.kwonlyargs,
        *(argument for argument in optional_kw if argument is not None),
    )
