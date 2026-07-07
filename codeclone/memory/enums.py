# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Literal

from pydantic import TypeAdapter, ValidationError

MemoryRecordType = Literal[
    "module_role",
    "contract_note",
    "test_anchor",
    "document_link",
    "risk_note",
    "public_surface",
    "contradiction_note",
    "architecture_decision",
    "change_rationale",
    "protocol_rule",
    "stale_marker",
    "human_note",
]

MemoryStatus = Literal[
    "draft",
    "active",
    "historical",
    "stale",
    "superseded",
    "rejected",
    "archived",
]

MemoryConfidence = Literal["inferred", "supported", "verified"]

MemoryOrigin = Literal["system", "agent", "human"]

MemoryIngestSource = Literal[
    "analysis",
    "contract",
    "doc",
    "test",
    "git",
    "receipt",
    "audit",
    "agent",
    "human",
    "snapshot",
]

SubjectKind = Literal[
    "path",
    "symbol",
    "module",
    "package",
    "test",
    "doc",
    "contract",
    "mcp_tool",
    "mcp_resource",
    "cli_option",
    "report_field",
    "baseline_schema",
    "cache_schema",
    "config_key",
    "plugin_surface",
]

SubjectRelation = Literal[
    "about",
    "owns",
    "tests",
    "documents",
    "depends_on",
    "imports",
    "exports",
]

EvidenceKind = Literal[
    "code",
    "test",
    "doc",
    "spec",
    "receipt",
    "git_commit",
    "report",
    "baseline",
    "cache",
    "audit_event",
    "trajectory",
    "external_url",
]

LinkRelation = Literal[
    "supersedes",
    "depends_on",
    "contradicts",
    "explains",
    "implements",
    "tests",
    "documents",
    "deprecates",
    "related_to",
    "implicit_coupling",
]

IngestionMode = Literal["init", "refresh"]

IngestionRunStatus = Literal["running", "completed", "failed", "partial"]

MEMORY_RECORD_TYPE_VALUES: tuple[MemoryRecordType, ...] = (
    "module_role",
    "contract_note",
    "test_anchor",
    "document_link",
    "risk_note",
    "public_surface",
    "contradiction_note",
    "architecture_decision",
    "change_rationale",
    "protocol_rule",
    "stale_marker",
    "human_note",
)
MEMORY_STATUS_VALUES: tuple[MemoryStatus, ...] = (
    "draft",
    "active",
    "historical",
    "stale",
    "superseded",
    "rejected",
    "archived",
)
MEMORY_CONFIDENCE_VALUES: tuple[MemoryConfidence, ...] = (
    "inferred",
    "supported",
    "verified",
)
MEMORY_ORIGIN_VALUES: tuple[MemoryOrigin, ...] = ("system", "agent", "human")
MEMORY_INGEST_SOURCE_VALUES: tuple[MemoryIngestSource, ...] = (
    "analysis",
    "contract",
    "doc",
    "test",
    "git",
    "receipt",
    "audit",
    "agent",
    "human",
    "snapshot",
)
SUBJECT_KIND_VALUES: tuple[SubjectKind, ...] = (
    "path",
    "symbol",
    "module",
    "package",
    "test",
    "doc",
    "contract",
    "mcp_tool",
    "mcp_resource",
    "cli_option",
    "report_field",
    "baseline_schema",
    "cache_schema",
    "config_key",
    "plugin_surface",
)
SUBJECT_RELATION_VALUES: tuple[SubjectRelation, ...] = (
    "about",
    "owns",
    "tests",
    "documents",
    "depends_on",
    "imports",
    "exports",
)
EVIDENCE_KIND_VALUES: tuple[EvidenceKind, ...] = (
    "code",
    "test",
    "doc",
    "spec",
    "receipt",
    "git_commit",
    "report",
    "baseline",
    "cache",
    "audit_event",
    "trajectory",
    "external_url",
)
LINK_RELATION_VALUES: tuple[LinkRelation, ...] = (
    "supersedes",
    "depends_on",
    "contradicts",
    "explains",
    "implements",
    "tests",
    "documents",
    "deprecates",
    "related_to",
    "implicit_coupling",
)
INGESTION_MODE_VALUES: tuple[IngestionMode, ...] = ("init", "refresh")
INGESTION_RUN_STATUS_VALUES: tuple[IngestionRunStatus, ...] = (
    "running",
    "completed",
    "failed",
    "partial",
)

