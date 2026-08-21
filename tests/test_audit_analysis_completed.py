# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from codeclone.api.novelty import CLONE_NOVELTY_VALUES
from codeclone.audit.analysis_completed import (
    ANALYSIS_SOURCE_CLI,
    ANALYSIS_SOURCE_MCP,
    analysis_completed_payload,
    analysis_completed_payload_from_report,
    emit_analysis_completed,
    emit_analysis_completed_from_report,
)
from codeclone.audit.events import (
    EVENT_ANALYSIS_COMPLETED,
    compact_payload_for_event,
    event_summary,
)
from codeclone.audit.reader import read_latest_analysis_run
from codeclone.audit.schema import open_audit_db
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.contracts import REPORT_SCHEMA_VERSION

from ._report_fixtures import build_test_report_document


def _default_analysis_summary() -> dict[str, object]:
    return {
        "focus": "repository",
        "mode": "full",
        "schema": REPORT_SCHEMA_VERSION,
        "health": {"score": 91, "grade": "A"},
        "findings": {"total": 12, "new": 1},
        "inventory": {"files": 44, "lines": 1000, "functions": 200},
        "diff": {"new_clones": 0, "health_delta": None},
    }


def _write_analysis_completed_event(
    tmp_path: Path,
    *,
    summary: Mapping[str, object] | None = None,
    run_id: str = "run1234567890abcdef",
    agent_pid: int = 4242,
    agent_start_epoch: int = 1700000000,
    agent_label: str = "codeclone-mcp/test",
    report_digest: str = "d" * 64,
) -> Path:
    db_path = tmp_path / "audit.sqlite3"
    writer = SqliteAuditWriter(
        db_path=db_path,
        payloads="compact",
        retention_days=30,
    )
    emit_analysis_completed(
        root_path=tmp_path,
        summary=dict(summary or _default_analysis_summary()),
        source=ANALYSIS_SOURCE_MCP,
        report_digest=report_digest,
        run_id=run_id,
        agent_pid=agent_pid,
        agent_start_epoch=agent_start_epoch,
        agent_label=agent_label,
        writer=writer,
    )
    writer.close()
    return db_path


def _fetch_first_event_row(db_path: Path, sql: str) -> tuple[object, ...] | None:
    conn = open_audit_db(db_path)
    try:
        row = conn.execute(sql).fetchone()
    finally:
        conn.close()
    return None if row is None else tuple(row)


def _stored_payload(db_path: Path) -> dict[str, object]:
    """The payload of the single stored event, parsed off the wire."""

    row = _fetch_first_event_row(
        db_path,
        "SELECT payload_json FROM controller_events LIMIT 1",
    )
    assert row is not None
    return cast(dict[str, object], json.loads(str(row[0])))


def test_analysis_completed_summary() -> None:
    summary = event_summary(
        EVENT_ANALYSIS_COMPLETED,
        {"source": "mcp", "health": {"score": 88}},
    )
    assert summary == "analysis completed (mcp): health=88"


def test_read_latest_analysis_run_prefers_audit_event(tmp_path: Path) -> None:
    db_path = _write_analysis_completed_event(tmp_path)

    snapshot = read_latest_analysis_run(db_path=db_path, repo_root=tmp_path)
    assert snapshot is not None
    assert snapshot.run_id == "run12345"
    assert snapshot.health == 91
    assert snapshot.findings == 12
    assert snapshot.files == 44
    assert snapshot.source == "audit_mcp"
    assert snapshot.age_seconds is not None
    assert snapshot.age_seconds >= 0


def test_open_audit_db_stores_agent_start_epoch(tmp_path: Path) -> None:
    db_path = _write_analysis_completed_event(
        tmp_path,
        summary={
            **_default_analysis_summary(),
            "health": {"score": 70, "grade": "B"},
            "findings": {"total": 1, "new": 0},
            "inventory": {"files": 2, "lines": 10, "functions": 1},
        },
        run_id="runabcdef",
        agent_pid=111,
        agent_start_epoch=123456,
        agent_label="agent",
        report_digest="e" * 64,
    )

    row = _fetch_first_event_row(
        db_path,
        "SELECT agent_start_epoch, payload_json FROM controller_events LIMIT 1",
    )
    assert row is not None
    assert row[0] == 123456
    payload = json.loads(str(row[1]))
    assert payload["source"] == "mcp"
    assert payload["health_score"] == 70
    assert payload["files"] == 2


