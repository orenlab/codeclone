# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic canonical JSON codec vNext (F-3 §7), wire revision 0.

The codec owns its own serializer: the legacy ``orjson OPT_SORT_KEYS``
canonizer sorts the top level and silently turns NaN into ``null`` — both
violate this contract, so it is never called here.

Wire revision 0 grammar (root keys, declared order — every reference points
backward, never forward)::

    format · revisions · values · domains · sets · scope · facts · integrity

``comparison`` and ``evaluation`` join in later waves with a wire revision
bump: emitting an empty object today would present "not populated by this
model revision" as "measured empty", which the four-state law forbids.

Canonical byte laws implemented here:

* one lexical form per finite float — ``repr(value)`` shortest round-trip;
  NaN and the infinities are refused, never substituted (W06);
* one escape form per string — only mandatory JSON escapes, short forms
  where JSON defines them, lowercase ``\\u00xx`` for the rest of C0; no
  Unicode normalization ever (§7.9);
* integers in ``[0, 2**31 - 1]`` for every ordinal and counter (W07);
* the ``integrity`` member seals the preceding members: its digest is
  ``sha256(DOMAIN + body)`` where *body* is exactly the serialized bytes of
  all preceding root members — keys, colons and commas included, outer
  braces excluded — so a third party recomputes it one way only;
* a decoded document must re-encode to the identical bytes (W24) — one
  semantic document has exactly one byte encoding.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from itertools import pairwise
from typing import Any, TypeVar, cast

from codeclone.canonical.errors import CanonicalModelError, WireDecodeError
from codeclone.canonical.identity import (
    DOMAIN_TAG_FILE,
    DOMAIN_TAG_MODULE,
    EFFECT_KINDS,
    HEAD_TAG_OPAQUE,
    OPERATION_KINDS,
    ROOT_FAMILY_EFFECT,
    ROOT_FAMILY_OPERATION,
    ROOT_FAMILY_PRODUCER,
    ROOT_FAMILY_UNRESOLVED,
    AnalysisFile,
    EffectLabelRoot,
    EffectRoot,
    FileId,
    KnownModule,
    ModuleId,
    OpaqueDottedHead,
    OperationHead,
    OperationRoot,
    OperationTarget,
    ProducerRoot,
    SymbolId,
    UnresolvedRoot,
    canonical_key,
    root_family,
)
from codeclone.canonical.model import (
    CandidateRow,
    CanonicalFacts,
    CanonicalModel,
    ContractRow,
    FileModuleRelation,
    GraphNodeRow,
    SemanticEdge,
    SinkRoleRow,
)
from codeclone.canonical.registry import wire_columns, wire_fact_family_order
from codeclone.contracts import (
    AUTHORITY_ANALYSIS_REVISION,
    CANONICAL_MODEL_REVISION,
    CANONICAL_WIRE_REVISION,
    CONTRACT_IR_VERSION,
    MODULE_IDENTITY_VERSION,
)

_FORMAT_NAME = "codeclone-canonical"
_ROOT_KEYS = (
    "format",
    "revisions",
    "values",
    "domains",
    "sets",
    "scope",
    "facts",
    "integrity",
)
_DOMAIN_KEYS = ("files", "modules", "symbols", "effect_roots")
_SET_KEYS = ("coupled_sets", "producer_sets", "root_sets")
_REVISION_KEYS = (
    "authority_analysis",
    "canonical_model",
    "contract_ir",
    "module_identity",
)
_SUPPORTED_REVISIONS = {
    "authority_analysis": AUTHORITY_ANALYSIS_REVISION,
    "canonical_model": CANONICAL_MODEL_REVISION,
    "contract_ir": CONTRACT_IR_VERSION,
    "module_identity": MODULE_IDENTITY_VERSION,
}
_INTEGRITY_DOMAIN = b"cc-canonical-wire:0\x00"
_INTEGRITY_MARKER = b',"integrity":'
_MAX_INT = 2**31 - 1
_ROOT_FAMILIES = (
    ROOT_FAMILY_OPERATION,
    ROOT_FAMILY_PRODUCER,
    ROOT_FAMILY_EFFECT,
    ROOT_FAMILY_UNRESOLVED,
)
_VARIANT_SLOTS: dict[str, frozenset[str]] = {
    ROOT_FAMILY_OPERATION: frozenset({"head", "local_name", "operation_kind"}),
    ROOT_FAMILY_PRODUCER: frozenset({"target"}),
    ROOT_FAMILY_EFFECT: frozenset({"effect_kind", "label"}),
    ROOT_FAMILY_UNRESOLVED: frozenset(),
}
_EFFECT_ROOT_SPARSE_COLUMNS = (
    "effect_kind",
    "head",
    "label",
    "local_name",
    "operation_kind",
    "target",
)
_KNOWN_REFERENCE_TAGS = frozenset(
    {DOMAIN_TAG_FILE, DOMAIN_TAG_MODULE, "symbol", "effect_root", HEAD_TAG_OPAQUE}
)
_HEAD_TAGS = frozenset({DOMAIN_TAG_FILE, DOMAIN_TAG_MODULE, HEAD_TAG_OPAQUE})

