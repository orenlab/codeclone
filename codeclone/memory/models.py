# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Literal

from ..contracts import ENGINEERING_MEMORY_SCHEMA_VERSION
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
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def parse_payload_json(text: str | None) -> dict[str, object] | None:
    if text is None or not text.strip():
        return None
    loaded = json.loads(text)
    if not isinstance(loaded, dict):
        msg = "payload_json must decode to an object"
        raise TypeError(msg)
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
]
