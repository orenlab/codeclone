# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Durable post-clear retrieval of typed audit-trail artifacts.

A single read-only surface for fetching artifacts exactly as they were persisted
in the audit trail — the review receipt (``get_review_receipt``) and the full
forensic patch trail (``get_patch_trail``). Both survive ``auto_clear`` and are
never re-derived from current state. The class holds only the two tool entry
points; the shared retrieval skeleton and the per-artifact render / envelope /
lookup helpers are module-level functions so the class stays cohesive.
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
    StoredPatchTrail,
    StoredReviewReceipt,
    lookup_patch_trail,
    lookup_review_receipt,
)
from ._context_governance import (
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


class _MCPSessionAuditArtifactMixin:
    """Read-only durable retrieval of typed audit-trail artifacts."""

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
        return _durable_artifact_response(
            root=root,
            run_id=run_id,
            artifact_digest=patch_trail_digest,
            digest_key="patch_trail_digest",
            output_format=format,
            supported_formats=_PATCH_TRAIL_RETRIEVAL_FORMATS,
            require_message="get_patch_trail requires run_id or patch_trail_digest.",
            lookup=_patch_trail_lookup,
            render=lambda artifact, fmt: _render_stored_patch_trail(
                cast("StoredPatchTrail", artifact), output_format=fmt
            ),
            envelope=_patch_trail_envelope,
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
        "source": "audit_event",
        "durable": True,
        "retention_bounded": True,
        "patch_trail": patch_trail.payload,
    }


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


def _patch_trail_envelope(payload: dict[str, object]) -> dict[str, object]:
    return attach_passive_context_governance(
        payload,
        projection_kind=PATCH_TRAIL_RETRIEVAL_RESPONSE_PROJECTION_KIND,
        response={
            "tool": "get_patch_trail",
            "budget_scope": "whole_response",
            "evidence_policy": "observe_only_no_omission",
            "retrieval": "durable_audit_event",
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
