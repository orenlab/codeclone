# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatchcase
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._workspace_intent_store import WorkspaceIntentStore

from ...contracts.legacy_scope import (
    CURRENT_GRAMMAR,
    HISTORICAL_PRODUCER_SPECIFIC,
    HISTORICAL_UNAMBIGUOUS,
    LEGACY_AMBIGUOUS,
    SCOPE_INTERPRETER_FIELD,
    AuditScopeEntry,
    LegacyScope,
    ScopeGeneration,
    ScopeInterpretation,
    ScopeRelation,
    audit_scope_payload,
    audit_scope_relation,
    read_audit_scope,
    read_audit_scope_entry,
    read_stored_scope_entry,
    scope_interpreter_from_record,
)
from ...contracts.scope_grammar import (
    overlapping_entries,
    read_scope_entry,
    render_scope_entry,
)
from ...workspace_intent.contract import (
    DEFAULT_LEASE_SECONDS,
    DEFAULT_TTL_SECONDS,
    LEGACY_REGISTRY_VERSION,
    MAX_LEASE_SECONDS,
    MAX_TTL_SECONDS,
    MIN_LEASE_SECONDS,
    MIN_TTL_SECONDS,
    REGISTRY_VERSION,
    BeforeExecutionWitness,
    WorkspaceDocumentRead,
    WorkspaceDocumentReadKind,
    WorkspaceIntentRecord,
    compute_intent_digest,
    compute_scope_digest,
    verify_intent_integrity,
)
from ...workspace_intent.lifecycle import (
    WORKSPACE_INTENT_LIFECYCLE_VALUES,
    PidLiveness,
    WorkspaceIntentLifecycle,
    WorkspaceIntentStatus,
    is_workspace_intent_lifecycle,
    lifecycle_for_verification_outcome,
    utc_now,
)
from ...workspace_intent.lifecycle import (
    lease_expiry as _lease_expiry,
)
from ...workspace_intent.lifecycle import (
    parse_utc as _parse_utc,
)
from ...workspace_intent.ownership import (
    IntentOwnership,
)
from ...workspace_intent.ownership import (
    classify_intent_ownership as _classify_intent_ownership,
)
from ...workspace_intent.ownership import (
    is_recovery_candidate as is_recovery_candidate,
)
from ...workspace_intent.paths import (
    intent_filename,
    intent_id_from_filename,
    intent_path,
    registry_dir,
)
from ...workspace_intent.paths import (
    is_safe_intent_id as _is_safe_intent_id,
)
from ...workspace_intent.paths import (
    is_safe_intent_path as _is_safe_intent_path,
)
from ...workspace_intent.paths import (
    unlink as _unlink,
)
from ._workspace_intent_paths import (
    read_payload as _read_payload,
)
from ._workspace_intent_paths import (
    safe_remove_own_intent as safe_remove_own_intent,
)
from ._workspace_intent_staleness import (
    stale_reason,
)
from ._workspace_intent_staleness import (
    ttl_expired as _ttl_expired,
)


def _is_pid_alive(pid: int) -> bool:
    return _pid_liveness(pid) == PidLiveness.ALIVE


def _pid_liveness(pid: int) -> PidLiveness:
    from . import _workspace_intent_pid as pid_mod

    return pid_mod.agent_pid_liveness(pid)


def _record_liveness(record: WorkspaceIntentRecord) -> PidLiveness:
    """Liveness of the recorded agent, not of the pid slot it once held."""

    from ...workspace_intent.lifecycle import agent_identity_liveness
    from . import _workspace_intent_pid as pid_mod

    return agent_identity_liveness(
        record,
        base=_pid_liveness(record.agent_pid),
        base_is_declared=pid_mod.agent_pid_liveness_is_declared(),
    )


def is_orphaned(record: WorkspaceIntentRecord) -> bool:
    return _record_liveness(record) == PidLiveness.DEAD


def is_stale(record: WorkspaceIntentRecord) -> bool:
    return stale_reason(record) is not None


def signed_payload(record: WorkspaceIntentRecord) -> dict[str, object]:
    from ...workspace_intent.models import signed_payload_dict_from_record

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
    # The forensic projection of an already-written scope. It rides beside the
    # raw scope, never instead of it: an audit reader that met a pre-grammar
    # entry used to get the total reader's literal answer, which reads as a
    # measured "outside this scope" while being a verdict today's grammar has
    # no standing to give about a record that predates it.
    payload["scope_audit"] = audit_scope_payload(
        record.scope,
        interpreter=scope_interpreter_from_record(payload),
    )
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
    return _classify_intent_ownership(
        record,
        own_pid=own_pid,
        own_start_epoch=own_start_epoch,
        now=now,
        pid_liveness=_pid_liveness,
        record_liveness=_record_liveness,
    )


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
    from ...workspace_intent.models import (
        parse_workspace_document,
        record_from_document,
    )

    document = parse_workspace_document(data)
    if document is None:
        return None
    return record_from_document(document)


def write_workspace_intent(*, root: Path, record: WorkspaceIntentRecord) -> bool:
    return bool(_intent_store(root).write(record))


