# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from codeclone.audit.analysis_completed import _sequence
from codeclone.audit.events import AuditEvent, event_core_for_event
from codeclone.audit.writer import _event_core_json
from codeclone.cache.integrity import read_json_document
from codeclone.config.intent_registry import IntentRegistryConfigError
from codeclone.config.memory import IngestConfig
from codeclone.contracts import ExitCode
from codeclone.memory.experience.store import _facet_kind, _status
from codeclone.memory.ingest.paths import (
    resolve_contract_constants_paths,
    resolve_document_link_paths,
    resolve_mcp_tool_contradiction_sources,
    resolve_mcp_tool_schema_snapshot_path,
)
from codeclone.memory.trajectory.agents import (
    aggregate_agent_rows,
    trajectory_agent_label,
)
from codeclone.memory.trajectory.cli_render import (
    render_projection_run,
    render_trajectory_agents,
    render_trajectory_anomalies,
    render_trajectory_detail,
    render_trajectory_list,
    render_trajectory_search_results,
    render_trajectory_status,
)
from codeclone.memory.trajectory.models import (
    Trajectory,
    TrajectoryListItem,
    TrajectoryOutcome,
    TrajectoryProjectionRun,
    TrajectoryStep,
    TrajectorySubject,
)
from codeclone.surfaces.cli.observability import observability_main
from codeclone.surfaces.mcp.payloads import measure_payload
from codeclone.workspace_intent.gate import (
    HOOK_AUTHORIZE_FOREIGN_ENV,
    WorkspaceIntentRegistryUnavailable,
    _hook_authorizes_foreign_active,
    _include_record_in_hook_cleanup,
    list_unclosed_workspace_intents_for_hook_cleanup,
)
from tests.test_workspace_intents import _record
from tests.workspace_intent_gate_helpers import write_workspace_record


class _CapturePrinter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *objects: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(item) for item in objects))


def _projection_run(*, legacy: int = 0) -> TrajectoryProjectionRun:
    return TrajectoryProjectionRun(
        id="run-1",
        project_id="proj",
        repo_root_digest="digest",
        projection_version="2",
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:01:00Z",
        status="ok",
        workflows_seen=2,
        trajectories_created=1,
        trajectories_updated=0,
        trajectories_unchanged=1,
        legacy_event_count=legacy,
        message=None,
    )


def _trajectory(*, outcome: str = "accepted", agent: bool = True) -> Trajectory:
    subjects = (
        (
            TrajectorySubject(
                subject_kind="agent",
                subject_key="cursor-vscode/1.0.0",
                relation="actor",
            ),
        )
        if agent
        else ()
    )
    return Trajectory(
        id="traj-1",
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        intent_id="intent-a",
        primary_run_id="run1234567890abcdef",
        first_run_id="run1234567890abcdef",
        last_run_id="run1234567890abcdef",
        report_digest="a" * 64,
        outcome=cast(TrajectoryOutcome, outcome),
        quality_tier="verified",
        quality_score=90,
        labels=(),
        summary="workflow summary",
        trajectory_digest="b" * 64,
        source_event_stream_digest="c" * 64,
        projection_version="2",
        event_count=2,
        step_count=2,
        incident_count=1,
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:01:00Z",
        projected_at_utc="2026-01-01T00:01:00Z",
        updated_at_utc="2026-01-01T00:01:00Z",
        steps=(
            TrajectoryStep(
                step_index=0,
                audit_sequence=1,
                event_id="evt-1",
                event_type="intent.declared",
                status="active",
                run_id="run1234567890abcdef",
                report_digest=None,
                event_core_sha256="d" * 64,
                event_core_json="{}",
                summary="declared",
                created_at_utc="2026-01-01T00:00:00Z",
            ),
        ),
        subjects=subjects,
        evidence=(),
    )


