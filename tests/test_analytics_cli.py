# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from argparse import Namespace
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from codeclone.analytics.capabilities import CapabilityStatus
from codeclone.analytics.contracts import (
    ClusterAssignmentRecord,
    ClusteringRunRecord,
    ClusteringRunStatus,
    CorpusSnapshotRecord,
)
from codeclone.analytics.embedding.generation import EmbeddingBatchResult
from codeclone.analytics.exceptions import (
    AnalyticsCapabilityError,
    AnalyticsWorkflowError,
)
from codeclone.analytics.store.protocols import SnapshotBuildResult
from codeclone.analytics.store.sqlite import SqliteCorpusAnalyticsStore
from codeclone.analytics.workflow import BuildResult
from codeclone.contracts import ExitCode
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)
from codeclone.surfaces.cli import analytics as analytics_cli
from tests.fixtures.analytics.helpers import write_intent_declared_event


def _snapshot() -> CorpusSnapshotRecord:
    return CorpusSnapshotRecord(
        snapshot_id="snapshot",
        lane="intent",
        representation_kind="intent.description.v1",
        representation_version="2",
        source_stores_json="{}",
        source_schema_versions_json="{}",
        record_count=2,
        source_digest="digest",
        created_at_utc="2026-01-01T00:00:00Z",
    )


def _run(
    run_id: str = "run",
    *,
    status: str = "completed",
) -> ClusteringRunRecord:
    return ClusteringRunRecord(
        clustering_run_id=run_id,
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        requested_parameters_json="{}",
        effective_parameters_json="{}",
        random_seed=42,
        run_digest="digest",
        recommended_by_heuristic=True,
        selected_by_maintainer=False,
        status=cast(ClusteringRunStatus, status),
        created_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:00:01Z",
        error_message=None,
    )


class _ReadStore:
    def __init__(self) -> None:
        self.snapshot: CorpusSnapshotRecord | None = _snapshot()
        self.runs: tuple[ClusteringRunRecord, ...] = (_run(),)
        self.assignments = (
            ClusterAssignmentRecord("run", "noise", -1, 0.1, "noise-digest"),
            ClusterAssignmentRecord("run", "clustered", 0, 0.9, "cluster-digest"),
        )
        self.closed = False

    def get_snapshot(self, _snapshot_id: str) -> CorpusSnapshotRecord | None:
        return self.snapshot

    def list_clustering_runs(
        self,
        *,
        snapshot_id: str,
        embedding_generation_id: str | None = None,
    ) -> tuple[ClusteringRunRecord, ...]:
        assert snapshot_id == "snapshot"
        assert embedding_generation_id in {None, "embedding"}
        return self.runs

    def get_clustering_run(self, run_id: str) -> ClusteringRunRecord | None:
        return next(
            (run for run in self.runs if run.clustering_run_id == run_id),
            None,
        )

    def list_assignments(
        self,
        _run_id: str,
    ) -> tuple[ClusterAssignmentRecord, ...]:
        return self.assignments

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def quiet_cli_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def fake_operation(**_kwargs: object) -> Iterator[None]:
        yield

    monkeypatch.setattr(analytics_cli, "bootstrap", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(analytics_cli, "shutdown", lambda: None)
    monkeypatch.setattr(analytics_cli, "operation", fake_operation)


def test_analytics_namespace_is_direct() -> None:
    parser = analytics_cli._build_parser()
    help_text = parser.format_help()

    assert help_text.startswith("usage: codeclone analytics")
    assert " analytics corpus " not in help_text
    assert set(analytics_cli._COMMAND_HANDLERS) == {
        "build",
        "cluster",
        "cluster-show",
        "clusters",
        "embed",
        "outliers",
        "snapshot",
    }


def test_representation_and_capability_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert analytics_cli._representation_kind("description").endswith("description.v1")
    assert analytics_cli._representation_kind("description_with_frame").endswith(
        "description_with_frame.v1"
    )
    with pytest.raises(AnalyticsWorkflowError, match="unsupported representation"):
        analytics_cli._representation_kind("unknown")

    monkeypatch.setattr(
        analytics_cli,
        "check_capability",
        lambda _capability: CapabilityStatus(False, ("fastembed", "lancedb")),
    )
    with pytest.raises(AnalyticsCapabilityError, match="fastembed, lancedb"):
        analytics_cli._require_capability("embed")


def test_cluster_missing_ids_returns_contract_error_without_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = analytics_cli.analytics_main(["cluster", "--root", str(tmp_path)])

    captured = capsys.readouterr()
    assert code == int(ExitCode.CONTRACT_ERROR)
    assert "--snapshot-id and --embedding-generation-id are required" in captured.err
    assert "Traceback" not in captured.err


def test_use_recommended_requires_sweep_before_capability_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        analytics_cli,
        "_require_capability",
        lambda _capability: pytest.fail("capability check must not run"),
    )

    code = analytics_cli.analytics_main(
        ["build", "--root", str(tmp_path), "--use-recommended"]
    )

    captured = capsys.readouterr()
    assert code == int(ExitCode.CONTRACT_ERROR)
    assert "--use-recommended requires --sweep" in captured.err
    assert not (tmp_path / ".codeclone").exists()