def write_workspace_intent_with_existing(
    *,
    root: Path,
    record: WorkspaceIntentRecord,
) -> tuple[tuple[WorkspaceIntentRecord, ...], bool]:
    from ._workspace_intent_store import write_workspace_intent_with_existing as _write

    return _write(root=root, record=record)


def update_workspace_intent_status(
    *,
    root: Path,
    pid: int,
    start_epoch: int,
    intent_id: str,
    new_status: str,
    ttl_seconds: int | None = None,
) -> bool:
    """Move a row along the LIFECYCLE axis.

    The only writer that ever took a status word from its caller, and so the
    only one through which a verification verdict could reach the column that
    decides findability.  It now refuses one outright: callers holding a
    verdict must translate it with
    :func:`lifecycle_for_verification_outcome` and say what fate they mean.
    The refusal is raised rather than returned as ``False`` -- every caller
    here already ignores the boolean, and a lost write that looks like a lost
    race is how the incident stayed invisible.
    """

    from ._workspace_intent_store import registry_transaction

    if not is_workspace_intent_lifecycle(new_status):
        raise ValueError(
            "workspace intent status is a lifecycle, not a verification "
            f"verdict: {new_status!r} is not one of "
            f"{sorted(WORKSPACE_INTENT_LIFECYCLE_VALUES)}"
        )
    store = _intent_store(root)
    with registry_transaction(store):
        record = store.find_current_unlocked(intent_id)
        if record is None:
            return False
        if record.agent_pid != pid or record.agent_start_epoch != start_epoch:
            return False
        updated = _updated_record(
            record,
            new_status=new_status,
            ttl_seconds=ttl_seconds,
        )
        return bool(store.write_unlocked(updated))


def renew_workspace_intent_lease(
    *,
    root: Path,
    pid: int,
    start_epoch: int,
    intent_id: str,
    lease_seconds: int | None = None,
) -> bool:
    from ._workspace_intent_store import registry_transaction

    store = _intent_store(root)
    with registry_transaction(store):
        record = store.find_current_unlocked(intent_id)
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
        return bool(store.write_unlocked(updated))


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
    # No sort: the store owns queue order and a filter preserves it. This
    # facade passes the sequence through so that a store which got the order
    # wrong is visible here rather than silently repaired.
    return tuple(
        record
        for record in _intent_store(root).list_records()
        if not exclude_stale or stale_reason(record) is None
    )


def list_workspace_intent_records_raw(
    *,
    root: Path,
) -> tuple[WorkspaceIntentRecord, ...]:
    """Active registry rows without running lazy close."""
    return _intent_store(root).list_records_raw()


def list_workspace_intent_records_for_recovery(
    *,
    root: Path,
) -> tuple[WorkspaceIntentRecord, ...]:
    """Registry rows for recovery listing without lazy-close side effects."""
    return _intent_store(root).list_records_for_hygiene()


def find_workspace_intent(
    *,
    root: Path,
    intent_id: str,
    apply_lazy_close: bool = True,
) -> WorkspaceIntentRecord | None:
    store = _intent_store(root)
    if apply_lazy_close:
        return store.find(intent_id)
    return store.find_raw(intent_id)


def unreadable_workspace_intent_ids(*, root: Path) -> frozenset[str]:
    """Ids of stored rows this build cannot read and did not remove.

    The complement of :func:`find_workspace_intent` returning ``None``: absent
    and unreadable are different answers, and only this one distinguishes them.
    """

    from ._workspace_intent_store import (
        registry_transaction,
        unreadable_intent_ids,
    )

    store = _intent_store(root)
    with registry_transaction(store):
        return unreadable_intent_ids(store)


def read_workspace_intent(*, root: Path, intent_id: str) -> WorkspaceDocumentRead:
    """What is stored under this id: the record, nothing, or bytes beyond us.

    One typed answer where callers used to ask twice — ``find`` for the
    record, then a separate scan to decide whether ``None`` meant absent.  Two
    lookups holding one fact between them is how "not found" came to be said
    about a row that was sitting right there.

    Lazy close is deliberately not applied: a caller asking "is it gone, or is
    it merely beyond me?" should not have the act of asking change the answer.
    """

    found = find_workspace_intent(
        root=root,
        intent_id=intent_id,
        apply_lazy_close=False,
    )
    if found is not None:
        return WorkspaceDocumentRead.of_record(found)
    if intent_id in unreadable_workspace_intent_ids(root=root):
        return WorkspaceDocumentRead(WorkspaceDocumentReadKind.INCOMPATIBLE)
    return WorkspaceDocumentRead(WorkspaceDocumentReadKind.ABSENT)


