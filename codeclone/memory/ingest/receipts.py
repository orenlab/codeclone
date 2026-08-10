# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import suppress

from ...report.meta import current_report_timestamp_utc
from ..enums import EvidenceKind, MemoryRecordType, validate_memory_record_type
from ..governance import record_candidate
from ..models import MemoryEvidence, MemoryProject, generate_memory_id
from ..sqlite_store import SqliteEngineeringMemoryStore
from ..statement_markdown import (
    STATEMENT_FORMAT_PAYLOAD_KEY,
    resolve_statement_format,
)

# Key under which the neutral finish payload carries the attested identifiers of
# the finished change. The controller populates it from the finish result
# (receipt digest, patch-trail digest, commit sha, run id); the digest is the
# durable truth (reproducible via get_review_receipt / get_patch_trail), the
# human-readable text is only a locator/quote alongside it.
_ATTESTED_EVIDENCE_KEY = "attested_evidence"
# Durable identifiers that make an attested-evidence bundle worth writing. run_id
# and branch are context that rides ref/locator, never a standalone evidence row.
_DURABLE_IDENTIFIER_KEYS = ("receipt_digest", "patch_trail_digest", "commit")
_ATTESTED_IDENTIFIER_KEYS = (*_DURABLE_IDENTIFIER_KEYS, "run_id", "branch")

# One durable evidence row per identifier, driven by a single loop so the three
# rows share one construction path (no duplicated branches). Fields:
# (bundle_key, evidence_kind, ref_prefix, quote, value_is_digest). A commit is
# content-addressed by its sha, so the sha is the ref and there is no separate
# digest column — matching the existing git_commit evidence convention.
_ATTESTED_EVIDENCE_SPECS: tuple[
    tuple[str, EvidenceKind, str, str | None, bool], ...
] = (
    (
        "receipt_digest",
        "receipt",
        "receipt:",
        "review receipt for finished change",
        True,
    ),
    (
        "patch_trail_digest",
        "audit_event",
        "patch_trail:",
        "audit patch-trail for finished change",
        True,
    ),
    ("commit", "git_commit", "", None, False),
)


