# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import uuid
from pathlib import Path

from ...config.analytics import AnalyticsConfig, resolve_analytics_config
from ...memory.project import compute_project_id, resolve_memory_db_path
from ...report.meta import current_report_timestamp_utc
from ...utils.json_io import json_text
from ..contracts import CorpusItemRecord, CorpusLane, CorpusSnapshotRecord
from ..store.protocols import CorpusStore, SnapshotBuildResult
from ..store.sqlite import SqliteCorpusAnalyticsStore
from .adapters.intent_historical import (
    compute_source_digest,
    default_source_schema_versions,
    extract_historical_intent_items,
    materialize_corpus_item,
)
from .keys import representation_version_for_kind


def _manifest_path(root_path: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root_path.resolve()).as_posix()
    except ValueError:
        return "<external>"


def _relative_store_paths(
    root_path: Path,
    *,
    audit_db_path: Path,
    memory_db_path: Path,
) -> dict[str, str]:
    return {
        "audit": _manifest_path(root_path, audit_db_path),
        "memory": _manifest_path(root_path, memory_db_path),
    }


def build_intent_snapshot(
    *,
    root_path: Path,
    representation_kind: str,
    config: AnalyticsConfig | None = None,
    registry_db_path: Path | None = None,
    store: CorpusStore | None = None,
) -> SnapshotBuildResult:
    resolved_root = root_path.resolve()
    analytics_config = config or resolve_analytics_config(resolved_root)
    owned_store = store is None
    active_store = store or SqliteCorpusAnalyticsStore.open(analytics_config.db_path)
    try:
        lane: CorpusLane = "intent"
        rep_version = representation_version_for_kind(representation_kind)
        memory_db_path = resolve_memory_db_path(resolved_root)
        source_items = extract_historical_intent_items(
            root_path=resolved_root,
            representation_kind=representation_kind,
            audit_db_path=analytics_config.audit_db_path,
            memory_db_path=memory_db_path,
            registry_db_path=registry_db_path,
        )
        source_digest = compute_source_digest(
            items=source_items,
            lane=lane,
            representation_kind=representation_kind,
            representation_version=rep_version,
            source_schema_versions=default_source_schema_versions(),
        )
        snapshot_id = f"snap-{uuid.uuid4().hex[:16]}"
        created_at = current_report_timestamp_utc()
        project_id = compute_project_id(resolved_root)
        corpus_items: list[CorpusItemRecord] = []
        for source_item in source_items:
            (
                rep_key,
                snap_item_id,
                source_key,
                normalized_text,
                normalized_digest,
                normalizer_version,
                rep_digest,
                metadata_json,
                overlay_json,
                _rep_version,
            ) = materialize_corpus_item(
                snapshot_id=snapshot_id,
                lane=lane,
                representation_kind=representation_kind,
                item=source_item,
            )
            corpus_items.append(
                CorpusItemRecord(
                    snapshot_id=snapshot_id,
                    representation_key=rep_key,
                    snapshot_item_id=snap_item_id,
                    source_record_key=source_key,
                    project_id=project_id,
                    intent_id=source_item.intent_id,
                    normalized_text=normalized_text,
                    normalized_digest=normalized_digest,
                    normalizer_version=normalizer_version,
                    representation_digest=rep_digest,
                    metadata_json=metadata_json,
                    registry_overlay_json=overlay_json,
                )
            )
        snapshot = CorpusSnapshotRecord(
            snapshot_id=snapshot_id,
            lane=lane,
            representation_kind=representation_kind,
            representation_version=rep_version,
            source_stores_json=json_text(
                _relative_store_paths(
                    resolved_root,
                    audit_db_path=analytics_config.audit_db_path,
                    memory_db_path=memory_db_path,
                ),
                sort_keys=True,
            ),
            source_schema_versions_json=json_text(
                default_source_schema_versions(),
                sort_keys=True,
            ),
            record_count=len(corpus_items),
            source_digest=source_digest,
            created_at_utc=created_at,
        )
        active_store.insert_snapshot(snapshot, corpus_items)
        active_store.commit()
        return SnapshotBuildResult(
            snapshot_id=snapshot_id,
            source_digest=source_digest,
            record_count=len(corpus_items),
        )
    finally:
        if owned_store:
            active_store.close()


__all__ = ["build_intent_snapshot"]
