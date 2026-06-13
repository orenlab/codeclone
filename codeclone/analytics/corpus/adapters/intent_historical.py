# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ....audit.events import repo_root_digest
from ....audit.reader import AuditRecord, read_intent_declared_records
from ....audit.validation import AUDIT_SCHEMA_VERSION, DEFAULT_AUDIT_PATH
from ....config.intent_registry import (
    IntentRegistryConfigError,
    resolve_intent_registry_config,
)
from ....contracts import (
    CORPUS_NORMALIZER_VERSION,
    ENGINEERING_MEMORY_SCHEMA_VERSION,
    PATCH_TRAIL_SCHEMA_VERSION,
)
from ....memory.project import compute_project_id, resolve_memory_db_path
from ....memory.schema import open_memory_db_readonly
from ....memory.trajectory.agents import trajectory_agent_label
from ....memory.trajectory.anomalies import detect_trajectory_anomalies
from ....memory.trajectory.models import Trajectory
from ....memory.trajectory.patch_trail import patch_trail_from_mapping
from ....memory.trajectory.store import (
    list_trajectories_for_intent_id,
    load_trajectory_patch_trail,
)
from ....utils.json_io import json_text
from ...agent_labels import map_agent_family
from ..keys import (
    representation_key,
    representation_version_for_kind,
    sha256_hex,
    snapshot_item_id,
    source_record_key,
)
from ..normalizer import normalize_corpus_text, source_content_digest
from ..registry_overlay import read_registry_overlay
from ..representations.intent import (
    IntentRepresentationInput,
    build_representation_text,
    declared_constraints_from_audit_payload,
    declared_path_families_from_patch_trail,
)
from ..representations.intent import (
    representation_digest as compute_representation_digest,
)
from ..trajectory_selection import (
    TRAJECTORY_SELECTION_RULE_VERSION,
    scope_expanded_from_labels,
    select_trajectory_for_intent,
)


@dataclass(frozen=True, slots=True)
class HistoricalIntentSourceItem:
    project_id: str
    intent_id: str
    source_record_key_value: str
    source_content_digest: str
    provenance: dict[str, object]
    metadata: dict[str, object]
    registry_overlay: dict[str, object] | None
    representation_input: IntentRepresentationInput


@dataclass(frozen=True, slots=True)
class SourceDigestItem:
    source_record_key: str
    source_content_digest: str
    provenance_digest: str


def _payload_mapping(record: AuditRecord) -> dict[str, object]:
    if record.payload_json:
        try:
            parsed = json.loads(record.payload_json)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    if record.event_core_json:
        try:
            parsed = json.loads(record.event_core_json)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _intent_description(payload: Mapping[str, object]) -> str:
    value = payload.get("intent_description")
    if isinstance(value, str):
        return value
    return ""


def _intent_kind(payload: Mapping[str, object]) -> str | None:
    value = payload.get("intent_kind")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _canonical_declaration(
    records: Sequence[AuditRecord],
) -> tuple[AuditRecord, bool, tuple[str, ...]]:
    ordered = sorted(
        records,
        key=lambda item: (item.audit_sequence or 0, item.event_id),
    )
    canonical = ordered[0]
    descriptions = {
        _intent_description(_payload_mapping(item)).strip()
        for item in ordered
        if _intent_description(_payload_mapping(item)).strip()
    }
    description_conflict = len(descriptions) > 1
    declaration_event_ids = tuple(item.event_id for item in ordered)
    return canonical, description_conflict, declaration_event_ids


def _resolved_registry_db_path(
    root_path: Path,
    registry_db_path: Path | None,
) -> Path | None:
    if registry_db_path is not None:
        return registry_db_path
    try:
        config = resolve_intent_registry_config(root_path)
    except (IntentRegistryConfigError, OSError, ValueError):
        return None
    if config.backend != "sqlite":
        return None
    return config.storage_path


