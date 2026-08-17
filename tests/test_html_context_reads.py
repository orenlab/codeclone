# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""No HTML renderer may read a key its producer does not emit.

``_as_int`` answers a missing key with ``0`` and ``_as_mapping`` answers it
with ``{}``, so "the document does not carry this field" and "the run measured
none of them" arrive at the reader as the same picture: an honest-looking zero,
or an empty panel with a confident explanation of why it is empty. The Cohesion
cards asked the cohesion summary for ``high_risk`` and ``medium_risk``, the
Coupling cards asked for ``medium_risk``, and no metric family publishes either
spelling -- so three cards had shown zero in every report ever built. The
Overview's source breakdown asked ``derived.overview`` for ``source_breakdown``,
a key only a materializer no production path calls would have added, so that
panel had always said "No source data available" while the document beside it
counted ninety-five production files.

:mod:`tests.test_report_document_reads` already pins this class for consumers
that read the document directly. It is blind here by construction: its anchors
are the document itself (``report_document``/``document``/``payload``), and the
HTML package never touches those -- it reads :class:`ReportContext`, a
projection built once and handed to every section. So the whole package sat
outside the only pin that could have seen it.

This module closes that gap with the same shape, resolved against the same
maximally populated document:

    No module under ``codeclone/report/html/`` may read a key that the
    projection of a maximal report document does not carry.

Resolution is against the *projection*, not the raw document, because the
projection is what a renderer actually holds: ``_metric_family_projection``
flattens each family's summary onto the family mapping, aliases ``items`` as
``functions``/``classes``/``edge_list`` and fills ``summary.source``. Resolving
against the document would report every one of those live reads as withdrawn.

The scan is mechanical -- every read in every module of the package, found by
walking the trees. Three refinements, each closing a way the rule could be
satisfied without being obeyed:

* Reads are followed **through the package**, not only within a statement. A
  section binds ``cohesion_summary`` and hands it to ``_cohesion_cards``, which
  asks the parameter for a key; the defect lives across that boundary, so a
  scan that stopped at the function edge would have seen none of the three
  cards it was written for. Local aliases, arguments bound at call sites,
  helper return values and a key spelled through a parameter are all resolved.
* All three read shapes count: ``mapping.get(key)``, ``mapping[key]`` and
  ``key in mapping``. The rule is about asking for a key, not about which
  operator asks.
* A read whose key is only known at run time cannot be resolved, and says so.
  :data:`_DYNAMIC_KEY_READS` registers those separately: "I could not look" and
  "I looked and it is fine" are different statements, and a register that
  conflated them would let a whole mapping leave the pin's sight by having its
  keys computed.

Both registers are two-sided. An unregistered absent read fails as growth; a
register entry whose read is gone from the code fails as a stale entry. A
one-sided register is a ratchet that can be satisfied by choosing a shape it
does not match, and it rots the moment the code moves on.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from codeclone.report.html._context import ReportContext, build_context
from codeclone.report.html.sections._coupling import _cohesion_cards, _coupling_cards
from codeclone.report.html.sections._dead_code import render_dead_code_panel
from codeclone.report.html.sections._meta import render_meta_panel
from codeclone.report.html.sections._overview import render_overview_panel
from codeclone.report.html.widgets.snippets import _FileCache

from ._report_fixtures import build_maximal_report_document

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HTML_PACKAGE = _REPO_ROOT / "codeclone" / "report" / "html"

#: Calls that coerce a value on its way through a read chain without changing
#: which mapping is being addressed.
_COERCIONS = frozenset({"as_mapping", "_as_mapping", "dict"})

#: The type whose attributes root a read. Names are resolved from annotations
#: rather than from the identifier, so renaming the parameter changes nothing.
_CONTEXT_TYPE = "ReportContext"

#: The factory that builds one. ``assemble.build_html_report`` takes the
#: document and projects it itself, so the assembler's own reads -- every tab
#: counter in the report -- are rooted at a local rather than at a parameter.
_CONTEXT_FACTORY = "build_context"

_FIELDS = frozenset(ReportContext.__dataclass_fields__)

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef)

