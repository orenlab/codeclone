# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from fnmatch import fnmatchcase
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._workspace_intent_store import WorkspaceIntentStore

from ._workspace_intent_contract import (
    DEFAULT_LEASE_SECONDS,
    DEFAULT_TTL_SECONDS,
    LEGACY_REGISTRY_VERSION,
    MAX_LEASE_SECONDS,
    MAX_TTL_SECONDS,
    MIN_LEASE_SECONDS,
    MIN_TTL_SECONDS,
    REGISTRY_VERSION,
    WorkspaceIntentRecord,
    compute_intent_digest,
    compute_scope_digest,
    verify_intent_integrity,
)
from ._workspace_intent_lifecycle import (
    WorkspaceIntentStatus,
    utc_now,
)
from ._workspace_intent_lifecycle import (
    is_lease_expired as _is_lease_expired,
)
from ._workspace_intent_lifecycle import (
    is_pid_alive as _is_pid_alive,
)
from ._workspace_intent_lifecycle import (
    lease_expiry as _lease_expiry,
)
from ._workspace_intent_lifecycle import (
    parse_utc as _parse_utc,
)
from ._workspace_intent_lifecycle import (
    ttl_expired as _ttl_expired,
)
from ._workspace_intent_paths import (
    intent_filename,
    intent_path,
    registry_dir,
    safe_remove_own_intent,
)
from ._workspace_intent_paths import (
    is_safe_intent_id as _is_safe_intent_id,
)
from ._workspace_intent_paths import (
    is_safe_intent_path as _is_safe_intent_path,
)
from ._workspace_intent_paths import (
    read_payload as _read_payload,
)
from ._workspace_intent_paths import (
    record_sort_key as _record_sort_key,
)
from ._workspace_intent_paths import (
    unlink as _unlink,
)


class IntentOwnership(str, Enum):
    OWN_ACTIVE = "own_active"
    OWN_STALE = "own_stale"
    FOREIGN_ACTIVE = "foreign_active"
    FOREIGN_STALE = "foreign_stale"
    RECOVERABLE = "recoverable"
    EXPIRED = "expired"


def is_orphaned(record: WorkspaceIntentRecord) -> bool:
    return not _is_pid_alive(record.agent_pid)


def stale_reason(record: WorkspaceIntentRecord) -> str | None:
    if record.status == WorkspaceIntentStatus.EXPIRED.value:
        return "expired"
    if record.status == WorkspaceIntentStatus.ORPHANED.value:
        return "orphaned"
    expires = _parse_utc(record.expires_at_utc)
    if expires is None or expires <= utc_now():
        return "expired"
    if is_orphaned(record):
        return "orphaned"
    if _is_lease_expired(record):
        return "lease_expired"
    return None


def is_stale(record: WorkspaceIntentRecord) -> bool:
    return stale_reason(record) is not None


def signed_payload(record: WorkspaceIntentRecord) -> dict[str, object]:
    from ._workspace_intent_models import signed_payload_dict_from_record

    return signed_payload_dict_from_record(record)