_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def canonical_string_lexeme(value: str) -> str:
    """The one canonical JSON lexeme of a string (§7.9)."""
    out = ['"']
    for char in value:
        code = ord(char)
        if 0xD800 <= code <= 0xDFFF:
            raise CanonicalModelError("lone surrogate is not canonical string content")
        escape = _ESCAPES.get(char)
        if escape is not None:
            out.append(escape)
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def canonical_float_lexeme(value: float) -> str:
    """The one canonical JSON lexeme of a finite float."""
    if value != value or value in (float("inf"), float("-inf")):
        raise CanonicalModelError("NaN and Infinity are refused, not encoded")
    return repr(value)


class _Obj:
    """A JSON object with explicit, contract-declared member order."""

    __slots__ = ("items",)

    def __init__(self, items: Sequence[tuple[str, object]]) -> None:
        self.items = list(items)


def _write(value: object) -> str:
    if isinstance(value, _Obj):
        members = ",".join(
            f"{canonical_string_lexeme(key)}:{_write(item)}"
            for key, item in value.items
        )
        return "{" + members + "}"
    if isinstance(value, str):
        return canonical_string_lexeme(value)
    if isinstance(value, bool):
        raise CanonicalModelError("wire revision 0 declares no boolean slots")
    if isinstance(value, int):
        if not 0 <= value <= _MAX_INT:
            raise CanonicalModelError(f"integer out of wire range: {value}")
        return str(value)
    if isinstance(value, float):
        return canonical_float_lexeme(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_write(item) for item in value) + "]"
    raise CanonicalModelError(f"value has no wire form: {value!r}")


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------

_ValueT = TypeVar("_ValueT")


def _ordinals(values: Sequence[_ValueT]) -> dict[_ValueT, int]:
    return {value: ordinal for ordinal, value in enumerate(values)}


def _sorted_domain(values: Iterable[_ValueT]) -> list[_ValueT]:
    return sorted(set(values), key=canonical_key)


def _domain_symbols(facts: CanonicalFacts) -> list[SymbolId]:
    referenced: set[SymbolId] = set()
    for contract in facts.contracts:
        referenced.add(contract.function)
        referenced.update(
            root.target for root in contract.root_set if isinstance(root, ProducerRoot)
        )
    for node in facts.graph_nodes:
        referenced.add(node.function)
        referenced.update(
            root.target for root in node.root_set if isinstance(root, ProducerRoot)
        )
    referenced.update(row.symbol for row in facts.sink_roles)
    for candidate in facts.candidates:
        referenced.update(candidate.producer_set)
    for edge in facts.semantic_edges:
        referenced.add(edge.source)
        referenced.add(edge.target)
    return _sorted_domain(referenced)


def _domain_roots(facts: CanonicalFacts) -> list[EffectRoot]:
    return _sorted_domain(
        root for row in facts.contracts | facts.graph_nodes for root in row.root_set
    )


def _head_value(
    head: OperationHead,
    module_ordinal: Mapping[ModuleId, int],
    file_ordinal: Mapping[FileId, int],
) -> object:
    if isinstance(head, KnownModule):
        return [DOMAIN_TAG_MODULE, module_ordinal[head.module]]
    if isinstance(head, AnalysisFile):
        return [DOMAIN_TAG_FILE, file_ordinal[head.file]]
    return [HEAD_TAG_OPAQUE, head.text]


def _encode_effect_roots(
    roots: Sequence[EffectRoot],
    module_ordinal: Mapping[ModuleId, int],
    file_ordinal: Mapping[FileId, int],
    symbol_ordinal: Mapping[SymbolId, int],
) -> _Obj:
    family_column: list[str] = []
    sparse: dict[str, list[tuple[str, object]]] = {
        name: [] for name in _EFFECT_ROOT_SPARSE_COLUMNS
    }
    for position, root in enumerate(roots):
        family_column.append(root_family(root))
        key = str(position)
        if isinstance(root, OperationRoot):
            sparse["head"].append(
                (key, _head_value(root.target.head, module_ordinal, file_ordinal))
            )
            sparse["local_name"].append((key, root.target.local_name))
            sparse["operation_kind"].append((key, root.operation_kind))
        elif isinstance(root, ProducerRoot):
            sparse["target"].append((key, symbol_ordinal[root.target]))
        elif isinstance(root, EffectLabelRoot):
            sparse["effect_kind"].append((key, root.effect_kind))
            sparse["label"].append((key, root.label))
    members: list[tuple[str, object]] = [("family", family_column)]
    members.extend(
        (name, _Obj(sparse[name]))
        for name in _EFFECT_ROOT_SPARSE_COLUMNS
        if sparse[name]
    )
    return _Obj(members)