def _clean_identifier(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    return None


def _read_attested_evidence(
    finish_payload: Mapping[str, object],
) -> dict[str, str] | None:
    """Extract the attested-identifier bundle from the neutral finish payload.

    Returns ``None`` when no bundle is present or it carries no durable
    identifier, so pre-fix callers that pass no bundle keep their exact behavior
    (no evidence rows written).
    """
    raw = finish_payload.get(_ATTESTED_EVIDENCE_KEY)
    if not isinstance(raw, Mapping):
        return None
    bundle: dict[str, str] = {}
    for key in _ATTESTED_IDENTIFIER_KEYS:
        identifier = _clean_identifier(raw.get(key))
        if identifier is not None:
            bundle[key] = identifier
    if not any(key in bundle for key in _DURABLE_IDENTIFIER_KEYS):
        return None
    return bundle


def _attach_attested_evidence(
    store: SqliteEngineeringMemoryStore,
    *,
    memory_id: str,
    bundle: Mapping[str, str] | None,
) -> None:
    """Write the attested identifiers as durable ``memory_evidence`` rows.

    No-ops when ``bundle`` is ``None`` so callers stay branch-free. The digest is
    the truth: ``receipt_digest`` becomes an EvidenceKind ``receipt`` row,
    ``patch_trail_digest`` an ``audit_event`` row, and the ``commit`` sha a
    ``git_commit`` row (ref=sha, matching the existing git evidence convention).
    ``run_id`` rides the locator as context — it is an identifier, not a digest.
    This is the durable-artifact-ref shape a resolution's evidence consumes
    natively, not a throwaway prose stub.
    """
    if bundle is None:
        return
    now = current_report_timestamp_utc()
    run_id = bundle.get("run_id")
    branch = bundle.get("branch")
    rows: list[MemoryEvidence] = []
    for key, kind, ref_prefix, quote, value_is_digest in _ATTESTED_EVIDENCE_SPECS:
        value = bundle.get(key)
        if value is None:
            continue
        rows.append(
            MemoryEvidence(
                id=generate_memory_id(prefix="evid"),
                memory_id=memory_id,
                evidence_kind=kind,
                ref=f"{ref_prefix}{value}",
                locator=(branch or run_id) if key == "commit" else run_id,
                quote=quote,
                digest=value if value_is_digest else None,
                created_at_utc=now,
            )
        )
    if not rows:
        return
    for row in rows:
        store.write_evidence(row)
    store.commit()


def _try_append_text_candidate(
    store: SqliteEngineeringMemoryStore,
    *,
    project: MemoryProject,
    record_type: MemoryRecordType,
    text: object,
    subject_path: str | None,
    created_by: str,
    max_candidates: int,
    max_statement_chars: int,
) -> dict[str, object] | None:
    if not isinstance(text, str) or not text.strip() or not subject_path:
        return None
    try:
        canonical_type = validate_memory_record_type(record_type)
        record = record_candidate(
            store,
            project=project,
            record_type=canonical_type,
            statement=text.strip()[:max_statement_chars],
            subject_path=subject_path,
            created_by=created_by,
            max_candidates=max_candidates,
            max_statement_chars=max_statement_chars,
        )
    except Exception:
        # Best-effort draft proposal: a single failed candidate must not break
        # the finish flow. Count the drop as observability telemetry (no-op when
        # disabled) so silently skipped candidates stay visible. Never re-raises.
        with suppress(Exception):
            from ...observability import record_counter

            record_counter("memory.propose_candidate_dropped")
        return None
    summary: dict[str, object] = {
        "id": record.id,
        "type": record.type,
        "status": record.status,
        "statement": record.statement,
    }
    marker = resolve_statement_format(record.statement, record.payload)
    if marker is not None:
        summary[STATEMENT_FORMAT_PAYLOAD_KEY] = marker
    return summary


def propose_memory_from_finish_payload(
    store: SqliteEngineeringMemoryStore,
    *,
    project: MemoryProject,
    finish_payload: Mapping[str, object],
    max_candidates: int,
    max_statement_chars: int,
) -> list[dict[str, object]]:
    """Extract draft memory candidates from a neutral finish payload."""
    candidates: list[dict[str, object]] = []
    primary_subject_path: str | None = None
    attested = _read_attested_evidence(finish_payload)
    scope_check = finish_payload.get("scope_check")
    if isinstance(scope_check, Mapping):
        declared = scope_check.get("declared_scope")
        if isinstance(declared, list):
            for path in declared[:10]:
                if not isinstance(path, str) or not path.endswith(".py"):
                    continue
                if primary_subject_path is None:
                    primary_subject_path = path
                try:
                    record = record_candidate(
                        store,
                        project=project,
                        record_type="module_role",
                        statement=(
                            f"Patch touched scope includes {path}; "
                            "review module role after change."
                        ),
                        subject_path=path,
                        created_by="finish_hook",
                        max_candidates=max_candidates,
                        max_statement_chars=max_statement_chars,
                    )
                except Exception:
                    continue
                _attach_attested_evidence(store, memory_id=record.id, bundle=attested)
                summary: dict[str, object] = {
                    "id": record.id,
                    "type": record.type,
                    "status": record.status,
                    "statement": record.statement,
                }
                marker = resolve_statement_format(record.statement, record.payload)
                if marker is not None:
                    summary[STATEMENT_FORMAT_PAYLOAD_KEY] = marker
                candidates.append(summary)

    claims_text = finish_payload.get("claims_text")
    claims_candidate = _try_append_text_candidate(
        store,
        project=project,
        record_type="change_rationale",
        text=claims_text,
        subject_path=primary_subject_path,
        created_by="finish_hook",
        max_candidates=max_candidates,
        max_statement_chars=max_statement_chars,
    )
    if claims_candidate is not None:
        _attach_attested_evidence(
            store, memory_id=str(claims_candidate["id"]), bundle=attested
        )
        candidates.append(claims_candidate)

    review_text = finish_payload.get("review_text")
    review_candidate = _try_append_text_candidate(
        store,
        project=project,
        record_type="architecture_decision",
        text=review_text,
        subject_path=primary_subject_path,
        created_by="finish_hook",
        max_candidates=max_candidates,
        max_statement_chars=max_statement_chars,
    )
    if review_candidate is not None:
        _attach_attested_evidence(
            store, memory_id=str(review_candidate["id"]), bundle=attested
        )
        candidates.append(review_candidate)

    verification = finish_payload.get("verification")
    if isinstance(verification, Mapping):
        profile = verification.get("verification_profile")
        if isinstance(profile, str):
            now = current_report_timestamp_utc()
            candidates.append(
                {
                    "id": generate_memory_id(prefix="mem-proposal"),
                    "type": "contract_note",
                    "status": "draft",
                    "statement": (f"Patch verified under profile {profile} at {now}."),
                    "proposal_only": True,
                }
            )

    return candidates


def propose_memory_from_changed_paths(
    store: SqliteEngineeringMemoryStore,
    *,
    project: MemoryProject,
    changed_paths: Sequence[str],
    claims_text: str | None,
    review_text: str | None,
    verification_profile: str | None,
    max_candidates: int,
    max_statement_chars: int,
    attested_evidence: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    payload: dict[str, object] = {
        "scope_check": {"declared_scope": list(changed_paths)},
        "claims_text": claims_text,
        "review_text": review_text,
        "verification": {"verification_profile": verification_profile},
        _ATTESTED_EVIDENCE_KEY: attested_evidence,
    }
    return propose_memory_from_finish_payload(
        store,
        project=project,
        finish_payload=payload,
        max_candidates=max_candidates,
        max_statement_chars=max_statement_chars,
    )


__all__ = [
    "propose_memory_from_changed_paths",
    "propose_memory_from_finish_payload",
]