def test_observability_cli_help_and_stdout_trace(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert observability_main([]) == int(ExitCode.CONTRACT_ERROR)
    assert "trace" in capsys.readouterr().out

    from codeclone.config.observability import ObservabilityConfig
    from codeclone.observability import bootstrap, operation, shutdown
    from codeclone.observability.models import OperationRecord
    from codeclone.observability.store.schema import (
        observability_store_path,
        open_observability_store,
    )
    from codeclone.observability.store.writer import write_operation

    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        with operation(name="cli.analyze", surface="cli"):
            pass
    finally:
        shutdown()
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        write_operation(
            conn,
            OperationRecord(
                operation_id="op-1",
                correlation_id="corr",
                surface="cli",
                name="cli.analyze",
                started_at_utc="2026-01-01T00:00:00Z",
                duration_ms=1.0,
                status="ok",
                spans=(),
            ),
        )
    finally:
        conn.close()

    code = observability_main(["trace", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == int(ExitCode.SUCCESS)
    assert '"operation_tree"' in out


def test_measure_payload_handles_unserializable_values() -> None:
    class _Bad:
        def __str__(self) -> str:
            raise TypeError("nope")

    bytes_size, tokens = measure_payload({"bad": _Bad()})
    assert bytes_size == 0
    assert tokens == 0


def test_cache_integrity_read_json_document_forwards_max_bytes(tmp_path: Path) -> None:
    path = tmp_path / "doc.json"
    path.write_text('{"ok": true}', encoding="utf-8")
    assert read_json_document(path, max_bytes=64) == {"ok": True}


def test_analysis_completed_sequence_helper() -> None:
    assert _sequence("not-a-list") == ()
    assert _sequence([1, 2]) == (1, 2)
    assert _sequence(42) == ()


def test_event_core_json_fallback_on_canonical_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    def _canonical_or_fallback(payload: object) -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise TypeError("cannot serialize")
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    monkeypatch.setattr(
        "codeclone.audit.writer._canonical_json",
        _canonical_or_fallback,
    )
    event = AuditEvent(
        event_type="intent.declared",
        severity="info",
        repo_root_digest="digest",
        agent_pid=1,
        agent_label="agent",
        status="active",
        payload={},
    )
    payload = json.loads(_event_core_json(event))
    assert payload["truncated"] is True
    assert payload["event_type"] == "intent.declared"
    assert event_core_for_event(event)["event_type"] == "intent.declared"


def test_workspace_hook_cleanup_resolves_env_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_intent_pid.is_agent_pid_alive",
        lambda _pid: True,
    )
    own_pid = os.getpid()
    own = replace(
        _record(intent_id="intent-own-env-001", status="active"),
        agent_pid=own_pid,
        agent_start_epoch=42,
    )
    write_workspace_record(tmp_path, own)
    monkeypatch.setenv("CODECLONE_HOOK_OWN_AGENT_PID", str(own_pid))
    monkeypatch.setenv("CODECLONE_HOOK_OWN_AGENT_START_EPOCH", "42")

    unclosed = list_unclosed_workspace_intents_for_hook_cleanup(tmp_path)

    assert len(unclosed) == 1
    assert unclosed[0].intent_id == "intent-own-env-001"


def test_workspace_hook_cleanup_registry_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_root: Path) -> object:
        raise ValueError("broken registry")

    monkeypatch.setattr(
        "codeclone.workspace_intent.gate.resolve_intent_registry_config",
        _boom,
    )
    with pytest.raises(WorkspaceIntentRegistryUnavailable, match="broken registry"):
        list_unclosed_workspace_intents_for_hook_cleanup(tmp_path)


def test_workspace_hook_include_record_edges() -> None:
    from codeclone.surfaces.mcp._workspace_intent_lifecycle import utc_now

    recoverable = replace(
        _record(intent_id="intent-rec-001", status="active"),
        agent_pid=os.getpid() + 5000,
        agent_label="cursor-vscode/dead",
    )
    now = utc_now()
    assert (
        _include_record_in_hook_cleanup(
            recoverable,
            own_pid=os.getpid(),
            own_start_epoch=1,
            recoverable_agent_label_prefix=None,
            include_foreign=False,
            now=now,
        )
        is False
    )
    assert (
        _include_record_in_hook_cleanup(
            recoverable,
            own_pid=os.getpid(),
            own_start_epoch=1,
            recoverable_agent_label_prefix="cursor-vscode/",
            include_foreign=False,
            now=now,
        )
        is True
    )


def test_hook_authorizes_foreign_active_env_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(HOOK_AUTHORIZE_FOREIGN_ENV, raising=False)
    assert _hook_authorizes_foreign_active() is True
    monkeypatch.setenv(HOOK_AUTHORIZE_FOREIGN_ENV, "maybe")
    assert _hook_authorizes_foreign_active() is False
    monkeypatch.setenv(HOOK_AUTHORIZE_FOREIGN_ENV, "off")
    assert _hook_authorizes_foreign_active() is False


def test_experience_store_private_validators() -> None:
    with pytest.raises(ValueError, match="unknown experience facet kind"):
        _facet_kind("not-a-facet")
    with pytest.raises(ValueError, match="unknown experience status"):
        _status("archived")


def test_trajectory_agents_aggregate_covers_failed_and_anomalies() -> None:
    assert trajectory_agent_label(_trajectory(agent=False)) is None
    violated = _trajectory(outcome="violated")
    rows = aggregate_agent_rows(
        (violated,),
        anomaly_by_id={"traj-1": ()},
    )
    assert rows[0].failed_outcome_count == 1
    assert rows[0].anomaly_count == 0
    assert rows[0].intent_count == 1


def test_trajectory_cli_render_populated_and_empty_paths() -> None:
    printer = _CapturePrinter()
    render_trajectory_status(
        console=printer,
        enabled=True,
        count=1,
        latest_run=_projection_run(legacy=3),
    )
    assert any("legacy events" in line for line in printer.lines)

    printer = _CapturePrinter()
    render_projection_run(console=printer, run=_projection_run(legacy=2))
    assert any("legacy audit events" in line for line in printer.lines)

    printer = _CapturePrinter()
    render_trajectory_list(console=printer, items=[])
    assert printer.lines == ["No trajectories found."]

    item = TrajectoryListItem(
        id="traj-1",
        workflow_id="intent:a",
        outcome="accepted",
        quality_tier="verified",
        quality_score=90,
        event_count=2,
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:01:00Z",
        summary="summary",
    )
    printer = _CapturePrinter()
    render_trajectory_list(console=printer, items=[item])
    assert any("traj-1" in line for line in printer.lines)

    printer = _CapturePrinter()
    render_trajectory_search_results(
        console=printer,
        query="recover",
        trajectories=[],
    )
    assert any("No matching trajectories" in line for line in printer.lines)

    printer = _CapturePrinter()
    render_trajectory_agents(console=printer, payload={"agents": []})
    assert any("No agent-labeled" in line for line in printer.lines)

    printer = _CapturePrinter()
    render_trajectory_agents(
        console=printer,
        payload={
            "agent_count": 1,
            "trajectory_count": 1,
            "unlabeled_trajectory_count": 0,
            "agents": [
                "not-a-mapping",
                {"agent_label": "agent", "trajectory_count": 1},
            ],
        },
    )
    assert any("agent" in line for line in printer.lines)

    printer = _CapturePrinter()
    render_trajectory_anomalies(
        console=printer,
        payload={
            "summary": {
                "trajectories_with_anomalies": 1,
                "anomaly_count": 1,
                "error_count": 1,
                "warn_count": 0,
            },
            "trajectories": [
                "skip",
                {
                    "trajectory_id": "traj-1",
                    "agent_label": "agent",
                    "outcome": "violated",
                    "quality_tier": "incident",
                    "anomalies": [
                        "skip",
                        {
                            "severity": "error",
                            "kind": "scope_violation",
                            "message": "bad scope",
                        },
                    ],
                },
            ],
        },
    )
    assert any("scope_violation" in line for line in printer.lines)

    printer = _CapturePrinter()
    trajectory = _trajectory()
    render_trajectory_detail(console=printer, trajectory=trajectory)
    joined = "\n".join(printer.lines)
    assert "workflow summary" in joined
    assert "labels:" not in joined


def test_ingest_path_resolvers_skip_missing_and_escape(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    ingest = IngestConfig(
        contract_constants_paths=("missing/contracts.py",),
        document_link_paths=("../escape.md",),
        mcp_tool_schema_snapshot_path="missing-tools.json",
        mcp_tool_count_doc_paths=("missing-doc.md",),
    )
    assert (
        resolve_contract_constants_paths(
            root_path=root,
            registry_paths=frozenset(),
            ingest=ingest,
        )
        == ()
    )
    assert (
        resolve_document_link_paths(
            root_path=root,
            registry_paths=frozenset({"docs/book/01.md"}),
            ingest=ingest,
        )
        == ()
    )
    assert resolve_mcp_tool_schema_snapshot_path(root_path=root, ingest=ingest) is None
    assert resolve_mcp_tool_contradiction_sources(root_path=root, ingest=ingest) is None


def test_intent_registry_path_outside_repo_raises(tmp_path: Path) -> None:
    from codeclone.config.intent_registry import resolve_intent_registry_db_path

    root = tmp_path / "repo"
    root.mkdir()
    outside = (tmp_path / "outside" / "intents.sqlite3").resolve()
    with pytest.raises(IntentRegistryConfigError, match="relative to the repository"):
        resolve_intent_registry_db_path(
            root_path=root,
            value=str(outside),
        )


def test_core_worker_signature_cache_handles_broken_callable() -> None:
    from codeclone.core import worker as core_worker

    core_worker._supported_process_file_kwarg_names.cache_clear()

    def _broken(*_args: object, **_kwargs: object) -> object:
        return None

    assert core_worker._supported_process_file_kwarg_names(_broken) is None
    core_worker._supported_process_file_kwarg_names.cache_clear()


def test_measure_payload_estimate_failure_uses_char_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_payload: object) -> object:
        raise TypeError("estimate failed")

    monkeypatch.setattr(
        "codeclone.surfaces.mcp.payloads.estimate_payload",
        _boom,
    )
    byte_size, tokens = measure_payload({"ok": True})
    assert byte_size > 0
    assert tokens > 0


def test_observability_cli_missing_store_and_file_outputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    code = observability_main(["trace", "--root", str(empty_root)])
    assert code == int(ExitCode.SUCCESS)
    assert "No observability store" in capsys.readouterr().out

    from codeclone.observability.models import OperationRecord
    from codeclone.observability.store.schema import (
        observability_store_path,
        open_observability_store,
    )
    from codeclone.observability.store.writer import write_operation

    repo = tmp_path / "repo"
    repo.mkdir()
    conn = open_observability_store(observability_store_path(repo))
    try:
        write_operation(
            conn,
            OperationRecord(
                operation_id="op-cli",
                correlation_id="op-cli",
                surface="cli",
                name="cli.analyze",
                started_at_utc="2026-01-01T00:00:00Z",
                duration_ms=1.0,
                status="ok",
                spans=(),
            ),
        )
    finally:
        conn.close()

    json_path = tmp_path / "trace.json"
    html_path = tmp_path / "trace.html"
    code = observability_main(
        [
            "trace",
            "--root",
            str(repo),
            "--json",
            str(json_path),
            "--html",
            str(html_path),
        ]
    )
    out = capsys.readouterr().out
    assert code == int(ExitCode.SUCCESS)
    assert json_path.is_file()
    assert html_path.is_file()
    assert f"Wrote {json_path}" in out
    assert f"Wrote {html_path}" in out


def test_render_html_format_helpers_and_semantic_row() -> None:
    from codeclone.observability.render_html import _bytes, _mb, _semantic_row, _tokens
    from codeclone.observability.views import SpanCostView

    assert _mb(None) == "—"
    assert "GB" in _mb(2048.0)
    assert "MB" in _mb(512.0)
    assert _bytes(None) == "—"
    assert "MB" in _bytes(1024 * 1024)
    assert "KB" in _bytes(2048)
    assert _bytes(12).endswith(" B")
    assert _tokens(None) == "—"
    assert _tokens(0) == "—"
    assert _tokens(1500).endswith("k")

    costly = SpanCostView(
        span_id="s1",
        name="memory.semantic.reindex",
        surface="memory",
        operation_id="op",
        operation_name="memory.projection.job",
        duration_ms=6000.0,
        no_op=True,
        reason_kind="schema_version_changed",
    )
    costly_html = _semantic_row(costly)
    assert "no-op · costly" in costly_html
    assert "schema_version_changed" in costly_html

    noop = replace(costly, duration_ms=10.0)
    assert "no-op" in _semantic_row(noop)
    assert "costly" not in _semantic_row(noop)

    productive = replace(noop, no_op=False, reason_kind=None)
    assert "productive" in _semantic_row(productive)


def test_observability_reader_epoch_ms_and_empty_correlation_filter(
    tmp_path: Path,
) -> None:
    from codeclone.observability.store.reader import _by_correlations, _epoch_ms
    from codeclone.observability.store.schema import (
        observability_store_path,
        open_observability_store,
    )

    assert _epoch_ms("") == 0.0
    assert _epoch_ms("not-a-date") == 0.0
    assert _epoch_ms("2026-01-01T00:00:00Z") > 0.0

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        assert _by_correlations(conn, []) == []
    finally:
        conn.close()


def test_pyproject_loader_symlink_and_invalid_ingest_table(tmp_path: Path) -> None:
    from codeclone.config.pyproject_loader import (
        ConfigValidationError,
        _validate_nested_ingest_table,
        load_pyproject_config,
        open_repo_config,
    )

    broken = tmp_path / "pyproject.toml"
    broken.symlink_to(tmp_path / "missing.toml")
    with pytest.raises(ConfigValidationError, match="must not be a symlink"):
        load_pyproject_config(tmp_path)

    real = tmp_path / "real.toml"
    real.write_text("[tool.codeclone]\n", encoding="utf-8")
    broken.unlink()
    link = tmp_path / "pyproject.toml"
    link.symlink_to(real)
    with pytest.raises(ConfigValidationError, match="must not be a symlink"):
        open_repo_config(tmp_path)

    with pytest.raises(ConfigValidationError, match="must be object"):
        _validate_nested_ingest_table(
            ingest_obj="not-a-table",
            config_path=tmp_path / "pyproject.toml",
        )


def test_resolve_semantic_index_writer_disabled_returns_none() -> None:
    from codeclone.config.memory import SemanticConfig
    from codeclone.memory.semantic import resolve_semantic_index_writer

    assert resolve_semantic_index_writer(SemanticConfig(enabled=False)) is None


def test_semantic_retrieval_hydrate_trajectory_edges() -> None:
    from codeclone.memory.retrieval.semantic import _hydrate_trajectory
    from codeclone.memory.semantic.models import SemanticHit

    hit = SemanticHit(source_id="traj-1", source="trajectory", score=0.4)

    class _StoreWithoutTrajectoryApi:
        pass

    assert _hydrate_trajectory(hit, _StoreWithoutTrajectoryApi(), 80) is None

    class _StoreMissingTrajectory:
        def find_trajectory(self, _trajectory_id: str) -> None:
            return None

    assert _hydrate_trajectory(hit, _StoreMissingTrajectory(), 80) is None


def test_execute_trajectory_rebuild_incremental_mode(tmp_path: Path) -> None:
    from codeclone.config.memory import resolve_memory_config
    from codeclone.memory.trajectory.rebuild_workflow import execute_trajectory_rebuild

    from .memory_fixtures import memory_store, seed_trajectory_audit_workflow

    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = root / ".codeclone" / "db" / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        config = resolve_memory_config(root)
        full = execute_trajectory_rebuild(
            root_path=root,
            config=config,
            store=store,
            project=project,
        )
        assert full["status"] == "ok"
        assert full["mode"] == "full"
        incremental = execute_trajectory_rebuild(
            root_path=root,
            config=config,
            store=store,
            project=project,
            incremental_after_event_core_id=1,
        )
        assert incremental["status"] == "ok"
        assert incremental["mode"] == "incremental"


def test_memory_state_path_validation_errors(tmp_path: Path) -> None:
    from codeclone.config.memory import _resolve_memory_state_path

    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(TypeError, match="must resolve to a string path"):
        _resolve_memory_state_path(
            key="memory.semantic.index_path",
            value=123,
            root_path=root,
        )
    with pytest.raises(ValueError, match="must stay under the repository root"):
        _resolve_memory_state_path(
            key="memory.semantic.index_path",
            value="../outside.lance",
            root_path=root,
        )


def test_hook_authorizes_foreign_active_truthy_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(HOOK_AUTHORIZE_FOREIGN_ENV, "yes")
    assert _hook_authorizes_foreign_active() is True


def test_hydrate_trajectory_hits_detail_levels(tmp_path: Path) -> None:
    from codeclone.memory.retrieval import service as retrieval_service
    from codeclone.memory.semantic.models import SemanticHit

    from .memory_fixtures import memory_store, seed_trajectory_audit_workflow

    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        trajectory = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        ).trajectories[0]
        hit = SemanticHit(source_id=trajectory.id, source="trajectory", score=0.5)
        compact = retrieval_service._hydrate_trajectory_hits(
            store,
            project_id=project.id,
            hits=[hit],
            detail_level="compact",
        )
        full = retrieval_service._hydrate_trajectory_hits(
            store,
            project_id=project.id,
            hits=[hit],
            detail_level="full",
        )
        assert compact and full
        assert compact[0]["semantic_score"] == 0.5
        assert full[0]["semantic_score"] == 0.5
        assert "steps" in full[0]