def test_snapshot_stdout_is_json_and_bootstrap_precedes_handler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []

    @contextmanager
    def fake_operation(**_kwargs: object) -> Iterator[None]:
        events.append("operation")
        yield

    monkeypatch.setattr(
        analytics_cli,
        "bootstrap",
        lambda *_args, **_kwargs: events.append("bootstrap"),
    )
    monkeypatch.setattr(analytics_cli, "shutdown", lambda: events.append("shutdown"))
    monkeypatch.setattr(analytics_cli, "operation", fake_operation)
    monkeypatch.setattr(analytics_cli, "_require_capability", lambda _capability: None)

    def fake_snapshot(**_kwargs: object) -> SnapshotBuildResult:
        events.append("snapshot")
        return SnapshotBuildResult(
            snapshot_id="snap-1",
            source_digest="digest-1",
            record_count=3,
        )

    monkeypatch.setattr(
        analytics_cli,
        "run_snapshot",
        fake_snapshot,
    )

    code = analytics_cli.analytics_main(["snapshot", "--root", str(tmp_path)])

    payload = json.loads(capsys.readouterr().out)
    assert code == int(ExitCode.SUCCESS)
    assert payload == {
        "record_count": 3,
        "snapshot_id": "snap-1",
        "source_digest": "digest-1",
    }
    assert events == ["bootstrap", "operation", "snapshot", "shutdown"]


def test_snapshot_observability_captures_span_and_db_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_intent_declared_event(
        db_path=tmp_path / ".codeclone/db/audit.sqlite3",
        repo_root=tmp_path,
        intent_id="intent-a",
        description="Observe analytics snapshot",
    )
    monkeypatch.setenv("CODECLONE_OBSERVABILITY_ENABLED", "1")
    monkeypatch.setattr(
        "codeclone.analytics.corpus.snapshot.resolve_memory_db_path",
        lambda _root: tmp_path / ".codeclone/memory/missing.sqlite3",
    )

    code = analytics_cli.analytics_main(["snapshot", "--root", str(tmp_path)])

    assert code == int(ExitCode.SUCCESS)
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        operation_row = conn.execute(
            "SELECT name, status FROM platform_operations"
        ).fetchone()
        span_row = conn.execute(
            "SELECT name, counters_json FROM platform_spans "
            "WHERE name='analytics.snapshot'"
        ).fetchone()
    finally:
        conn.close()
    assert operation_row == ("cli.analytics.snapshot", "ok")
    assert span_row is not None
    counters = json.loads(span_row[1])
    assert counters["db_queries"] > 0


def test_snapshot_command_writes_atomic_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(analytics_cli, "_require_capability", lambda _value: None)
    monkeypatch.setattr(
        analytics_cli,
        "run_snapshot",
        lambda **_kwargs: SnapshotBuildResult("snapshot", "digest", 2),
    )
    output = tmp_path / "nested" / "snapshot.json"
    code = analytics_cli._run_snapshot_command(
        Namespace(representation="description", output_json=output),
        tmp_path,
    )
    assert code == ExitCode.SUCCESS
    assert json.loads(output.read_text(encoding="utf-8"))["snapshot_id"] == "snapshot"


