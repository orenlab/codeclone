# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import json
import re
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from ...contracts import (
    BASELINE_SCHEMA_VERSION,
    CACHE_VERSION,
    REPORT_SCHEMA_VERSION,
)
from ...report.meta import current_report_timestamp_utc
from ...utils.coerce import as_mapping, as_sequence
from ..display import format_document_link_statement
from ..identity import make_identity_key
from ..models import (
    MemoryEvidence,
    MemoryProject,
    MemoryRecord,
    MemorySubject,
    RecordBatch,
    generate_memory_id,
)
from ..project import GitProvenance, code_fingerprint_for_memory_subject

_CODE_PATH_RE = re.compile(r"`([a-zA-Z0-9_./-]+\.(?:py|md|json|toml|yml))`")
_MCP_TOOL_SCHEMAS = "tests/fixtures/contract_snapshots/mcp_tool_schemas.json"


def _new_metrics_batch(
    report_document: Mapping[str, object],
) -> tuple[RecordBatch, str, Mapping[str, object]]:
    return (
        RecordBatch(),
        current_report_timestamp_utc(),
        as_mapping(report_document.get("metrics")),
    )


def _inventory_module_key(file_item: object, seen: set[str]) -> str | None:
    file_path = str(file_item).replace("\\", "/").strip("/")
    if not file_path.endswith(".py"):
        return None
    module_path = file_path.removesuffix(".py").replace("/", ".")
    if module_path.endswith(".__init__"):
        module_path = module_path[: -len(".__init__")]
    if not module_path or module_path in seen:
        return None
    seen.add(module_path)
    return module_path


def _normalized_mapping_path(
    mapping: Mapping[str, object],
    *field_names: str,
) -> str | None:
    for field_name in field_names:
        raw = mapping.get(field_name)
        if raw is None:
            continue
        path = str(raw).strip()
        if path:
            return path
    return None


def _iter_mapping_paths(
    items: Sequence[object],
    *field_names: str,
) -> list[tuple[Mapping[str, object], str]]:
    pairs: list[tuple[Mapping[str, object], str]] = []
    for item in items:
        mapping = as_mapping(item)
        path = _normalized_mapping_path(mapping, *field_names)
        if path is not None:
            pairs.append((mapping, path))
    return pairs


def _append_path_risk_note(
    batch: RecordBatch,
    *,
    project: MemoryProject,
    root_path: Path,
    path: str,
    now: str,
    git: GitProvenance,
    report_digest: str | None,
    analysis_fingerprint: str | None,
    discriminator: str,
    statement: str,
    payload: Mapping[str, object],
    confidence: str,
) -> None:
    identity = make_identity_key(
        type="risk_note",
        subject_kind="path",
        subject_key=path,
        discriminator=discriminator,
    )
    record_id = generate_memory_id()
    batch.records.append(
        MemoryRecord(
            id=record_id,
            project_id=project.id,
            identity_key=identity,
            type="risk_note",
            status="active",
            confidence=confidence,  # type: ignore[arg-type]
            origin="system",
            ingest_source="analysis",
            statement=statement,
            summary=None,
            payload=dict(payload),
            created_at_utc=now,
            updated_at_utc=now,
            last_verified_at_utc=now,
            expires_at_utc=None,
            created_by="memory_init",
            verified_by=None,
            approved_by=None,
            approved_at_utc=None,
            report_digest=report_digest,
            code_fingerprint=code_fingerprint_for_memory_subject(
                root_path,
                subject_path=path,
                analysis_fingerprint=analysis_fingerprint,
            ),
            stale_reason=None,
            created_on_branch=git.branch,
            created_at_commit=git.head,
            verified_on_branch=git.branch,
            verified_at_commit=git.head,
        )
    )
    batch.subjects.append(
        MemorySubject(
            id=generate_memory_id(prefix="subj"),
            memory_id=record_id,
            subject_kind="path",
            subject_key=path,
            relation="about",
        )
    )