def test_emit_reads_the_canonical_run_summary_shape(tmp_path: Path) -> None:
    """One spelling per figure: the canonical run summary, nothing beside it.

    The emitter used to accept a second spelling of every figure -- the run
    session's internal ``analysis_mode``/``report_schema_version``/
    ``findings_summary`` -- so a surface handing over the wrong object still
    produced a row that looked populated. It no longer does, and the surfaces
    hand over the summary they publish.
    """

    db_path = _write_analysis_completed_event(
        tmp_path,
        summary={
            "mode": "full",
            "schema": REPORT_SCHEMA_VERSION,
            "health": {"score": 88, "grade": "A"},
            "findings": {"total": 3, "new": 0},
            "inventory": {"files": 10, "lines": 100, "functions": 5},
            "diff": {"new_clones": 0, "health_delta": None},
        },
        run_id="runmcpinternal",
        agent_label="cursor-vscode/test",
    )

    row = _fetch_first_event_row(
        db_path,
        "SELECT status, agent_label, payload_json FROM controller_events LIMIT 1",
    )
    assert row is not None
    assert row[0] == "full"
    assert row[1] == "cursor-vscode/test"
    payload = json.loads(str(row[2]))
    assert payload["mode"] == "full"
    assert payload["findings_total"] == 3


def test_analysis_completed_payload_keeps_uncompared_novelty_null(
    tmp_path: Path,
) -> None:
    # No clone lane was compared, so the audit row must not record a zero the
    # run never measured.
    payload = analysis_completed_payload_from_report(
        report_document=_document_with_distinct_figures(tmp_path),
        source=ANALYSIS_SOURCE_CLI,
        new_func_count=None,
        new_block_count=None,
    )

    assert cast(dict[str, object], payload["diff"])["new_clones"] is None


def test_emit_analysis_completed_from_report_writes_row(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone]\naudit_enabled = true\n",
        encoding="utf-8",
    )
    emit_analysis_completed_from_report(
        root_path=tmp_path,
        report_document=_document_with_distinct_figures(tmp_path),
        report_digest="d" * 64,
        run_id="runfromreport",
        source=ANALYSIS_SOURCE_CLI,
        new_func_count=0,
        new_block_count=0,
    )
    row = _fetch_first_event_row(
        tmp_path / ".codeclone/db/audit.sqlite3",
        "SELECT status, agent_label FROM controller_events LIMIT 1",
    )
    assert row is not None
    assert row[0] == "changed_paths"
    assert str(row[1]).startswith("codeclone-cli/")


def test_analysis_completed_payload_records_uncounted_entities_as_null() -> None:
    """A run that counted nothing must not be recorded as having counted zero.

    ``inventory.code`` is absent from a document whose run never counted
    entities, and a zero there would be a measurement that never happened --
    the same refusal the uncompared clone lane makes for ``diff.new_clones``.
    """

    payload = analysis_completed_payload_from_report(
        report_document={
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "meta": {"analysis_mode": "full"},
            "inventory": {},
            "findings": {"summary": {"total": 0}},
            "metrics": {"summary": {"health": {"score": 1, "grade": "F"}}},
        },
        source=ANALYSIS_SOURCE_CLI,
        new_func_count=0,
        new_block_count=0,
    )

    assert payload["inventory"] == {
        "files": None,
        "lines": None,
        "functions": None,
    }


def test_analysis_mode_fallback_to_completed() -> None:
    payload = analysis_completed_payload(
        summary={"health": {"score": 1}, "findings": {}, "inventory": {}, "diff": {}},
        source=ANALYSIS_SOURCE_MCP,
    )
    assert payload["mode"] == "completed"


def test_analysis_mode_blank_string_falls_back_to_completed() -> None:
    payload = analysis_completed_payload(
        summary={
            "mode": "   ",
            "health": {"score": 1},
            "findings": {},
            "inventory": {},
            "diff": {},
        },
        source=ANALYSIS_SOURCE_MCP,
    )
    assert payload["mode"] == "completed"