def test_embed_and_cluster_commands_emit_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    capabilities: list[str] = []
    monkeypatch.setattr(
        analytics_cli,
        "_require_capability",
        lambda value: capabilities.append(value),
    )
    monkeypatch.setattr(
        analytics_cli,
        "run_embed",
        lambda **_kwargs: EmbeddingBatchResult("embedding", 2),
    )
    assert (
        analytics_cli._run_embed_command(
            Namespace(snapshot_id="snapshot"),
            tmp_path,
        )
        == ExitCode.SUCCESS
    )
    assert json.loads(capsys.readouterr().out) == {
        "embedding_generation_id": "embedding",
        "item_count": 2,
    }

    selected: list[str] = []
    monkeypatch.setattr(
        analytics_cli,
        "select_cluster_run",
        lambda **kwargs: selected.append(str(kwargs["clustering_run_id"])),
    )
    assert (
        analytics_cli._run_cluster_command(
            Namespace(
                select_run="run",
                snapshot_id=None,
                embedding_generation_id=None,
                sweep=False,
            ),
            tmp_path,
        )
        == ExitCode.SUCCESS
    )
    assert selected == ["run"]
    assert json.loads(capsys.readouterr().out) == {"selected_run_id": "run"}

    monkeypatch.setattr(
        analytics_cli,
        "run_clustering",
        lambda **_kwargs: ("run-a", "run-b"),
    )
    assert (
        analytics_cli._run_cluster_command(
            Namespace(
                select_run=None,
                snapshot_id="snapshot",
                embedding_generation_id="embedding",
                sweep=True,
            ),
            tmp_path,
        )
        == ExitCode.SUCCESS
    )
    assert json.loads(capsys.readouterr().out) == {
        "clustering_run_ids": ["run-a", "run-b"]
    }
    assert capabilities == ["embed", "base", "cluster"]


def test_build_command_runs_exports_and_prints_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(analytics_cli, "_require_capability", lambda _value: None)
    result = BuildResult("snapshot", "embedding", ("run",), "run")
    monkeypatch.setattr(analytics_cli, "run_build", lambda **_kwargs: result)
    exported: list[BuildResult] = []
    monkeypatch.setattr(
        analytics_cli,
        "_write_build_exports",
        lambda **kwargs: exported.append(kwargs["build_result"]),
    )
    code = analytics_cli._run_build_command(
        Namespace(
            use_recommended=True,
            sweep=True,
            representation="description_with_frame",
            json_out=tmp_path / "report.json",
            html_out=None,
        ),
        tmp_path,
    )
    assert code == ExitCode.SUCCESS
    assert exported == [result]
    assert json.loads(capsys.readouterr().out)["recommended_run_id"] == "run"


def test_clusters_command_rejects_unknown_snapshot_and_lists_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(analytics_cli, "_require_capability", lambda _value: None)
    config = SimpleNamespace(db_path=tmp_path / "analytics.sqlite3")
    monkeypatch.setattr(analytics_cli, "resolve_analytics_config", lambda _root: config)
    store = _ReadStore()
    monkeypatch.setattr(
        SqliteCorpusAnalyticsStore,
        "open_readonly",
        lambda _path: store,
    )
    assert (
        analytics_cli._run_clusters_command(
            Namespace(snapshot_id="snapshot"),
            tmp_path,
        )
        == ExitCode.SUCCESS
    )
    assert json.loads(capsys.readouterr().out) == [
        {
            "clustering_run_id": "run",
            "recommended_by_heuristic": True,
            "selected_by_maintainer": False,
            "status": "completed",
        }
    ]
    assert store.closed is True

    missing = _ReadStore()
    missing.snapshot = None
    monkeypatch.setattr(
        SqliteCorpusAnalyticsStore,
        "open_readonly",
        lambda _path: missing,
    )
    with pytest.raises(AnalyticsWorkflowError, match="unknown snapshot"):
        analytics_cli._run_clusters_command(
            Namespace(snapshot_id="missing"),
            tmp_path,
        )
    assert missing.closed is True


