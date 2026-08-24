# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical normalized model (F-3): one semantic model, two representations.

Frozen semantic substrate of the run-store backend (a2 wave 1).  The four
architecture walls hold here by construction: cache is never truth, a run is
never a previous run plus a patch, storage identifiers never escape into the
wire, and the normalized wire is never the expanded legacy object.
"""

from codeclone.canonical.authority_identity import (
    CANDIDATE_IDENTITY_CONTRACT,
    VIOLATION_IDENTITY_CONTRACT,
    candidate_handle,
    candidate_total_order_key,
    legacy_symbol_key,
    violation_handle,
)
from codeclone.canonical.codec import (
    canonical_float_lexeme,
    canonical_string_lexeme,
    decode_canonical_json,
    encode_canonical_json,
)
from codeclone.canonical.errors import CanonicalModelError, WireDecodeError
from codeclone.canonical.identity import (
    DEPENDENCY_BINDINGS,
    EFFECT_KINDS,
    IMPORT_TYPES,
    OPERATION_KINDS,
    VIOLATION_KINDS,
    AnalysisFile,
    DependencyEndpoint,
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
    endpoint_key,
    head_tag,
    root_family,
)
from codeclone.canonical.model import (
    CandidateRow,
    CanonicalFacts,
    CanonicalModel,
    ContractRow,
    DependencyEdgeRow,
    FileModuleRelation,
    GraphNodeRow,
    SemanticEdge,
    SinkRoleRow,
    ViolationRow,
)
from codeclone.canonical.registry import (
    FACT_FAMILY_FIELDS,
    FieldDeclaration,
    derived_wire_columns,
    sparse_bool_wire_columns,
    wire_columns,
    wire_fact_family_order,
)

__all__ = [
    "CANDIDATE_IDENTITY_CONTRACT",
    "DEPENDENCY_BINDINGS",
    "EFFECT_KINDS",
    "FACT_FAMILY_FIELDS",
    "IMPORT_TYPES",
    "OPERATION_KINDS",
    "VIOLATION_IDENTITY_CONTRACT",
    "VIOLATION_KINDS",
    "AnalysisFile",
    "CandidateRow",
    "CanonicalFacts",
    "CanonicalModel",
    "CanonicalModelError",
    "ContractRow",
    "DependencyEdgeRow",
    "DependencyEndpoint",
    "EffectLabelRoot",
    "EffectRoot",
    "FieldDeclaration",
    "FileId",
    "FileModuleRelation",
    "GraphNodeRow",
    "KnownModule",
    "ModuleId",
    "OpaqueDottedHead",
    "OperationHead",
    "OperationRoot",
    "OperationTarget",
    "ProducerRoot",
    "SemanticEdge",
    "SinkRoleRow",
    "SymbolId",
    "UnresolvedRoot",
    "ViolationRow",
    "WireDecodeError",
    "candidate_handle",
    "candidate_total_order_key",
    "canonical_float_lexeme",
    "canonical_key",
    "canonical_string_lexeme",
    "decode_canonical_json",
    "derived_wire_columns",
    "encode_canonical_json",
    "endpoint_key",
    "head_tag",
    "legacy_symbol_key",
    "root_family",
    "sparse_bool_wire_columns",
    "violation_handle",
    "wire_columns",
    "wire_fact_family_order",
]
