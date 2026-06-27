# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from codeclone.audit import EVENT_RECEIPT_CREATED, AuditEvent
from codeclone.audit.analysis_completed import ANALYSIS_SOURCE_CLI
from codeclone.audit.reader import (
    AnalysisRunSnapshot,
    _analysis_payload_from_json,
    _analysis_run_source_label,
    _short_run_id,
    lookup_review_receipt,
    read_audit_summary,
    read_latest_analysis_run,
)
from codeclone.audit.validation import (
    AuditConfigError,
    AuditReadError,
    AuditValidationError,
    EventRow,
    resolve_audit_path,
    validate_event_row,
)
from codeclone.audit.writer import SqliteAuditWriter

from .audit_fixtures import write_compact_analysis_completed_event


def _write_cli_analysis_event(tmp_path: Path) -> Path:
    return write_compact_analysis_completed_event(
        tmp_path,
        summary={
            "mode": "full",
            "health": {"score": 77, "grade": "B"},
            "findings": {"total": 5, "new": 1},
            "inventory": {"files": 9, "lines": 100, "functions": 3},
            "diff": {"new_clones": 0, "health_delta": None},
        },
        source=ANALYSIS_SOURCE_CLI,
        report_digest="c" * 64,
        run_id="runcli1234567890",
        agent_pid=100,
        agent_start_epoch=999,
        agent_label="codeclone-cli/test",
    )


def _read_latest_analysis_run_with_payload(
    tmp_path: Path,
    payload: dict[str, object],
) -> AnalysisRunSnapshot | None:
    import json

    from codeclone.audit import EVENT_ANALYSIS_COMPLETED

    db_path = _write_cli_analysis_event(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE controller_events SET payload_json = ? WHERE event_type = ?",
            (json.dumps(payload), EVENT_ANALYSIS_COMPLETED),
        )
        conn.commit()
    finally:
        conn.close()
    return read_latest_analysis_run(db_path=db_path, repo_root=tmp_path)


def test_read_latest_analysis_run_missing_db(tmp_path: Path) -> None:
    assert (
        read_latest_analysis_run(
            db_path=tmp_path / "missing.sqlite3",
            repo_root=tmp_path,
        )
        is None
    )


