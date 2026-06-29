# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Durable post-clear retrieval of typed audit-trail artifacts.

A single read-only surface for fetching artifacts exactly as they were persisted
in the audit trail — the review receipt (``get_review_receipt``), the full
forensic patch trail (``get_patch_trail``), and the start-time blast artifact
(``get_blast_artifact``). They survive ``auto_clear`` and are never re-derived
from current state. The class holds only the tool entry points; the shared
retrieval skeleton and the per-artifact render / envelope / lookup helpers are
module-level functions so the class stays cohesive.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from ...audit import (
    DEFAULT_AUDIT_PATH,
    AuditReadError,
    resolve_audit_path,
)
from ...audit.reader import (
    StoredBlastArtifact,
    StoredPatchTrail,
    StoredReviewReceipt,
    lookup_blast_artifact,
    lookup_patch_trail,
    lookup_review_receipt,
)
from ...config.memory import resolve_memory_config
from ...memory.project import resolve_memory_db_path, resolve_project_identity
from ...memory.schema import open_memory_db_readonly
from ...memory.trajectory.store import find_trajectory_patch_trails_for_lookup
from ._context_governance import (
    BLAST_ARTIFACT_RETRIEVAL_RESPONSE_PROJECTION_KIND,
    PATCH_TRAIL_RETRIEVAL_RESPONSE_PROJECTION_KIND,
    REVIEW_RECEIPT_RESPONSE_PROJECTION_KIND,
    attach_passive_context_governance,
)
from ._review_receipt import render_receipt_markdown
from ._session_shared import MCPServiceContractError

# Retrieval output formats for get_review_receipt: structured is the typed JSON
# receipt (canonical), markdown is the rendered view. "structured" avoids the
# ambiguity of "json" (the whole MCP response is already JSON transport).
_RECEIPT_RETRIEVAL_FORMATS = frozenset({"structured", "markdown"})
# get_patch_trail returns the full forensic trail; "structured" is the only
# output (the bounded summary already rides finish/the trajectory lane).
_PATCH_TRAIL_RETRIEVAL_FORMATS = frozenset({"structured"})
_BLAST_ARTIFACT_RETRIEVAL_FORMATS = frozenset({"structured"})


class _MCPSessionAuditArtifactMixin:
    """Read-only durable retrieval of typed audit-trail artifacts."""

    def get_blast_artifact(
        self,
        *,
        root: str,
        run_id: str | None = None,
        blast_artifact_id: str | None = None,
        projection_digest: str | None = None,
        format: str = "structured",
    ) -> dict[str, object]:
        """Return a durably stored start-time blast artifact.

        Read-only and exact: it returns the full blast projection exactly as
        persisted when ``start_controlled_change`` produced its slim summary,
        never re-derived from current state. At least one of ``run_id`` /
        ``blast_artifact_id`` / ``projection_digest`` is required; if multiple
        keys are given they must identify the same artifact. Durability is
        bounded by audit retention. Fail-closed statuses: ok, not_found,
        ambiguous, digest_mismatch, artifact_id_mismatch,
        malformed_stored_blast_artifact, unsupported_format.
        """
        return _blast_artifact_response(
            root=root,
            run_id=run_id,
            blast_artifact_id=blast_artifact_id,
            projection_digest=projection_digest,
            output_format=format,
        )

    def get_review_receipt(
        self,
        *,
        root: str,
        run_id: str | None = None,
        receipt_digest: str | None = None,
        format: str = "structured",
    ) -> dict[str, object]:
        """Return a durably stored review receipt from the audit trail.

        Read-only and exact: it returns the receipt exactly as persisted when it
        was created (survives ``auto_clear``), never re-derived from current
        state. At least one of ``run_id`` / ``receipt_digest`` is required; if both
        are given they must identify the same receipt. Durability is bounded by
        audit retention. Fail-closed statuses: ok, not_found, ambiguous,
        digest_mismatch, malformed_stored_receipt, unsupported_format.
        """
        return _durable_artifact_response(
            root=root,
            run_id=run_id,
            artifact_digest=receipt_digest,
            digest_key="receipt_digest",
            output_format=format,
            supported_formats=_RECEIPT_RETRIEVAL_FORMATS,
            require_message="get_review_receipt requires run_id or receipt_digest.",
            lookup=_review_receipt_lookup,
            render=lambda artifact, fmt: _render_stored_receipt(
                cast("StoredReviewReceipt", artifact), output_format=fmt
            ),
            envelope=_review_receipt_envelope,
        )

    def get_patch_trail(
        self,
        *,
        root: str,
        run_id: str | None = None,
        patch_trail_digest: str | None = None,
        format: str = "structured",
    ) -> dict[str, object]:
        """Return a durably stored patch trail from the audit trail.

        Read-only and exact: it returns the full forensic patch trail exactly as
        persisted when it was computed (survives ``auto_clear``), never re-derived
        from current state. At least one of ``run_id`` / ``patch_trail_digest`` is
        required; if both are given they must identify the same trail. Durability
        is bounded by audit retention. Fail-closed statuses: ok, not_found,
        ambiguous, digest_mismatch, malformed_stored_patch_trail,
        unsupported_format.
        """
        return _patch_trail_response(
            root=root,
            run_id=run_id,
            patch_trail_digest=patch_trail_digest,
            output_format=format,
        )


