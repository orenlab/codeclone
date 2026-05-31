# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Literal

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

__all__ = [
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
]