def workspace_intent_to_payload(
    record: WorkspaceIntentRecord,
    *,
    own_pid: int | None = None,
    own_start_epoch: int | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    current_time = now or utc_now()
    ownership = classify_intent_ownership(
        record,
        own_pid=own_pid or 0,
        own_start_epoch=own_start_epoch or 0,
        now=current_time,
    )
    payload = record.unsigned_payload()
    payload["ownership"] = ownership.value
    payload["is_own"] = ownership in {
        IntentOwnership.OWN_ACTIVE,
        IntentOwnership.OWN_STALE,
    }
    lease_expiry = _lease_expiry(record)
    if lease_expiry is not None:
        remaining = int((lease_expiry - current_time).total_seconds())
        payload["lease_expires_in_seconds"] = max(0, remaining)
    if ownership == IntentOwnership.FOREIGN_ACTIVE:
        payload["escalation_hint"] = (
            "This intent belongs to a live process with a valid lease. "
            "Do NOT kill the process. Ask the user to confirm whether "
            "this is an abandoned session or a parallel agent."
        )
    elif ownership == IntentOwnership.FOREIGN_STALE:
        payload["escalation_hint"] = (
            "This intent belongs to a live process whose lease has expired. "
            "The owner may still be working (context overflow, long edit, "
            "test run). Coordinate with the user before proceeding."
        )
    return payload


def classify_intent_ownership(
    record: WorkspaceIntentRecord,
    *,
    own_pid: int,
    own_start_epoch: int,
    now: datetime,
) -> IntentOwnership:
    expires = _parse_utc(record.expires_at_utc)
    if expires is None or expires <= now:
        return IntentOwnership.EXPIRED

    is_own = record.agent_pid == own_pid and record.agent_start_epoch == own_start_epoch
    lease_expiry = _lease_expiry(record)
    lease_valid = lease_expiry is not None and lease_expiry > now
    if is_own:
        return IntentOwnership.OWN_ACTIVE if lease_valid else IntentOwnership.OWN_STALE
    if _is_pid_alive(record.agent_pid):
        return (
            IntentOwnership.FOREIGN_ACTIVE
            if lease_valid
            else IntentOwnership.FOREIGN_STALE
        )
    return IntentOwnership.RECOVERABLE


def resolved_lease_seconds(value: object = None, *, env_value: object = None) -> int:
    return _resolved_seconds(
        value=value,
        env_value=env_value,
        default=DEFAULT_LEASE_SECONDS,
        minimum=MIN_LEASE_SECONDS,
        maximum=MAX_LEASE_SECONDS,
    )


def format_utc(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )


def resolved_ttl_seconds(value: object = None, *, env_value: object = None) -> int:
    return _resolved_seconds(
        value=value,
        env_value=env_value,
        default=DEFAULT_TTL_SECONDS,
        minimum=MIN_TTL_SECONDS,
        maximum=MAX_TTL_SECONDS,
    )


def _resolved_seconds(
    *,
    value: object,
    env_value: object,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = value if value is not None else env_value
    if raw is None:
        return default
    if isinstance(raw, bool):
        return default
    try:
        parsed = int(str(raw).strip())
    except ValueError:
        return default
    return min(maximum, max(minimum, parsed))


def expires_at(*, declared_at: datetime, ttl_seconds: int) -> str:
    return format_utc(declared_at + timedelta(seconds=ttl_seconds))


def validate_workspace_record(data: object) -> WorkspaceIntentRecord | None:
    from ._workspace_intent_models import parse_workspace_document, record_from_document

    document = parse_workspace_document(data)
    if document is None:
        return None
    return record_from_document(document)


def write_workspace_intent(*, root: Path, record: WorkspaceIntentRecord) -> bool:
    return bool(_intent_store(root).write(record))


def update_workspace_intent_status(
    *,
    root: Path,
    pid: int,
    start_epoch: int,
    intent_id: str,
    new_status: str,
    ttl_seconds: int | None = None,
) -> bool:
    record = find_workspace_intent(root=root, intent_id=intent_id)
    if record is None:
        return False
    if record.agent_pid != pid or record.agent_start_epoch != start_epoch:
        return False
    updated = _updated_record(record, new_status=new_status, ttl_seconds=ttl_seconds)
    return bool(_intent_store(root).write(updated))


def renew_workspace_intent_lease(
    *,
    root: Path,
    pid: int,
    start_epoch: int,
    intent_id: str,
    lease_seconds: int | None = None,
) -> bool:
    record = find_workspace_intent(root=root, intent_id=intent_id)
    if record is None:
        return False
    if record.agent_pid != pid or record.agent_start_epoch != start_epoch:
        return False
    now = utc_now()
    expires = _parse_utc(record.expires_at_utc)
    if expires is None or expires <= now:
        return False
    new_lease = (
        resolved_lease_seconds(lease_seconds)
        if lease_seconds is not None
        else record.lease_seconds
    )
    updated = replace(
        record, lease_renewed_at_utc=format_utc(now), lease_seconds=new_lease
    )
    return bool(_intent_store(root).write(updated))


def remove_workspace_intent(
    *,
    root: Path,
    pid: int,
    start_epoch: int,
    intent_id: str,
) -> bool:
    """Remove a workspace intent file with path-containment safety.

    Delegates to :func:`safe_remove_own_intent` which validates that the
    constructed path resolves inside the registry directory, rejects
    symlink indirection, and checks filename structure before unlinking.
    """
    return bool(
        _intent_store(root).remove(
            pid=pid,
            start_epoch=start_epoch,
            intent_id=intent_id,
        )
    )


def remove_workspace_record(*, root: Path, record: WorkspaceIntentRecord) -> bool:
    return remove_workspace_intent(
        root=root,
        pid=record.agent_pid,
        start_epoch=record.agent_start_epoch,
        intent_id=record.intent_id,
    )


def list_workspace_intents(
    *,
    root: Path,
    exclude_stale: bool = True,
) -> tuple[WorkspaceIntentRecord, ...]:
    records = [
        record
        for record in _intent_store(root).list_records()
        if not exclude_stale or stale_reason(record) is None
    ]
    return tuple(sorted(records, key=_record_sort_key))


def find_workspace_intent(
    *,
    root: Path,
    intent_id: str,
) -> WorkspaceIntentRecord | None:
    return _intent_store(root).find(intent_id)


def workspace_status_counts(*, root: Path) -> dict[str, int]:
    records = list(_intent_store(root).list_records())
    stale_records = [record for record in records if stale_reason(record) is not None]
    return {
        "stale_count": len(stale_records),
        "orphaned_count": sum(
            1 for record in records if not _is_pid_alive(record.agent_pid)
        ),
        "total_agents": len({record.agent_pid for record in records}),
    }


_CONFLICT_OWNERSHIP: frozenset[IntentOwnership] = frozenset(
    {
        IntentOwnership.FOREIGN_ACTIVE,
        IntentOwnership.FOREIGN_STALE,
    }
)

_CONFLICT_SEVERITY: dict[IntentOwnership, str] = {
    IntentOwnership.FOREIGN_ACTIVE: "active",
    IntentOwnership.FOREIGN_STALE: "stale",
}

_CONFLICT_ACTION: dict[IntentOwnership, str] = {
    IntentOwnership.FOREIGN_ACTIVE: "stop_and_coordinate",
    IntentOwnership.FOREIGN_STALE: "coordinate_or_recover",
}


def detect_conflicts(
    *,
    new_scope: Mapping[str, object],
    existing: Sequence[WorkspaceIntentRecord],
    own_pid: int,
    own_start_epoch: int,
) -> list[dict[str, object]]:
    conflicts, _relations = _detect_scope_state(
        new_scope=new_scope,
        existing=existing,
        own_pid=own_pid,
        own_start_epoch=own_start_epoch,
    )
    return conflicts


def detect_workspace_relations(
    *,
    new_scope: Mapping[str, object],
    existing: Sequence[WorkspaceIntentRecord],
    own_pid: int,
    own_start_epoch: int,
) -> list[dict[str, object]]:
    _conflicts, relations = _detect_scope_state(
        new_scope=new_scope,
        existing=existing,
        own_pid=own_pid,
        own_start_epoch=own_start_epoch,
    )
    return relations


def _detect_scope_state(
    *,
    new_scope: Mapping[str, object],
    existing: Sequence[WorkspaceIntentRecord],
    own_pid: int,
    own_start_epoch: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    new_allowed, new_related, new_forbidden = _scope_all_sets(new_scope)
    conflicts: list[dict[str, object]] = []
    relations: list[dict[str, object]] = []
    now = utc_now()
    for record in existing:
        ownership = classify_intent_ownership(
            record,
            own_pid=own_pid,
            own_start_epoch=own_start_epoch,
            now=now,
        )
        if (
            record.status == WorkspaceIntentStatus.QUEUED.value
            or ownership not in _CONFLICT_OWNERSHIP
        ):
            continue
        existing_allowed, existing_related, existing_forbidden = _scope_all_sets(
            record.scope
        )
        hard_overlap = tuple(sorted(new_allowed.intersection(existing_allowed)))
        soft_overlap = tuple(
            sorted(
                new_allowed.intersection(existing_related).union(
                    new_related.intersection(existing_allowed)
                )
            )
        )
        if hard_overlap or soft_overlap:
            conflict = _edit_overlap_payload(
                record=record,
                ownership=ownership,
                hard_overlap=hard_overlap,
                soft_overlap=soft_overlap,
            )
            conflicts.append(conflict)
            relations.append(
                {
                    **conflict,
                    "relation": "edit_overlap",
                    "message": "Foreign agent has overlapping editable scope.",
                }
            )
            continue
        foreign_excludes = _forbidden_matches(
            files=new_allowed,
            patterns=existing_forbidden,
        )
        if foreign_excludes:
            relations.append(
                _forbidden_relation_payload(
                    record=record,
                    ownership=ownership,
                    relation="foreign_excludes_target",
                    matching_patterns=foreign_excludes,
                    message=(
                        "Foreign agent explicitly excludes files in current scope."
                    ),
                )
            )
            continue
        target_excludes = _forbidden_matches(
            files=existing_allowed,
            patterns=new_forbidden,
        )
        if target_excludes:
            relations.append(
                _forbidden_relation_payload(
                    record=record,
                    ownership=ownership,
                    relation="target_excludes_foreign",
                    matching_patterns=target_excludes,
                    message=(
                        "Current scope explicitly excludes files in foreign scope."
                    ),
                )
            )
    return (
        sorted(conflicts, key=_scope_state_sort_key),
        sorted(relations, key=_scope_state_sort_key),
    )


def _edit_overlap_payload(
    *,
    record: WorkspaceIntentRecord,
    ownership: IntentOwnership,
    hard_overlap: Sequence[str],
    soft_overlap: Sequence[str],
) -> dict[str, object]:
    return {
        "intent_id": record.intent_id,
        "agent_pid": record.agent_pid,
        "agent_start_epoch": record.agent_start_epoch,
        "agent_label": record.agent_label,
        "intent": record.intent,
        "ownership": ownership.value,
        "severity": _CONFLICT_SEVERITY[ownership],
        "recommended_action": _CONFLICT_ACTION[ownership],
        "overlap_type": _overlap_type(
            hard=bool(hard_overlap),
            soft=bool(soft_overlap),
        ),
        "hard_overlap": list(hard_overlap),
        "soft_overlap": list(soft_overlap),
        "declared_at_utc": record.declared_at_utc,
        "expires_at_utc": record.expires_at_utc,
    }


def _forbidden_relation_payload(
    *,
    record: WorkspaceIntentRecord,
    ownership: IntentOwnership,
    relation: str,
    matching_patterns: Sequence[str],
    message: str,
) -> dict[str, object]:
    return {
        "intent_id": record.intent_id,
        "agent_pid": record.agent_pid,
        "agent_start_epoch": record.agent_start_epoch,
        "agent_label": record.agent_label,
        "intent": record.intent,
        "ownership": ownership.value,
        "relation": relation,
        "severity": "info",
        "matching_patterns": list(matching_patterns),
        "message": message,
        "declared_at_utc": record.declared_at_utc,
        "expires_at_utc": record.expires_at_utc,
    }


def _scope_state_sort_key(
    item: Mapping[str, object],
) -> tuple[str, str, str, str, int, str]:
    return (
        str(item.get("severity", "")),
        str(item.get("relation", "")),
        str(item.get("overlap_type", "")),
        str(item.get("agent_label", "")),
        _sort_agent_pid(item.get("agent_pid")),
        str(item.get("intent_id", "")),
    )


def _forbidden_matches(
    *,
    files: set[str],
    patterns: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                pattern
                for pattern in patterns
                for path in files
                if fnmatchcase(path, pattern)
            }
        )
    )


def gc_workspace(*, root: Path) -> dict[str, object]:
    return dict(_intent_store(root).gc())


def _updated_record(
    record: WorkspaceIntentRecord,
    *,
    new_status: str,
    ttl_seconds: int | None,
) -> WorkspaceIntentRecord:
    if ttl_seconds is None:
        return replace(record, status=new_status)
    declared_at = utc_now()
    return replace(
        record,
        declared_at_utc=format_utc(declared_at),
        expires_at_utc=expires_at(declared_at=declared_at, ttl_seconds=ttl_seconds),
        ttl_seconds=ttl_seconds,
        lease_renewed_at_utc=format_utc(declared_at),
        status=new_status,
    )


def _intent_store(root: Path) -> WorkspaceIntentStore:
    from ._workspace_intent_store import get_workspace_intent_store

    return get_workspace_intent_store(root)


def _valid_path_list(value: object, *, required: bool) -> list[str] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None
    paths: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        path = item.replace("\\", "/").strip()
        if not path:
            continue
        if Path(path).is_absolute() or ".." in Path(path).parts:
            return None
        paths.append(path.rstrip("/"))
    deduped = sorted(set(paths))
    if required and not deduped:
        return None
    return deduped


def _scope_all_sets(
    scope: Mapping[str, object],
) -> tuple[set[str], set[str], tuple[str, ...]]:
    allowed = set(_valid_path_list(scope.get("allowed_files"), required=False) or [])
    related = set(
        _valid_path_list(scope.get("allowed_related", ()), required=False) or []
    )
    forbidden = tuple(
        _valid_path_list(scope.get("forbidden", ()), required=False) or []
    )
    return allowed, related, forbidden


def _sort_agent_pid(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _overlap_type(*, hard: bool, soft: bool) -> str:
    if hard and soft:
        return "both"
    return "hard" if hard else "soft"


__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_TTL_SECONDS",
    "LEGACY_REGISTRY_VERSION",
    "MAX_LEASE_SECONDS",
    "MAX_TTL_SECONDS",
    "MIN_LEASE_SECONDS",
    "MIN_TTL_SECONDS",
    "REGISTRY_VERSION",
    "IntentOwnership",
    "WorkspaceIntentRecord",
    "WorkspaceIntentStatus",
    "_is_pid_alive",
    "_is_safe_intent_id",
    "_is_safe_intent_path",
    "_lease_expiry",
    "_parse_utc",
    "_read_payload",
    "_ttl_expired",
    "_unlink",
    "classify_intent_ownership",
    "compute_intent_digest",
    "compute_scope_digest",
    "detect_conflicts",
    "detect_workspace_relations",
    "expires_at",
    "find_workspace_intent",
    "format_utc",
    "gc_workspace",
    "intent_filename",
    "intent_path",
    "is_orphaned",
    "is_stale",
    "list_workspace_intents",
    "registry_dir",
    "remove_workspace_intent",
    "remove_workspace_record",
    "renew_workspace_intent_lease",
    "resolved_lease_seconds",
    "resolved_ttl_seconds",
    "safe_remove_own_intent",
    "signed_payload",
    "stale_reason",
    "update_workspace_intent_status",
    "utc_now",
    "validate_workspace_record",
    "verify_intent_integrity",
    "workspace_intent_to_payload",
    "workspace_status_counts",
    "write_workspace_intent",
]