def _fact_tables(
    facts: CanonicalFacts,
    file_ordinal: Mapping[FileId, int],
    module_ordinal: Mapping[ModuleId, int],
    symbol_ordinal: Mapping[SymbolId, int],
    file_modules: frozenset[FileModuleRelation],
    root_ordinal: Mapping[EffectRoot, int],
    producer_set_ordinal: Mapping[tuple[int, ...], int],
    root_set_ordinal: Mapping[tuple[int, ...], int],
) -> dict[str, list[dict[str, object]]]:
    def producer_ref(row: CandidateRow) -> tuple[int, ...]:
        return tuple(sorted(symbol_ordinal[p] for p in row.producer_set))

    def root_set_ref(row_set: frozenset[EffectRoot]) -> int:
        return root_set_ordinal[tuple(sorted(root_ordinal[r] for r in row_set))]

    return {
        "candidates": [
            {
                "level": row.level,
                "producer_set": producer_set_ordinal[producer_ref(row)],
                "shared_fact": row.shared_fact,
            }
            for row in sorted(
                facts.candidates,
                key=lambda row: (
                    row.level.encode("utf-8"),
                    row.shared_fact.encode("utf-8"),
                    producer_ref(row),
                ),
            )
        ],
        "contracts": [
            {
                "effect_signature": row.effect_signature,
                "function": symbol_ordinal[row.function],
                "root_set": root_set_ref(row.root_set),
            }
            for row in sorted(
                facts.contracts, key=lambda row: symbol_ordinal[row.function]
            )
        ],
        "file_modules": [
            {
                "file": file_ordinal[rel.file],
                "module": module_ordinal[rel.module],
            }
            for rel in sorted(
                file_modules,
                key=lambda rel: (file_ordinal[rel.file], module_ordinal[rel.module]),
            )
        ],
        "graph_nodes": [
            {
                "effect_signature": row.effect_signature,
                "function": symbol_ordinal[row.function],
                "output_facts": list(row.output_facts),
                "resolution_state": row.resolution_state,
                "root_set": root_set_ref(row.root_set),
            }
            for row in sorted(
                facts.graph_nodes, key=lambda row: symbol_ordinal[row.function]
            )
        ],
        "semantic_edges": [
            {
                "source": symbol_ordinal[edge.source],
                "target": symbol_ordinal[edge.target],
            }
            for edge in sorted(
                facts.semantic_edges,
                key=lambda e: (symbol_ordinal[e.source], symbol_ordinal[e.target]),
            )
        ],
        "sink_roles": [
            {
                "authority_status": row.authority_status,
                "symbol": symbol_ordinal[row.symbol],
            }
            for row in sorted(
                facts.sink_roles, key=lambda row: symbol_ordinal[row.symbol]
            )
        ],
    }


def _seal(members: Sequence[tuple[str, object]]) -> bytes:
    body = ",".join(
        f"{canonical_string_lexeme(key)}:{_write(value)}" for key, value in members
    ).encode("utf-8")
    digest = hashlib.sha256(_INTEGRITY_DOMAIN + body).hexdigest()
    integrity = _Obj([("algorithm", "sha256"), ("value", digest)])
    tail = f',"integrity":{_write(integrity)}'.encode()
    return b"{" + body + tail + b"}"


def _interned_labels(
    model: CanonicalModel,
) -> tuple[list[str], list[tuple[int, ...]]]:
    labels = sorted({label for group in model.coupled_sets for label in group})
    label_ordinal = _ordinals(labels)
    coupled_tables = sorted(
        tuple(sorted(label_ordinal[label] for label in group))
        for group in model.coupled_sets
    )
    return labels, coupled_tables


def _interned_producer_sets(
    facts: CanonicalFacts, symbol_ordinal: Mapping[SymbolId, int]
) -> list[tuple[int, ...]]:
    return sorted(
        {
            tuple(sorted(symbol_ordinal[p] for p in row.producer_set))
            for row in facts.candidates
        }
    )


def _interned_root_sets(
    facts: CanonicalFacts, root_ordinal: Mapping[EffectRoot, int]
) -> list[tuple[int, ...]]:
    return sorted(
        {
            tuple(sorted(root_ordinal[r] for r in row.root_set))
            for row in facts.contracts | facts.graph_nodes
        }
    )


def _domains_member(
    files: Sequence[FileId],
    modules: Sequence[ModuleId],
    symbols: Sequence[SymbolId],
    roots: Sequence[EffectRoot],
    file_ordinal: Mapping[FileId, int],
    module_ordinal: Mapping[ModuleId, int],
    symbol_ordinal: Mapping[SymbolId, int],
) -> _Obj:
    return _Obj(
        [
            ("files", _Obj([("path", [f.path for f in files])])),
            ("modules", _Obj([("module", [m.module for m in modules])])),
            (
                "symbols",
                _Obj(
                    [
                        ("file", [file_ordinal[s.file] for s in symbols]),
                        ("qualname", [s.qualname for s in symbols]),
                    ]
                ),
            ),
            (
                "effect_roots",
                _encode_effect_roots(
                    roots, module_ordinal, file_ordinal, symbol_ordinal
                ),
            ),
        ]
    )


def _facts_member(tables: Mapping[str, list[dict[str, object]]]) -> _Obj:
    return _Obj(
        [
            (
                family,
                _Obj(
                    [
                        (column, [row[column] for row in tables[family]])
                        for column in wire_columns(family)
                    ]
                ),
            )
            for family in wire_fact_family_order()
        ]
    )