#: Reads of keys the projection does not carry, owned by another live branch.
#: Two-sided on purpose: a new absent read fails as growth, and a repaired one
#: fails as a stale entry, so the register can only shrink and cannot rot.
_ABSENT_READS_OWNED_ELSEWHERE: dict[str, tuple[str, ...]] = {}

#: Reads whose key is computed at run time. Each one addresses a mapping keyed
#: by identity -- a clone kind, a group key, a severity, a directory bucket --
#: so there is no fixed key to resolve and the pin states that it did not look
#: rather than implying that it looked and approved. Registered by the mapping
#: addressed, so a mapping cannot leave the pin's sight by having its keys
#: spelled dynamically.
_DYNAMIC_KEY_READS: dict[str, tuple[str, ...]] = {
    "codeclone/report/html/_context.py": (
        # The clone totals, summed over the three clone kinds in turn.
        "clone_summary",
    ),
    "codeclone/report/html/sections/_clones.py": (
        # Per-clone-group display facts, keyed by group key.
        "block_group_facts",
    ),
    "codeclone/report/html/sections/_overview.py": (
        # Directory hotspots, keyed by source-kind bucket.
        "overview_data.directory_hotspots",
    ),
    "codeclone/report/html/sections/_review.py": (
        # Review-queue counts, keyed by severity.
        "derived_map.review_queue.summary.by_severity",
    ),
}


@dataclass(frozen=True, slots=True)
class ContextRead:
    """One read of a projection mapping, with where it is written."""

    module: str
    line: int
    path: str
    code: str


