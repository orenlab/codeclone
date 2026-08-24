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

from codeclone.canonical.codec import (
    canonical_float_lexeme,
    canonical_string_lexeme,
    decode_canonical_json,
    encode_canonical_json,
)
from codeclone.canonical.errors import CanonicalModelError, WireDecodeError
from codeclone.canonical.identity import (
    EFFECT_KINDS,
    OPERATION_KINDS,
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
    head_tag,
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
from codeclone.canonical.registry import (
    FACT_FAMILY_FIELDS,
    FieldDeclaration,
    wire_columns,
    wire_fact_family_order,
)

__all__ = [
    "EFFECT_KINDS",
    "FACT_FAMILY_FIELDS",
    "OPERATION_KINDS",
    "AnalysisFile",
    "CandidateRow",
    "CanonicalFacts",
    "CanonicalModel",
    "CanonicalModelError",
    "ContractRow",
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
    "WireDecodeError",
    "canonical_float_lexeme",
    "canonical_key",
    "canonical_string_lexeme",
    "decode_canonical_json",
    "encode_canonical_json",
    "head_tag",
    "root_family",
    "wire_columns",
    "wire_fact_family_order",
]