def extract_module_roles(
    *,
    project: MemoryProject,
    root_path: Path,
    report_document: Mapping[str, object],
    git: GitProvenance,
    report_digest: str | None,
    analysis_fingerprint: str | None,
) -> RecordBatch:
    batch = RecordBatch()
    inventory = as_mapping(report_document.get("inventory"))
    file_registry = as_mapping(inventory.get("file_registry"))
    file_items = as_sequence(file_registry.get("items"))
    now = current_report_timestamp_utc()
    seen: set[str] = set()
    for item in file_items:
        module_path = _inventory_module_key(item, seen)
        if module_path is None:
            continue
        identity = make_identity_key(
            type="module_role",
            subject_kind="module",
            subject_key=module_path,
            discriminator="inventory_module",
        )
        record_id = generate_memory_id()
        batch.records.append(
            MemoryRecord(
                id=record_id,
                project_id=project.id,
                identity_key=identity,
                type="module_role",
                status="active",
                confidence="supported",
                origin="system",
                ingest_source="analysis",
                statement=(
                    f"{module_path} is an analyzed Python module in project inventory."
                ),
                summary=None,
                payload={
                    "module_path": module_path,
                    "role_kind": "inventory_module",
                },
                created_at_utc=now,
                updated_at_utc=now,
                last_verified_at_utc=now,
                expires_at_utc=None,
                created_by="memory_init",
                verified_by=None,
                approved_by=None,
                approved_at_utc=None,
                report_digest=report_digest,
                code_fingerprint=code_fingerprint_for_memory_subject(
                    root_path,
                    module_key=module_path,
                    analysis_fingerprint=analysis_fingerprint,
                ),
                stale_reason=None,
                created_on_branch=git.branch,
                created_at_commit=git.head,
                verified_on_branch=git.branch,
                verified_at_commit=git.head,
            )
        )
        batch.subjects.append(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=record_id,
                subject_kind="module",
                subject_key=module_path,
                relation="about",
            )
        )
    return batch


def extract_contract_notes(
    *,
    project: MemoryProject,
    root_path: Path,
    git: GitProvenance,
    report_digest: str | None,
    analysis_fingerprint: str | None,
) -> RecordBatch:
    batch = RecordBatch()
    contracts_path = root_path / "codeclone" / "contracts" / "__init__.py"
    if not contracts_path.is_file():
        return batch
    now = current_report_timestamp_utc()
    constants = {
        "BASELINE_SCHEMA_VERSION": BASELINE_SCHEMA_VERSION,
        "CACHE_VERSION": CACHE_VERSION,
        "REPORT_SCHEMA_VERSION": REPORT_SCHEMA_VERSION,
    }
    for name, value in sorted(constants.items()):
        identity = make_identity_key(
            type="contract_note",
            subject_kind="contract",
            subject_key=name,
            discriminator="schema_constant",
        )
        record_id = generate_memory_id()
        batch.records.append(
            MemoryRecord(
                id=record_id,
                project_id=project.id,
                identity_key=identity,
                type="contract_note",
                status="active",
                confidence="verified",
                origin="system",
                ingest_source="contract",
                statement=f"{name} = {value!r} in codeclone/contracts/__init__.py.",
                summary=None,
                payload={
                    "contract_kind": "schema_constant",
                    "schema_version": value,
                    "constant_name": name,
                },
                created_at_utc=now,
                updated_at_utc=now,
                last_verified_at_utc=now,
                expires_at_utc=None,
                created_by="memory_init",
                verified_by=None,
                approved_by=None,
                approved_at_utc=None,
                report_digest=report_digest,
                code_fingerprint=analysis_fingerprint,
                stale_reason=None,
                created_on_branch=git.branch,
                created_at_commit=git.head,
                verified_on_branch=git.branch,
                verified_at_commit=git.head,
            )
        )
        batch.subjects.append(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=record_id,
                subject_kind="contract",
                subject_key=name,
                relation="about",
            )
        )
        batch.evidence.append(
            MemoryEvidence(
                id=generate_memory_id(prefix="evid"),
                memory_id=record_id,
                evidence_kind="code",
                ref=str(contracts_path.relative_to(root_path)),
                locator=f"{contracts_path.name}",
                quote=f"{name} = {value!r}",
                digest=None,
                created_at_utc=now,
            )
        )
    return batch