def _callee(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _strip(node: ast.expr) -> ast.expr:
    while (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and not node.keywords
        and _callee(node.func) in _COERCIONS
    ):
        node = node.args[0]
    return node


def _annotation_names(node: ast.expr | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ast.unparse(node)


def _scope_nodes(node: ast.AST) -> Iterator[ast.AST]:
    """Yield one scope's nodes in source order, without entering nested scopes."""

    for child in ast.iter_child_nodes(node):
        if isinstance(child, (*_SCOPES, ast.ClassDef, ast.Lambda)):
            continue
        yield child
        yield from _scope_nodes(child)


@dataclass(frozen=True, slots=True)
class _Scope:
    module: str
    name: str
    node: ast.AST
    parent: str | None
    context_names: frozenset[str]


def _arguments(node: ast.AST) -> list[ast.arg]:
    if not isinstance(node, _SCOPES):
        return []
    return [
        *node.args.posonlyargs,
        *node.args.args,
        *node.args.kwonlyargs,
    ]


def _positional_names(node: ast.AST) -> Sequence[str]:
    """The parameters a positional argument at a call site can bind to."""

    if not isinstance(node, _SCOPES):
        return ()
    return tuple(argument.arg for argument in (*node.args.posonlyargs, *node.args.args))


class _Package:
    """Every module of the package, indexed for cross-module resolution."""

    def __init__(self, sources: Mapping[str, str]) -> None:
        self.trees = {module: ast.parse(source) for module, source in sources.items()}
        self.scopes: dict[tuple[str, str], _Scope] = {}
        for module, tree in self.trees.items():
            self._collect(module, tree, qualname="", enclosing_class="")
        by_stem: dict[str, list[str]] = {}
        for module in self.trees:
            by_stem.setdefault(Path(module).stem, []).append(module)
        self.imports = {
            module: self._import_table(tree, by_stem)
            for module, tree in self.trees.items()
        }

    def _import_table(
        self,
        tree: ast.Module,
        by_stem: Mapping[str, Sequence[str]],
    ) -> dict[str, str]:
        """Which module each name imported into one tree comes from.

        Resolved by the last segment of the imported module, which is what the
        package's relative imports spell; an ambiguous stem resolves to
        nothing rather than to a guess.
        """

        table: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            owners = by_stem.get((node.module or "").rsplit(".", 1)[-1], ())
            if len(owners) == 1:
                table.update(
                    {
                        alias.asname or alias.name: owners[0]
                        for alias in node.names
                        if (owners[0], alias.name) in self.scopes
                    }
                )
        return table

    def _collect(
        self,
        module: str,
        node: ast.AST,
        *,
        qualname: str,
        enclosing_class: str,
    ) -> None:
        if qualname == "":
            self.scopes[(module, "")] = _Scope(
                module=module,
                name="",
                node=node,
                parent=None,
                context_names=frozenset(),
            )
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                self._collect(
                    module,
                    child,
                    qualname=qualname,
                    enclosing_class=child.name,
                )
                continue
            if not isinstance(child, _SCOPES):
                continue
            names = {
                argument.arg
                for argument in _arguments(child)
                if _annotation_names(argument.annotation) == _CONTEXT_TYPE
            }
            if enclosing_class == _CONTEXT_TYPE:
                names.add("self")
            self.scopes[(module, child.name)] = _Scope(
                module=module,
                name=child.name,
                node=child,
                parent=qualname,
                context_names=frozenset(names),
            )
            self._collect(
                module,
                child,
                qualname=child.name,
                enclosing_class="",
            )

    def resolve(self, module: str, name: str) -> tuple[str, str] | None:
        """Which scope a called name refers to, locally or through an import."""

        if (module, name) in self.scopes and name:
            return (module, name)
        owner = self.imports.get(module, {}).get(name)
        return None if owner is None else (owner, name)


@dataclass(frozen=True, slots=True)
class _Bindings:
    """What one scope knows: paths by name, strings by name, context roots."""

    paths: dict[str, set[str]]
    strings: dict[str, set[str]]
    roots: frozenset[str]


class _Resolver:
    """Reconstructs the projection path every read in the package addresses.

    Three tables are learned to a fixpoint, because a read is often spelled
    several statements and one call away from the context that roots it:
    what each function hands back, what each parameter is bound to at its
    call sites, and which string literals reach a parameter used as a key.
    """

    def __init__(self, sources: Mapping[str, str]) -> None:
        self.package = _Package(sources)
        self.returns: dict[tuple[str, str], set[str]] = {}
        self.parameters: dict[tuple[str, str, str], set[str]] = {}
        self.literals: dict[tuple[str, str, str], set[str]] = {}

    # -- reconstruction ---------------------------------------------------

    def string_of(
        self,
        node: ast.expr,
        strings: Mapping[str, set[str]],
    ) -> set[str] | None:
        """The string a node states, directly or through a bound name."""

        node = _strip(node)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, ast.Name) and node.id in strings:
            return set(strings[node.id])
        return None

    def path_of(self, scope: _Scope, node: ast.expr, known: _Bindings) -> set[str]:
        """The projection path an expression addresses, or an empty set."""

        node = _strip(node)
        if isinstance(node, ast.Name):
            return set(known.paths.get(node.id, ()))
        if isinstance(node, ast.Attribute):
            roots_a_read = (
                isinstance(node.value, ast.Name)
                and node.value.id in known.roots
                and node.attr in _FIELDS
            )
            return {node.attr} if roots_a_read else set()
        if isinstance(node, ast.Call):
            return self._call_path(scope, node, known)
        return set()

    def _call_path(self, scope: _Scope, node: ast.Call, known: _Bindings) -> set[str]:
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
        ):
            base = self.path_of(scope, node.func.value, known)
            keys = self.string_of(node.args[0], known.strings)
            if not base or keys is None:
                return set()
            return {f"{stem}.{key}" for stem in base for key in keys}
        if isinstance(node.func, ast.Name):
            target = self.package.resolve(scope.module, node.func.id)
            if target is not None:
                return set(self.returns.get(target, ()))
        return set()

    # -- per-scope tables -------------------------------------------------

    def _context_roots(self, scope: _Scope) -> frozenset[str]:
        """Names holding a context: annotated parameters plus local builds."""

        names = set(scope.context_names)
        for target, value in _simple_assignments(scope):
            built = _strip(value)
            if isinstance(built, ast.Call) and _callee(built.func) == _CONTEXT_FACTORY:
                names.add(target.id)
        return frozenset(names)

    def bindings(self, scope: _Scope) -> _Bindings:
        known = _Bindings(paths={}, strings={}, roots=self._context_roots(scope))
        outer = (
            None
            if scope.parent is None
            else self.package.scopes.get((scope.module, scope.parent))
        )
        if outer is not None:
            inherited = self.bindings(outer)
            known.paths.update(inherited.paths)
            known.strings.update(inherited.strings)
            known = _Bindings(
                paths=known.paths,
                strings=known.strings,
                roots=known.roots | inherited.roots,
            )
        for argument in _arguments(scope.node):
            slot = (scope.module, scope.name, argument.arg)
            if slot in self.parameters:
                known.paths[argument.arg] = set(self.parameters[slot])
            if slot in self.literals:
                known.strings[argument.arg] = set(self.literals[slot])
        for _pass in range(3):
            for target, value in _simple_assignments(scope):
                found = self.path_of(scope, value, known)
                if found:
                    known.paths.setdefault(target.id, set()).update(found)
                text = self.string_of(value, known.strings)
                if text:
                    known.strings.setdefault(target.id, set()).update(text)
        return known

    # -- fixpoint ---------------------------------------------------------

    def solve(self) -> None:
        # Every scope is visited in every round on purpose: a short-circuiting
        # ``any`` here stops the round at the first scope that learned
        # something, and the review-queue severity read -- bound two calls deep
        # -- stopped being resolved at all.
        for _round in range(10):
            learned = [
                self._learn(self.package.scopes[key], key)
                for key in sorted(self.package.scopes)
            ]
            if not any(learned):
                return

    def _learn(self, scope: _Scope, key: tuple[str, str]) -> bool:
        known = self.bindings(scope)
        changed = False
        for node in _scope_nodes(scope.node):
            if isinstance(node, ast.Return) and node.value is not None:
                found = self.path_of(scope, node.value, known)
                if found - self.returns.get(key, set()):
                    self.returns.setdefault(key, set()).update(found)
                    changed = True
            if isinstance(node, ast.Call):
                changed |= self._learn_call(scope, node, known)
        return changed

    def _learn_call(self, scope: _Scope, node: ast.Call, known: _Bindings) -> bool:
        if not isinstance(node.func, ast.Name):
            return False
        target = self.package.resolve(scope.module, node.func.id)
        if target is None:
            return False
        changed = False
        for name, expression in _bound_arguments(
            node, _positional_names(self.package.scopes[target].node)
        ):
            slot = (target[0], target[1], name)
            found = self.path_of(scope, expression, known)
            if found - self.parameters.get(slot, set()):
                self.parameters.setdefault(slot, set()).update(found)
                changed = True
            text = self.string_of(expression, known.strings)
            if text and text - self.literals.get(slot, set()):
                self.literals.setdefault(slot, set()).update(text)
                changed = True
        return changed

    # -- report -----------------------------------------------------------

    def reads(self) -> tuple[list[ContextRead], list[ContextRead]]:
        resolved: set[ContextRead] = set()
        dynamic: set[ContextRead] = set()
        for key in sorted(self.package.scopes):
            scope = self.package.scopes[key]
            known = self.bindings(scope)
            for node in _scope_nodes(scope.node):
                for probe in _probes(node):
                    base = self.path_of(scope, probe.mapping, known)
                    keys = self.string_of(probe.key, known.strings)
                    lane = dynamic if keys is None else resolved
                    lane.update(
                        ContextRead(
                            module=scope.module,
                            line=probe.line,
                            path=path,
                            code=probe.code,
                        )
                        for path in _read_paths(base, keys)
                    )
        return sorted(resolved, key=_read_order), sorted(dynamic, key=_read_order)