def test_mcp_payload_paginate_and_finding_resolution() -> None:
    from codeclone.surfaces.mcp.payloads import (
        PageWindow,
        paginate,
        resolve_finding_id,
        short_id,
    )

    window = paginate([1, 2, 3, 4], offset=1, limit=2, max_limit=10)
    assert isinstance(window, PageWindow)
    assert window.items == [2, 3]
    assert window.next_offset == 3

    tail = paginate([9], offset=0, limit=5, max_limit=10)
    assert tail.next_offset is None

    canonical = {"finding-abcdef12": "short"}
    assert (
        resolve_finding_id(
            canonical_to_short=canonical,
            short_to_canonical={"short": "finding-abcdef12"},
            finding_id="finding-abcdef12",
        )
        == "finding-abcdef12"
    )
    assert (
        resolve_finding_id(
            canonical_to_short=canonical,
            short_to_canonical={"short": "finding-abcdef12"},
            finding_id="short",
        )
        == "finding-abcdef12"
    )
    assert (
        resolve_finding_id(
            canonical_to_short=canonical,
            short_to_canonical={},
            finding_id="missing",
        )
        is None
    )
    assert short_id("finding-abcdef12", length=8) == "finding-"


def test_workspace_hook_cleanup_sqlite_load_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Config:
        backend = "sqlite"
        storage_path = Path(".codeclone/db/intents.sqlite3")

    monkeypatch.setattr(
        "codeclone.workspace_intent.gate.resolve_intent_registry_config",
        lambda _root: _Config(),
    )

    def _load_fail(*_args: object, **_kwargs: object) -> object:
        raise OSError("cannot read sqlite")

    monkeypatch.setattr(
        "codeclone.workspace_intent.gate._load_registry_records_read_only",
        _load_fail,
    )
    with pytest.raises(WorkspaceIntentRegistryUnavailable, match="cannot read sqlite"):
        list_unclosed_workspace_intents_for_hook_cleanup(tmp_path)