def test_read_latest_analysis_run_connect_error(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    db_path.write_text("x", encoding="utf-8")
    with (
        patch("sqlite3.connect", side_effect=sqlite3.Error("disk I/O error")),
        pytest.raises(AuditReadError, match="cannot open audit database"),
    ):
        read_latest_analysis_run(db_path=db_path, repo_root=tmp_path)


def test_read_latest_analysis_run_read_error(tmp_path: Path) -> None:
    db_path = _write_cli_analysis_event(tmp_path)

    class _FailingConnection:
        def execute(self, *_args: object, **_kwargs: object) -> object:
            raise sqlite3.Error("query failed")

        def close(self) -> None:
            return None

    with (
        patch(
            "codeclone.audit.reader.open_audit_db_readonly",
            return_value=_FailingConnection(),
        ),
        pytest.raises(AuditReadError, match="cannot read audit database"),
    ):
        read_latest_analysis_run(db_path=db_path, repo_root=tmp_path)


def test_read_latest_analysis_run_cli_source_label(tmp_path: Path) -> None:
    db_path = _write_cli_analysis_event(tmp_path)
    snapshot = read_latest_analysis_run(db_path=db_path, repo_root=tmp_path)
    assert snapshot is not None
    assert snapshot.source == "audit_cli"
    assert snapshot.run_id == "runcli12"
    assert snapshot.health == 77
    assert snapshot.findings == 5
    assert snapshot.files == 9


def test_read_audit_summary_exposes_replay_identity_fields(tmp_path: Path) -> None:
    db_path = _write_cli_analysis_event(tmp_path)
    summary = read_audit_summary(db_path=db_path, limit=5)

    record = summary.events[0]
    assert record.audit_sequence == 1
    assert record.workflow_id == "run:runcli1234567890"
    assert record.surface == "cli"
    assert record.tool_name == "cli:analysis"
    assert record.report_digest == "c" * 64
    assert record.event_core_json is not None
    assert record.event_core_sha256 is not None
    assert record.payload_sha256 is not None


def test_analysis_payload_from_json_edge_cases() -> None:
    assert _analysis_payload_from_json(None) == {}
    assert _analysis_payload_from_json("") == {}
    assert _analysis_payload_from_json("{not-json") == {}
    assert _analysis_payload_from_json("[]") == {}


def test_analysis_run_source_label_unknown() -> None:
    assert _analysis_run_source_label("other") == "audit_unknown"


def test_short_run_id_edge_cases() -> None:
    assert _short_run_id(None, {}) is None
    assert _short_run_id("   ", {}) is None
    assert _short_run_id("abc", {}) == "abc"


def test_read_latest_analysis_run_compact_payload_fallbacks(tmp_path: Path) -> None:
    db_path = write_compact_analysis_completed_event(
        tmp_path,
        summary={
            "mode": "full",
            "health": {"score": 88, "grade": "A"},
            "findings": {"total": 3, "new": 0},
            "inventory": {"files": 10, "lines": 100, "functions": 5},
            "diff": {"new_clones": 0, "health_delta": None},
        },
        source=ANALYSIS_SOURCE_CLI,
        report_digest="c" * 64,
        run_id="runcompact123456",
        agent_pid=100,
        agent_start_epoch=999,
        agent_label="codeclone-cli/test",
    )
    snapshot = read_latest_analysis_run(db_path=db_path, repo_root=tmp_path)
    assert snapshot is not None
    assert snapshot.health == 88
    assert snapshot.findings == 3
    assert snapshot.files == 10


def test_read_latest_analysis_run_top_level_metric_fallbacks(tmp_path: Path) -> None:
    legacy_payload = {
        "source": "cli",
        "health_score": 72,
        "findings_total": 11,
        "files": 42,
    }
    snapshot = _read_latest_analysis_run_with_payload(tmp_path, legacy_payload)
    assert snapshot is not None
    assert snapshot.health == 72
    assert snapshot.findings == 11
    assert snapshot.files == 42


def test_read_audit_summary_without_token_columns_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = _write_cli_analysis_event(tmp_path)
    monkeypatch.setattr(
        "codeclone.audit.reader._has_token_columns",
        lambda _conn: False,
    )
    summary = read_audit_summary(db_path=db_path, limit=5)
    assert summary.total_events == 1
    assert summary.payload_footprint is None


def test_resolve_audit_path_wraps_repo_path_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.utils.repo_paths import RepoPathError

    def _boom(*_args: object, **_kwargs: object) -> Path:
        raise RepoPathError("cannot resolve path")

    monkeypatch.setattr(
        "codeclone.audit.validation.resolve_under_repo_root",
        _boom,
    )
    with pytest.raises(AuditConfigError, match="invalid audit_path"):
        resolve_audit_path(root_path=tmp_path, value=".codeclone/db/audit.sqlite3")


def test_validate_event_row_rejects_invalid_agent_start_epoch() -> None:
    row = EventRow(
        event_id="evt_1",
        event_type="analysis.completed",
        severity="info",
        created_at_utc="2026-05-25T00:00:00Z",
        repo_root_digest="a" * 16,
        run_id="run1234567890abcdef",
        intent_id=None,
        report_digest="b" * 64,
        agent_label="agent",
        agent_pid=1,
        agent_start_epoch=cast(int | None, True),
        status="full",
        payload_json="{}",
    )
    with pytest.raises(
        AuditValidationError, match="agent_start_epoch must be an integer"
    ):
        validate_event_row(row)

    row_negative = EventRow(
        event_id="evt_2",
        event_type="analysis.completed",
        severity="info",
        created_at_utc="2026-05-25T00:00:00Z",
        repo_root_digest="a" * 16,
        run_id="run1234567890abcdef",
        intent_id=None,
        report_digest="b" * 64,
        agent_label="agent",
        agent_pid=1,
        agent_start_epoch=-1,
        status="full",
        payload_json="{}",
    )
    with pytest.raises(
        AuditValidationError,
        match="agent_start_epoch must be non-negative",
    ):
        validate_event_row(row_negative)


def _receipt_payload(
    *, verdict: str = "clean", digest: str = "abc123"
) -> dict[str, object]:
    return {
        "run_id": "30b56d21",
        "format": "markdown",
        "receipt_version": "1",
        "verdict": verdict,
        "receipt_digest": {
            "kind": "receipt_v1",
            "algorithm": "sha256",
            "digest_version": "1",
            "value": digest,
        },
        "content": "## CodeClone Agent Review Receipt\n...",
        "receipt": {"receipt_version": "1", "verdict": verdict, "provenance": {}},
    }


def _write_receipt_event(
    db_path: Path,
    *,
    run_id: str,
    payload: dict[str, object],
    payloads: str = "compact",
) -> None:
    writer = SqliteAuditWriter(
        db_path=db_path,
        payloads=cast("Any", payloads),
        retention_days=30,
    )
    writer.emit(
        AuditEvent(
            event_type=EVENT_RECEIPT_CREATED,
            severity="info",
            repo_root_digest="rootdigest0000",
            agent_pid=1,
            agent_start_epoch=1,
            agent_label="test",
            run_id=run_id,
            intent_id=None,
            report_digest="reportdigest",
            status=str(payload.get("verdict", "")),
            payload=payload,
        )
    )
    writer.close()


def test_lookup_review_receipt_by_run_id(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    _write_receipt_event(db_path, run_id="30b56d21", payload=_receipt_payload())

    result = lookup_review_receipt(db_path, run_id="30b56d21")

    assert result.status == "ok"
    assert result.receipt is not None
    assert result.receipt.receipt_digest == "abc123"
    assert result.receipt.verdict == "clean"
    # Returns the stored typed receipt, not a recomputed one.
    assert result.receipt.payload["receipt"] == {
        "receipt_version": "1",
        "verdict": "clean",
        "provenance": {},
    }


def test_lookup_review_receipt_compact_mode_preserves_full_receipt(
    tmp_path: Path,
) -> None:
    # The whole point of the forensic-retention policy: even the default compact
    # audit mode keeps the complete typed receipt durably retrievable.
    db_path = tmp_path / "audit.sqlite3"
    _write_receipt_event(
        db_path, run_id="30b56d21", payload=_receipt_payload(), payloads="compact"
    )

    result = lookup_review_receipt(db_path, run_id="30b56d21", receipt_digest="abc123")

    assert result.status == "ok"
    assert result.receipt is not None
    typed = cast("dict[str, object]", result.receipt.payload["receipt"])
    assert typed["verdict"] == "clean"


def test_lookup_review_receipt_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "absent.sqlite3"
    assert lookup_review_receipt(missing, run_id="30b56d21").status == "not_found"

    db_path = tmp_path / "audit.sqlite3"
    _write_receipt_event(db_path, run_id="30b56d21", payload=_receipt_payload())
    assert lookup_review_receipt(db_path, run_id="ffffffff").status == "not_found"


def test_lookup_review_receipt_ambiguous(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    _write_receipt_event(
        db_path, run_id="30b56d21", payload=_receipt_payload(digest="aaa")
    )
    _write_receipt_event(
        db_path, run_id="30b56d21", payload=_receipt_payload(digest="bbb")
    )

    # run id alone cannot pick between two receipts.
    assert lookup_review_receipt(db_path, run_id="30b56d21").status == "ambiguous"
    # the digest disambiguates exactly.
    exact = lookup_review_receipt(db_path, run_id="30b56d21", receipt_digest="bbb")
    assert exact.status == "ok"
    assert exact.receipt is not None
    assert exact.receipt.receipt_digest == "bbb"


def test_lookup_review_receipt_digest_mismatch(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    _write_receipt_event(
        db_path, run_id="30b56d21", payload=_receipt_payload(digest="aaa")
    )

    result = lookup_review_receipt(db_path, run_id="30b56d21", receipt_digest="zzz")
    assert result.status == "digest_mismatch"
    assert result.receipt is None


def test_lookup_review_receipt_malformed(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    _write_receipt_event(db_path, run_id="30b56d21", payload=_receipt_payload())
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE controller_events SET payload_json='{not valid json' "
        "WHERE event_type=?",
        (EVENT_RECEIPT_CREATED,),
    )
    conn.commit()
    conn.close()

    result = lookup_review_receipt(db_path, run_id="30b56d21")
    assert result.status == "malformed_stored_receipt"


def test_audit_reader_payload_parsers_and_builder_guards() -> None:
    from codeclone.audit.reader import (
        _blast_artifact_digest_value,
        _build_blast_artifact,
        _build_patch_trail,
        _build_review_receipt,
        _parse_payload_mapping,
        _receipt_digest_value,
        _run_id_matches,
    )

    assert _parse_payload_mapping(None) is None
    assert _parse_payload_mapping("") is None
    assert _parse_payload_mapping("{not-json") is None
    assert _parse_payload_mapping("[]") is None
    assert _run_id_matches(None, "run") is False
    assert _run_id_matches("", "run") is False
    assert _run_id_matches("run", "run-full") is True

    assert _build_review_receipt("run", "now", {}) is None
    assert _build_review_receipt("run", "now", {"receipt": "bad"}) is None
    assert _build_patch_trail("run", "now", {}) is None
    assert _build_blast_artifact("run", "now", {}) is None
    assert _build_blast_artifact("run", "now", {"blast_artifact_id": "x"}) is None

    assert _receipt_digest_value({"receipt_digest": "flat"}) == "flat"
    assert _receipt_digest_value({"receipt_digest": {"value": "nested"}}) == "nested"
    assert _blast_artifact_digest_value({"projection_digest": "flat"}) == "flat"
    assert (
        _blast_artifact_digest_value({"projection_digest": {"value": "nested"}})
        == "nested"
    )


def test_read_latest_analysis_run_prefers_nested_metrics_before_flat_fallbacks(
    tmp_path: Path,
) -> None:
    nested_payload = {
        "source": "cli",
        "health": {"score": 91},
        "findings": {"total": 4},
        "inventory": {"files": 7},
        "health_score": 72,
        "findings_total": 11,
        "files": 42,
    }
    snapshot = _read_latest_analysis_run_with_payload(tmp_path, nested_payload)
    assert snapshot is not None
    assert snapshot.health == 91
    assert snapshot.findings == 4
    assert snapshot.files == 7


def test_lookup_blast_artifact_read_errors_surface_as_audit_read_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.audit.reader import lookup_blast_artifact
    from codeclone.audit.validation import AuditReadError

    db_path = tmp_path / "audit.sqlite3"
    db_path.write_text("not sqlite", encoding="utf-8")

    class _BrokenConnection:
        def execute(self, *_args: object, **_kwargs: object) -> object:
            raise sqlite3.OperationalError("read failed")

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "codeclone.audit.reader.open_audit_db_readonly",
        lambda _path: _BrokenConnection(),
    )
    with pytest.raises(AuditReadError, match="cannot read audit database"):
        lookup_blast_artifact(db_path, run_id="run123")


def test_read_event_payload_rows_open_failure_raises_audit_read_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.audit.reader import _read_event_payload_rows
    from codeclone.audit.validation import AuditReadError

    db_path = tmp_path / "audit.sqlite3"
    db_path.write_text("not sqlite", encoding="utf-8")

    def _raise_open(_path: Path) -> object:
        raise OSError("permission denied")

    monkeypatch.setattr(
        "codeclone.audit.reader.open_audit_db_readonly",
        _raise_open,
    )
    with pytest.raises(AuditReadError, match="cannot open audit database"):
        _read_event_payload_rows(db_path, "analysis.completed")
