# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Identity domains of the frozen canonical semantic model (F-3 SS2-SS3).

Four identity domains — ``FILE``, ``MODULE``, ``SYMBOL``, ``EFFECT_ROOT`` —
plus the two ratified union slots that never leak into ``SYMBOL``:

* ``DependencyEndpoint = MODULE | FILE`` (dependency facts);
* ``OperationHead = KnownModule | AnalysisFile | OpaqueDottedHead``
  (operation-root targets; a dotted string outside the module registry has
  no right to pretend it is a MODULE identity).

``SYMBOL = (FILE, qualname)`` is frozen: the legacy ModuleKey-headed
addressing was measured to normalize into FILE-based symbols without loss
(phase 0 of wave 1, ``lossless_normalization=YES`` on the frozen corpus).

Every domain carries a *total* canonical order defined purely by canonical
keys (§3): ``semantic key → total order → ordinal → wire reference``.
Ordinals are computed at projection time and never stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from codeclone.canonical.errors import CanonicalModelError

# Contract tag strings (F-3 §7.3). Codes are stable contract strings, never
# integers and never Python enum order; renaming one is a
# CANONICAL_MODEL_REVISION change.
DOMAIN_TAG_FILE: Final = "file"
DOMAIN_TAG_MODULE: Final = "module"
DOMAIN_TAG_SYMBOL: Final = "symbol"
DOMAIN_TAG_EFFECT_ROOT: Final = "effect_root"
HEAD_TAG_OPAQUE: Final = "opaque"

ROOT_FAMILY_OPERATION: Final = "operation"
ROOT_FAMILY_PRODUCER: Final = "producer"
ROOT_FAMILY_EFFECT: Final = "effect"
ROOT_FAMILY_UNRESOLVED: Final = "unresolved"

# Closed contract vocabularies (F-3 §2.1.7, §7.3). ``pure_builtin`` is
# contract-declared and corpus-unpopulated (0 of 34 221); an unpopulated tag
# is a fact about the corpus, not about the contract, so it stays.
OPERATION_KINDS: Final = ("canonical_operation", "pure_builtin")
EFFECT_KINDS: Final = (
    "artifact_write",
    "field_write",
    "publish_event",
    "security_observation",
    "serialize_field",
)

# Closed fact-family vocabularies of the wave-1.5 families. Values are the
# contract dictionaries the wire refuses unknowns for (W08); they mirror the
# producer's Literal types in ``codeclone.models`` and are pinned against
# them by test — a silent drift on either side is loud, never absorbed.
# ``deferred_getattr`` and ``lazy_syntax`` are corpus-unpopulated (0 of
# 5 244 rows); unpopulated tags stay, as above.
IMPORT_TYPES: Final = ("import", "from_import")
DEPENDENCY_BINDINGS: Final = (
    "import_time",
    "deferred_function",
    "deferred_getattr",
    "type_checking",
    "lazy_syntax",
)
VIOLATION_KINDS: Final = (
    "multiple_independent_producers",
    "shadow_projection",
    "owner_bypass",
    "reconstructed_contract",
    "divergent_failure_semantics",
    "divergent_canonicalization",
)
# F2 coupling_cohesion_observations (wave 4): the producer's closed dimension
# set (observations/projection.py `_coupling_cohesion_observations`), measured
# 2 091/2 091 rows on the frozen corpus with every dimension populated.  The
# wire refuses unknowns (W08); meaning is owned by
# DESIGN_METRICS_ALGORITHM_REVISION (the Wave D lane split: complexity moved
# to its own revision, this family stays on design metrics).
COUPLING_COHESION_DIMENSIONS: Final = (
    "cbo",
    "instance_variables",
    "lcom4",
    "methods",
)
# F1 risk_observations (ruling 2026-08-26, fork (b)): the producer's closed
# dimension set (observations/projection.py `_risk_observations`), mirrored
# verbatim.  The wire refuses unknowns (W08); meaning is owned by
# COMPLEXITY_ALGORITHM_REVISION (the Wave D lane split: the risk lane rides
# the complexity revision, never the shared design-metrics one).
RISK_DIMENSIONS: Final = ("cyclomatic_complexity", "nesting_depth")
# F7 dependency_cycles (wave 4): the producer's closed cycle-kind vocabulary
# (``codeclone.models.DependencyCycleKind``), mirrored verbatim and pinned
# against it by test.  The wire refuses unknowns (W08).  The classification
# law — ``import_cycle`` iff the import-time edges still cycle among the
# members — is applied exactly once by the one producer owner
# (``metrics/dependencies.runtime_cycle_facts``); the family stores the
# verdict as an analysis FACT and never re-derives it on read.
DEPENDENCY_CYCLE_KINDS: Final = ("import_cycle", "deferred_cycle")
# F8 clone_groups (wave 4): the emitted clone-kind vocabulary, mirrored
# verbatim from the contract constants (CLONE_KIND_FUNCTION / _BLOCK /
# _SEGMENT) and pinned against them by test.  The wire refuses unknowns
# (W08); the producer group_key's meaning is owned by the clone fingerprint
# generation (BASELINE_FINGERPRINT_VERSION).  This family carries the
# EMITTED population only: the suppressed container is a DIFFERENT
# population (ruling 2026-08-24 §10 — the known dialect root) and never
# enters it.
CLONE_KINDS: Final = ("function", "block", "segment")
# F5 api_symbols (wave 4): the producer's closed vocabularies, mirrored
# verbatim in producer Literal order (``codeclone.models``: ApiSymbolKind /
# ApiVisibility / ApiParameterKind) and pinned against them by test — a
# silent drift on either side is loud, never absorbed.  The wire refuses
# unknowns (W08); signature meaning is owned by
# ``api_signature_identity_contract.v1`` (API_SURFACE_SIGNATURE_VERSION).
API_SYMBOL_KINDS: Final = ("function", "class", "method", "constant")
API_VISIBILITIES: Final = ("all", "name")
API_PARAMETER_KINDS: Final = ("pos_only", "pos_or_kw", "vararg", "kw_only", "kwarg")


