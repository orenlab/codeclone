# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The ONE normative owner of the canonical identity grammar.

``codeclone.canonical.identity`` owns the identity TYPES — ``SymbolId``,
``OperationHead``, ``EffectRoot`` and their variants.  This module owns the
GRAMMAR: how the producer's own string spellings become those types, and
which spellings are refused.

Why it exists (maintainer ratification 2026-08-31).  The grammar used to
live as private helpers of the legacy ingest oracle, so a producer-native
publication path could only re-spell it — and a second spelling of one
identity law is exactly the drift the canonical model exists to remove.
This is an AUTHORITY TRANSPLANT, not new semantics: the rules below are the
oracle's rules, moved rather than rewritten, and the wire is unchanged
because the normalized result is byte-identical.

Three boundary properties hold, and each is pinned by test:

* **One owner.** No consumer defines an effect-root, operation-head or
  root-family rule of its own; the structural ratchet in
  ``tests/test_canonical_semantic_grammar.py`` reads the package's syntax
  trees and refuses a second definition.
* **One typed result.** Both consumers surface :class:`SemanticGrammarError`
  for a grammar refusal.  There is no per-consumer error dialect and no
  "if the parser did not understand it, try the old shape" fallback: an
  unresolvable form fails closed, in both consumers, identically.
* **Frozen outward edges.** This module reaches only ``canonical.errors``
  and ``canonical.identity``.  It deliberately does NOT accept a
  ``ModuleRegistryHandle`` (that type lives in ``codeclone.models``, ring
  r2, which ``canonical`` may not import): each consumer extracts
  ``(path, module)`` pairs from ITS OWN source and hands them here, and the
  conflict law over those pairs is enforced here, once.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from codeclone.canonical.errors import SemanticGrammarError
from codeclone.canonical.identity import (
    AnalysisFile,
    DeadCodeEntity,
    DependencyEndpoint,
    EffectLabelRoot,
    EffectRoot,
    FileId,
    FileLine,
    KnownModule,
    ModuleId,
    ModuleSymbol,
    OpaqueDottedHead,
    OpaqueEntity,
    OperationHead,
    OperationRoot,
    OperationTarget,
    ProducerRoot,
    SourceLocation,
    SymbolId,
    UnresolvedLocation,
    UnresolvedRoot,
    source_location_key,
)

#: The nullary sentinel spelling of an unresolved effect root.
UNRESOLVED_ROOT_TEXT = "unresolved"
#: The root families the producer tags its effect roots with.
ROOT_FAMILY_OPERATION = "operation"
ROOT_FAMILY_PRODUCER = "producer"
ROOT_FAMILY_EFFECT = "effect"
#: The closed root-family vocabulary, in one place.  A tag outside it is a
#: refusal, never a guess: an unknown family names no entity.
ROOT_FAMILIES: tuple[str, ...] = (
    ROOT_FAMILY_EFFECT,
    ROOT_FAMILY_OPERATION,
    ROOT_FAMILY_PRODUCER,
)


@dataclass(frozen=True, slots=True)
class IdentityIndex:
    """The run's own registry projection, as the grammar needs to see it.

    Plain mappings rather than a registry handle: the handle is an r2 type
    and this ring may not import it, and the two consumers get their pairs
    from genuinely different places (a rendered document's registry rows,
    a live ``ModuleRegistryHandle``).  What must NOT differ is the law over
    those pairs, and that lives in :func:`build_identity_index`.
    """

    module_to_path: Mapping[str, str]
    path_to_module: Mapping[str, str]
    analyzed_paths: frozenset[str]


def build_identity_index(
    pairs: Iterable[tuple[str, str]],
    *,
    analyzed_paths: frozenset[str],
) -> IdentityIndex:
    """Index ``(path, module)`` pairs, refusing a registry at war with itself.

    A module claiming two files, or a file claiming two modules, is a
    producer defect: resolving it either way would mint an identity the
    producer never asserted, and that identity would become a wrong content
    address in the run store.
    """

    module_to_path: dict[str, str] = {}
    path_to_module: dict[str, str] = {}
    for path, module in pairs:
        if module_to_path.get(module, path) != path:
            raise SemanticGrammarError(
                f"module {module!r} claims two files: "
                f"{module_to_path[module]!r} and {path!r}"
            )
        if path_to_module.get(path, module) != module:
            raise SemanticGrammarError(
                f"file {path!r} claims two modules: "
                f"{path_to_module[path]!r} and {module!r}"
            )
        module_to_path[module] = path
        path_to_module[path] = module
    return IdentityIndex(
        module_to_path=module_to_path,
        path_to_module=path_to_module,
        analyzed_paths=analyzed_paths,
    )