def _read_paths(base: set[str], keys: set[str] | None) -> list[str]:
    """One path per (mapping, key) pair, or the mapping itself when dynamic."""

    if keys is None:
        return sorted(base)
    return sorted(f"{stem}.{key}" for stem in base for key in keys)


def _simple_assignments(scope: _Scope) -> list[tuple[ast.Name, ast.expr]]:
    """Every ``name = value`` in one scope, without entering nested scopes."""

    found: list[tuple[ast.Name, ast.expr]] = []
    for node in _scope_nodes(scope.node):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name):
            found.append((target, node.value))
    return found


def _bound_arguments(
    node: ast.Call,
    names: Sequence[str],
) -> list[tuple[str, ast.expr]]:
    """Which parameter each argument of one call binds to."""

    bound: list[tuple[str, ast.expr]] = [
        (names[index], argument)
        for index, argument in enumerate(node.args)
        if index < len(names)
    ]
    bound.extend(
        (keyword.arg, keyword.value) for keyword in node.keywords if keyword.arg
    )
    return bound


def context_reads(
    sources: Mapping[str, str],
) -> tuple[list[ContextRead], list[ContextRead]]:
    """Every projection read the given modules perform, resolved and dynamic.

    The first list holds reads whose key is written down; the second holds
    reads of a projection mapping whose key is only known at run time.
    """

    resolver = _Resolver(sources)
    resolver.solve()
    return resolver.reads()