def extract_public_surfaces(
    *,
    project: MemoryProject,
    root_path: Path,
    report_document: Mapping[str, object],
    git: GitProvenance,
    report_digest: str | None,
    analysis_fingerprint: str | None,
) -> RecordBatch:
    batch, now, metrics = _new_metrics_batch(report_document)
    api_surface = as_mapping(metrics.get("api_surface"))
    for item in as_sequence(api_surface.get("items")):
        mapping = as_mapping(item)
        symbol = str(mapping.get("qualname") or mapping.get("name") or "").strip()
        file_path = str(mapping.get("file") or mapping.get("path") or "").strip()
        if not symbol:
            continue
        identity = make_identity_key(
            type="public_surface",
            subject_kind="symbol",
            subject_key=symbol,
            discriminator="api_surface",
        )
        record_id = generate_memory_id()
        batch.records.append(
            MemoryRecord(
                id=record_id,
                project_id=project.id,
                identity_key=identity,
                type="public_surface",
                status="active",
                confidence="supported",
                origin="system",
                ingest_source="analysis",
                statement=f"Public API surface includes symbol {symbol}.",
                summary=None,
                payload={
                    "surface_kind": "api_symbol",
                    "surface_name": symbol,
                    "file_path": file_path,
                },
                created_at_utc=now,
                updated_at_utc=now,
                last_verified_at_utc=now,
                expires_at_utc=None,
                created_by="memory_init",
                verified_by=None,
                approved_by=None,
                approved_at_utc=None,
                report_digest=report_digest,
                code_fingerprint=analysis_fingerprint,
                stale_reason=None,
                created_on_branch=git.branch,
                created_at_commit=git.head,
                verified_on_branch=git.branch,
                verified_at_commit=git.head,
            )
        )
        batch.subjects.append(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=record_id,
                subject_kind="symbol",
                subject_key=symbol,
                relation="exports",
            )
        )

    snapshot_path = root_path / _MCP_TOOL_SCHEMAS
    if snapshot_path.is_file():
        payload = json.loads(snapshot_path.read_text("utf-8"))
        tools_obj = payload.get("tools") if isinstance(payload, dict) else None
        if isinstance(tools_obj, dict):
            for tool_name in sorted(tools_obj.keys()):
                identity = make_identity_key(
                    type="public_surface",
                    subject_kind="mcp_tool",
                    subject_key=tool_name,
                    discriminator="mcp_tool_schema",
                )
                record_id = generate_memory_id()
                batch.records.append(
                    MemoryRecord(
                        id=record_id,
                        project_id=project.id,
                        identity_key=identity,
                        type="public_surface",
                        status="active",
                        confidence="verified",
                        origin="system",
                        ingest_source="snapshot",
                        statement=(
                            f"MCP tool {tool_name} is registered in contract snapshot."
                        ),
                        summary=None,
                        payload={
                            "surface_kind": "mcp_tool",
                            "surface_name": tool_name,
                        },
                        created_at_utc=now,
                        updated_at_utc=now,
                        last_verified_at_utc=now,
                        expires_at_utc=None,
                        created_by="memory_init",
                        verified_by=None,
                        approved_by=None,
                        approved_at_utc=None,
                        report_digest=report_digest,
                        code_fingerprint=analysis_fingerprint,
                        stale_reason=None,
                        created_on_branch=git.branch,
                        created_at_commit=git.head,
                        verified_on_branch=git.branch,
                        verified_at_commit=git.head,
                    )
                )
                batch.subjects.append(
                    MemorySubject(
                        id=generate_memory_id(prefix="subj"),
                        memory_id=record_id,
                        subject_kind="mcp_tool",
                        subject_key=tool_name,
                        relation="about",
                    )
                )
    return batch