def encode_canonical_json(model: CanonicalModel) -> bytes:
    """Project a canonical model to its one canonical byte encoding."""
    model = model.normalize()
    facts = model.facts

    files = _sorted_domain(model.files)
    modules = _sorted_domain(model.modules)
    symbols = _domain_symbols(facts)
    roots = _domain_roots(facts)
    file_ordinal = _ordinals(files)
    module_ordinal = _ordinals(modules)
    symbol_ordinal = _ordinals(symbols)
    root_ordinal = _ordinals(roots)

    labels, coupled_tables = _interned_labels(model)
    producer_set_tables = _interned_producer_sets(facts, symbol_ordinal)
    root_set_tables = _interned_root_sets(facts, root_ordinal)
    tables = _fact_tables(
        facts,
        file_ordinal,
        module_ordinal,
        symbol_ordinal,
        model.file_modules,
        root_ordinal,
        _ordinals(producer_set_tables),
        _ordinals(root_set_tables),
    )

    sets = _Obj(
        [
            ("coupled_sets", [list(t) for t in coupled_tables]),
            ("producer_sets", [list(t) for t in producer_set_tables]),
            ("root_sets", [list(t) for t in root_set_tables]),
        ]
    )
    scope = _Obj(
        [
            (
                "analyzed_files",
                sorted(file_ordinal[f] for f in model.analyzed_files),
            )
        ]
    )
    members: list[tuple[str, object]] = [
        (
            "format",
            _Obj([("name", _FORMAT_NAME), ("wire", CANONICAL_WIRE_REVISION)]),
        ),
        (
            "revisions",
            _Obj([(key, _SUPPORTED_REVISIONS[key]) for key in _REVISION_KEYS]),
        ),
        ("values", _Obj([("coupled_class_labels", labels)])),
        (
            "domains",
            _domains_member(
                files,
                modules,
                symbols,
                roots,
                file_ordinal,
                module_ordinal,
                symbol_ordinal,
            ),
        ),
        ("sets", sets),
        ("scope", scope),
        ("facts", _facts_member(tables)),
    ]
    return _seal(members)


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------


def _refuse(code: str, detail: str) -> WireDecodeError:
    return WireDecodeError(code, detail)


def _pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen = set()
    for key, _value in pairs:
        if key in seen:
            raise _refuse("W03", f"duplicate object key {key!r}")
        seen.add(key)
    return dict(pairs)


def _parse_constant(text: str) -> object:
    raise _refuse("W06", f"non-finite literal {text!r}")


def _parse_float(text: str) -> float:
    value = float(text)
    if text != repr(value):
        raise _refuse(
            "W24", f"float lexeme {text!r} is not the canonical {repr(value)!r}"
        )
    return value


def _expect_object(
    value: object, declared: Sequence[str], where: str
) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise _refuse("W01", f"{where} is not an object")
    keys = list(value.keys())
    if set(keys) != set(declared):
        raise _refuse(
            "W01",
            f"{where} keys {keys!r} do not match the declared set {list(declared)!r}",
        )
    if keys != list(declared):
        raise _refuse("W02", f"{where} keys {keys!r} are not in the declared order")
    return cast("Mapping[str, object]", value)


def _expect_string(value: object, where: str) -> str:
    if value is None:
        raise _refuse("W18", f"{where} is null where the contract forbids null")
    if not isinstance(value, str):
        raise _refuse("W18", f"{where} is not a string")
    for char in value:
        if 0xD800 <= ord(char) <= 0xDFFF:
            raise _refuse("W05", f"{where} carries a lone surrogate")
    return value


def _expect_ordinal(value: object, size: int, where: str) -> int:
    if value is None:
        raise _refuse("W18", f"{where} is null where the contract forbids null")
    if isinstance(value, bool):
        raise _refuse("W18", f"{where} is a boolean where an integer is declared")
    if isinstance(value, float):
        raise _refuse("W07", f"{where} is fractional where an integer is declared")
    if not isinstance(value, int):
        raise _refuse("W18", f"{where} is not an integer")
    if not 0 <= value <= _MAX_INT:
        raise _refuse("W07", f"{where} integer {value} outside [0, 2**31-1]")
    if value >= size:
        raise _refuse("W10", f"{where} ordinal {value} outside table of {size}")
    return value


def _expect_list(value: object, where: str) -> list[object]:
    if not isinstance(value, list):
        raise _refuse("W18", f"{where} is not an array")
    return cast("list[object]", value)


def _expect_strictly_increasing(rows: Sequence[Any], where: str) -> None:
    # Any: each call site passes one homogeneous key shape (int tuples or
    # byte tuples); the comparison itself is the canonical-order check.
    for left, right in pairwise(rows):
        if left == right:
            raise _refuse("W13", f"{where} carries a duplicate canonical key")
        if left > right:
            raise _refuse("W12", f"{where} is not in canonical order")


def _expect_increasing_elements(values: Sequence[int], where: str) -> None:
    for left, right in pairwise(values):
        if right <= left:
            raise _refuse("W14", f"{where} elements are not strictly increasing")


def _decode_file_path(value: object, where: str) -> str:
    text = _expect_string(value, where)
    try:
        FileId(text)
    except CanonicalModelError as error:
        raise _refuse("W17", f"{where}: {error}") from error
    return text


def _decode_sparse_map(value: object, row_count: int, where: str) -> dict[int, object]:
    if not isinstance(value, dict):
        raise _refuse("W18", f"{where} is not a sparse map object")
    entries = cast("dict[str, object]", value)
    positions: dict[int, object] = {}
    previous = -1
    for key, item in entries.items():
        if not key.isdigit() or (len(key) > 1 and key.startswith("0")):
            raise _refuse(
                "W19", f"{where} key {key!r} is not a canonical decimal position"
            )
        position = int(key)
        if position >= row_count:
            raise _refuse("W19", f"{where} position {position} outside the row range")
        if position <= previous:
            raise _refuse("W02", f"{where} positions are not in canonical order")
        previous = position
        positions[position] = item
    return positions


