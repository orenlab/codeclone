# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from codeclone.audit.events import EVENT_INTENT_DECLARED, repo_root_digest
from codeclone.audit.schema import open_audit_db
from codeclone.memory.schema import ensure_schema as ensure_memory_schema

if TYPE_CHECKING:
    from codeclone.analytics.clustering.models import ClusteringParameters
    from codeclone.analytics.corpus.adapters.intent_historical import (
        HistoricalIntentSourceItem,
    )
    from codeclone.config.analytics import AnalyticsConfig


def write_intent_declared_event(
    *,
    db_path: Path,
    repo_root: Path,
    intent_id: str,
    description: str,
    audit_sequence: int = 1,
    agent_label: str = "cursor-agent",
    intent_kind: str | None = None,
) -> None:
    digest = repo_root_digest(repo_root.resolve())
    conn = open_audit_db(db_path)
    try:
        payload = {
            "intent_description": description,
            "intent_kind": intent_kind,
            "scope": {"allowed_files": ["codeclone/analytics"]},
        }
        conn.execute(
            """
            INSERT INTO controller_events (
                event_id, event_type, severity, created_at_utc,
                repo_root_digest, intent_id, workflow_id, agent_label, agent_pid,
                status, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"evt-{audit_sequence}",
                EVENT_INTENT_DECLARED,
                "info",
                f"2026-01-01T00:00:{audit_sequence:02d}Z",
                digest,
                intent_id,
                f"intent:{intent_id}",
                agent_label,
                1,
                "active",
                json.dumps(payload, sort_keys=True),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def seed_memory_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    ensure_memory_schema(conn)
    return conn


def trajectory_digest(payload: dict[str, object]) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def patch_snapshot_missing_memory_db(
    monkeypatch: pytest.MonkeyPatch, config: AnalyticsConfig
) -> None:
    monkeypatch.setattr(
        "codeclone.analytics.corpus.snapshot.resolve_memory_db_path",
        lambda _root: config.db_path.parent / "missing.sqlite3",
    )


def patch_deterministic_embedding_provider(
    monkeypatch: pytest.MonkeyPatch, config: AnalyticsConfig
) -> None:
    from codeclone.memory.embedding import DeterministicHashEmbeddingProvider

    monkeypatch.setattr(
        "codeclone.analytics.embedding.generation._resolve_fastembed_provider",
        lambda _config: DeterministicHashEmbeddingProvider(
            dimension=config.embedding_dimension
        ),
    )


def patch_historical_adapter_without_memory(
    monkeypatch: pytest.MonkeyPatch, root: Path
) -> None:
    monkeypatch.setattr(
        "codeclone.analytics.corpus.adapters.intent_historical.resolve_memory_db_path",
        lambda _root: root / ".codeclone/memory/missing.sqlite3",
    )
    monkeypatch.setattr(
        "codeclone.analytics.corpus.adapters.intent_historical._resolved_registry_db_path",
        lambda *_args, **_kwargs: None,
    )


def extract_historical_description_items(
    root: Path, *, memory_db_path: Path | None = None
) -> tuple[HistoricalIntentSourceItem, ...]:
    from codeclone.analytics.contracts import INTENT_REPRESENTATION_DESCRIPTION
    from codeclone.analytics.corpus.adapters.intent_historical import (
        extract_historical_intent_items,
    )

    if memory_db_path is None:
        items = extract_historical_intent_items(
            root_path=root,
            representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        )
    else:
        items = extract_historical_intent_items(
            root_path=root,
            representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
            memory_db_path=memory_db_path,
        )
    return items


def standard_eom_clustering_parameters() -> ClusteringParameters:
    from codeclone.analytics.clustering.models import ClusteringParameters

    return ClusteringParameters(
        pca_dimensions=8,
        min_cluster_size=3,
        min_samples=1,
        cluster_selection_method="eom",
    )


def open_analytics_store_and_close(path: Path) -> None:
    from codeclone.analytics.store.sqlite import SqliteCorpusAnalyticsStore

    store = SqliteCorpusAnalyticsStore.open(path)
    store.close()


def write_bundled_profile_pyproject(
    tmp_path: Path,
    *,
    profile_filename: str,
    analytics_toml_body: str,
) -> Path:
    from codeclone.analytics.profiles.loader import (
        canonical_manifest_json,
        load_bundled_profiles,
    )

    profile = load_bundled_profiles()["intent-small-balanced-v1"]
    profile_path = tmp_path / profile_filename
    profile_path.write_text(canonical_manifest_json(profile), encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        analytics_toml_body.strip(),
        encoding="utf-8",
    )
    return profile_path


def seed_registry_overlay_intent(
    db_path: Path,
    *,
    intent_id: str,
    payload: object,
) -> None:
    from codeclone.surfaces.mcp._workspace_intent_schema import open_intent_registry_db

    if isinstance(payload, (dict, list)):
        payload_json: object = json.dumps(payload)
    else:
        payload_json = payload
    conn = open_intent_registry_db(db_path)
    try:
        conn.execute(
            """
            INSERT INTO workspace_intents (
                agent_pid, agent_start_epoch, intent_id, declared_at_utc,
                payload_json, closed_at_utc, updated_at_utc
            ) VALUES (
                1, 1, ?, '2026-01-01T00:00:00Z', ?, NULL,
                '2026-01-01T00:00:00Z'
            )
            """,
            (intent_id, payload_json),
        )
        conn.commit()
    finally:
        conn.close()


def patch_cli_resolve_analytics_config(
    monkeypatch: pytest.MonkeyPatch,
    analytics_cli: object,
    config: object,
) -> None:
    monkeypatch.setattr(
        analytics_cli,
        "resolve_analytics_config",
        lambda _root: config,
    )
