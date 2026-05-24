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

REGISTRY_VERSION: Final = "1"
REGISTRY_DIR_PARTS: Final = (".cache", "codeclone", "intents")
DEFAULT_TTL_SECONDS: Final = 3600
MIN_TTL_SECONDS: Final = 60
MAX_TTL_SECONDS: Final = 86400
_HEX_DIGEST_LENGTH: Final = 64


class WorkspaceIntentStatus(str, Enum):
    ACTIVE = "active"
    CLEAN = "clean"
    EXPANDED = "expanded"
    VIOLATED = "violated"
    EXPIRED = "expired"
    ORPHANED = "orphaned"


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
    ) -> dict[str, object]:
        payload = self.unsigned_payload()
        payload["is_own"] = self.agent_pid == own_pid and (
            own_start_epoch is None or self.agent_start_epoch == own_start_epoch
        )
        return payload


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
    raw = value if value is not None else env_value
    if raw is None:
        return DEFAULT_TTL_SECONDS
    if isinstance(raw, bool):
        return DEFAULT_TTL_SECONDS
    try:
        parsed = int(str(raw).strip())
    except ValueError:
        return DEFAULT_TTL_SECONDS
    return min(MAX_TTL_SECONDS, max(MIN_TTL_SECONDS, parsed))


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
    if data.get("registry_version") != REGISTRY_VERSION:
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
    if (
        intent_id is None
        or agent_pid is None
        or agent_start_epoch is None
        or run_id is None
        or declared_at_utc is None
        or expires_at_utc is None
        or ttl_seconds is None
        or status not in _valid_status_values()
        or intent is None
        or scope is None
        or not _is_hex_digest(scope_digest)
        or blast_radius_summary is None
    ):
        return None
    if _parse_utc(declared_at_utc) is None or _parse_utc(expires_at_utc) is None:
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
    )


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
) -> list[dict[str, object]]:
    new_allowed, new_related = _scope_file_sets(new_scope)
    conflicts: list[dict[str, object]] = []
    for record in existing:
        if record.agent_pid == own_pid or stale_reason(record) is not None:
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
        reason = stale_reason(record)
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
    "DEFAULT_TTL_SECONDS",
    "MAX_TTL_SECONDS",
    "MIN_TTL_SECONDS",
    "REGISTRY_VERSION",
    "WorkspaceIntentRecord",
    "WorkspaceIntentStatus",
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
    "resolved_ttl_seconds",
    "stale_reason",
    "update_workspace_intent_status",
    "utc_now",
    "validate_workspace_record",
    "verify_intent_integrity",
    "workspace_status_counts",
    "write_workspace_intent",
]