_MEMORY_RECORD_TYPE_ADAPTER: TypeAdapter[MemoryRecordType] = TypeAdapter(
    MemoryRecordType
)
_MEMORY_STATUS_ADAPTER: TypeAdapter[MemoryStatus] = TypeAdapter(MemoryStatus)
_MEMORY_CONFIDENCE_ADAPTER: TypeAdapter[MemoryConfidence] = TypeAdapter(
    MemoryConfidence
)
_MEMORY_ORIGIN_ADAPTER: TypeAdapter[MemoryOrigin] = TypeAdapter(MemoryOrigin)
_MEMORY_INGEST_SOURCE_ADAPTER: TypeAdapter[MemoryIngestSource] = TypeAdapter(
    MemoryIngestSource
)
_SUBJECT_KIND_ADAPTER: TypeAdapter[SubjectKind] = TypeAdapter(SubjectKind)
_SUBJECT_RELATION_ADAPTER: TypeAdapter[SubjectRelation] = TypeAdapter(SubjectRelation)
_EVIDENCE_KIND_ADAPTER: TypeAdapter[EvidenceKind] = TypeAdapter(EvidenceKind)
_LINK_RELATION_ADAPTER: TypeAdapter[LinkRelation] = TypeAdapter(LinkRelation)
_INGESTION_MODE_ADAPTER: TypeAdapter[IngestionMode] = TypeAdapter(IngestionMode)
_INGESTION_RUN_STATUS_ADAPTER: TypeAdapter[IngestionRunStatus] = TypeAdapter(
    IngestionRunStatus
)


def _choices(values: tuple[str, ...]) -> str:
    return ", ".join(repr(value) for value in values)


def _literal_error(field: str, value: object, values: tuple[str, ...]) -> ValueError:
    return ValueError(
        f"Invalid Engineering Memory {field}: {value!r}. "
        f"Allowed values: {_choices(values)}."
    )


def validate_memory_record_type(
    value: object, *, field: str = "record_type"
) -> MemoryRecordType:
    try:
        return _MEMORY_RECORD_TYPE_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise _literal_error(field, value, MEMORY_RECORD_TYPE_VALUES) from exc


def validate_memory_status(
    value: object, *, field: str = "record_status"
) -> MemoryStatus:
    try:
        return _MEMORY_STATUS_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise _literal_error(field, value, MEMORY_STATUS_VALUES) from exc


def validate_memory_confidence(
    value: object, *, field: str = "record_confidence"
) -> MemoryConfidence:
    try:
        return _MEMORY_CONFIDENCE_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise _literal_error(field, value, MEMORY_CONFIDENCE_VALUES) from exc


def validate_memory_origin(
    value: object, *, field: str = "record_origin"
) -> MemoryOrigin:
    try:
        return _MEMORY_ORIGIN_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise _literal_error(field, value, MEMORY_ORIGIN_VALUES) from exc


def validate_memory_ingest_source(
    value: object, *, field: str = "record_ingest_source"
) -> MemoryIngestSource:
    try:
        return _MEMORY_INGEST_SOURCE_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise _literal_error(field, value, MEMORY_INGEST_SOURCE_VALUES) from exc


def validate_subject_kind(value: object, *, field: str = "subject_kind") -> SubjectKind:
    try:
        return _SUBJECT_KIND_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise _literal_error(field, value, SUBJECT_KIND_VALUES) from exc


def validate_subject_relation(
    value: object, *, field: str = "subject_relation"
) -> SubjectRelation:
    try:
        return _SUBJECT_RELATION_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise _literal_error(field, value, SUBJECT_RELATION_VALUES) from exc


def validate_evidence_kind(
    value: object, *, field: str = "evidence_kind"
) -> EvidenceKind:
    try:
        return _EVIDENCE_KIND_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise _literal_error(field, value, EVIDENCE_KIND_VALUES) from exc


def validate_link_relation(
    value: object, *, field: str = "link_relation"
) -> LinkRelation:
    try:
        return _LINK_RELATION_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise _literal_error(field, value, LINK_RELATION_VALUES) from exc


def validate_ingestion_mode(
    value: object, *, field: str = "ingestion_mode"
) -> IngestionMode:
    try:
        return _INGESTION_MODE_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise _literal_error(field, value, INGESTION_MODE_VALUES) from exc


def validate_ingestion_run_status(
    value: object, *, field: str = "ingestion_run_status"
) -> IngestionRunStatus:
    try:
        return _INGESTION_RUN_STATUS_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise _literal_error(field, value, INGESTION_RUN_STATUS_VALUES) from exc


__all__ = [
    "EVIDENCE_KIND_VALUES",
    "INGESTION_MODE_VALUES",
    "INGESTION_RUN_STATUS_VALUES",
    "LINK_RELATION_VALUES",
    "MEMORY_CONFIDENCE_VALUES",
    "MEMORY_INGEST_SOURCE_VALUES",
    "MEMORY_ORIGIN_VALUES",
    "MEMORY_RECORD_TYPE_VALUES",
    "MEMORY_STATUS_VALUES",
    "SUBJECT_KIND_VALUES",
    "SUBJECT_RELATION_VALUES",
    "EvidenceKind",
    "IngestionMode",
    "IngestionRunStatus",
    "LinkRelation",
    "MemoryConfidence",
    "MemoryIngestSource",
    "MemoryOrigin",
    "MemoryRecordType",
    "MemoryStatus",
    "SubjectKind",
    "SubjectRelation",
    "validate_evidence_kind",
    "validate_ingestion_mode",
    "validate_ingestion_run_status",
    "validate_link_relation",
    "validate_memory_confidence",
    "validate_memory_ingest_source",
    "validate_memory_origin",
    "validate_memory_record_type",
    "validate_memory_status",
    "validate_subject_kind",
    "validate_subject_relation",
]