def test_emit_analysis_completed_from_report_custom_agent_fields(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone]\naudit_enabled = true\n",
        encoding="utf-8",
    )
    emit_analysis_completed_from_report(
        root_path=tmp_path,
        report_document=_document_with_distinct_figures(tmp_path),
        report_digest="d" * 64,
        run_id="runcustomagent",
        source=ANALYSIS_SOURCE_MCP,
        new_func_count=0,
        new_block_count=0,
        agent_pid=4242,
        agent_start_epoch=1700000001,
        agent_label="custom-agent",
    )
    row = _fetch_first_event_row(
        tmp_path / ".codeclone/db/audit.sqlite3",
        (
            "SELECT agent_pid, agent_start_epoch, agent_label "
            "FROM controller_events LIMIT 1"
        ),
    )
    assert row == (4242, 1700000001, "custom-agent")


def _document_with_distinct_figures(scan_root: Path) -> dict[str, object]:
    """A product-built report whose figures cannot coincide.

    ``as_mapping`` answers a missing key with an empty mapping, so a read of a
    key the document never carried is indistinguishable from a read of a zero
    -- and a fixture full of zeros cannot tell them apart either. Every count
    here differs from every other one: 37 files were found while the file
    registry holds 4 paths, parsed lines, functions and methods are pairwise
    distinct, and the health score matches none of them. A payload that reports
    the wrong fact therefore cannot look right by accident.
    """

    return build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"analysis_mode": "changed_paths", "scan_root": str(scan_root)},
        inventory={
            "file_list": [str(scan_root / f"pkg/mod_{index}.py") for index in range(4)],
            "files": {"total_found": 37, "analyzed": 31, "cached": 0, "skipped": 6},
            "code": {
                "parsed_lines": 6131,
                "functions": 419,
                "methods": 57,
                "classes": 23,
            },
        },
        metrics={"health": {"score": 74, "grade": "B"}},
    )


def test_analysis_completed_payload_reports_the_documents_own_figures(
    tmp_path: Path,
) -> None:
    """The CLI event carries the run's counts, not a recount of a rendered list.

    ``inventory.lines`` and ``inventory.functions`` are keys the canonical
    document has never had, so both were recorded as null on every CLI
    analysis, and the file count was the length of the file registry rather
    than the number of files the run found. The registry is a projection of
    the paths that resolved under the scan root; equating it with
    ``inventory.files.total_found`` is a second counter of a fact the document
    already publishes, and here the two differ by 33.
    """

    document = _document_with_distinct_figures(tmp_path)
    inventory = cast(dict[str, object], document["inventory"])
    registry = cast(dict[str, object], inventory["file_registry"])
    assert len(cast(list[object], registry["items"])) == 4

    payload = analysis_completed_payload_from_report(
        report_document=document,
        source=ANALYSIS_SOURCE_CLI,
        new_func_count=1,
        new_block_count=2,
    )

    assert payload["mode"] == "changed_paths"
    assert payload["health"] == {"score": 74, "grade": "B"}
    assert payload["inventory"] == {"files": 37, "lines": 6131, "functions": 476}
    assert cast(dict[str, object], payload["findings"])["total"] == 0
    assert cast(dict[str, object], payload["diff"])["new_clones"] == 3


def test_analysis_completed_payload_ignores_the_withdrawn_locations(
    tmp_path: Path,
) -> None:
    """The keys the document stopped carrying must not be consulted at all.

    Each of these was read first and the correct location second, so every one
    of them was right by coincidence: the fallback happened to hold the truth.
    Asserting only the correct answer stays green with the withdrawn read
    restored in front of it, which is why each withdrawn location is filled
    here with a value no correct payload can report.
    """

    document = _document_with_distinct_figures(tmp_path)
    meta = cast(dict[str, object], document["meta"])
    cast(dict[str, object], meta["runtime"])["analysis_mode"] = "full"
    meta["health_score"] = 999
    meta["health_grade"] = "Z"
    cast(dict[str, object], document["findings"])["total"] = 999

    payload = analysis_completed_payload_from_report(
        report_document=document,
        source=ANALYSIS_SOURCE_CLI,
        new_func_count=0,
        new_block_count=0,
    )

    assert payload["mode"] == "changed_paths"
    assert payload["health"] == {"score": 74, "grade": "B"}
    assert cast(dict[str, object], payload["findings"])["total"] == 0


