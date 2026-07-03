# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated, Literal

import orjson
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..contracts import ENGINEERING_MEMORY_SCHEMA_VERSION
from ..utils.json_io import json_text
from .enums import (
    EvidenceKind,
    IngestionMode,
    IngestionRunStatus,
    LinkRelation,
    MemoryConfidence,
    MemoryIngestSource,
    MemoryOrigin,
    MemoryRecordType,
    MemoryStatus,
    SubjectKind,
    SubjectRelation,
)
from .identity import make_identity_key

UpsertAction = Literal["created", "updated", "unchanged", "skipped"]
NonEmptyStr = Annotated[str, Field(min_length=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]


def generate_memory_id(*, prefix: str = "mem") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


@dataclass(frozen=True, slots=True)
class MemoryProject:
    id: str
    root: str
    git_remote: str | None
    git_branch: str | None
    git_head: str | None
    python_tag: str | None
    created_at_utc: str
    updated_at_utc: str


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    id: str
    project_id: str
    identity_key: str
    type: MemoryRecordType
    status: MemoryStatus
    confidence: MemoryConfidence
    origin: MemoryOrigin
    ingest_source: MemoryIngestSource
    statement: str
    summary: str | None
    payload: dict[str, object] | None
    created_at_utc: str
    updated_at_utc: str
    last_verified_at_utc: str | None
    expires_at_utc: str | None
    created_by: str
    verified_by: str | None
    approved_by: str | None
    approved_at_utc: str | None
    report_digest: str | None
    code_fingerprint: str | None
    stale_reason: str | None
    created_on_branch: str | None
    created_at_commit: str | None
    verified_on_branch: str | None
    verified_at_commit: str | None
    schema_version: str = ENGINEERING_MEMORY_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class MemorySubject:
    id: str
    memory_id: str
    subject_kind: SubjectKind
    subject_key: str
    relation: SubjectRelation = "about"


@dataclass(frozen=True, slots=True)
class MemoryEvidence:
    id: str
    memory_id: str
    evidence_kind: EvidenceKind
    ref: str
    locator: str | None
    quote: str | None
    digest: str | None
    created_at_utc: str


@dataclass(frozen=True, slots=True)
class MemoryLink:
    id: str
    project_id: str
    from_memory_id: str
    to_memory_id: str
    relation: LinkRelation
    created_by: str
    created_at_utc: str


@dataclass(frozen=True, slots=True)
class IngestionRun:
    id: str
    project_id: str
    mode: IngestionMode
    started_at_utc: str
    finished_at_utc: str | None
    status: IngestionRunStatus
    analysis_fingerprint: str | None
    report_digest: str | None
    branch: str | None
    commit: str | None
    records_created: int = 0
    records_updated: int = 0
    records_marked_stale: int = 0
    candidates_created: int = 0
    contradictions_found: int = 0
    message: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryRevision:
    id: str
    memory_id: str
    revision_number: int
    previous_statement: str | None
    new_statement: str
    previous_payload: dict[str, object] | None
    new_payload: dict[str, object] | None
    reason: str | None
    changed_by: str
    changed_at_utc: str
    branch: str | None
    commit: str | None


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    project_id: str
    types: tuple[MemoryRecordType, ...] = ()
    statuses: tuple[MemoryStatus, ...] = ()
    subject_kind: SubjectKind | None = None
    subject_key: str | None = None
    subject_key_prefix: str | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, slots=True)
class UpsertResult:
    action: UpsertAction
    record_id: str
    revision_written: bool = False


class _StrictMemoryInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class _MemoryProjectInput(_StrictMemoryInput):
    id: NonEmptyStr
    root: NonEmptyStr
    git_remote: str | None
    git_branch: str | None
    git_head: str | None
    python_tag: str | None
    created_at_utc: NonEmptyStr
    updated_at_utc: NonEmptyStr


class _MemoryRecordInput(_StrictMemoryInput):
    id: NonEmptyStr
    project_id: NonEmptyStr
    identity_key: NonEmptyStr
    type: MemoryRecordType
    status: MemoryStatus
    confidence: MemoryConfidence
    origin: MemoryOrigin
    ingest_source: MemoryIngestSource
    statement: NonEmptyStr
    summary: str | None
    payload: dict[str, object] | None
    created_at_utc: NonEmptyStr
    updated_at_utc: NonEmptyStr
    last_verified_at_utc: str | None
    expires_at_utc: str | None
    created_by: NonEmptyStr
    verified_by: str | None
    approved_by: str | None
    approved_at_utc: str | None
    report_digest: str | None
    code_fingerprint: str | None
    stale_reason: str | None
    created_on_branch: str | None
    created_at_commit: str | None
    verified_on_branch: str | None
    verified_at_commit: str | None
    schema_version: NonEmptyStr

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != ENGINEERING_MEMORY_SCHEMA_VERSION:
            raise ValueError(
                "schema_version must match ENGINEERING_MEMORY_SCHEMA_VERSION"
            )
        return value