def test_cluster_show_supports_stdout_and_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(analytics_cli, "_require_capability", lambda _value: None)
    monkeypatch.setattr(
        analytics_cli,
        "resolve_analytics_config",
        lambda _root: SimpleNamespace(db_path=tmp_path / "analytics.sqlite3"),
    )
    stores: list[_ReadStore] = []

    def open_store(_path: Path) -> _ReadStore:
        store = _ReadStore()
        stores.append(store)
        return store

    monkeypatch.setattr(
        SqliteCorpusAnalyticsStore,
        "open_readonly",
        open_store,
    )
    monkeypatch.setattr(
        analytics_cli,
        "export_clustering_json",
        lambda **_kwargs: '{"run":"run"}\n',
    )
    assert (
        analytics_cli._run_cluster_show_command(
            Namespace(snapshot_id="snapshot", run_id="run", output=None),
            tmp_path,
        )
        == ExitCode.SUCCESS
    )
    assert capsys.readouterr().out == '{"run":"run"}\n'
    output = tmp_path / "nested" / "run.json"
    assert (
        analytics_cli._run_cluster_show_command(
            Namespace(snapshot_id="snapshot", run_id="run", output=output),
            tmp_path,
        )
        == ExitCode.SUCCESS
    )
    assert output.read_text(encoding="utf-8") == '{"run":"run"}\n'
    assert all(store.closed for store in stores)


def test_outliers_command_validates_run_and_filters_noise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(analytics_cli, "_require_capability", lambda _value: None)
    monkeypatch.setattr(
        analytics_cli,
        "resolve_analytics_config",
        lambda _root: SimpleNamespace(db_path=tmp_path / "analytics.sqlite3"),
    )
    store = _ReadStore()
    monkeypatch.setattr(
        SqliteCorpusAnalyticsStore,
        "open_readonly",
        lambda _path: store,
    )
    validated: list[str] = []
    monkeypatch.setattr(
        analytics_cli,
        "validate_persisted_run",
        lambda **kwargs: validated.append(str(kwargs["clustering_run_id"])),
    )
    assert (
        analytics_cli._run_outliers_command(
            Namespace(snapshot_id="snapshot", run_id="run"),
            tmp_path,
        )
        == ExitCode.SUCCESS
    )
    assert validated == ["run"]
    assert json.loads(capsys.readouterr().out) == {"noise_items": ["noise"]}
    assert store.closed is True


def test_build_export_routing_and_missing_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(db_path=tmp_path / "analytics.sqlite3")
    monkeypatch.setattr(analytics_cli, "resolve_analytics_config", lambda _root: config)
    store = _ReadStore()
    monkeypatch.setattr(
        SqliteCorpusAnalyticsStore,
        "open_readonly",
        lambda _path: store,
    )
    monkeypatch.setattr(
        analytics_cli,
        "export_sweep_comparison_json",
        lambda **_kwargs: '{"kind":"sweep"}\n',
    )
    monkeypatch.setattr(
        analytics_cli,
        "render_analytics_html",
        lambda **kwargs: f"<html>{kwargs['comparison_only']}</html>",
    )
    args = Namespace(
        json_out=tmp_path / "nested" / "sweep.json",
        html_out=tmp_path / "nested" / "sweep.html",
        sweep=True,
        use_recommended=False,
    )
    analytics_cli._write_build_exports(
        args=args,
        root=tmp_path,
        build_result=BuildResult("snapshot", "embedding", ("run",), None),
    )
    assert json.loads(args.json_out.read_text(encoding="utf-8")) == {"kind": "sweep"}
    assert args.html_out.read_text(encoding="utf-8") == "<html>True</html>"

    store.snapshot = None
    with pytest.raises(AnalyticsWorkflowError, match="snapshot missing"):
        analytics_cli._write_build_exports(
            args=args,
            root=tmp_path,
            build_result=BuildResult("snapshot", "embedding", ("run",), None),
        )
    store.snapshot = _snapshot()
    store.runs = ()
    with pytest.raises(AnalyticsWorkflowError, match="clustering run missing"):
        analytics_cli._write_build_exports(
            args=args,
            root=tmp_path,
            build_result=BuildResult("snapshot", "embedding", ("run",), None),
        )


def test_analytics_main_handles_invalid_root_and_expected_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    quiet_cli_runtime: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing"
    assert (
        analytics_cli.analytics_main(["snapshot", "--root", str(missing)])
        == ExitCode.CONTRACT_ERROR
    )
    assert "not a directory" in capsys.readouterr().err

    monkeypatch.setattr(
        analytics_cli,
        "_COMMAND_HANDLERS",
        {
            **analytics_cli._COMMAND_HANDLERS,
            "snapshot": lambda _args, _root: (_ for _ in ()).throw(
                ValueError("expected failure")
            ),
        },
    )
    assert (
        analytics_cli.analytics_main(["snapshot", "--root", str(tmp_path)])
        == ExitCode.CONTRACT_ERROR
    )
    assert "expected failure" in capsys.readouterr().err