def test_workspace_ownership_authorizes_foreign_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
    from codeclone.workspace_intent import gate as gate_mod

    monkeypatch.setattr(gate_mod, "_hook_authorizes_foreign_active", lambda: True)
    assert (
        gate_mod._ownership_authorizes_hook(
            workspace_intents.IntentOwnership.FOREIGN_ACTIVE,
            liveness=workspace_intents.PidLiveness.ALIVE,
        )
        is True
    )
    monkeypatch.setattr(gate_mod, "_hook_authorizes_foreign_active", lambda: False)
    assert (
        gate_mod._ownership_authorizes_hook(
            workspace_intents.IntentOwnership.FOREIGN_ACTIVE,
            liveness=workspace_intents.PidLiveness.ALIVE,
        )
        is False
    )


def test_agent_pid_liveness_honors_monkeypatched_boolean_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.surfaces.mcp import _workspace_intent_pid as pid_mod
    from codeclone.surfaces.mcp._workspace_intent_lifecycle import PidLiveness

    monkeypatch.setattr(pid_mod, "is_agent_pid_alive", lambda _pid: False)
    assert pid_mod.agent_pid_liveness(123) is PidLiveness.DEAD


def test_record_elapsed_span_noop_without_active_operation(tmp_path: Path) -> None:
    from codeclone.config.observability import ObservabilityConfig
    from codeclone.observability import bootstrap, record_elapsed_span, shutdown

    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        record_elapsed_span(
            "orphan-span",
            started_at_utc="2026-01-01T00:00:00Z",
            duration_ms=1.0,
        )
    finally:
        shutdown()