def _decode_head(
    value: object, files: Sequence[FileId], modules: Sequence[ModuleId], where: str
) -> OperationHead:
    pair = _expect_list(value, where)
    if len(pair) != 2:
        raise _refuse("W18", f"{where} is not a [tag, value] pair")
    tag = _expect_string(pair[0], f"{where}.tag")
    if tag not in _KNOWN_REFERENCE_TAGS:
        raise _refuse("W08", f"unknown reference tag {tag!r}")
    if tag not in _HEAD_TAGS:
        raise _refuse(
            "W09", f"reference tag {tag!r} is not admitted for an operation head"
        )
    if tag == DOMAIN_TAG_MODULE:
        return KnownModule(modules[_expect_ordinal(pair[1], len(modules), where)])
    if tag == DOMAIN_TAG_FILE:
        return AnalysisFile(files[_expect_ordinal(pair[1], len(files), where)])
    text = _expect_string(pair[1], where)
    if not text:
        raise _refuse("W18", f"{where} opaque head is empty")
    return OpaqueDottedHead(text)


def _decode_root_row(
    family: str,
    position: int,
    sparse: Mapping[str, dict[int, object]],
    files: Sequence[FileId],
    modules: Sequence[ModuleId],
    symbols: Sequence[SymbolId],
) -> EffectRoot:
    if family == ROOT_FAMILY_OPERATION:
        kind = _expect_string(
            sparse["operation_kind"][position],
            f"effect_roots.operation_kind[{position}]",
        )
        if kind not in OPERATION_KINDS:
            raise _refuse("W08", f"unknown operation_kind tag {kind!r}")
        head = _decode_head(
            sparse["head"][position], files, modules, f"effect_roots.head[{position}]"
        )
        local_name = _expect_string(
            sparse["local_name"][position], f"effect_roots.local_name[{position}]"
        )
        if not local_name:
            raise _refuse("W18", f"effect_roots.local_name[{position}] is empty")
        return OperationRoot(kind, OperationTarget(head, local_name))
    if family == ROOT_FAMILY_PRODUCER:
        ordinal = _expect_ordinal(
            sparse["target"][position],
            len(symbols),
            f"effect_roots.target[{position}]",
        )
        return ProducerRoot(symbols[ordinal])
    if family == ROOT_FAMILY_EFFECT:
        kind = _expect_string(
            sparse["effect_kind"][position], f"effect_roots.effect_kind[{position}]"
        )
        if kind not in EFFECT_KINDS:
            raise _refuse("W08", f"unknown effect_kind tag {kind!r}")
        label = _expect_string(
            sparse["label"][position], f"effect_roots.label[{position}]"
        )
        if not label:
            raise _refuse("W18", f"effect_roots.label[{position}] is empty")
        return EffectLabelRoot(kind, label)
    return UnresolvedRoot()


def _decode_effect_roots(
    value: object,
    files: Sequence[FileId],
    modules: Sequence[ModuleId],
    symbols: Sequence[SymbolId],
) -> list[EffectRoot]:
    if not isinstance(value, dict):
        raise _refuse("W01", "domains.effect_roots is not an object")
    table = cast("dict[str, object]", value)
    keys = list(table.keys())
    if not keys or keys[0] != "family":
        raise _refuse(
            "W02", "effect_roots discriminator column 'family' must come first"
        )
    tail = keys[1:]
    if any(key not in _EFFECT_ROOT_SPARSE_COLUMNS for key in tail):
        raise _refuse("W01", f"effect_roots carries unknown columns: {tail!r}")
    if tail != sorted(tail):
        raise _refuse("W02", "effect_roots variant columns are not in canonical order")
    family_column = _expect_list(table["family"], "effect_roots.family")
    families: list[str] = []
    for index, item in enumerate(family_column):
        family = _expect_string(item, f"effect_roots.family[{index}]")
        if family not in _ROOT_FAMILIES:
            raise _refuse("W08", f"unknown effect-root family tag {family!r}")
        families.append(family)
    sparse = {
        name: _decode_sparse_map(table[name], len(families), f"effect_roots.{name}")
        for name in tail
    }
    for name, positions in sparse.items():
        for position in positions:
            if name not in _VARIANT_SLOTS[families[position]]:
                raise _refuse(
                    "W20",
                    f"variant slot {name!r} is not consistent with family "
                    f"{families[position]!r} at row {position}",
                )
    roots: list[EffectRoot] = []
    for position, family in enumerate(families):
        for slot in _VARIANT_SLOTS[family]:
            if slot not in sparse or position not in sparse[slot]:
                raise _refuse(
                    "W20",
                    f"mandatory variant slot {slot!r} missing for family "
                    f"{family!r} at row {position}",
                )
        roots.append(
            _decode_root_row(family, position, sparse, files, modules, symbols)
        )
    _expect_strictly_increasing(
        [canonical_key(root) for root in roots], "domains.effect_roots"
    )
    return roots