def _durable_artifact_response(
    *,
    root: str,
    run_id: str | None,
    artifact_digest: str | None,
    digest_key: str,
    output_format: str,
    supported_formats: frozenset[str],
    require_message: str,
    lookup: Callable[[Path, str | None, str | None], tuple[str, int, object | None]],
    render: Callable[[object, str], dict[str, object]],
    envelope: Callable[[dict[str, object]], dict[str, object]],
) -> dict[str, object]:
    """Shared skeleton for durable audit-artifact retrieval tools.

    ``lookup`` returns ``(status, match_count, artifact_or_None)``; ``render``
    projects a found artifact; ``envelope`` wraps the bare payload in the tool's
    observe-only governance envelope. Fail-closed and read-only.
    """
    if output_format not in supported_formats:
        return envelope(
            {
                "status": "unsupported_format",
                "requested_format": output_format,
                "supported_formats": sorted(supported_formats),
            }
        )
    if not run_id and not artifact_digest:
        raise MCPServiceContractError(require_message)
    audit_path = resolve_audit_path(root_path=Path(root), value=DEFAULT_AUDIT_PATH)
    try:
        status, match_count, artifact = lookup(audit_path, run_id, artifact_digest)
    except AuditReadError as exc:
        raise MCPServiceContractError(str(exc)) from exc
    if status != "ok" or artifact is None:
        return envelope(
            {
                "status": status,
                "run_id": run_id,
                digest_key: artifact_digest,
                "match_count": match_count,
                "source": "audit_event",
                "durable": True,
            }
        )
    return envelope(render(artifact, output_format))


def _patch_trail_response(
    *,
    root: str,
    run_id: str | None,
    patch_trail_digest: str | None,
    output_format: str,
) -> dict[str, object]:
    if output_format not in _PATCH_TRAIL_RETRIEVAL_FORMATS:
        return _patch_trail_envelope(
            {
                "status": "unsupported_format",
                "requested_format": output_format,
                "supported_formats": sorted(_PATCH_TRAIL_RETRIEVAL_FORMATS),
            }
        )
    if not run_id and not patch_trail_digest:
        raise MCPServiceContractError(
            "get_patch_trail requires run_id or patch_trail_digest."
        )
    root_path = Path(root)
    audit_path = resolve_audit_path(root_path=root_path, value=DEFAULT_AUDIT_PATH)
    try:
        status, match_count, artifact = _patch_trail_lookup(
            audit_path,
            run_id,
            patch_trail_digest,
        )
    except AuditReadError as exc:
        raise MCPServiceContractError(str(exc)) from exc
    if status == "ok" and artifact is not None:
        return _patch_trail_envelope(
            _render_stored_patch_trail(artifact, output_format=output_format)
        )

    fallback_status, fallback_count, fallback = _memory_patch_trail_lookup(
        root_path=root_path,
        run_id=run_id,
        patch_trail_digest=patch_trail_digest,
    )
    if fallback_status == "ok" and fallback is not None:
        return _patch_trail_envelope(
            _render_stored_patch_trail(
                fallback,
                output_format=output_format,
                source="memory_trajectory_patch_trail",
            )
        )
    if fallback_status != "not_found":
        status = fallback_status
        match_count = fallback_count
    return _patch_trail_envelope(
        {
            "status": status,
            "run_id": run_id,
            "patch_trail_digest": patch_trail_digest,
            "match_count": match_count,
            "source": "audit_event",
            "fallback_source": "memory_trajectory_patch_trail",
            "durable": True,
        }
    )