def _read_order(read: ContextRead) -> tuple[str, int, str]:
    return read.module, read.line, read.path


@dataclass(frozen=True, slots=True)
class _Probe:
    """One "ask this mapping for this key", whatever operator asked."""

    mapping: ast.expr
    key: ast.expr
    line: int
    code: str


def _probes(node: ast.AST) -> Iterator[_Probe]:
    """Every read shape written at one node: ``get``, subscript, membership."""

    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
    ):
        yield _Probe(node.func.value, node.args[0], node.lineno, ast.unparse(node))
    elif isinstance(node, ast.Subscript):
        yield _Probe(node.value, node.slice, node.lineno, ast.unparse(node))
    elif isinstance(node, ast.Compare):
        for operator, right in zip(node.ops, node.comparators, strict=True):
            if isinstance(operator, (ast.In, ast.NotIn)):
                yield _Probe(right, node.left, node.lineno, ast.unparse(node))


def maximal_projection() -> ReportContext:
    """The projection a renderer holds for a maximally populated document."""

    return build_context(
        report_document=build_maximal_report_document(),
        file_cache=_FileCache(),
    )


def projection_carries(context: ReportContext, path: str) -> bool | None:
    """Whether the projection carries one path, or None if it is no mapping.

    ``None`` is not a pass: it means the path does not address a mapping at
    all -- a tuple field, a sequence element -- so there is no key to resolve
    and the read is outside this rule rather than approved by it.
    """

    root, *keys = path.split(".")
    current: object = getattr(context, root, None)
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        if key not in current:
            return False
        current = current[key]
    return True


def _package_sources() -> dict[str, str]:
    return {
        path.relative_to(_REPO_ROOT).as_posix(): path.read_text("utf-8")
        for path in sorted(_HTML_PACKAGE.rglob("*.py"))
    }


def _absent_reads() -> dict[str, tuple[str, ...]]:
    context = maximal_projection()
    resolved, _dynamic = context_reads(_package_sources())
    absent: dict[str, set[str]] = {}
    for read in resolved:
        if projection_carries(context, read.path) is False:
            absent.setdefault(read.module, set()).add(read.path)
    return {module: tuple(sorted(paths)) for module, paths in sorted(absent.items())}


def _dynamic_reads() -> dict[str, tuple[str, ...]]:
    _resolved, dynamic = context_reads(_package_sources())
    found: dict[str, set[str]] = {}
    for read in dynamic:
        found.setdefault(read.module, set()).add(read.path)
    return {module: tuple(sorted(paths)) for module, paths in sorted(found.items())}