def _decode_set_table(
    value: object, element_count: int, where: str
) -> list[tuple[int, ...]]:
    table = _expect_list(value, where)
    decoded: list[tuple[int, ...]] = []
    for index, row in enumerate(table):
        elements = _expect_list(row, f"{where}[{index}]")
        ordinals = [
            _expect_ordinal(item, element_count, f"{where}[{index}]")
            for item in elements
        ]
        _expect_increasing_elements(ordinals, f"{where}[{index}]")
        decoded.append(tuple(ordinals))
    _expect_strictly_increasing(decoded, where)
    return decoded


def _decode_columns(
    family: str, value: object, expected: Sequence[str]
) -> dict[str, list[object]]:
    table = _expect_object(value, expected, f"facts.{family}")
    columns = {
        name: _expect_list(table[name], f"facts.{family}.{name}") for name in expected
    }
    lengths = {len(column) for column in columns.values()}
    if len(lengths) > 1:
        raise _refuse(
            "W15", f"facts.{family} columns have diverging lengths {lengths!r}"
        )
    return columns


def _parse_document(data: bytes) -> Mapping[str, object]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _refuse("W05", f"document is not UTF-8: {error}") from error
    decoder = json.JSONDecoder(
        object_pairs_hook=_pairs_hook,
        parse_float=_parse_float,
        parse_constant=_parse_constant,
    )
    try:
        document, end = decoder.raw_decode(text)
    except json.JSONDecodeError as error:
        raise _refuse("W01", f"document is not a JSON object: {error}") from error
    if text[end:]:
        raise _refuse("W04", "bytes after the end of the document")
    return _expect_object(document, _ROOT_KEYS, "document root")


def _decode_format_and_revisions(root: Mapping[str, object]) -> None:
    fmt = _expect_object(root["format"], ("name", "wire"), "format")
    if (
        _expect_string(fmt["name"], "format.name") != _FORMAT_NAME
        or _expect_string(fmt["wire"], "format.wire") != CANONICAL_WIRE_REVISION
    ):
        raise _refuse("W21", "format declares an incompatible generation")
    revisions_raw = root["revisions"]
    if not isinstance(revisions_raw, dict):
        raise _refuse("W21", "revisions member is not an object")
    revisions_view = cast("dict[str, object]", revisions_raw)
    if set(revisions_view.keys()) != set(_REVISION_KEYS):
        raise _refuse(
            "W21",
            f"revisions are incomplete: {sorted(revisions_view.keys())!r} "
            f"against declared {list(_REVISION_KEYS)!r}",
        )
    revisions = _expect_object(revisions_raw, _REVISION_KEYS, "revisions")
    for key, expected_value in _SUPPORTED_REVISIONS.items():
        if _expect_string(revisions[key], f"revisions.{key}") != expected_value:
            raise _refuse(
                "W21",
                f"revisions.{key} declares an incompatible generation "
                f"{revisions[key]!r} (supported: {expected_value!r})",
            )


def _decode_values(root: Mapping[str, object]) -> list[str]:
    values_section = _expect_object(root["values"], ("coupled_class_labels",), "values")
    labels = [
        _expect_string(item, f"values.coupled_class_labels[{index}]")
        for index, item in enumerate(
            _expect_list(
                values_section["coupled_class_labels"], "values.coupled_class_labels"
            )
        )
    ]
    _expect_strictly_increasing(
        [label.encode("utf-8") for label in labels], "values.coupled_class_labels"
    )
    return labels


def _decode_files(domains: Mapping[str, object]) -> list[FileId]:
    files_table = _expect_object(domains["files"], ("path",), "domains.files")
    files = [
        FileId(_decode_file_path(item, f"domains.files.path[{index}]"))
        for index, item in enumerate(
            _expect_list(files_table["path"], "domains.files.path")
        )
    ]
    _expect_strictly_increasing([canonical_key(f) for f in files], "domains.files")
    return files


def _decode_modules(domains: Mapping[str, object]) -> list[ModuleId]:
    modules_table = _expect_object(domains["modules"], ("module",), "domains.modules")
    modules = []
    for index, item in enumerate(
        _expect_list(modules_table["module"], "domains.modules.module")
    ):
        text = _expect_string(item, f"domains.modules.module[{index}]")
        if not text:
            raise _refuse("W18", f"domains.modules.module[{index}] is empty")
        modules.append(ModuleId(text))
    _expect_strictly_increasing([canonical_key(m) for m in modules], "domains.modules")
    return modules


def _decode_symbols(
    domains: Mapping[str, object], files: Sequence[FileId]
) -> list[SymbolId]:
    symbols_table = _expect_object(
        domains["symbols"], ("file", "qualname"), "domains.symbols"
    )
    file_column = _expect_list(symbols_table["file"], "domains.symbols.file")
    qualname_column = _expect_list(
        symbols_table["qualname"], "domains.symbols.qualname"
    )
    if len(file_column) != len(qualname_column):
        raise _refuse("W15", "domains.symbols columns have diverging lengths")
    symbols = []
    for index in range(len(file_column)):
        ordinal = _expect_ordinal(
            file_column[index], len(files), f"domains.symbols.file[{index}]"
        )
        qualname = _expect_string(
            qualname_column[index], f"domains.symbols.qualname[{index}]"
        )
        if not qualname:
            raise _refuse("W18", f"domains.symbols.qualname[{index}] is empty")
        symbols.append(SymbolId(files[ordinal], qualname))
    _expect_strictly_increasing([canonical_key(s) for s in symbols], "domains.symbols")
    return symbols


