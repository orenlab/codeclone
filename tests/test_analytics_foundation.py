# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from codeclone.analytics.agent_labels import map_agent_family
from codeclone.analytics.clustering.diagnostics import correlation_rate
from codeclone.analytics.clustering.sweep import iter_sweep_candidates
from codeclone.analytics.contracts import INTENT_REPRESENTATION_DESCRIPTION
from codeclone.analytics.corpus.adapters.intent_historical import (
    compute_source_digest,
    extract_historical_intent_items,
    materialize_corpus_item,
)
from codeclone.analytics.corpus.keys import (
    representation_key,
    snapshot_item_id,
    source_record_key,
)
from tests.fixtures.analytics.helpers import write_intent_declared_event


def _audit_db(root: Path) -> Path:
    path = root / ".codeclone" / "db" / "audit.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _seed_intent_repo(
    tmp_path: Path, *, description: str, audit_sequence: int = 1
) -> Path:
    """Create a repo root and write one intent.declared audit event."""
    root = tmp_path / "repo"
    root.mkdir()
    write_intent_declared_event(
        db_path=_audit_db(root),
        repo_root=root,
        intent_id="intent-a",
        description=description,
        audit_sequence=audit_sequence,
    )
    return root


def test_identity_keys() -> None:
    project_id = "proj-abc"
    intent_id = "intent-1"
    source_key = source_record_key(project_id=project_id, intent_id=intent_id)
    rep_key = representation_key(
        lane="intent",
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        representation_version="1",
        source_record_key_value=source_key,
    )
    snap_item = snapshot_item_id(snapshot_id="snap-1", representation_key_value=rep_key)
    assert len(source_key) == 64
    assert len(rep_key) == 64
    assert len(snap_item) == 64
    assert source_key != rep_key != snap_item


def test_registry_not_in_normalized_text(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    audit_db = _audit_db(root)
    write_intent_declared_event(
        db_path=audit_db,
        repo_root=root,
        intent_id="intent-a",
        description="Add analytics module",
    )
    items = extract_historical_intent_items(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
    )
    assert len(items) == 1
    before = materialize_corpus_item(
        snapshot_id="snap-1",
        lane="intent",
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        item=items[0],
    )
    overlay_item = replace(
        items[0],
        registry_overlay={"present": True, "status": "active"},
    )
    after = materialize_corpus_item(
        snapshot_id="snap-1",
        lane="intent",
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        item=overlay_item,
    )
    assert before[3] == after[3]
    assert before[6] == after[6]


def test_intent_adapter_audit_first(tmp_path: Path) -> None:
    root = _seed_intent_repo(tmp_path, description="First description")
    write_intent_declared_event(
        db_path=_audit_db(root),
        repo_root=root,
        intent_id="intent-a",
        description="Later description",
        audit_sequence=2,
    )
    items = extract_historical_intent_items(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
    )
    assert len(items) == 1
    assert items[0].representation_input.description == "First description"


def test_duplicate_declaration_conflict(tmp_path: Path) -> None:
    root = _seed_intent_repo(tmp_path, description="Alpha")
    write_intent_declared_event(
        db_path=_audit_db(root),
        repo_root=root,
        intent_id="intent-a",
        description="Beta",
        audit_sequence=2,
    )
    items = extract_historical_intent_items(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
    )
    description = items[0].provenance["description"]
    assert isinstance(description, dict)
    assert description["description_conflict"] is True


def test_source_digest_stable(tmp_path: Path) -> None:
    root = _seed_intent_repo(tmp_path, description="Stable intent")
    items = extract_historical_intent_items(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
    )
    digest_a = compute_source_digest(
        items=items,
        lane="intent",
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        representation_version="1",
        source_schema_versions={"audit": "4"},
    )
    digest_b = compute_source_digest(
        items=items,
        lane="intent",
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        representation_version="1",
        source_schema_versions={"audit": "4"},
    )
    assert digest_a == digest_b


def test_session_intent_never_in_corpus(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _audit_db(root)
    items = extract_historical_intent_items(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
    )
    assert items == ()


def test_correlation_sample_guard() -> None:
    cell = correlation_rate(numerator=2, denominator=4, min_sample_size=5)
    assert cell.insufficient_sample is True
    assert cell.rate is None


def test_sweep_effective_dedup() -> None:
    candidates = iter_sweep_candidates(n_samples=10, n_features=384)
    keys = [candidate.dedupe_key for candidate in candidates]
    assert len(keys) == len(set(keys))


def test_agent_family_mapping() -> None:
    assert map_agent_family("cursor-vscode") == "cursor"
    assert map_agent_family(None) == "unknown"
