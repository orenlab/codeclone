# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ...report.meta import current_report_timestamp_utc
from ..governance import record_candidate
from ..models import MemoryProject, generate_memory_id
from ..sqlite_store import SqliteEngineeringMemoryStore


def propose_memory_from_finish_payload(
    store: SqliteEngineeringMemoryStore,
    *,
    project: MemoryProject,
    finish_payload: Mapping[str, object],
    max_candidates: int,
) -> list[dict[str, object]]:
    """Extract draft memory candidates from a neutral finish payload."""
    candidates: list[dict[str, object]] = []
    scope_check = finish_payload.get("scope_check")
    if isinstance(scope_check, Mapping):
        declared = scope_check.get("declared_scope")
        if isinstance(declared, list):
            for path in declared[:10]:
                if not isinstance(path, str) or not path.endswith(".py"):
                    continue
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
                    )
                except Exception:
                    continue
                candidates.append(
                    {
                        "id": record.id,
                        "type": record.type,
                        "status": record.status,
                        "statement": record.statement,
                    }
                )

    claims_text = finish_payload.get("claims_text")
    if isinstance(claims_text, str) and claims_text.strip():
        try:
            record = record_candidate(
                store,
                project=project,
                record_type="change_rationale",
                statement=claims_text.strip()[:2000],
                created_by="finish_hook",
                max_candidates=max_candidates,
            )
            candidates.append(
                {
                    "id": record.id,
                    "type": record.type,
                    "status": record.status,
                    "statement": record.statement,
                }
            )
        except Exception:
            pass

    review_text = finish_payload.get("review_text")
    if isinstance(review_text, str) and review_text.strip():
        try:
            record = record_candidate(
                store,
                project=project,
                record_type="architecture_decision",
                statement=review_text.strip()[:2000],
                created_by="finish_hook",
                max_candidates=max_candidates,
            )
            candidates.append(
                {
                    "id": record.id,
                    "type": record.type,
                    "status": record.status,
                    "statement": record.statement,
                }
            )
        except Exception:
            pass

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
) -> list[dict[str, object]]:
    payload: dict[str, object] = {
        "scope_check": {"declared_scope": list(changed_paths)},
        "claims_text": claims_text,
        "review_text": review_text,
        "verification": {"verification_profile": verification_profile},
    }
    return propose_memory_from_finish_payload(
        store,
        project=project,
        finish_payload=payload,
        max_candidates=max_candidates,
    )


__all__ = [
    "propose_memory_from_changed_paths",
    "propose_memory_from_finish_payload",
]
