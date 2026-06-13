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

from codeclone.audit.events import EVENT_INTENT_DECLARED, repo_root_digest
from codeclone.audit.schema import open_audit_db
from codeclone.memory.schema import ensure_schema as ensure_memory_schema


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