def workspace_status_counts(*, root: Path) -> dict[str, int]:
    records = list(_intent_store(root).list_records_current())
    stale_records = [record for record in records if stale_reason(record) is not None]
    return {
        "stale_count": len(stale_records),
        "orphaned_count": sum(
            1 for record in records if _record_liveness(record) == PidLiveness.DEAD
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
        # Overlap is decided by the grammar owner, never by literal string
        # intersection: `tests/` and `tests/test_api.py` are two spellings of
        # one authorised region, and a set intersection reported them disjoint.
        hard_overlap = overlapping_entries(
            sorted(new_allowed), sorted(existing_allowed)
        )
        soft_overlap = tuple(
            sorted(
                {
                    *overlapping_entries(sorted(new_allowed), sorted(existing_related)),
                    *overlapping_entries(sorted(new_related), sorted(existing_allowed)),
                }
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
    store = _intent_store(root)
    payload = dict(store.gc())
    payload["raw_active_count"] = len(store.list_records_raw())
    return payload


def _updated_record(
    record: WorkspaceIntentRecord,
    *,
    new_status: str,
    ttl_seconds: int | None,
) -> WorkspaceIntentRecord:
    if ttl_seconds is None:
        return replace(record, status=new_status)
    renewed_at = utc_now()
    # ``declared_at_utc`` is deliberately not restamped. The hold starts now,
    # so the expiry and the lease do run from now -- but the declaration
    # happened when the recorded agent declared it, and on the reset path that
    # agent is a different, already dead one whose pid and start epoch this
    # record keeps. Writing now over it would make the row say that agent
    # declared its intent after it was recovered, and would move the row
    # inside ``record_sort_key``, which is the order the edit gate reads its
    # queue in.
    return replace(
        record,
        expires_at_utc=expires_at(declared_at=renewed_at, ttl_seconds=ttl_seconds),
        ttl_seconds=ttl_seconds,
        lease_renewed_at_utc=format_utc(renewed_at),
        status=new_status,
    )


def _intent_store(root: Path) -> WorkspaceIntentStore:
    from ._workspace_intent_store import get_workspace_intent_store

    return get_workspace_intent_store(root)


def _valid_path_list(value: object, *, required: bool) -> list[str] | None:
    """Validate a ``forbidden`` deny-pattern list from an untrusted payload."""

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


def _valid_scope_entry_list(value: object) -> list[str] | None:
    """Validate a declared scope list, keeping each entry's grammatical form.

    ``_valid_path_list`` strips the trailing slash, which is the whole
    difference between an exact file and a directory prefix. Reading a stored
    record must not refuse a form the door no longer accepts, so the total
    reader is used here and the refusal stays at the door.
    """

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None
    entries: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        path = item.replace("\\", "/").strip()
        if not path:
            continue
        if Path(path).is_absolute() or ".." in Path(path).parts:
            return None
        entries.append(render_scope_entry(read_scope_entry(path)))
    return sorted(set(entries))


def _scope_all_sets(
    scope: Mapping[str, object],
) -> tuple[set[str], set[str], tuple[str, ...]]:
    allowed = set(_valid_scope_entry_list(scope.get("allowed_files")) or [])
    related = set(_valid_scope_entry_list(scope.get("allowed_related", ())) or [])
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
    "CURRENT_GRAMMAR",
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_TTL_SECONDS",
    "HISTORICAL_PRODUCER_SPECIFIC",
    "HISTORICAL_UNAMBIGUOUS",
    "LEGACY_AMBIGUOUS",
    "LEGACY_REGISTRY_VERSION",
    "MAX_LEASE_SECONDS",
    "MAX_TTL_SECONDS",
    "MIN_LEASE_SECONDS",
    "MIN_TTL_SECONDS",
    "REGISTRY_VERSION",
    "SCOPE_INTERPRETER_FIELD",
    "AuditScopeEntry",
    "BeforeExecutionWitness",
    "IntentOwnership",
    "LegacyScope",
    "PidLiveness",
    "ScopeGeneration",
    "ScopeInterpretation",
    "ScopeRelation",
    "WorkspaceDocumentRead",
    "WorkspaceDocumentReadKind",
    "WorkspaceIntentLifecycle",
    "WorkspaceIntentRecord",
    "WorkspaceIntentStatus",
    "_is_pid_alive",
    "_is_safe_intent_id",
    "_is_safe_intent_path",
    "_lease_expiry",
    "_parse_utc",
    "_pid_liveness",
    "_read_payload",
    "_record_liveness",
    "_ttl_expired",
    "_unlink",
    "audit_scope_payload",
    "audit_scope_relation",
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
    "intent_id_from_filename",
    "intent_path",
    "is_orphaned",
    "is_recovery_candidate",
    "is_stale",
    "lifecycle_for_verification_outcome",
    "list_workspace_intent_records_for_recovery",
    "list_workspace_intent_records_raw",
    "list_workspace_intents",
    "read_audit_scope",
    "read_audit_scope_entry",
    "read_stored_scope_entry",
    "read_workspace_intent",
    "registry_dir",
    "remove_workspace_intent",
    "remove_workspace_record",
    "renew_workspace_intent_lease",
    "resolved_lease_seconds",
    "resolved_ttl_seconds",
    "safe_remove_own_intent",
    "scope_interpreter_from_record",
    "signed_payload",
    "stale_reason",
    "unreadable_workspace_intent_ids",
    "update_workspace_intent_status",
    "utc_now",
    "validate_workspace_record",
    "verify_intent_integrity",
    "workspace_intent_to_payload",
    "workspace_status_counts",
    "write_workspace_intent",
    "write_workspace_intent_with_existing",
]
