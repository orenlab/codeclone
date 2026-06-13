# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.trajectory.export import (
    export_trajectories_jsonl,
    resolve_export_output_path,
)
from codeclone.memory.trajectory.profiles import resolve_export_profile

from .memory_fixtures import memory_store, seed_trajectory_audit_workflow


def test_export_disabled_by_default(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        config = resolve_memory_config(root)
        out = tmp_path / "out.jsonl"
        with pytest.raises(MemoryContractError, match="disabled"):
            export_trajectories_jsonl(
                store=store,
                project=project,
                root_path=root,
                config=config,
                profile_name="agent-change-control-v1",
                output_path=out,
            )


def test_export_writes_deterministic_jsonl(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(
            root=root, audit_db=audit_db, scope_path="pkg/service.py"
        )
        store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        config = resolve_memory_config(root)
        enabled = replace(config, trajectory_export_enabled=True)
        out = tmp_path / "export.jsonl"
        first = export_trajectories_jsonl(
            store=store,
            project=project,
            root_path=root,
            config=enabled,
            profile_name="agent-change-control-v1",
            output_path=out,
        )
        second = export_trajectories_jsonl(
            store=store,
            project=project,
            root_path=root,
            config=enabled,
            profile_name="agent-change-control-v1",
            output_path=out,
        )

    assert first.records_written == second.records_written
    assert out.read_text(encoding="utf-8") == out.read_text(encoding="utf-8")
    assert first.manifest["profile"] == "agent-change-control-v1"
    line = out.read_text(encoding="utf-8").strip().splitlines()[0]
    payload = json.loads(line)
    assert payload["profile"] == "agent-change-control-v1"
    assert payload["schema_version"] == "2"
    assert "digests" in payload
    assert "context" in payload
    assert "citations" in payload
    assert "/Users/" not in json.dumps(payload)


def test_unsupported_profile_fails() -> None:
    with pytest.raises(ValueError, match="Unsupported trajectory export profile"):
        resolve_export_profile("missing-profile")


def test_external_output_requires_explicit_opt_in(tmp_path: Path) -> None:
    with (
        memory_store(tmp_path) as (root, _project, _store, _db_path),
        pytest.raises(MemoryContractError, match="escapes repository root"),
    ):
        resolve_export_output_path(
            root_path=root,
            raw_path="/tmp/codeclone-export.jsonl",
            allow_external_out=False,
        )


def test_jsonl_accumulator_enforces_record_and_file_limits() -> None:
    from codeclone.memory.trajectory.export import _JsonlExportAccumulator

    accumulator = _JsonlExportAccumulator()
    assert accumulator.try_append("oversized", record_limit=2, file_limit=100) is False
    assert accumulator.truncated_records == 1

    assert accumulator.try_append("ok", record_limit=10, file_limit=2) is False
    assert accumulator.records_written == 0

    assert accumulator.try_append("ok", record_limit=10, file_limit=10) is True
    assert accumulator.lines == ["ok"]


def test_parse_contract_constants_and_patch_trail_projector_edges(
    tmp_path: Path,
) -> None:
    from codeclone.memory.ingest.extractors import _parse_contract_constants
    from codeclone.memory.trajectory.patch_trail_projector import (
        project_patch_trail_from_audit,
    )

    from .test_memory_trajectory_projector import _record

    broken = tmp_path / "broken.py"
    broken.write_text("def (\n", encoding="utf-8")
    assert _parse_contract_constants(broken) == {}

    constants = tmp_path / "constants.py"
    constants.write_text(
        "CACHE_VERSION = 2\nIGNORED = 1\n",
        encoding="utf-8",
    )
    parsed = _parse_contract_constants(constants)
    assert parsed.get("CACHE_VERSION") == "2"

    assert project_patch_trail_from_audit(records=(), repo_root_digest="digest") is None
    non_intent = replace(
        _record(1, "intent.declared", status="active", scope_paths=["pkg/a.py"]),
        workflow_id="analysis:run-1",
    )
    assert (
        project_patch_trail_from_audit(
            records=(non_intent,),
            repo_root_digest="digest",
        )
        is None
    )


def test_patch_trail_projector_additional_audit_branches() -> None:
    from codeclone.audit.events import EVENT_INTENT_DECLARED
    from codeclone.memory.trajectory.patch_trail_projector import (
        _apply_audit_record,
        _WorkflowAuditState,
        project_patch_trail_from_audit,
    )

    from .test_memory_trajectory_projector import _record

    state = _WorkflowAuditState()
    _apply_audit_record(
        state,
        replace(
            _record(1, EVENT_INTENT_DECLARED, status="active"), audit_sequence=None
        ),
    )
    assert state.declared_files == ()

    assert (
        project_patch_trail_from_audit(
            records=(_record(1, EVENT_INTENT_DECLARED, status="active"),),
            repo_root_digest="digest",
        )
        is None
    )


def test_serialize_patch_trail_summary_from_computed_trail() -> None:
    from codeclone.memory.trajectory.patch_trail import compute_patch_trail
    from codeclone.memory.trajectory.retrieval import serialize_patch_trail_summary

    from .test_memory_trajectory_coverage import _patch_trail_inputs

    trail = compute_patch_trail(_patch_trail_inputs())
    summary = serialize_patch_trail_summary(
        trail.to_payload(detail_level="summary"),
    )
    assert summary is not None
    assert summary["verification_status"] == "accepted"