def _blast_artifact_response(
    *,
    root: str,
    run_id: str | None,
    blast_artifact_id: str | None,
    projection_digest: str | None,
    output_format: str,
) -> dict[str, object]:
    if output_format not in _BLAST_ARTIFACT_RETRIEVAL_FORMATS:
        return _blast_artifact_envelope(
            {
                "status": "unsupported_format",
                "requested_format": output_format,
                "supported_formats": sorted(_BLAST_ARTIFACT_RETRIEVAL_FORMATS),
            }
        )
    if not run_id and not blast_artifact_id and not projection_digest:
        raise MCPServiceContractError(
            "get_blast_artifact requires run_id, blast_artifact_id, "
            "or projection_digest."
        )
    audit_path = resolve_audit_path(root_path=Path(root), value=DEFAULT_AUDIT_PATH)
    try:
        result = lookup_blast_artifact(
            audit_path,
            run_id=run_id,
            blast_artifact_id=blast_artifact_id,
            projection_digest=projection_digest,
        )
    except AuditReadError as exc:
        raise MCPServiceContractError(str(exc)) from exc
    if result.status != "ok" or result.blast_artifact is None:
        return _blast_artifact_envelope(
            {
                "status": result.status,
                "run_id": run_id,
                "blast_artifact_id": blast_artifact_id,
                "projection_digest": projection_digest,
                "match_count": result.match_count,
                "source": "audit_event",
                "durable": True,
            }
        )
    return _blast_artifact_envelope(
        _render_stored_blast_artifact(
            result.blast_artifact,
            output_format=output_format,
        )
    )


def _render_stored_blast_artifact(
    artifact: StoredBlastArtifact,
    *,
    output_format: str,
) -> dict[str, object]:
    return {
        "status": "ok",
        "run_id": artifact.run_id,
        "blast_artifact_id": artifact.blast_artifact_id,
        "projection_digest": artifact.projection_digest,
        "detail_contract_version": artifact.detail_contract_version,
        "radius_level": artifact.radius_level,
        "created_at_utc": artifact.created_at_utc,
        "format": output_format,
        "source": "audit_event",
        "durable": True,
        "retention_bounded": True,
        "blast_radius": artifact.payload.get("blast_radius"),
    }


def _render_stored_receipt(
    receipt: StoredReviewReceipt,
    *,
    output_format: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "ok",
        "run_id": receipt.run_id,
        "receipt_digest": receipt.receipt_digest,
        "verdict": receipt.verdict,
        "receipt_version": receipt.receipt_version,
        "created_at_utc": receipt.created_at_utc,
        "source": "audit_event",
        "durable": True,
        "retention_bounded": True,
    }
    if output_format == "markdown":
        payload["format"] = "markdown"
        payload["content"] = _stored_receipt_markdown(receipt)
        return payload
    payload["format"] = "structured"
    payload["structured_receipt"] = receipt.payload.get("receipt")
    return payload


def _render_stored_patch_trail(
    patch_trail: StoredPatchTrail,
    *,
    output_format: str,
    source: str = "audit_event",
) -> dict[str, object]:
    return {
        "status": "ok",
        "run_id": patch_trail.run_id,
        "patch_trail_digest": patch_trail.patch_trail_digest,
        "scope_check_status": patch_trail.scope_check_status,
        "verification_status": patch_trail.verification_status,
        "schema_version": patch_trail.schema_version,
        "created_at_utc": patch_trail.created_at_utc,
        "format": output_format,
        "source": source,
        "durable": True,
        "retention_bounded": True,
        "patch_trail": patch_trail.payload,
    }