def _two_sided(
    live: Mapping[str, tuple[str, ...]],
    register: Mapping[str, tuple[str, ...]],
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    unexpected = {
        module: tuple(sorted(set(paths) - set(register.get(module, ()))))
        for module, paths in live.items()
        if set(paths) - set(register.get(module, ()))
    }
    stale = {
        module: tuple(sorted(set(paths) - set(live.get(module, ()))))
        for module, paths in register.items()
        if set(paths) - set(live.get(module, ()))
    }
    return unexpected, stale


def test_html_reads_address_keys_the_projection_carries() -> None:
    """No HTML module reads a key the report projection does not carry."""

    unexpected, stale = _two_sided(_absent_reads(), _ABSENT_READS_OWNED_ELSEWHERE)

    assert unexpected == {}, (
        "these HTML modules read keys the report projection does not carry, so "
        "the absence renders as a measured zero; read the key the producer "
        f"emits, or stop drawing a figure nobody publishes: {unexpected}"
    )
    assert stale == {}, (
        "these registered absent reads are gone from the code; delete the "
        f"entries rather than carrying them: {stale}"
    )


def test_dynamic_key_reads_are_registered_rather_than_assumed_live() -> None:
    """A read the scan cannot resolve is declared, never quietly passed.

    "I could not look" and "I looked and it is fine" are different statements.
    Without this side a mapping could leave the pin's sight entirely by having
    its keys computed, and the pin would stay green while saying nothing.
    """

    unexpected, stale = _two_sided(_dynamic_reads(), _DYNAMIC_KEY_READS)

    assert unexpected == {}, (
        "these HTML modules read a projection mapping with a key known only at "
        "run time; register the mapping with the reason its keys are dynamic, "
        f"or spell the key: {unexpected}"
    )
    assert stale == {}, (
        "these registered dynamic reads are gone from the code; delete the "
        f"entries rather than carrying them: {stale}"
    )


def test_scanner_reads_every_shape_a_renderer_can_write() -> None:
    """``get``, subscript and membership all ask for a key.

    Without this the class pin could go quietly blind: a scanner that
    reconstructs nothing reports nothing and stays green forever.
    """

    source = (
        "def panel(ctx: ReportContext) -> str:\n"
        "    summary = _as_mapping(ctx.cohesion_map.get('summary'))\n"
        "    a = summary.get('ghost_one')\n"
        "    b = summary['ghost_two']\n"
        "    c = 'ghost_three' in summary\n"
        "    return f'{a}{b}{c}'\n"
    )

    resolved, dynamic = context_reads({"m.py": source})

    assert [read.path for read in resolved] == [
        "cohesion_map.summary",
        "cohesion_map.summary.ghost_one",
        "cohesion_map.summary.ghost_two",
        "cohesion_map.summary.ghost_three",
    ]
    assert dynamic == []


def test_scanner_follows_a_summary_into_the_helper_that_draws_it() -> None:
    """The three cards this module was written for live across a call.

    ``render_quality_panel`` binds ``cohesion_summary`` and hands it to
    ``_cohesion_cards``, which asks the parameter for ``high_risk``. A scan
    that stopped at the function edge would have found none of the reads that
    made this pin necessary, so the argument binding is load-bearing rather
    than a refinement.
    """

    source = (
        "def _cards(summary):\n"
        "    return summary.get('ghost')\n"
        "def panel(ctx: ReportContext) -> str:\n"
        "    cohesion_summary = _as_mapping(ctx.cohesion_map.get('summary'))\n"
        "    return _cards(cohesion_summary)\n"
    )

    resolved, _dynamic = context_reads({"m.py": source})

    assert "cohesion_map.summary.ghost" in {read.path for read in resolved}


def test_scanner_follows_a_summary_across_a_module_boundary() -> None:
    """A helper imported from a sibling module is still the same read.

    The coverage-join summary is built in ``_coverage_join`` and consumed in
    ``_coupling``; a package-local scan that resolved names per module would
    lose every read spelled that way.
    """

    sources = {
        "producer.py": (
            "def summary_of(ctx: ReportContext):\n"
            "    return _as_mapping(ctx.coupling_map.get('summary'))\n"
        ),
        "consumer.py": (
            "from .producer import summary_of\n"
            "def panel(ctx: ReportContext) -> str:\n"
            "    summary = summary_of(ctx)\n"
            "    return summary.get('ghost')\n"
        ),
    }

    resolved, _dynamic = context_reads(sources)

    assert ("consumer.py", "coupling_map.summary.ghost") in {
        (read.module, read.path) for read in resolved
    }


def test_scanner_resolves_a_key_spelled_through_a_parameter() -> None:
    """Naming the key elsewhere does not remove it.

    ``_summary_card_inputs`` takes ``max_key`` from its callers and asks the
    summary for it. A scan that only read string literals at the call would
    report that read as unresolvable and quietly excuse it.
    """

    source = (
        "def _inputs(summary, *, max_key):\n"
        "    return summary.get(max_key)\n"
        "def panel(ctx: ReportContext) -> str:\n"
        "    summary = _as_mapping(ctx.coupling_map.get('summary'))\n"
        "    return _inputs(summary, max_key='ghost')\n"
    )

    resolved, dynamic = context_reads({"m.py": source})

    assert "coupling_map.summary.ghost" in {read.path for read in resolved}
    assert dynamic == []


def test_scanner_reports_a_computed_key_as_dynamic_not_as_resolved() -> None:
    """An unresolvable key lands in the dynamic list, never in the clean one."""

    source = (
        "def panel(ctx: ReportContext) -> str:\n"
        "    summary = _as_mapping(ctx.cohesion_map.get('summary'))\n"
        "    return ''.join(summary.get(name) for name in _names())\n"
    )

    resolved, dynamic = context_reads({"m.py": source})

    assert [read.path for read in dynamic] == ["cohesion_map.summary"]
    assert [read.path for read in resolved] == ["cohesion_map.summary"]


def test_scanner_roots_on_the_annotation_rather_than_the_identifier() -> None:
    """The context is found by its type, and nothing else is mistaken for it.

    Rooting on the name ``ctx`` would make the pin trivially avoidable by
    renaming a parameter, and would also root on any unrelated object that
    happens to carry an attribute sharing a field name.
    """

    source = (
        "def panel(report: ReportContext, row: Mapping[str, object]) -> str:\n"
        "    return f\"{report.meta.get('ghost')}{row.meta.get('ghost')}\"\n"
    )

    resolved, _dynamic = context_reads({"m.py": source})

    assert [read.path for read in resolved] == ["meta.ghost"]


def test_projection_used_for_resolution_is_maximal() -> None:
    """The pin resolves against a populated projection, not an empty one.

    Every path below is read by a live renderer and is optional in the
    document: the analysis profile appears only when thresholds are declared,
    the health dimensions only when metrics ran, the coverage-join family only
    when coverage was joined. Resolved against a thinner document each of them
    would read as a withdrawn key, and the register would fill with entries
    that describe the fixture rather than the code.
    """

    context = maximal_projection()

    for path in (
        "meta.analysis_profile.min_loc",
        "health_map.dimensions.dependencies",
        "metrics_map.coverage_join.summary.status",
        "cohesion_map.summary.low_cohesion",
        "overview_data.source_scope_breakdown",
    ):
        assert projection_carries(context, path) is True, path


def test_scanner_sees_the_whole_package() -> None:
    """The inventory is built by walking the package, not from a list of files.

    A scan pointed at the section modules alone would have missed the tab
    counters in ``assemble.py`` and the clone totals on the context itself.
    """

    scanned = set(_package_sources())

    assert len(scanned) > 30
    assert "codeclone/report/html/assemble.py" in scanned
    assert "codeclone/report/html/_context.py" in scanned
    assert set(_ABSENT_READS_OWNED_ELSEWHERE) <= scanned
    assert set(_DYNAMIC_KEY_READS) <= scanned


def _block(document: Mapping[str, object], *path: str) -> dict[str, object]:
    """One nested mapping of a built document, as a mutable block."""

    current: object = document
    for key in path:
        assert isinstance(current, dict), path
        current = current[key]
    assert isinstance(current, dict), path
    return current


# --------------------------------------------------------------------------
# What each repaired read now draws.
#
# The pin above says the key exists; these say the panel shows it. Every
# fixture below makes coincidence impossible: the key that is read carries a
# value no other key in the same summary carries, so "reads the right field"
# and "reads an absence" cannot produce the same picture.
# --------------------------------------------------------------------------


def test_cohesion_cards_draw_only_the_figures_cohesion_publishes() -> None:
    """Two cards, both read from the summary; no unmeasured third and fourth.

    Every figure in the fixture is distinct, so a card reading the wrong key
    cannot land on the right number by accident: 3 is the low-cohesion count
    and nothing else in the summary is 3.
    """

    cards = _cohesion_cards({"total": 9, "average": 2.5, "max": 4, "low_cohesion": 3})

    assert '<div class="meta-value meta-value--bad">3</div>' in cards
    assert '<div class="meta-value meta-value--bad">4</div>' in cards
    assert "Low-cohesion classes" in cards
    assert "Max LCOM4" in cards
    assert "High risk" not in cards
    assert "Medium risk" not in cards


def test_cohesion_cards_follow_the_document_they_are_given() -> None:
    """Change a published figure and the card must change with it.

    Without this the two surviving cards could be constants and the test above
    would not notice.
    """

    fewer = _cohesion_cards({"total": 9, "average": 2.5, "max": 2, "low_cohesion": 1})

    assert '<div class="meta-value meta-value--bad">1</div>' in fewer
    assert '<div class="meta-value meta-value--bad">3</div>' not in fewer
    assert '<div class="meta-value meta-value--warn">2</div>' in fewer


def test_coupling_cards_stop_drawing_a_medium_risk_population() -> None:
    """Coupling publishes a high-risk count and no medium tail.

    The three surviving cards keep reading the document; only the card whose
    key nobody emits is gone.
    """

    cards = _coupling_cards({"total": 12, "average": 1.4, "max": 10, "high_risk": 2})

    assert "High-coupling classes" in cards
    assert '<div class="meta-value meta-value--bad">2</div>' in cards
    assert "Max CBO" in cards
    assert '<div class="meta-value meta-value--warn">10</div>' in cards
    assert "Avg CBO" in cards
    assert '<div class="meta-value">1.4</div>' in cards
    assert "Medium risk" not in cards


def test_dead_code_panel_reads_high_confidence_and_not_the_old_spelling() -> None:
    """The withdrawn ``critical`` spelling must not be consulted at all.

    Asserting only that ``high_confidence`` is shown would stay green with the
    old fallback restored in front of it, because the fallback is reached only
    when the live key is missing. Feeding a document that carries *only* the
    withdrawn name is what tells the two apart: it must produce nothing.
    """

    document = build_maximal_report_document()
    dead_code = _block(document, "metrics", "families", "dead_code")
    dead_code["items"] = []
    dead_code["summary"] = {"total": 7, "high_confidence": 5}

    panel = render_dead_code_panel(
        build_context(report_document=document, file_cache=_FileCache())
    )

    assert ">5<" in panel

    dead_code["summary"] = {"total": 7, "critical": 5}
    withdrawn_only = render_dead_code_panel(
        build_context(report_document=document, file_cache=_FileCache())
    )

    assert ">5<" not in withdrawn_only


def test_source_breakdown_draws_the_counts_the_document_publishes() -> None:
    """The Overview panel shows the source scope, not an empty state.

    ``derived.overview`` publishes ``source_scope_breakdown``; the flat
    ``source_breakdown`` name the panel used to ask for is added only by a
    materializer no production path calls, so the panel had always fallen to
    its "No source data available" message. Both halves are asserted: the
    published name fills the panel, and the withdrawn one leaves it empty.
    """

    document = build_maximal_report_document()
    overview = _block(document, "derived", "overview")
    overview["source_scope_breakdown"] = {"production": 3, "tests": 1}

    panel = render_overview_panel(
        build_context(report_document=document, file_cache=_FileCache())
    )

    assert "No source data available" not in panel
    assert '<span class="breakdown-count">3</span>' in panel

    overview["source_scope_breakdown"] = {}
    overview["source_breakdown"] = {"production": 3, "tests": 1}
    withdrawn_only = render_overview_panel(
        build_context(report_document=document, file_cache=_FileCache())
    )

    assert "No source data available" in withdrawn_only


def test_provenance_panel_reads_the_blocks_not_the_withdrawn_flat_names() -> None:
    """Injecting the pre-v3 spellings must not change a single row.

    ``meta`` is pass-through in the projection, so a caller *can* put
    ``baseline_status`` there; the document never does. Asserting only that
    the nested value is shown would stay green with the withdrawn lookups
    restored in front of it, because both routes reach the same string. The
    proof is that a document carrying the flat names in addition renders
    byte-for-byte the same panel.
    """

    document = build_maximal_report_document()
    meta = _block(document, "meta")
    _block(document, "meta", "baseline").update(
        {"status": "ok", "loaded": True, "schema_version": "3.0"}
    )
    _block(document, "meta", "cache").update({"status": "warm", "used": True})
    from_blocks = render_meta_panel(
        build_context(report_document=document, file_cache=_FileCache())
    )

    assert ">ok<" in from_blocks
    assert ">warm<" in from_blocks

    meta.update(
        {
            "baseline_status": "INJECTED",
            "baseline_loaded": False,
            "baseline_schema_version": "INJECTED",
            "cache_status": "INJECTED",
            "cache_used": False,
        }
    )
    with_withdrawn_names = render_meta_panel(
        build_context(report_document=document, file_cache=_FileCache())
    )

    assert with_withdrawn_names == from_blocks
    assert "INJECTED" not in with_withdrawn_names