def _decode_candidates(
    facts: Mapping[str, object],
    symbols: Sequence[SymbolId],
    producer_tables: Sequence[tuple[int, ...]],
) -> frozenset[CandidateRow]:
    columns = _decode_columns(
        "candidates", facts["candidates"], wire_columns("candidates")
    )
    rows = []
    keys = []
    for index in range(len(columns["level"])):
        level = _expect_string(
            columns["level"][index], f"facts.candidates.level[{index}]"
        )
        shared_fact = _expect_string(
            columns["shared_fact"][index], f"facts.candidates.shared_fact[{index}]"
        )
        set_ordinal = _expect_ordinal(
            columns["producer_set"][index],
            len(producer_tables),
            f"facts.candidates.producer_set[{index}]",
        )
        rows.append(
            CandidateRow(
                level,
                shared_fact,
                frozenset(symbols[o] for o in producer_tables[set_ordinal]),
            )
        )
        keys.append((level.encode("utf-8"), shared_fact.encode("utf-8"), set_ordinal))
    _expect_strictly_increasing(keys, "facts.candidates")
    return frozenset(rows)


def _decode_contracts(
    facts: Mapping[str, object],
    symbols: Sequence[SymbolId],
    roots: Sequence[EffectRoot],
    root_tables: Sequence[tuple[int, ...]],
) -> tuple[frozenset[ContractRow], set[int]]:
    columns = _decode_columns(
        "contracts", facts["contracts"], wire_columns("contracts")
    )
    rows = []
    ordinals = []
    for index in range(len(columns["function"])):
        ordinal = _expect_ordinal(
            columns["function"][index],
            len(symbols),
            f"facts.contracts.function[{index}]",
        )
        set_ordinal = _expect_ordinal(
            columns["root_set"][index],
            len(root_tables),
            f"facts.contracts.root_set[{index}]",
        )
        rows.append(
            ContractRow(
                symbols[ordinal],
                _expect_string(
                    columns["effect_signature"][index],
                    f"facts.contracts.effect_signature[{index}]",
                ),
                frozenset(roots[r] for r in root_tables[set_ordinal]),
            )
        )
        ordinals.append(ordinal)
    _expect_strictly_increasing(ordinals, "facts.contracts")
    return frozenset(rows), set(ordinals)


def _decode_file_modules(
    facts: Mapping[str, object],
    files: Sequence[FileId],
    modules: Sequence[ModuleId],
) -> frozenset[FileModuleRelation]:
    columns = _decode_columns(
        "file_modules", facts["file_modules"], wire_columns("file_modules")
    )
    rows = []
    keys = []
    for index in range(len(columns["file"])):
        file_ref = _expect_ordinal(
            columns["file"][index], len(files), f"facts.file_modules.file[{index}]"
        )
        module_ref = _expect_ordinal(
            columns["module"][index],
            len(modules),
            f"facts.file_modules.module[{index}]",
        )
        rows.append(FileModuleRelation(files[file_ref], modules[module_ref]))
        keys.append((file_ref, module_ref))
    _expect_strictly_increasing(keys, "facts.file_modules")
    return frozenset(rows)


def _decode_graph_nodes(
    facts: Mapping[str, object],
    symbols: Sequence[SymbolId],
    roots: Sequence[EffectRoot],
    root_tables: Sequence[tuple[int, ...]],
) -> frozenset[GraphNodeRow]:
    columns = _decode_columns(
        "graph_nodes", facts["graph_nodes"], wire_columns("graph_nodes")
    )
    rows = []
    ordinals = []
    for index in range(len(columns["function"])):
        ordinal = _expect_ordinal(
            columns["function"][index],
            len(symbols),
            f"facts.graph_nodes.function[{index}]",
        )
        set_ordinal = _expect_ordinal(
            columns["root_set"][index],
            len(root_tables),
            f"facts.graph_nodes.root_set[{index}]",
        )
        output_facts = tuple(
            _expect_string(item, f"facts.graph_nodes.output_facts[{index}]")
            for item in _expect_list(
                columns["output_facts"][index],
                f"facts.graph_nodes.output_facts[{index}]",
            )
        )
        rows.append(
            GraphNodeRow(
                symbols[ordinal],
                _expect_string(
                    columns["effect_signature"][index],
                    f"facts.graph_nodes.effect_signature[{index}]",
                ),
                frozenset(roots[r] for r in root_tables[set_ordinal]),
                output_facts,
                _expect_string(
                    columns["resolution_state"][index],
                    f"facts.graph_nodes.resolution_state[{index}]",
                ),
            )
        )
        ordinals.append(ordinal)
    _expect_strictly_increasing(ordinals, "facts.graph_nodes")
    return frozenset(rows)


def _decode_semantic_edges(
    facts: Mapping[str, object], symbols: Sequence[SymbolId]
) -> frozenset[SemanticEdge]:
    columns = _decode_columns(
        "semantic_edges", facts["semantic_edges"], wire_columns("semantic_edges")
    )
    rows = []
    keys = []
    for index in range(len(columns["source"])):
        source = _expect_ordinal(
            columns["source"][index],
            len(symbols),
            f"facts.semantic_edges.source[{index}]",
        )
        target = _expect_ordinal(
            columns["target"][index],
            len(symbols),
            f"facts.semantic_edges.target[{index}]",
        )
        rows.append(SemanticEdge(symbols[source], symbols[target]))
        keys.append((source, target))
    _expect_strictly_increasing(keys, "facts.semantic_edges")
    return frozenset(rows)


