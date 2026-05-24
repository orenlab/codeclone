# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Final

from ...cache.integrity import canonical_json
from ...utils.json_io import read_json_object, write_json_document_atomically

LEGACY_REGISTRY_VERSION: Final = "1"
REGISTRY_VERSION: Final = "2"
REGISTRY_DIR_PARTS: Final = (".cache", "codeclone", "intents")
DEFAULT_TTL_SECONDS: Final = 3600
MIN_TTL_SECONDS: Final = 60
MAX_TTL_SECONDS: Final = 86400
DEFAULT_LEASE_SECONDS: Final = 300
MIN_LEASE_SECONDS: Final = 60
MAX_LEASE_SECONDS: Final = 3600
_HEX_DIGEST_LENGTH: Final = 64


class WorkspaceIntentStatus(str, Enum):
    ACTIVE = "active"
    CLEAN = "clean"
    EXPANDED = "expanded"
    VIOLATED = "violated"
    EXPIRED = "expired"
    ORPHANED = "orphaned"


class IntentOwnership(str, Enum):
    OWN_ACTIVE = "own_active"
    OWN_STALE = "own_stale"
    RECOVERABLE = "recoverable"
    FOREIGN_ACTIVE = "foreign_active"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class WorkspaceIntentRecord:
    intent_id: str
    agent_pid: int
    agent_start_epoch: int
    agent_label: str
    run_id: str
    declared_at_utc: str
    expires_at_utc: str
    ttl_seconds: int
    status: str
    intent: str
    scope: dict[str, object]
    scope_digest: str
    blast_radius_summary: dict[str, object]
    lease_renewed_at_utc: str
    lease_seconds: int
    report_digest: str

    def unsigned_payload(self) -> dict[str, object]:
        return {
            "registry_version": REGISTRY_VERSION,
            "intent_id": self.intent_id,
            "agent_pid": self.agent_pid,
            "agent_start_epoch": self.agent_start_epoch,
            "agent_label": self.agent_label,
            "run_id": self.run_id,
            "declared_at_utc": self.declared_at_utc,
            "expires_at_utc": self.expires_at_utc,
            "ttl_seconds": self.ttl_seconds,
            "status": self.status,
            "intent": self.intent,
            "scope": self.scope,
            "scope_digest": self.scope_digest,
            "blast_radius_summary": self.blast_radius_summary,
            "lease_renewed_at_utc": self.lease_renewed_at_utc,
            "lease_seconds": self.lease_seconds,
            "report_digest": self.report_digest,
        }

    def signed_payload(self) -> dict[str, object]:
        payload = self.unsigned_payload()
        payload["integrity"] = {"payload_sha256": compute_intent_digest(payload)}
        return payload

    def to_payload(
        self,
        *,
        own_pid: int | None = None,
        own_start_epoch: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, object]:
        current_time = now or utc_now()
        ownership = classify_intent_ownership(
            self,
            own_pid=own_pid or 0,
            own_start_epoch=own_start_epoch or 0,
            now=current_time,
        )
        payload = self.unsigned_payload()
        payload["ownership"] = ownership.value
        payload["is_own"] = ownership in {
            IntentOwnership.OWN_ACTIVE,
            IntentOwnership.OWN_STALE,
        }
        lease_expiry = _lease_expiry(self)
        if lease_expiry is not None:
            remaining = int((lease_expiry - current_time).total_seconds())
            payload["lease_expires_in_seconds"] = max(0, remaining)
        if ownership == IntentOwnership.FOREIGN_ACTIVE:
            payload["escalation_hint"] = (
                "This intent belongs to a live process with a valid lease. "
                "Do NOT kill the process. Ask the user to confirm whether "
                "this is an abandoned session or a parallel agent."
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
    if not lease_valid:
        return IntentOwnership.RECOVERABLE
    if not _is_pid_alive(record.agent_pid):
        return IntentOwnership.RECOVERABLE
    return IntentOwnership.FOREIGN_ACTIVE


def _lease_expiry(record: WorkspaceIntentRecord) -> datetime | None:
    renewed_at = _parse_utc(record.lease_renewed_at_utc)
    if renewed_at is None:
        return None
    return renewed_at + timedelta(seconds=record.lease_seconds)


def _is_lease_expired(record: WorkspaceIntentRecord) -> bool:
    lease_expiry = _lease_expiry(record)
    return lease_expiry is None or lease_expiry <= utc_now()


def resolved_lease_seconds(value: object = None, *, env_value: object = None) -> int:
    return _resolved_seconds(
        value=value,
        env_value=env_value,
        default=DEFAULT_LEASE_SECONDS,
        minimum=MIN_LEASE_SECONDS,
        maximum=MAX_LEASE_SECONDS,
    )


def registry_dir(root: Path) -> Path:
    return root.joinpath(*REGISTRY_DIR_PARTS)


def intent_filename(*, pid: int, start_epoch: int, intent_id: str) -> str:
    return f"{pid}-{start_epoch}-{intent_id}.json"


def intent_path(
    *,
    root: Path,
    pid: int,
    start_epoch: int,
    intent_id: str,
) -> Path:
    return registry_dir(root) / intent_filename(
        pid=pid,
        start_epoch=start_epoch,
        intent_id=intent_id,
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


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


def compute_scope_digest(scope: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(dict(scope)).encode("utf-8")).hexdigest()


def compute_intent_digest(data: Mapping[str, object]) -> str:
    digestable = {key: value for key, value in data.items() if key != "integrity"}
    return hashlib.sha256(canonical_json(digestable).encode("utf-8")).hexdigest()


def verify_intent_integrity(data: Mapping[str, object]) -> bool:
    integrity = _as_mapping(data.get("integrity"))
    stored = integrity.get("payload_sha256")
    if not _is_hex_digest(stored):
        return False
    expected = compute_intent_digest(data)
    return hmac.compare_digest(str(stored), expected)


def validate_workspace_record(data: object) -> WorkspaceIntentRecord | None:
    if not isinstance(data, Mapping):
        return None
    if not all(isinstance(key, str) for key in data):
        return None
    if not verify_intent_integrity(data):
        return None
    version = data.get("registry_version")
    if version not in {REGISTRY_VERSION, LEGACY_REGISTRY_VERSION}:
        return None
    intent_id = _required_string(data.get("intent_id"))
    agent_pid = _positive_int(data.get("agent_pid"))
    agent_start_epoch = _positive_int(data.get("agent_start_epoch"))
    agent_label = _string_value(data.get("agent_label"))
    run_id = _required_string(data.get("run_id"))
    declared_at_utc = _required_string(data.get("declared_at_utc"))
    expires_at_utc = _required_string(data.get("expires_at_utc"))
    ttl_seconds = _positive_int(data.get("ttl_seconds"))
    status = _required_string(data.get("status"))
    intent = _required_string(data.get("intent"))
    scope = _valid_scope(data.get("scope"))
    scope_digest = data.get("scope_digest")
    blast_radius_summary = _dict_payload(data.get("blast_radius_summary"))
    lease_fields = _lease_fields_for_version(
        data=data,
        version=str(version),
        declared_at_utc=declared_at_utc,
    )
    if lease_fields is None:
        return None
    lease_renewed_at_utc, lease_seconds, report_digest = lease_fields
    if _record_required_value_missing(
        intent_id,
        agent_pid,
        agent_start_epoch,
        run_id,
        declared_at_utc,
        expires_at_utc,
        ttl_seconds,
        intent,
        blast_radius_summary,
    ):
        return None
    assert intent_id is not None
    assert agent_pid is not None
    assert agent_start_epoch is not None
    assert run_id is not None
    assert declared_at_utc is not None
    assert expires_at_utc is not None
    assert ttl_seconds is not None
    assert intent is not None
    assert blast_radius_summary is not None
    if status not in _valid_status_values() or scope is None:
        return None
    assert status is not None
    if not _is_hex_digest(scope_digest):
        return None
    if not _valid_record_dates(
        declared_at_utc,
        expires_at_utc,
        lease_renewed_at_utc,
    ):
        return None
    if compute_scope_digest(scope) != str(scope_digest):
        return None
    return WorkspaceIntentRecord(
        intent_id=intent_id,
        agent_pid=agent_pid,
        agent_start_epoch=agent_start_epoch,
        agent_label=agent_label,
        run_id=run_id,
        declared_at_utc=declared_at_utc,
        expires_at_utc=expires_at_utc,
        ttl_seconds=ttl_seconds,
        status=status,
        intent=intent,
        scope=scope,
        scope_digest=str(scope_digest),
        blast_radius_summary=blast_radius_summary,
        lease_renewed_at_utc=lease_renewed_at_utc,
        lease_seconds=lease_seconds,
        report_digest=report_digest,
    )


def _lease_fields_for_version(
    *,
    data: Mapping[str, object],
    version: str,
    declared_at_utc: str | None,
) -> tuple[str, int, str] | None:
    if version == REGISTRY_VERSION:
        lease_renewed_at_utc = _required_string(data.get("lease_renewed_at_utc"))
        lease_seconds = _valid_lease_seconds(data.get("lease_seconds"))
        report_digest = _required_string(data.get("report_digest"))
    else:
        lease_renewed_at_utc = declared_at_utc
        lease_seconds = DEFAULT_LEASE_SECONDS
        report_digest = _string_value(data.get("report_digest"))
    if lease_renewed_at_utc is None or lease_seconds is None or report_digest is None:
        return None
    return lease_renewed_at_utc, lease_seconds, report_digest


def _record_required_value_missing(*values: object) -> bool:
    return any(value is None for value in values)


def _valid_record_dates(*values: str) -> bool:
    return all(_parse_utc(value) is not None for value in values)


def write_workspace_intent(*, root: Path, record: WorkspaceIntentRecord) -> bool:
    try:
        write_json_document_atomically(
            path=intent_path(
                root=root,
                pid=record.agent_pid,
                start_epoch=record.agent_start_epoch,
                intent_id=record.intent_id,
            ),
            document=record.signed_payload(),
            sort_keys=True,
            trailing_newline=True,
        )
    except OSError:
        return False
    return True


def update_workspace_intent_status(
    *,
    root: Path,
    pid: int,
    start_epoch: int,
    intent_id: str,
    new_status: str,
    ttl_seconds: int | None = None,
) -> bool:
    found = find_workspace_intent(root=root, intent_id=intent_id)
    if found is None:
        return False
    path, record = found
    if record.agent_pid != pid or record.agent_start_epoch != start_epoch:
        return False
    updated = _updated_record(record, new_status=new_status, ttl_seconds=ttl_seconds)
    try:
        write_json_document_atomically(
            path=path,
            document=updated.signed_payload(),
            sort_keys=True,
            trailing_newline=True,
        )
    except OSError:
        return False
    return True


def renew_workspace_intent_lease(
    *,
    root: Path,
    pid: int,
    start_epoch: int,
    intent_id: str,
) -> bool:
    found = find_workspace_intent(root=root, intent_id=intent_id)
    if found is None:
        return False
    path, record = found
    if record.agent_pid != pid or record.agent_start_epoch != start_epoch:
        return False
    now = utc_now()
    expires = _parse_utc(record.expires_at_utc)
    if expires is None or expires <= now:
        return False
    updated = replace(record, lease_renewed_at_utc=format_utc(now))
    try:
        write_json_document_atomically(
            path=path,
            document=updated.signed_payload(),
            sort_keys=True,
            trailing_newline=True,
        )
    except OSError:
        return False
    return True


def remove_workspace_intent(
    *,
    root: Path,
    pid: int,
    start_epoch: int,
    intent_id: str,
) -> bool:
    path = intent_path(
        root=root,
        pid=pid,
        start_epoch=start_epoch,
        intent_id=intent_id,
    )
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True


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
        for _, record in _valid_registry_entries(root)
        if not exclude_stale or stale_reason(record) is None
    ]
    return tuple(sorted(records, key=_record_sort_key))


def find_workspace_intent(
    *,
    root: Path,
    intent_id: str,
) -> tuple[Path, WorkspaceIntentRecord] | None:
    matches = [
        (path, record)
        for path, record in _valid_registry_entries(root)
        if record.intent_id == intent_id
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda item: _record_sort_key(item[1]))[-1]


def workspace_status_counts(*, root: Path) -> dict[str, int]:
    records = [record for _, record in _valid_registry_entries(root)]
    stale_records = [record for record in records if stale_reason(record) is not None]
    return {
        "stale_count": len(stale_records),
        "orphaned_count": sum(1 for record in records if is_orphaned(record)),
        "total_agents": len({record.agent_pid for record in records}),
    }


def detect_conflicts(
    *,
    new_scope: Mapping[str, object],
    existing: Sequence[WorkspaceIntentRecord],
    own_pid: int,
    own_start_epoch: int,
) -> list[dict[str, object]]:
    new_allowed, new_related = _scope_file_sets(new_scope)
    conflicts: list[dict[str, object]] = []
    now = utc_now()
    for record in existing:
        ownership = classify_intent_ownership(
            record,
            own_pid=own_pid,
            own_start_epoch=own_start_epoch,
            now=now,
        )
        if ownership != IntentOwnership.FOREIGN_ACTIVE:
            continue
        existing_allowed, existing_related = _scope_file_sets(record.scope)
        hard_overlap = tuple(sorted(new_allowed.intersection(existing_allowed)))
        soft_overlap = tuple(
            sorted(
                new_allowed.intersection(existing_related).union(
                    new_related.intersection(existing_allowed)
                )
            )
        )
        if hard_overlap or soft_overlap:
            conflicts.append(
                {
                    "intent_id": record.intent_id,
                    "agent_pid": record.agent_pid,
                    "agent_start_epoch": record.agent_start_epoch,
                    "agent_label": record.agent_label,
                    "intent": record.intent,
                    "overlap_type": _overlap_type(
                        hard=bool(hard_overlap),
                        soft=bool(soft_overlap),
                    ),
                    "hard_overlap": list(hard_overlap),
                    "soft_overlap": list(soft_overlap),
                    "declared_at_utc": record.declared_at_utc,
                    "expires_at_utc": record.expires_at_utc,
                }
            )
    return sorted(
        conflicts,
        key=lambda item: (
            str(item["overlap_type"]),
            str(item["agent_label"]),
            _sort_agent_pid(item.get("agent_pid")),
            str(item["intent_id"]),
        ),
    )


def gc_workspace(*, root: Path) -> dict[str, object]:
    removed_ids: list[str] = []
    removed_reasons: dict[str, str] = {}
    corrupted_filenames: list[str] = []
    for path in _registry_files(root):
        payload = _read_payload(path)
        record = validate_workspace_record(payload) if payload is not None else None
        if record is None:
            if _unlink(path):
                corrupted_filenames.append(path.name)
            continue
        reason = _gc_removal_reason(record)
        if reason is None:
            continue
        if _unlink(path):
            removed_ids.append(record.intent_id)
            removed_reasons[record.intent_id] = reason
    remaining = len(list_workspace_intents(root=root, exclude_stale=False))
    return {
        "removed": len(removed_ids),
        "removed_intent_ids": removed_ids,
        "removed_reasons": removed_reasons,
        "corrupted_removed": len(corrupted_filenames),
        "corrupted_filenames": corrupted_filenames,
        "remaining": remaining,
    }


def _gc_removal_reason(record: WorkspaceIntentRecord) -> str | None:
    reason = stale_reason(record)
    if reason == "lease_expired" and not _ttl_expired(record):
        return None
    return reason


def _ttl_expired(record: WorkspaceIntentRecord) -> bool:
    expires = _parse_utc(record.expires_at_utc)
    return expires is None or expires <= utc_now()


def is_stale(record: WorkspaceIntentRecord) -> bool:
    return stale_reason(record) is not None


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


def is_orphaned(record: WorkspaceIntentRecord) -> bool:
    return not _is_pid_alive(record.agent_pid)


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


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


def _valid_registry_entries(
    root: Path,
) -> tuple[tuple[Path, WorkspaceIntentRecord], ...]:
    entries: list[tuple[Path, WorkspaceIntentRecord]] = []
    for path in _registry_files(root):
        payload = _read_payload(path)
        record = validate_workspace_record(payload) if payload is not None else None
        if record is not None:
            entries.append((path, record))
    return tuple(entries)


def _registry_files(root: Path) -> tuple[Path, ...]:
    directory = registry_dir(root)
    try:
        return tuple(sorted(directory.glob("*.json")))
    except OSError:
        return ()


def _read_payload(path: Path) -> dict[str, object] | None:
    try:
        return read_json_object(path)
    except (OSError, TypeError, ValueError):
        return None


def _unlink(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def _is_safe_intent_path(expected: Path, registry: Path) -> bool:
    """Return True only if *expected* is safe to delete.

    Checks (all must pass):
    1. *expected* is an absolute path.
    2. *expected* resolves to itself — no symlink indirection.
    3. Resolved path is strictly inside *registry* directory.
    4. Filename matches the ``{pid}-{start_epoch}-{intent_id}.json`` pattern.
    5. Target is a regular file (not a directory, device, or pipe).
    """
    try:
        if not expected.is_absolute():
            return False
        resolved = expected.resolve(strict=False)
        resolved_registry = registry.resolve(strict=False)
        if resolved != expected:
            return False
        if not resolved.is_relative_to(resolved_registry):
            return False
        name = expected.name
        if not name.endswith(".json") or name.count("-") < 2:
            return False
        if expected.exists() and not expected.is_file():
            return False
    except (OSError, ValueError):
        return False
    return True


def safe_remove_own_intent(
    *,
    root: Path,
    pid: int,
    start_epoch: int,
    intent_id: str,
) -> bool:
    """Remove a workspace intent file ONLY if it belongs to the caller.

    Safety checks (all must pass):
    1. *root* is an absolute path.
    2. Constructed path resolves inside ``registry_dir(root)``.
    3. No symlink indirection (resolved == constructed).
    4. Target is a regular file.
    5. Filename matches expected pattern.

    Returns True if the file was removed or is already absent.
    Returns False if any safety check fails (file is NOT removed).
    Never raises.
    """
    try:
        if not root.is_absolute():
            return False
        registry = registry_dir(root)
        expected = intent_path(
            root=root,
            pid=pid,
            start_epoch=start_epoch,
            intent_id=intent_id,
        )
        if not _is_safe_intent_path(expected, registry):
            return False
        expected.unlink(missing_ok=True)
    except Exception:
        return False
    return True


def _record_sort_key(record: WorkspaceIntentRecord) -> tuple[str, int, str]:
    return (record.declared_at_utc, record.agent_pid, record.intent_id)


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _dict_payload(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if not all(isinstance(key, str) for key in value):
        return None
    return dict(value)


def _string_value(value: object) -> str:
    return value if isinstance(value, str) else ""


def _required_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _valid_lease_seconds(value: object) -> int | None:
    parsed = _positive_int(value)
    if parsed is None:
        return None
    if parsed < MIN_LEASE_SECONDS or parsed > MAX_LEASE_SECONDS:
        return None
    return parsed


def _is_hex_digest(value: object) -> bool:
    if not isinstance(value, str) or len(value) != _HEX_DIGEST_LENGTH:
        return False
    return all(char in "0123456789abcdef" for char in value.lower())


def _valid_status_values() -> frozenset[str]:
    return frozenset(status.value for status in WorkspaceIntentStatus)


def _valid_scope(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if not all(isinstance(key, str) for key in value):
        return None
    allowed = _valid_path_list(value.get("allowed_files"), required=True)
    if allowed is None:
        return None
    related = _valid_path_list(value.get("allowed_related", ()), required=False)
    forbidden = _valid_path_list(value.get("forbidden", ()), required=False)
    if related is None or forbidden is None:
        return None
    return {
        "allowed_files": allowed,
        "allowed_related": related,
        "forbidden": forbidden,
    }


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


def _scope_file_sets(scope: Mapping[str, object]) -> tuple[set[str], set[str]]:
    allowed = set(_valid_path_list(scope.get("allowed_files"), required=False) or [])
    related = set(
        _valid_path_list(scope.get("allowed_related", ()), required=False) or []
    )
    return allowed, related


def _parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


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
    "classify_intent_ownership",
    "compute_intent_digest",
    "compute_scope_digest",
    "detect_conflicts",
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
    "stale_reason",
    "update_workspace_intent_status",
    "utc_now",
    "validate_workspace_record",
    "verify_intent_integrity",
    "workspace_status_counts",
    "write_workspace_intent",
]