def parse_symbol(index: IdentityIndex, key: str, where: str) -> SymbolId:
    """The ``head:local`` producer key as the ratified FILE-headed SYMBOL."""

    head, separator, qualname = key.partition(":")
    if not separator or not qualname:
        raise SemanticGrammarError(
            f"{where}: {key!r} is not a ModuleKey-headed symbol key"
        )
    if head in index.module_to_path:
        return SymbolId(FileId(index.module_to_path[head]), qualname)
    if head in index.analyzed_paths:
        return SymbolId(FileId(head), qualname)
    raise SemanticGrammarError(
        f"{where}: symbol head {head!r} is neither a registry module nor an "
        "analyzed path; refusing to guess an identity"
    )


def parse_endpoint(index: IdentityIndex, text: str, where: str) -> DependencyEndpoint:
    """The ratified ``MODULE | FILE`` union, resolved by the registry — never
    by the shape of the string (F-3 §2.1.8: the producer decides the
    domain, not the spelling)."""

    if text in index.module_to_path:
        return ModuleId(text)
    if text in index.analyzed_paths:
        return FileId(text)
    raise SemanticGrammarError(
        f"{where}: endpoint {text!r} is neither a registry module nor an analyzed path"
    )


def parse_lane_symbol(
    index: IdentityIndex, path: str, name: str, lane: str
) -> SymbolId:
    """The ONE spelling of the observation-lane identity law.

    A lane row carries a resolved source path plus a BARE qualname; the
    SYMBOL is the ratified FILE-headed spelling of the same entity.  A path
    outside the run's own analysis scope, or a name carrying a ModuleKey
    colon, is a typed refusal — never a guessed identity.
    """

    if path not in index.analyzed_paths:
        raise SemanticGrammarError(
            f"{lane} observation source {path!r} is not an analyzed path; "
            "refusing to guess an identity"
        )
    if ":" in name:
        raise SemanticGrammarError(
            f"{lane} observation name {name!r} is a glued identity; the "
            "producer's lane law forbids it"
        )
    return SymbolId(FileId(path), name)


def parse_dead_code_entity(index: IdentityIndex, text: str) -> DeadCodeEntity:
    """The ratified tagged entity reference (ruling 2026-08-24 §2).

    The producer glues ``head:local``; the head decides the variant through
    the run's OWN registry: a registry module keeps its MODULE head (the
    variant is identity — never normalized into the FILE spelling the
    producer did not make), an analyzed path is the FILE-headed SYMBOL, and
    everything else rides the opaque variant verbatim.  A string that does
    not parse under the producer's grammar is refused, never guessed.
    """

    head, separator, local = text.partition(":")
    if not separator or not local or not head:
        raise SemanticGrammarError(
            f"dead_code entity {text!r} is not a head:local glued reference"
        )
    if ":" in local:
        raise SemanticGrammarError(
            f"dead_code entity {text!r} carries a second ModuleKey colon; "
            "refusing to classify it"
        )
    if head in index.module_to_path:
        return ModuleSymbol(ModuleId(head), local)
    if head in index.analyzed_paths:
        return SymbolId(FileId(head), local)
    return OpaqueEntity(head, local)


def parse_source_location(index: IdentityIndex, path: str, line: int) -> SourceLocation:
    """One published evidence site as the tagged SOURCE_LOCATION union.

    The path decides the variant through the run's OWN analysis scope —
    :func:`parse_dead_code_entity`'s law, applied to a site instead of an
    entity: an analyzed path is the FILE-headed location, and anything else
    rides the unresolved variant VERBATIM rather than being repaired into a
    FILE identity the producer never asserted.

    There is no refusal branch and no drop branch, and both absences are
    deliberate.  A refusal would make one unplaceable site cost the whole
    run its snapshot, while the report publishes that site happily — the
    store would then disagree with the report by REFUSING, which is a
    different gap, not a closed one.  A drop is worse: it shortens the
    evidence tuple, and an emptied tuple reads as "the producer had nothing
    to say".  The variant is how the model says "something was said here,
    and this run could not place it".
    """

    if path in index.analyzed_paths:
        return FileLine(FileId(path), line)
    return UnresolvedLocation(path, line)