def test_staleness_anchor_drift_status_edges(tmp_path: Path) -> None:
    from codeclone.memory.models import MemorySubject, generate_memory_id
    from codeclone.memory.staleness import _evaluate_anchor_drift_status

    from .memory_fixtures import make_module_record, memory_store

    with memory_store(tmp_path) as (root, project, store, _db_path):
        record = replace(
            make_module_record(project.id, "pkg.mod"),
            created_at_commit="abc123",
            code_fingerprint="fp-1",
            status="active",
        )
        store.upsert_record(record)
        subject = MemorySubject(
            id=generate_memory_id(prefix="subj"),
            memory_id=record.id,
            subject_kind="path",
            subject_key="pkg/missing.py",
            relation="about",
        )
        store.write_subject(subject)
        assert (
            _evaluate_anchor_drift_status(
                record,
                anchor_subject=subject,
                root_path=root,
            )
            == "historical"
        )
        historical = replace(record, status="historical")
        assert (
            _evaluate_anchor_drift_status(
                historical,
                anchor_subject=subject,
                root_path=root,
            )
            is None
        )
        stale_record = replace(
            record, status="stale", stale_reason="subject_fingerprint_drift"
        )
        assert (
            _evaluate_anchor_drift_status(
                stale_record,
                anchor_subject=subject,
                root_path=root,
            )
            == "historical"
        )