def extract_risk_notes(
    *,
    project: MemoryProject,
    root_path: Path,
    report_document: Mapping[str, object],
    git: GitProvenance,
    report_digest: str | None,
    analysis_fingerprint: str | None,
) -> RecordBatch:
    batch, now, metrics = _new_metrics_batch(report_document)
    design = as_mapping(metrics.get("design"))
    complexity_items = as_sequence(design.get("complexity_hotspots"))
    for mapping, path in _iter_mapping_paths(complexity_items, "path", "file"):
        value = mapping.get("value")
        threshold = mapping.get("threshold")
        _append_path_risk_note(
            batch,
            project=project,
            root_path=root_path,
            path=path,
            now=now,
            git=git,
            report_digest=report_digest,
            analysis_fingerprint=analysis_fingerprint,
            discriminator="high_complexity",
            statement=(
                f"{path} has cyclomatic complexity {value} (threshold: {threshold})."
            ),
            payload={
                "risk_kind": "high_complexity",
                "metric_value": value,
                "threshold": threshold,
                "severity": "medium",
                "interpretation": "Structural complexity hotspot from analysis.",
            },
            confidence="verified",
        )

    security = as_mapping(metrics.get("security_surfaces"))
    for mapping, path in _iter_mapping_paths(
        as_sequence(security.get("items")),
        "path",
    ):
        category = str(mapping.get("category") or "security_surface").strip()
        _append_path_risk_note(
            batch,
            project=project,
            root_path=root_path,
            path=path,
            now=now,
            git=git,
            report_digest=report_digest,
            analysis_fingerprint=analysis_fingerprint,
            discriminator="security_surface",
            statement=(
                f"{path} is in the security surface inventory ({category}). "
                "Report-only inventory; not a vulnerability finding."
            ),
            payload={
                "risk_kind": "security_surface",
                "category": category,
                "interpretation": "report_only_inventory",
            },
            confidence="supported",
        )
    return batch