def extract_historical_intent_items(
    *,
    root_path: Path,
    representation_kind: str,
    audit_db_path: Path | None = None,
    memory_db_path: Path | None = None,
    registry_db_path: Path | None = None,
) -> tuple[HistoricalIntentSourceItem, ...]:
    resolved_root = root_path.resolve()
    project_id = compute_project_id(resolved_root)
    digest = repo_root_digest(resolved_root)
    audit_path = audit_db_path or (resolved_root / DEFAULT_AUDIT_PATH)
    records = read_intent_declared_records(
        db_path=audit_path,
        repo_root_digest=digest,
    )
    grouped: defaultdict[tuple[str, str], list[AuditRecord]] = defaultdict(list)
    for record in records:
        intent_id = record.intent_id
        if not intent_id:
            continue
        grouped[(project_id, intent_id)].append(record)

    memory_path = memory_db_path or resolve_memory_db_path(resolved_root)
    memory_conn = (
        open_memory_db_readonly(memory_path) if memory_path.is_file() else None
    )
    if memory_conn is not None:
        memory_conn.row_factory = sqlite3.Row

    resolved_registry_db = _resolved_registry_db_path(
        resolved_root,
        registry_db_path,
    )

    items: list[HistoricalIntentSourceItem] = []
    try:
        for (group_project_id, intent_id), group_records in sorted(grouped.items()):
            canonical, description_conflict, declaration_event_ids = (
                _canonical_declaration(group_records)
            )
            payload = _payload_mapping(canonical)
            description = _intent_description(payload)
            if not description.strip():
                continue
            trajectories: tuple[Trajectory, ...] = ()
            patch_trail_payload: dict[str, object] | None = None
            selected_trajectory = None
            discarded_ids: tuple[str, ...] = ()
            if memory_conn is not None:
                trajectories = list_trajectories_for_intent_id(
                    memory_conn,
                    project_id=group_project_id,
                    intent_id=intent_id,
                )
                selection = select_trajectory_for_intent(trajectories)
                selected_trajectory = selection.selected
                discarded_ids = selection.discarded_ids
                if selected_trajectory is not None:
                    patch_trail_payload = load_trajectory_patch_trail(
                        memory_conn,
                        trajectory_id=selected_trajectory.id,
                    )

            patch_trail_digest: str | None = None
            if patch_trail_payload is not None:
                trail = patch_trail_from_mapping(patch_trail_payload)
                if trail is not None:
                    patch_trail_digest = trail.patch_trail_digest

            provenance: dict[str, object] = {
                "description": {
                    "source": "audit",
                    "event_id": canonical.event_id,
                    "audit_sequence": canonical.audit_sequence,
                    "duplicate_declaration_count": len(group_records),
                    "description_conflict": description_conflict,
                    "declaration_event_ids": list(declaration_event_ids),
                },
                "trajectory": {
                    "selected_trajectory_id": (
                        selected_trajectory.id if selected_trajectory else None
                    ),
                    "discarded_trajectory_ids": list(discarded_ids),
                    "selection_rule_version": TRAJECTORY_SELECTION_RULE_VERSION,
                },
                "patch_trail": {
                    "source": "patch_trail",
                    "digest": patch_trail_digest,
                },
            }

            metadata: dict[str, object] = {
                "agent_client_raw": None,
                "agent_family": "unknown",
                "outcome": None,
                "quality_tier": None,
                "finished_at_utc": None,
                "scope_expanded": None,
                "anomaly_kinds": None,
                "scope_check_status": None,
                "verification_status": None,
                "declared_file_count": None,
                "changed_file_count": None,
            }
            agent_raw: str | None = None
            if selected_trajectory is not None:
                agent_raw = trajectory_agent_label(selected_trajectory)
                metadata["outcome"] = selected_trajectory.outcome
                metadata["quality_tier"] = selected_trajectory.quality_tier
                metadata["finished_at_utc"] = selected_trajectory.finished_at_utc
                metadata["scope_expanded"] = scope_expanded_from_labels(
                    selected_trajectory.labels
                )
                anomalies = detect_trajectory_anomalies(
                    selected_trajectory,
                    patch_trail_payload=patch_trail_payload,
                )
                metadata["anomaly_kinds"] = sorted({item.kind for item in anomalies})
            elif canonical.agent_label.strip():
                agent_raw = canonical.agent_label.strip()

            metadata["agent_client_raw"] = agent_raw
            metadata["agent_family"] = map_agent_family(agent_raw)

            if patch_trail_payload is not None:
                trail = patch_trail_from_mapping(patch_trail_payload)
                if trail is not None:
                    metadata["scope_check_status"] = trail.scope_check_status
                    metadata["verification_status"] = trail.verification_status
                    metadata["declared_file_count"] = len(trail.declared_files)
                    metadata["changed_file_count"] = len(trail.changed_files)

            registry_overlay = (
                read_registry_overlay(resolved_registry_db, intent_id=intent_id)
                if resolved_registry_db is not None
                else None
            )

            rep_input = IntentRepresentationInput(
                description=description,
                intent_kind=_intent_kind(payload),
                declared_path_families=declared_path_families_from_patch_trail(
                    patch_trail_payload
                ),
                declared_constraints=declared_constraints_from_audit_payload(payload),
            )

            items.append(
                HistoricalIntentSourceItem(
                    project_id=group_project_id,
                    intent_id=intent_id,
                    source_record_key_value=source_record_key(
                        project_id=group_project_id,
                        intent_id=intent_id,
                    ),
                    source_content_digest=source_content_digest(
                        _raw_representation_inputs(
                            representation_kind=representation_kind,
                            payload=rep_input,
                        )
                    ),
                    provenance=provenance,
                    metadata=metadata,
                    registry_overlay=registry_overlay,
                    representation_input=rep_input,
                )
            )
    finally:
        if memory_conn is not None:
            memory_conn.close()

    return tuple(items)