def test_instance_methods_decorator_and_base_name_fallbacks() -> None:
    import ast

    import codeclone.findings.design.instance_methods as instance_methods_mod

    assert instance_methods_mod._simple_decorator_name(ast.Constant(value=1)) == ""
    assert instance_methods_mod._simple_base_name(ast.Constant(value=1)) == ""


def test_workflow_audit_emit_and_digest_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from codeclone.surfaces.cli import workflow as cli_workflow

    class _Args:
        audit_enabled = True

    cli_workflow._emit_cli_analysis_completed_if_enabled(
        args=_Args(),
        root_path=tmp_path,
        report_document="not-a-dict",
        new_func_count=0,
        new_block_count=0,
    )
    cli_workflow._emit_cli_analysis_completed_if_enabled(
        args=_Args(),
        root_path=tmp_path,
        report_document={"integrity": {"digest": {"value": ""}}},
        new_func_count=0,
        new_block_count=0,
    )

    def _boom(**_kwargs: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(
        "codeclone.audit.analysis_completed.emit_analysis_completed_from_report",
        _boom,
    )
    cli_workflow._emit_cli_analysis_completed_if_enabled(
        args=_Args(),
        root_path=tmp_path,
        report_document={"integrity": {"digest": {"value": "a" * 64}}},
        new_func_count=1,
        new_block_count=0,
    )

    assert cli_workflow._report_digest_from_document({}) == ""
    assert (
        cli_workflow._report_digest_from_document(
            {"integrity": {"digest": "not-a-mapping"}}
        )
        == ""
    )

    monkeypatch.setattr(sys, "argv", ["codeclone", "observability"])
    with pytest.raises(SystemExit):
        cli_workflow.main()
    monkeypatch.setattr(sys, "argv", ["codeclone", "memory", "--help"])
    with pytest.raises(SystemExit):
        cli_workflow.main()


def test_observability_profile_open_fds_degrades_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from unittest.mock import MagicMock

    from codeclone.observability.profile import build_profile_sample

    process = MagicMock()
    process.memory_info.return_value = MagicMock(rss=1024 * 1024)
    process.cpu_times.return_value = MagicMock(user=0.1, system=0.2)
    process.num_fds.side_effect = OSError("unsupported")
    process.num_threads.return_value = 3
    mock_psutil = MagicMock()
    mock_psutil.Process.return_value = process
    monkeypatch.setitem(sys.modules, "psutil", mock_psutil)

    sample = build_profile_sample((512 * 1024, 0.0, 0.0))
    assert sample is not None
    assert sample.open_fds is None