def extract_test_anchors(
    *,
    project: MemoryProject,
    root_path: Path,
    git: GitProvenance,
    report_digest: str | None,
    analysis_fingerprint: str | None,
) -> RecordBatch:
    batch = RecordBatch()
    now = current_report_timestamp_utc()
    tests_dir = root_path / "tests"
    if not tests_dir.is_dir():
        return batch
    for test_file in sorted(tests_dir.rglob("test_*.py")):
        rel = str(test_file.relative_to(root_path)).replace("\\", "/")
        try:
            tree = ast.parse(test_file.read_text("utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        symbols: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.isidentifier() or "." in node.value:
                    symbols.add(node.value.split(".")[0])
            elif isinstance(node, ast.Name):
                symbols.add(node.id)
        for symbol in sorted(s for s in symbols if len(s) > 3)[:5]:
            identity = make_identity_key(
                type="test_anchor",
                subject_kind="test",
                subject_key=rel,
                discriminator=f"symbol:{symbol}",
            )
            record_id = generate_memory_id()
            batch.records.append(
                MemoryRecord(
                    id=record_id,
                    project_id=project.id,
                    identity_key=identity,
                    type="test_anchor",
                    status="active",
                    confidence="supported",
                    origin="system",
                    ingest_source="test",
                    statement=(f"{rel} contains tests referencing symbol {symbol}."),
                    summary=None,
                    payload={
                        "test_file": rel,
                        "referenced_symbols": [symbol],
                        "reference_kind": "ast_name_or_string",
                    },
                    created_at_utc=now,
                    updated_at_utc=now,
                    last_verified_at_utc=now,
                    expires_at_utc=None,
                    created_by="memory_init",
                    verified_by=None,
                    approved_by=None,
                    approved_at_utc=None,
                    report_digest=report_digest,
                    code_fingerprint=code_fingerprint_for_memory_subject(
                        root_path,
                        subject_path=rel,
                        analysis_fingerprint=analysis_fingerprint,
                    ),
                    stale_reason=None,
                    created_on_branch=git.branch,
                    created_at_commit=git.head,
                    verified_on_branch=git.branch,
                    verified_at_commit=git.head,
                )
            )
            batch.subjects.append(
                MemorySubject(
                    id=generate_memory_id(prefix="subj"),
                    memory_id=record_id,
                    subject_kind="test",
                    subject_key=rel,
                    relation="tests",
                )
            )
    return batch


def _resolve_doc_anchor_path(
    anchored: str,
    *,
    root_path: Path,
    registry_paths: frozenset[str],
) -> str | None:
    normalized = anchored.replace("\\", "/").strip("/")
    if not normalized:
        return None
    if normalized in registry_paths:
        return normalized
    if (root_path / normalized).is_file():
        return normalized
    if "/" in normalized or "\\" in anchored:
        return None
    basename = PurePosixPath(normalized).name
    matches = sorted(
        path
        for path in registry_paths
        if path == basename or path.endswith(f"/{basename}")
    )
    if len(matches) == 1:
        return matches[0]
    return None


def extract_document_links(
    *,
    project: MemoryProject,
    root_path: Path,
    git: GitProvenance,
    report_digest: str | None,
    analysis_fingerprint: str | None,
    registry_paths: frozenset[str] | None = None,
) -> RecordBatch:
    batch = RecordBatch()
    now = current_report_timestamp_utc()
    registry = registry_paths or frozenset()
    doc_paths = [
        root_path / "docs" / "mcp.md",
        root_path / "AGENTS.md",
        root_path / "CLAUDE.md",
    ]
    for doc_path in doc_paths:
        if not doc_path.is_file():
            continue
        rel = str(doc_path.relative_to(root_path)).replace("\\", "/")
        text = doc_path.read_text("utf-8", errors="replace")
        heading = "root"
        for line in text.splitlines():
            if line.startswith("#"):
                heading = line.lstrip("#").strip() or heading
            for match in _CODE_PATH_RE.finditer(line):
                anchored = match.group(1)
                resolved_path = _resolve_doc_anchor_path(
                    anchored,
                    root_path=root_path,
                    registry_paths=registry,
                )
                identity = make_identity_key(
                    type="document_link",
                    subject_kind="doc",
                    subject_key=rel,
                    discriminator=f"path:{anchored}",
                )
                record_id = generate_memory_id()
                batch.records.append(
                    MemoryRecord(
                        id=record_id,
                        project_id=project.id,
                        identity_key=identity,
                        type="document_link",
                        status="active",
                        confidence="supported",
                        origin="system",
                        ingest_source="doc",
                        statement=format_document_link_statement(
                            doc_file=rel,
                            heading=heading,
                            anchored_path=anchored,
                        ),
                        summary=None,
                        payload={
                            "doc_file": rel,
                            "heading": heading,
                            "anchored_symbols": [anchored],
                            **(
                                {"resolved_path": resolved_path}
                                if resolved_path is not None
                                else {}
                            ),
                        },
                        created_at_utc=now,
                        updated_at_utc=now,
                        last_verified_at_utc=now,
                        expires_at_utc=None,
                        created_by="memory_init",
                        verified_by=None,
                        approved_by=None,
                        approved_at_utc=None,
                        report_digest=report_digest,
                        code_fingerprint=code_fingerprint_for_memory_subject(
                            root_path,
                            subject_path=rel,
                            analysis_fingerprint=analysis_fingerprint,
                        ),
                        stale_reason=None,
                        created_on_branch=git.branch,
                        created_at_commit=git.head,
                        verified_on_branch=git.branch,
                        verified_at_commit=git.head,
                    )
                )
                batch.subjects.append(
                    MemorySubject(
                        id=generate_memory_id(prefix="subj"),
                        memory_id=record_id,
                        subject_kind="doc",
                        subject_key=rel,
                        relation="documents",
                    )
                )
                anchored_path = resolved_path
                if anchored_path is not None and anchored_path.endswith(".py"):
                    batch.subjects.append(
                        MemorySubject(
                            id=generate_memory_id(prefix="subj"),
                            memory_id=record_id,
                            subject_kind="path",
                            subject_key=anchored_path,
                            relation="about",
                        )
                    )
    return batch


def extract_git_hotspots(
    *,
    project: MemoryProject,
    root_path: Path,
    git: GitProvenance,
    report_digest: str | None,
    analysis_fingerprint: str | None,
    period_days: int = 90,
    min_changes: int = 10,
) -> RecordBatch:
    batch = RecordBatch()
    if not git.available:
        return batch
    try:
        completed = subprocess.run(
            [
                "git",
                "log",
                f"--since={period_days}.days",
                "--name-only",
                "--pretty=format:",
            ],
            cwd=root_path,
            check=True,
            capture_output=True,
            text=True,
            timeout=30.0,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return batch
    counts = Counter(
        line.strip().replace("\\", "/")
        for line in completed.stdout.splitlines()
        if line.strip().endswith(".py")
    )
    now = current_report_timestamp_utc()
    for path, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        if count < min_changes:
            continue
        identity = make_identity_key(
            type="risk_note",
            subject_kind="path",
            subject_key=path,
            discriminator="change_hotspot",
        )
        record_id = generate_memory_id()
        batch.records.append(
            MemoryRecord(
                id=record_id,
                project_id=project.id,
                identity_key=identity,
                type="risk_note",
                status="active",
                confidence="verified",
                origin="system",
                ingest_source="git",
                statement=(
                    f"{path} changed {count} times in the last {period_days} days."
                ),
                summary=None,
                payload={
                    "risk_kind": "change_hotspot",
                    "change_count": count,
                    "period_days": period_days,
                },
                created_at_utc=now,
                updated_at_utc=now,
                last_verified_at_utc=now,
                expires_at_utc=None,
                created_by="memory_init",
                verified_by=None,
                approved_by=None,
                approved_at_utc=None,
                report_digest=report_digest,
                code_fingerprint=code_fingerprint_for_memory_subject(
                    root_path,
                    subject_path=path,
                    analysis_fingerprint=analysis_fingerprint,
                ),
                stale_reason=None,
                created_on_branch=git.branch,
                created_at_commit=git.head,
                verified_on_branch=git.branch,
                verified_at_commit=git.head,
            )
        )
        batch.subjects.append(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=record_id,
                subject_kind="path",
                subject_key=path,
                relation="about",
            )
        )
        if git.head:
            batch.evidence.append(
                MemoryEvidence(
                    id=generate_memory_id(prefix="evid"),
                    memory_id=record_id,
                    evidence_kind="git_commit",
                    ref=git.head,
                    locator=git.branch,
                    quote=f"change_count={count}",
                    digest=None,
                    created_at_utc=now,
                )
            )
    return batch


def extract_contradictions(
    *,
    project: MemoryProject,
    root_path: Path,
    git: GitProvenance,
    report_digest: str | None,
    analysis_fingerprint: str | None,
) -> RecordBatch:
    batch = RecordBatch()
    snapshot_path = root_path / _MCP_TOOL_SCHEMAS
    docs_path = root_path / "docs" / "mcp.md"
    if not snapshot_path.is_file() or not docs_path.is_file():
        return batch
    tools_payload = json.loads(snapshot_path.read_text("utf-8"))
    tools_obj = tools_payload.get("tools") if isinstance(tools_payload, dict) else None
    if not isinstance(tools_obj, dict):
        return batch
    actual_count = len(tools_obj)
    doc_text = docs_path.read_text("utf-8", errors="replace")
    claimed_counts = [
        int(match.group(1))
        for match in re.finditer(r"(\d+)\s+(?:MCP\s+)?tools?", doc_text, re.I)
    ]
    now = current_report_timestamp_utc()
    for claimed in sorted(set(claimed_counts)):
        if claimed == actual_count:
            continue
        identity = make_identity_key(
            type="contradiction_note",
            subject_kind="doc",
            subject_key=str(docs_path.relative_to(root_path)),
            discriminator=f"tool_count:{claimed}_vs_{actual_count}",
        )
        record_id = generate_memory_id()
        rel_doc = str(docs_path.relative_to(root_path)).replace("\\", "/")
        batch.records.append(
            MemoryRecord(
                id=record_id,
                project_id=project.id,
                identity_key=identity,
                type="contradiction_note",
                status="draft",
                confidence="supported",
                origin="system",
                ingest_source="doc",
                statement=(
                    f"{rel_doc} claims {claimed} MCP tools but contract snapshot "
                    f"registers {actual_count}."
                ),
                summary=None,
                payload={
                    "source_a": rel_doc,
                    "source_b": str(snapshot_path.relative_to(root_path)),
                    "claim_a": str(claimed),
                    "claim_b": str(actual_count),
                },
                created_at_utc=now,
                updated_at_utc=now,
                last_verified_at_utc=now,
                expires_at_utc=None,
                created_by="memory_init",
                verified_by=None,
                approved_by=None,
                approved_at_utc=None,
                report_digest=report_digest,
                code_fingerprint=analysis_fingerprint,
                stale_reason=None,
                created_on_branch=git.branch,
                created_at_commit=git.head,
                verified_on_branch=git.branch,
                verified_at_commit=git.head,
            )
        )
        batch.subjects.append(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=record_id,
                subject_kind="doc",
                subject_key=rel_doc,
                relation="about",
            )
        )
    return batch


def merge_batches(batches: Sequence[RecordBatch]) -> RecordBatch:
    merged = RecordBatch()
    for batch in batches:
        merged += batch
    return merged


__all__ = [
    "extract_contract_notes",
    "extract_contradictions",
    "extract_document_links",
    "extract_git_hotspots",
    "extract_module_roles",
    "extract_public_surfaces",
    "extract_risk_notes",
    "extract_test_anchors",
    "merge_batches",
]