def _decode_sink_roles(
    facts: Mapping[str, object], symbols: Sequence[SymbolId]
) -> frozenset[SinkRoleRow]:
    columns = _decode_columns(
        "sink_roles", facts["sink_roles"], wire_columns("sink_roles")
    )
    rows = []
    ordinals = []
    for index in range(len(columns["symbol"])):
        ordinal = _expect_ordinal(
            columns["symbol"][index],
            len(symbols),
            f"facts.sink_roles.symbol[{index}]",
        )
        rows.append(
            SinkRoleRow(
                symbols[ordinal],
                _expect_string(
                    columns["authority_status"][index],
                    f"facts.sink_roles.authority_status[{index}]",
                ),
            )
        )
        ordinals.append(ordinal)
    _expect_strictly_increasing(ordinals, "facts.sink_roles")
    return frozenset(rows)


def _check_function_role(
    producer_tables: Sequence[tuple[int, ...]], function_ordinals: set[int]
) -> None:
    for table in producer_tables:
        for ordinal in table:
            if ordinal not in function_ordinals:
                raise _refuse(
                    "W16",
                    f"producer set references symbol ordinal {ordinal} "
                    "without the FUNCTION role",
                )


def _check_integrity(data: bytes, root: Mapping[str, object]) -> None:
    integrity = _expect_object(root["integrity"], ("algorithm", "value"), "integrity")
    if _expect_string(integrity["algorithm"], "integrity.algorithm") != "sha256":
        raise _refuse("W23", "integrity algorithm is not sha256")
    declared_digest = _expect_string(integrity["value"], "integrity.value")
    marker_at = data.rfind(_INTEGRITY_MARKER)
    if marker_at < 0:
        raise _refuse("W24", "integrity member is not in canonical byte form")
    body = data[1:marker_at]
    recomputed = hashlib.sha256(_INTEGRITY_DOMAIN + body).hexdigest()
    if declared_digest != recomputed:
        raise _refuse(
            "W23",
            "integrity digest does not seal the preceding members "
            f"(declared {declared_digest[:12]}…, recomputed {recomputed[:12]}…)",
        )


def decode_canonical_json(data: bytes) -> CanonicalModel:
    """Decode canonical bytes into the canonical semantic model.

    Refusals are typed (``W``-codes) and never degrade silently; a document
    that decodes successfully re-encodes to the identical bytes.
    """
    root = _parse_document(data)
    _decode_format_and_revisions(root)
    labels = _decode_values(root)
    domains = _expect_object(root["domains"], _DOMAIN_KEYS, "domains")
    files = _decode_files(domains)
    modules = _decode_modules(domains)
    symbols = _decode_symbols(domains, files)
    roots = _decode_effect_roots(domains["effect_roots"], files, modules, symbols)

    sets_section = _expect_object(root["sets"], _SET_KEYS, "sets")
    coupled_tables = _decode_set_table(
        sets_section["coupled_sets"], len(labels), "sets.coupled_sets"
    )
    producer_tables = _decode_set_table(
        sets_section["producer_sets"], len(symbols), "sets.producer_sets"
    )
    root_tables = _decode_set_table(
        sets_section["root_sets"], len(roots), "sets.root_sets"
    )

    scope = _expect_object(root["scope"], ("analyzed_files",), "scope")
    analyzed_ordinals = [
        _expect_ordinal(item, len(files), "scope.analyzed_files")
        for item in _expect_list(scope["analyzed_files"], "scope.analyzed_files")
    ]
    _expect_increasing_elements(analyzed_ordinals, "scope.analyzed_files")

    facts_section = _expect_object(root["facts"], wire_fact_family_order(), "facts")
    candidates = _decode_candidates(facts_section, symbols, producer_tables)
    contracts, function_ordinals = _decode_contracts(
        facts_section, symbols, roots, root_tables
    )
    file_modules = _decode_file_modules(facts_section, files, modules)
    graph_nodes = _decode_graph_nodes(facts_section, symbols, roots, root_tables)
    semantic_edges = _decode_semantic_edges(facts_section, symbols)
    sink_roles = _decode_sink_roles(facts_section, symbols)
    _check_function_role(producer_tables, function_ordinals)
    _check_integrity(data, root)

    model = CanonicalModel(
        files=frozenset(files),
        modules=frozenset(modules),
        analyzed_files=frozenset(files[o] for o in analyzed_ordinals),
        file_modules=file_modules,
        facts=CanonicalFacts(
            contracts=contracts,
            graph_nodes=graph_nodes,
            sink_roles=sink_roles,
            candidates=candidates,
            semantic_edges=semantic_edges,
        ),
        coupled_sets=frozenset(
            frozenset(labels[o] for o in table) for table in coupled_tables
        ),
    )
    if encode_canonical_json(model) != data:
        raise _refuse(
            "W24", "document bytes are not the canonical encoding of their model"
        )
    return model