def parse_source_locations(
    index: IdentityIndex, sites: Iterable[tuple[str, int]]
) -> tuple[SourceLocation, ...]:
    """One violation's evidence tuple, in canonical order.

    Both publication paths — the legacy document oracle and the
    producer-native snapshot — hand their own ``(path, line)`` pairs here,
    so the ORDER is decided once.  Sorting is this function's job and not
    the caller's on purpose: canonical order is a model law, and a caller
    that passed the producer's own order through would make the stored row
    depend on the order the events happened to arrive in.

    Deliberately NOT deduplicated.  Two coinciding sites are a producer
    fact, and ``ViolationRow`` refuses the repeat rather than absorbing it —
    a silent collapse would delete an evidence point exactly where a count
    is what a reader relies on.
    """

    return tuple(
        sorted(
            (parse_source_location(index, path, line) for path, line in sites),
            key=source_location_key,
        )
    )


def format_source_location(location: SourceLocation) -> str:
    """The producer's own spelling of one evidence site's path.

    The inverse of :func:`parse_source_location` on the path slot, and the
    ONE renderer of it: a FILE-headed site spells the repository-relative
    path the FILE identity IS, and an unresolved site spells back exactly
    the string it was handed.
    """

    if isinstance(location, FileLine):
        return location.file.path
    return location.path


def surface_head(index: IdentityIndex, path: str, where: str) -> str:
    """The one legacy head of an analyzed FILE: its registry module when one
    exists, the path itself otherwise (the ``_legacy_symbol_keys`` law).  A
    path outside the run's own analysis scope is refused."""

    if path not in index.analyzed_paths:
        raise SemanticGrammarError(
            f"{where}: {path!r} is not an analyzed path; refusing to guess an identity"
        )
    return index.path_to_module.get(path, path)


def parse_operation_head(index: IdentityIndex, text: str) -> OperationHead:
    """A registry module, an analyzed file, or an opaque dotted head.

    The third variant is not a fallback: it is the producer's own measured
    third case (21 of 1 080 corpus targets), and it is carried verbatim
    rather than split at a dot, which would manufacture structure nobody
    asserted.
    """

    if text in index.module_to_path:
        return KnownModule(ModuleId(text))
    if text in index.analyzed_paths:
        return AnalysisFile(FileId(text))
    return OpaqueDottedHead(text)


def parse_effect_root(index: IdentityIndex, root: str, where: str) -> EffectRoot:
    """The root-family grammar: one tagged string, one EFFECT_ROOT variant."""

    if root == UNRESOLVED_ROOT_TEXT:
        return UnresolvedRoot()
    family, separator, rest = root.partition(":")
    if not separator:
        raise SemanticGrammarError(f"{where}: root {root!r} has no family tag")
    if family == ROOT_FAMILY_OPERATION:
        return _operation_root(index, rest, root, where)
    if family == ROOT_FAMILY_PRODUCER:
        return ProducerRoot(parse_symbol(index, rest, where))
    if family == ROOT_FAMILY_EFFECT:
        kind, kind_separator, label = rest.partition(":")
        if not kind_separator or not label:
            raise SemanticGrammarError(f"{where}: effect root {root!r} has no label")
        return EffectLabelRoot(kind, label)
    raise SemanticGrammarError(f"{where}: unknown root family in {root!r}")