class _MemorySubjectInput(_StrictMemoryInput):
    id: NonEmptyStr
    memory_id: NonEmptyStr
    subject_kind: SubjectKind
    subject_key: NonEmptyStr
    relation: SubjectRelation


class _MemoryEvidenceInput(_StrictMemoryInput):
    id: NonEmptyStr
    memory_id: NonEmptyStr
    evidence_kind: EvidenceKind
    ref: NonEmptyStr
    locator: str | None
    quote: str | None
    digest: str | None
    created_at_utc: NonEmptyStr


class _MemoryLinkInput(_StrictMemoryInput):
    id: NonEmptyStr
    project_id: NonEmptyStr
    from_memory_id: NonEmptyStr
    to_memory_id: NonEmptyStr
    relation: LinkRelation
    created_by: NonEmptyStr
    created_at_utc: NonEmptyStr


class _IngestionRunInput(_StrictMemoryInput):
    id: NonEmptyStr
    project_id: NonEmptyStr
    mode: IngestionMode
    started_at_utc: NonEmptyStr
    finished_at_utc: str | None
    status: IngestionRunStatus
    analysis_fingerprint: str | None
    report_digest: str | None
    branch: str | None
    commit: str | None
    records_created: NonNegativeInt
    records_updated: NonNegativeInt
    records_marked_stale: NonNegativeInt
    candidates_created: NonNegativeInt
    contradictions_found: NonNegativeInt
    message: str | None


class _MemoryRevisionInput(_StrictMemoryInput):
    id: NonEmptyStr
    memory_id: NonEmptyStr
    revision_number: PositiveInt
    previous_statement: str | None
    new_statement: NonEmptyStr
    previous_payload: dict[str, object] | None
    new_payload: dict[str, object] | None
    reason: str | None
    changed_by: NonEmptyStr
    changed_at_utc: NonEmptyStr
    branch: str | None
    commit: str | None


def _error_location(error: Mapping[str, object]) -> str:
    location = error.get("loc")
    if not isinstance(location, tuple) or not location:
        return "<root>"
    return ".".join(str(part) for part in location)


def _raise_validation_error(entity: str, exc: ValidationError) -> None:
    first = exc.errors()[0]
    location = _error_location(first)
    message = first.get("msg", "invalid input")
    raise ValueError(
        f"Invalid Engineering Memory {entity}: {location}: {message}"
    ) from exc


def _validate_input(
    model: type[_StrictMemoryInput],
    payload: Mapping[str, object],
    *,
    entity: str,
) -> None:
    try:
        model.model_validate(payload)
    except ValidationError as exc:
        _raise_validation_error(entity, exc)


def validate_memory_project(project: MemoryProject) -> MemoryProject:
    _validate_input(
        _MemoryProjectInput,
        {
            "id": project.id,
            "root": project.root,
            "git_remote": project.git_remote,
            "git_branch": project.git_branch,
            "git_head": project.git_head,
            "python_tag": project.python_tag,
            "created_at_utc": project.created_at_utc,
            "updated_at_utc": project.updated_at_utc,
        },
        entity="project",
    )
    return project


def validate_memory_record(record: MemoryRecord) -> MemoryRecord:
    _validate_input(
        _MemoryRecordInput,
        {
            "id": record.id,
            "project_id": record.project_id,
            "identity_key": record.identity_key,
            "type": record.type,
            "status": record.status,
            "confidence": record.confidence,
            "origin": record.origin,
            "ingest_source": record.ingest_source,
            "statement": record.statement,
            "summary": record.summary,
            "payload": record.payload,
            "created_at_utc": record.created_at_utc,
            "updated_at_utc": record.updated_at_utc,
            "last_verified_at_utc": record.last_verified_at_utc,
            "expires_at_utc": record.expires_at_utc,
            "created_by": record.created_by,
            "verified_by": record.verified_by,
            "approved_by": record.approved_by,
            "approved_at_utc": record.approved_at_utc,
            "report_digest": record.report_digest,
            "code_fingerprint": record.code_fingerprint,
            "stale_reason": record.stale_reason,
            "created_on_branch": record.created_on_branch,
            "created_at_commit": record.created_at_commit,
            "verified_on_branch": record.verified_on_branch,
            "verified_at_commit": record.verified_at_commit,
            "schema_version": record.schema_version,
        },
        entity="record",
    )
    return record