def _utf8(value: str) -> bytes:
    """UTF-8 bytes of canonical string content; a lone surrogate is refused
    with a typed error — it is not a sequence of Unicode scalars (§7.9)."""
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise CanonicalModelError(
            f"lone surrogate is not canonical string content: {error}"
        ) from error


def _require_file_path(path: str) -> str:
    """FILE path identity law (F-3 §7.8), enforced at the producer.

    Relative to the analysis root, POSIX separators, no leading ``./``, no
    ``.`` or ``..`` components, case and Unicode preserved.  The decoder
    enforces the same grammar as refusal ``W17``.
    """
    if not path:
        raise CanonicalModelError("FILE path must be non-empty")
    if "\\" in path:
        raise CanonicalModelError(f"FILE path must use POSIX separators: {path!r}")
    if path.startswith("/"):
        raise CanonicalModelError(f"FILE path must be relative: {path!r}")
    parts = path.split("/")
    if "" in parts:
        raise CanonicalModelError(f"FILE path has an empty component: {path!r}")
    if "." in parts or ".." in parts:
        raise CanonicalModelError(f"FILE path must not contain '.' or '..': {path!r}")
    return path


@dataclass(frozen=True, slots=True)
class FileId:
    """FILE identity: normalized POSIX path from the analysis root."""

    path: str

    def __post_init__(self) -> None:
        _require_file_path(self.path)


@dataclass(frozen=True, slots=True)
class ModuleId:
    """MODULE identity: dotted module name from the module registry."""

    module: str

    def __post_init__(self) -> None:
        if not self.module:
            raise CanonicalModelError("MODULE name must be non-empty")


@dataclass(frozen=True, slots=True)
class SymbolId:
    """SYMBOL identity: ``(FILE, qualname)`` — frozen, no module head."""

    file: FileId
    qualname: str

    def __post_init__(self) -> None:
        if not self.qualname:
            raise CanonicalModelError("SYMBOL qualname must be non-empty")


@dataclass(frozen=True, slots=True)
class KnownModule:
    """Operation head naming a registry MODULE identity."""

    module: ModuleId


@dataclass(frozen=True, slots=True)
class AnalysisFile:
    """Operation head naming an analyzed FILE identity (12 module-less files)."""

    file: FileId


@dataclass(frozen=True, slots=True)
class OpaqueDottedHead:
    """Dotted head outside the module registry — NOT a MODULE identity."""

    text: str

    def __post_init__(self) -> None:
        if not self.text:
            raise CanonicalModelError("opaque dotted head must be non-empty")


OperationHead = KnownModule | AnalysisFile | OpaqueDottedHead
DependencyEndpoint = ModuleId | FileId


@dataclass(frozen=True, slots=True)
class OperationTarget:
    """Target of an ``operation:`` root — never a SYMBOL (0 of 1 080).

    Identity is separate from resolution: a later-proven resolution
    (re-export alias to a SYMBOL) is a separate fact and never rewrites
    this identity in place.

    Measured on the frozen corpus (wave 2): 21 of 1 080 operation targets
    carry no ModuleKey colon at all — the producer asserted one opaque
    dotted string, not a ``head:local`` pair.  Splitting such a string at a
    dot would manufacture structure the producer never asserted (the exact
    defect class of the ``graph_packages`` projection), so the whole string
    is the opaque head and ``local_name`` is empty.  An empty local name
    under a ``KnownModule``/``AnalysisFile`` head stays refused: for those
    the producer's grammar always carries a local name.
    """

    head: OperationHead
    local_name: str

    def __post_init__(self) -> None:
        if not self.local_name and not isinstance(self.head, OpaqueDottedHead):
            raise CanonicalModelError(
                "operation target local name may be empty only under an "
                "opaque head (measured: 21 of 1 080 corpus targets are one "
                "opaque dotted string)"
            )