def build_source_digest_items(
    items: Sequence[HistoricalIntentSourceItem],
    *,
    lane: str,
    representation_kind: str,
) -> tuple[SourceDigestItem, ...]:
    digest_items: list[SourceDigestItem] = []
    for item in items:
        provenance_digest = sha256_hex(json_text(item.provenance, sort_keys=True))
        digest_items.append(
            SourceDigestItem(
                source_record_key=item.source_record_key_value,
                source_content_digest=item.source_content_digest,
                provenance_digest=provenance_digest,
            )
        )
    return tuple(sorted(digest_items, key=lambda entry: entry.source_record_key))


def _raw_representation_inputs(
    *,
    representation_kind: str,
    payload: IntentRepresentationInput,
) -> dict[str, object]:
    raw: dict[str, object] = {"description": payload.description}
    if representation_kind.endswith("description_with_frame.v1"):
        raw.update(
            {
                "intent_kind": payload.intent_kind,
                "declared_path_families": sorted(set(payload.declared_path_families)),
                "declared_constraints": sorted(set(payload.declared_constraints)),
            }
        )
    return raw


def compute_source_digest(
    *,
    items: Sequence[HistoricalIntentSourceItem],
    lane: str,
    representation_kind: str,
    representation_version: str,
    source_schema_versions: Mapping[str, str],
) -> str:
    digest_items = build_source_digest_items(
        items,
        lane=lane,
        representation_kind=representation_kind,
    )
    payload = {
        "source_schema_versions": dict(sorted(source_schema_versions.items())),
        "lane": lane,
        "representation_kind": representation_kind,
        "representation_version": representation_version,
        "normalizer_version": CORPUS_NORMALIZER_VERSION,
        "items": [
            {
                "source_record_key": entry.source_record_key,
                "source_content_digest": entry.source_content_digest,
                "provenance_digest": entry.provenance_digest,
            }
            for entry in digest_items
        ],
    }
    return sha256_hex(json_text(payload, sort_keys=True))


def materialize_corpus_item(
    *,
    snapshot_id: str,
    lane: str,
    representation_kind: str,
    item: HistoricalIntentSourceItem,
) -> tuple[str, str, str, str, str, str, str, str, str | None, str]:
    rep_version = representation_version_for_kind(representation_kind)
    source_key = item.source_record_key_value
    rep_key = representation_key(
        lane=lane,
        representation_kind=representation_kind,
        representation_version=rep_version,
        source_record_key_value=source_key,
    )
    snap_item_id = snapshot_item_id(
        snapshot_id=snapshot_id,
        representation_key_value=rep_key,
    )
    normalized = normalize_corpus_text(
        build_representation_text(
            representation_kind=representation_kind,
            payload=item.representation_input,
        )
    )
    if not normalized.text:
        msg = "normalized representation text is empty"
        raise ValueError(msg)
    rep_digest = compute_representation_digest(
        representation_kind=representation_kind,
        normalized_text=normalized.text,
    )
    metadata_json = json_text(item.metadata, sort_keys=True)
    overlay_json = (
        json_text(item.registry_overlay, sort_keys=True)
        if item.registry_overlay is not None
        else None
    )
    return (
        rep_key,
        snap_item_id,
        source_key,
        normalized.text,
        normalized.digest,
        normalized.normalizer_version,
        rep_digest,
        metadata_json,
        overlay_json,
        rep_version,
    )


def default_source_schema_versions() -> dict[str, str]:
    return {
        "audit": AUDIT_SCHEMA_VERSION,
        "memory": ENGINEERING_MEMORY_SCHEMA_VERSION,
        "patch_trail": PATCH_TRAIL_SCHEMA_VERSION,
    }


__all__ = [
    "HistoricalIntentSourceItem",
    "SourceDigestItem",
    "build_source_digest_items",
    "compute_source_digest",
    "default_source_schema_versions",
    "extract_historical_intent_items",
    "materialize_corpus_item",
]