def test_emitted_cli_analysis_row_carries_the_documents_file_count(
    tmp_path: Path,
) -> None:
    """The wire is what a reader sees; prove the number reaches it.

    The compact projection is the shape stored for every analysis, and the
    file count is the one inventory figure it carries. Reading it back from
    SQLite proves the fix survives the whole path, not only the builder.
    """

    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone]\naudit_enabled = true\n",
        encoding="utf-8",
    )
    emit_analysis_completed_from_report(
        root_path=tmp_path,
        report_document=_document_with_distinct_figures(tmp_path),
        report_digest="f" * 64,
        run_id="rundistinctfigures",
        source=ANALYSIS_SOURCE_CLI,
        new_func_count=0,
        new_block_count=0,
    )

    payload = _stored_payload(tmp_path / ".codeclone/db/audit.sqlite3")
    assert payload["files"] == 37
    assert payload["health_score"] == 74
    assert payload["mode"] == "changed_paths"


def test_analysis_completed_payload_carries_producer_novelty_tristate() -> None:
    """The builder keeps every novelty counter the run summary publishes.

    The MCP summary counts three novelty states under ``total``/``new``/
    ``known``/``unavailable``. A payload that keeps only total+new turns
    "26 findings, none compared" into "26 findings, no regressions" -- a
    forensic row that cannot be recomputed after the fact.
    """

    payload = analysis_completed_payload(
        summary={
            **_default_analysis_summary(),
            "findings": {"total": 26, "new": 0, "known": 0, "unavailable": 26},
        },
        source=ANALYSIS_SOURCE_MCP,
    )

    assert payload["findings"] == {
        "total": 26,
        "new": 0,
        "known": 0,
        "unavailable": 26,
    }


def test_row_with_unavailable_findings_stores_the_tristate(tmp_path: Path) -> None:
    """Forensic pin: the stored compact row keeps known and unavailable.

    ``total=26, new=0`` alone reads later as "no regressions" when all 26
    findings were never compared against a baseline. The wire row is the
    durable evidence, so the tristate must survive the whole path.
    """

    db_path = _write_analysis_completed_event(
        tmp_path,
        summary={
            **_default_analysis_summary(),
            "findings": {"total": 26, "new": 0, "known": 0, "unavailable": 26},
        },
    )

    payload = _stored_payload(db_path)
    assert payload["findings_total"] == 26
    assert payload["findings_new"] == 0
    assert payload["findings_known"] == 0
    assert payload["findings_unavailable"] == 26


def test_from_report_payload_records_novelty_rollup_absence_as_null(
    tmp_path: Path,
) -> None:
    """A from-report row records the rollup's absence, never an invented zero.

    The canonical document publishes novelty per finding and a clone-lane
    rollup, but no cross-family totals -- the same reason the existing
    ``new`` is recorded as null. ``known`` and ``unavailable`` follow the
    same rule: the key is present and the value states the absence.
    """

    payload = analysis_completed_payload_from_report(
        report_document=_document_with_distinct_figures(tmp_path),
        source=ANALYSIS_SOURCE_CLI,
        new_func_count=0,
        new_block_count=0,
    )

    findings = cast(dict[str, object], payload["findings"])
    assert "new" in findings and findings["new"] is None
    assert "known" in findings and findings["known"] is None
    assert "unavailable" in findings and findings["unavailable"] is None


def test_compact_row_novelty_counters_cover_the_vocabulary() -> None:
    """Arithmetic pin over the novelty vocabulary, derived from its owner.

    One stored counter per vocabulary value, and the counters sum to the
    stored total. ``CLONE_NOVELTY_VALUES`` is derived from the domain owner
    inside the R3 door, so a fourth vocabulary value reaches this pin -- and
    reds it -- without any test edit (wave-22 ratchet inheritance).
    """

    vocabulary = sorted(CLONE_NOVELTY_VALUES)
    counts = {value: index + 1 for index, value in enumerate(vocabulary)}
    total = sum(counts.values())

    compact = compact_payload_for_event(
        event_type=EVENT_ANALYSIS_COMPLETED,
        payload=analysis_completed_payload(
            summary={
                **_default_analysis_summary(),
                "findings": {"total": total, **counts},
            },
            source=ANALYSIS_SOURCE_MCP,
        ),
    )

    stored: dict[str, int] = {}
    for value in vocabulary:
        counter_name = f"findings_{value}"
        assert counter_name in compact, (
            f"novelty value {value!r} has no stored counter on the audit row"
        )
        counter = compact[counter_name]
        assert isinstance(counter, int), counter_name
        stored[value] = counter
    assert stored == counts
    assert compact["findings_total"] == total
    assert sum(stored.values()) == total