def validate_memory_subject(subject: MemorySubject) -> MemorySubject:
    _validate_input(
        _MemorySubjectInput,
        {
            "id": subject.id,
            "memory_id": subject.memory_id,
            "subject_kind": subject.subject_kind,
            "subject_key": subject.subject_key,
            "relation": subject.relation,
        },
        entity="subject",
    )
    return subject


def validate_memory_evidence(evidence: MemoryEvidence) -> MemoryEvidence:
    _validate_input(
        _MemoryEvidenceInput,
        {
            "id": evidence.id,
            "memory_id": evidence.memory_id,
            "evidence_kind": evidence.evidence_kind,
            "ref": evidence.ref,
            "locator": evidence.locator,
            "quote": evidence.quote,
            "digest": evidence.digest,
            "created_at_utc": evidence.created_at_utc,
        },
        entity="evidence",
    )
    return evidence


def validate_memory_link(link: MemoryLink) -> MemoryLink:
    _validate_input(
        _MemoryLinkInput,
        {
            "id": link.id,
            "project_id": link.project_id,
            "from_memory_id": link.from_memory_id,
            "to_memory_id": link.to_memory_id,
            "relation": link.relation,
            "created_by": link.created_by,
            "created_at_utc": link.created_at_utc,
        },
        entity="link",
    )
    return link


def validate_ingestion_run(run: IngestionRun) -> IngestionRun:
    _validate_input(
        _IngestionRunInput,
        {
            "id": run.id,
            "project_id": run.project_id,
            "mode": run.mode,
            "started_at_utc": run.started_at_utc,
            "finished_at_utc": run.finished_at_utc,
            "status": run.status,
            "analysis_fingerprint": run.analysis_fingerprint,
            "report_digest": run.report_digest,
            "branch": run.branch,
            "commit": run.commit,
            "records_created": run.records_created,
            "records_updated": run.records_updated,
            "records_marked_stale": run.records_marked_stale,
            "candidates_created": run.candidates_created,
            "contradictions_found": run.contradictions_found,
            "message": run.message,
        },
        entity="ingestion_run",
    )
    return run


def validate_memory_revision(revision: MemoryRevision) -> MemoryRevision:
    _validate_input(
        _MemoryRevisionInput,
        {
            "id": revision.id,
            "memory_id": revision.memory_id,
            "revision_number": revision.revision_number,
            "previous_statement": revision.previous_statement,
            "new_statement": revision.new_statement,
            "previous_payload": revision.previous_payload,
            "new_payload": revision.new_payload,
            "reason": revision.reason,
            "changed_by": revision.changed_by,
            "changed_at_utc": revision.changed_at_utc,
            "branch": revision.branch,
            "commit": revision.commit,
        },
        entity="revision",
    )
    return revision


@dataclass
class RecordBatch:
    records: list[MemoryRecord] = field(default_factory=list)
    subjects: list[MemorySubject] = field(default_factory=list)
    evidence: list[MemoryEvidence] = field(default_factory=list)
    links: list[MemoryLink] = field(default_factory=list)

    def __iadd__(self, other: RecordBatch) -> RecordBatch:
        self.records.extend(other.records)
        self.subjects.extend(other.subjects)
        self.evidence.extend(other.evidence)
        self.links.extend(other.links)
        return self


def payload_json_text(payload: dict[str, object] | None) -> str | None:
    if payload is None:
        return None
    return json_text(payload, sort_keys=True)


def parse_payload_json(text: str | None) -> dict[str, object] | None:
    # Read-side parser: a single damaged row must not crash the whole read path
    # (find_record, list_records, retrieval). Fail soft — a corrupt JSON payload
    # or a payload that does not decode to an object loads as None rather than
    # raising. Writes still serialize through payload_json_text.
    if text is None or not text.strip():
        return None
    try:
        loaded = orjson.loads(text)
    except orjson.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


__all__ = [
    "IngestionRun",
    "MemoryEvidence",
    "MemoryLink",
    "MemoryProject",
    "MemoryQuery",
    "MemoryRecord",
    "MemoryRevision",
    "MemorySubject",
    "RecordBatch",
    "UpsertAction",
    "UpsertResult",
    "generate_memory_id",
    "make_identity_key",
    "parse_payload_json",
    "payload_json_text",
    "validate_ingestion_run",
    "validate_memory_evidence",
    "validate_memory_link",
    "validate_memory_project",
    "validate_memory_record",
    "validate_memory_revision",
    "validate_memory_subject",
]