@dataclass(frozen=True, slots=True)
class OperationRoot:
    """EFFECT_ROOT variant: a call/reference target outside function contracts."""

    operation_kind: str
    target: OperationTarget

    def __post_init__(self) -> None:
        if self.operation_kind not in OPERATION_KINDS:
            raise CanonicalModelError(
                f"unknown operation_kind: {self.operation_kind!r}"
            )


@dataclass(frozen=True, slots=True)
class ProducerRoot:
    """EFFECT_ROOT variant: this function itself is the fact's source."""

    target: SymbolId


@dataclass(frozen=True, slots=True)
class EffectLabelRoot:
    """EFFECT_ROOT variant: opaque producer-side operation label, not a reference."""

    effect_kind: str
    label: str

    def __post_init__(self) -> None:
        if self.effect_kind not in EFFECT_KINDS:
            raise CanonicalModelError(f"unknown effect_kind: {self.effect_kind!r}")
        if not self.label:
            raise CanonicalModelError("effect label must be non-empty")


@dataclass(frozen=True, slots=True)
class UnresolvedRoot:
    """EFFECT_ROOT variant: nullary sentinel carrying a transitive fact."""


EffectRoot = OperationRoot | ProducerRoot | EffectLabelRoot | UnresolvedRoot

_HEAD_KEYS: Final[dict[type, str]] = {
    KnownModule: DOMAIN_TAG_MODULE,
    AnalysisFile: DOMAIN_TAG_FILE,
    OpaqueDottedHead: HEAD_TAG_OPAQUE,
}


def _head_key(head: OperationHead) -> tuple[str, bytes]:
    if isinstance(head, KnownModule):
        return (DOMAIN_TAG_MODULE, _utf8(head.module.module))
    if isinstance(head, AnalysisFile):
        return (DOMAIN_TAG_FILE, _utf8(head.file.path))
    return (HEAD_TAG_OPAQUE, _utf8(head.text))


def head_tag(head: OperationHead) -> str:
    """Contract tag string of an operation-head variant."""
    return _HEAD_KEYS[type(head)]


def endpoint_key(endpoint: DependencyEndpoint) -> tuple[str, bytes]:
    """Total canonical key of a dependency endpoint across the ratified
    ``MODULE | FILE`` union (F-3 §2.1.8): the domain tag first, then the
    domain's own key bytes — the same construction the operation head uses,
    so two unions never grow two orderings."""
    if isinstance(endpoint, ModuleId):
        return (DOMAIN_TAG_MODULE, _utf8(endpoint.module))
    if isinstance(endpoint, FileId):
        return (DOMAIN_TAG_FILE, _utf8(endpoint.path))
    raise CanonicalModelError(f"value is not a dependency endpoint: {endpoint!r}")


def canonical_key(value: object) -> tuple[object, ...]:
    """Total canonical sort key (F-3 §3), injective per domain.

    Keys are tuples of tag strings and UTF-8 byte strings; no string join is
    ever used, so values that would collide under a separator join
    (``a:b.c`` versus ``a.b:c``) stay distinct by construction.
    """
    if isinstance(value, FileId):
        return (_utf8(value.path),)
    if isinstance(value, ModuleId):
        return (_utf8(value.module),)
    if isinstance(value, SymbolId):
        return (_utf8(value.file.path), _utf8(value.qualname))
    if isinstance(value, OperationRoot):
        tag, head_bytes = _head_key(value.target.head)
        return (
            ROOT_FAMILY_OPERATION,
            value.operation_kind,
            tag,
            head_bytes,
            _utf8(value.target.local_name),
        )
    if isinstance(value, ProducerRoot):
        return (ROOT_FAMILY_PRODUCER, *canonical_key(value.target))
    if isinstance(value, EffectLabelRoot):
        return (
            ROOT_FAMILY_EFFECT,
            value.effect_kind,
            _utf8(value.label),
        )
    if isinstance(value, UnresolvedRoot):
        return (ROOT_FAMILY_UNRESOLVED,)
    raise CanonicalModelError(f"value has no canonical key: {value!r}")


def root_family(root: EffectRoot) -> str:
    """Contract family tag of an EFFECT_ROOT variant."""
    if isinstance(root, OperationRoot):
        return ROOT_FAMILY_OPERATION
    if isinstance(root, ProducerRoot):
        return ROOT_FAMILY_PRODUCER
    if isinstance(root, EffectLabelRoot):
        return ROOT_FAMILY_EFFECT
    return ROOT_FAMILY_UNRESOLVED