def _operation_root(
    index: IdentityIndex, rest: str, root: str, where: str
) -> OperationRoot:
    kind, kind_separator, target = rest.partition(":")
    if not kind_separator or not target:
        raise SemanticGrammarError(f"{where}: operation root {root!r} has no target")
    head_text, head_separator, local_name = target.partition(":")
    if not head_separator:
        # Measured: 21 of 1 080 corpus targets are one opaque dotted
        # string; the whole target is the head, no local name asserted.
        return OperationRoot(kind, OperationTarget(OpaqueDottedHead(target), ""))
    if not local_name:
        raise SemanticGrammarError(
            f"{where}: operation target {target!r} carries a ModuleKey colon "
            "but no local name; collapsing it would merge two distinct "
            "producer strings"
        )
    return OperationRoot(
        kind, OperationTarget(parse_operation_head(index, head_text), local_name)
    )


def parse_root_set(
    index: IdentityIndex, values: Iterable[str], where: str
) -> frozenset[EffectRoot]:
    return frozenset(parse_effect_root(index, value, where) for value in values)


def format_operation_head(head: OperationHead) -> str:
    """The producer spelling of one operation head.

    The inverse of :func:`parse_operation_head`, and it lives here for the
    same reason the forward rule does: a head variant is a grammar fact,
    and a second module deciding how a ``KnownModule`` spells itself is the
    drift this owner exists to remove.
    """

    match head:
        case KnownModule():
            return head.module.module
        case AnalysisFile():
            return head.file.path
        case OpaqueDottedHead():
            return head.text


def _operation_target_text(target: OperationTarget) -> str:
    """``head`` alone for the opaque form, ``head:local`` otherwise.

    The empty local name is not a missing value: it is the measured form
    (21 of 1 080 corpus targets) in which the producer asserted ONE opaque
    dotted string, and re-gluing a colon onto it would mint a spelling the
    producer never wrote.
    """

    head = format_operation_head(target.head)
    return f"{head}:{target.local_name}" if target.local_name else head


def format_effect_root(root: EffectRoot, legacy: Mapping[SymbolId, str]) -> str:
    """The producer spelling of one effect root -- inverse of the parse rule.

    ``legacy`` supplies the ModuleKey-headed key of a ``ProducerRoot``'s
    SYMBOL, for the same reason this module takes ``(path, module)`` pairs
    instead of a registry handle: the head is the caller's fact, the
    GRAMMAR over it is this module's.

    Round-trip, not merely shape: ``parse_effect_root`` resolves a head
    against the run's own registry, so a rendered root is only correct if
    re-parsing it yields the same variant. That is a measured claim about
    the (index, root) pair and is pinned by test, never assumed here.
    """

    match root:
        case UnresolvedRoot():
            return UNRESOLVED_ROOT_TEXT
        case ProducerRoot():
            return f"{ROOT_FAMILY_PRODUCER}:{legacy[root.target]}"
        case EffectLabelRoot():
            return f"{ROOT_FAMILY_EFFECT}:{root.effect_kind}:{root.label}"
        case OperationRoot():
            target = _operation_target_text(root.target)
            return f"{ROOT_FAMILY_OPERATION}:{root.operation_kind}:{target}"


def format_root_set(
    roots: Iterable[EffectRoot], legacy: Mapping[SymbolId, str]
) -> list[str]:
    """One root set as the published column: rendered, then sorted.

    Sorted here because the document builder sorts the strings it was
    handed, and a set has no order to preserve -- the ordering law belongs
    with the spelling law, not with each consumer that rebuilds a row.
    """

    return sorted(format_effect_root(root, legacy) for root in roots)


def parse_symbol_set(
    index: IdentityIndex, values: Iterable[str], where: str
) -> frozenset[SymbolId]:
    return frozenset(parse_symbol(index, value, where) for value in values)


__all__ = [
    "ROOT_FAMILIES",
    "ROOT_FAMILY_EFFECT",
    "ROOT_FAMILY_OPERATION",
    "ROOT_FAMILY_PRODUCER",
    "UNRESOLVED_ROOT_TEXT",
    "IdentityIndex",
    "OperationTarget",
    "SemanticGrammarError",
    "build_identity_index",
    "format_effect_root",
    "format_operation_head",
    "format_root_set",
    "format_source_location",
    "parse_dead_code_entity",
    "parse_effect_root",
    "parse_endpoint",
    "parse_lane_symbol",
    "parse_operation_head",
    "parse_root_set",
    "parse_source_location",
    "parse_source_locations",
    "parse_symbol",
    "parse_symbol_set",
    "surface_head",
]