def _memory_patch_trail_lookup(
    *,
    root_path: Path,
    run_id: str | None,
    patch_trail_digest: str | None,
) -> tuple[str, int, StoredPatchTrail | None]:
    config = resolve_memory_config(root_path)
    db_path = resolve_memory_db_path(root_path, config)
    if not db_path.exists():
        return "not_found", 0, None
    project = resolve_project_identity(root_path)
    conn = open_memory_db_readonly(db_path)
    try:
        payloads, malformed = find_trajectory_patch_trails_for_lookup(
            conn,
            project_id=project.id,
            patch_trail_digest=patch_trail_digest,
            run_id=run_id,
        )
        if len(payloads) == 1:
            artifact = _stored_patch_trail_from_memory(payloads[0])
            if artifact is None:
                return "malformed_stored_patch_trail", 0, None
            return "ok", 1, artifact
        if len(payloads) > 1:
            return "ambiguous", len(payloads), None
        if patch_trail_digest is not None and run_id is not None:
            run_payloads, run_malformed = find_trajectory_patch_trails_for_lookup(
                conn,
                project_id=project.id,
                run_id=run_id,
            )
            if run_payloads:
                return "digest_mismatch", 0, None
            malformed += run_malformed
        if malformed:
            return "malformed_stored_patch_trail", 0, None
        return "not_found", 0, None
    finally:
        conn.close()


def _stored_patch_trail_from_memory(
    row: Mapping[str, object],
) -> StoredPatchTrail | None:
    payload = row.get("payload")
    if not isinstance(payload, Mapping):
        return None
    digest = str(row.get("patch_trail_digest", "")).strip()
    if not digest:
        return None
    return StoredPatchTrail(
        run_id=str(row.get("run_id", "")).strip() or None,
        patch_trail_digest=digest,
        scope_check_status=_str_or_none(payload.get("scope_check_status")),
        verification_status=_str_or_none(payload.get("verification_status")),
        schema_version=_str_or_none(payload.get("schema_version")),
        created_at_utc=str(row.get("created_at_utc", "")).strip(),
        payload=dict(payload),
    )


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _review_receipt_envelope(payload: dict[str, object]) -> dict[str, object]:
    return attach_passive_context_governance(
        payload,
        projection_kind=REVIEW_RECEIPT_RESPONSE_PROJECTION_KIND,
        response={
            "tool": "get_review_receipt",
            "budget_scope": "whole_response",
            "evidence_policy": "observe_only_no_omission",
            "retrieval": "durable_audit_event",
        },
    )


def _blast_artifact_envelope(payload: dict[str, object]) -> dict[str, object]:
    return attach_passive_context_governance(
        payload,
        projection_kind=BLAST_ARTIFACT_RETRIEVAL_RESPONSE_PROJECTION_KIND,
        response={
            "tool": "get_blast_artifact",
            "budget_scope": "whole_response",
            "evidence_policy": "observe_only_no_omission",
            "retrieval": "durable_audit_event",
        },
    )


def _patch_trail_envelope(payload: dict[str, object]) -> dict[str, object]:
    return attach_passive_context_governance(
        payload,
        projection_kind=PATCH_TRAIL_RETRIEVAL_RESPONSE_PROJECTION_KIND,
        response={
            "tool": "get_patch_trail",
            "budget_scope": "whole_response",
            "evidence_policy": "observe_only_no_omission",
            "retrieval": "durable_audit_event_or_memory_projection",
        },
    )


def _stored_receipt_markdown(receipt: StoredReviewReceipt) -> str:
    """Markdown for a stored receipt: the persisted historical content when
    present, else re-rendered from the canonical typed receipt."""
    content = receipt.payload.get("content")
    if isinstance(content, str) and content:
        return content
    typed = receipt.payload.get("receipt")
    if isinstance(typed, Mapping):
        return render_receipt_markdown(dict(typed))
    return ""


def _review_receipt_lookup(
    audit_path: Path, run_id: str | None, digest: str | None
) -> tuple[str, int, StoredReviewReceipt | None]:
    result = lookup_review_receipt(audit_path, run_id=run_id, receipt_digest=digest)
    return result.status, result.match_count, result.receipt


def _patch_trail_lookup(
    audit_path: Path, run_id: str | None, digest: str | None
) -> tuple[str, int, StoredPatchTrail | None]:
    result = lookup_patch_trail(audit_path, run_id=run_id, patch_trail_digest=digest)
    return result.status, result.match_count, result.patch_trail


__all__ = ["_MCPSessionAuditArtifactMixin"]
