# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""What the CLI run identity is allowed to depend on, and how it refuses.

The value this names is written to the audit trail twice, as the
``analysis.completed`` row's ``run_id`` and as its ``report_digest``. Two
properties make it usable, and they pull in opposite directions:

* it must move whenever the answer moves -- otherwise two runs that disagree
  are recorded under one id and the trail cannot tell them apart;
* it must hold still when only the clock moves -- otherwise every re-analysis
  of an unchanged tree looks like a different run.

Exactly one digest tier satisfies both, and the first two tests are the pair
that says so: one refuses every tier below ``evaluation``, the other refuses
the envelope above it. The rest pin the refusal: a document that carries no
identity must say so, and must not leave an audit trail in which "nothing was
recorded" is indistinguishable from "audit was switched off".
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

from codeclone.surfaces.cli import workflow as cli_workflow
from codeclone.utils.mapping_paths import section
from codeclone.utils.run_identity import (
    ReportRunIdentityError,
    report_run_identity,
)

from ._report_fixtures import (
    GATE_POLICY_GENERATED_AT,
    build_gate_policy_disagreement_pair,
    build_gate_policy_report_document,
)

_GENERATED_AT_LATER = "2026-08-13T11:00:00Z"


def _identity(document: Mapping[str, object]) -> str:
    return report_run_identity(document)


def _digest(document: Mapping[str, object], tier: str) -> str:
    value = section(document, f"integrity.digests.{tier}").get("value")
    assert isinstance(value, str) and value
    return value


def _audit_enabled_root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone]\naudit_enabled = true\n",
        encoding="utf-8",
    )
    return tmp_path


def _audit_db_path(root: Path) -> Path:
    return root / ".codeclone/db/audit.sqlite3"


def _audit_row_count(root: Path) -> int:
    """Count recorded controller events with stdlib sqlite3 on purpose.

    This is a CLI-surface test: importing the audit package would raise the
    module's ring and register a new frozen boundary violation.
    """

    conn = sqlite3.connect(_audit_db_path(root))
    try:
        return int(conn.execute("SELECT COUNT(*) FROM controller_events").fetchone()[0])
    finally:
        conn.close()


def test_cli_run_identity_moves_when_the_gate_verdict_moves() -> None:
    """Same tree, different thresholds, different verdicts -- different ids.

    The audit row carries this value as the run's name. Taking it from the
    comparison tier -- facts and baseline, no policy -- gave two runs that
    answered differently the same name, because the thresholds and the
    outcome live one tier above it.

    The fixture owner makes an accidental pass impossible: it asserts that the
    two runs share every tier below ``evaluation`` (same tree, same baseline)
    and that they really do disagree on the verdict.
    """

    lenient, strict = build_gate_policy_disagreement_pair()

    assert _identity(lenient) != _identity(strict)


def test_cli_run_identity_holds_still_when_only_the_clock_moves() -> None:
    """Re-measuring an unchanged tree must not mint a new identity.

    ``meta.runtime.report_generated_at_utc`` is the document's only time-like
    field, and only the envelope tier seals it. An identity taken from the
    envelope would be new on every run, which reads as honest and is not: no
    consumer of the trail could ever tell a repeated measurement from a
    changed one.
    """

    first = build_gate_policy_report_document()
    second = build_gate_policy_report_document(
        report_generated_at_utc=_GENERATED_AT_LATER
    )

    assert (
        section(first, "meta.runtime").get("report_generated_at_utc")
        == GATE_POLICY_GENERATED_AT
    )
    assert (
        section(second, "meta.runtime").get("report_generated_at_utc")
        == _GENERATED_AT_LATER
    )
    assert _digest(first, "envelope") != _digest(second, "envelope")

    assert _identity(first) == _identity(second)


def test_cli_run_identity_refuses_a_document_without_the_tier() -> None:
    """No identity is a typed refusal, not a value.

    An empty string reads downstream as a digest that is present and blank,
    which is the same shape as a digest that was never looked for.
    """

    with pytest.raises(ReportRunIdentityError):
        _identity({"integrity": {"digests": {}}})


def test_audit_emit_refuses_a_document_without_an_identity(tmp_path: Path) -> None:
    """A nameless run must not be silently dropped from the trail.

    Skipping the row here produced a trail in which "this run was not
    recorded" and "audit was switched off" are the same absence.
    """

    root = _audit_enabled_root(tmp_path)

    with pytest.raises(ReportRunIdentityError):
        cli_workflow._emit_cli_analysis_completed_if_enabled(
            args=SimpleNamespace(audit_enabled=True),
            root_path=root,
            report_document={"integrity": {"digests": {}}},
            new_func_count=0,
            new_block_count=0,
        )

    assert not _audit_db_path(root).exists()


def test_audit_disabled_stays_silent_and_never_reads_the_document(
    tmp_path: Path,
) -> None:
    """The switched-off path is answered before the document is consulted.

    Guards the refusal from being hoisted above the ``audit_enabled`` check:
    a run with audit off must stay silent even when its document carries no
    identity at all.
    """

    root = _audit_enabled_root(tmp_path)

    cli_workflow._emit_cli_analysis_completed_if_enabled(
        args=SimpleNamespace(audit_enabled=False),
        root_path=root,
        report_document={"integrity": {"digests": {}}},
        new_func_count=0,
        new_block_count=0,
    )

    assert not _audit_db_path(root).exists()


def test_audit_row_carries_the_run_identity(tmp_path: Path) -> None:
    """The identity reaches the wire: one row, named by the same value.

    Without this the refusal pins above could both pass over an emit path
    that never writes anything.
    """

    root = _audit_enabled_root(tmp_path)
    document = build_gate_policy_report_document()

    cli_workflow._emit_cli_analysis_completed_if_enabled(
        args=SimpleNamespace(audit_enabled=True),
        root_path=root,
        report_document=document,
        new_func_count=1,
        new_block_count=0,
    )

    conn = sqlite3.connect(_audit_db_path(root))
    try:
        rows = conn.execute(
            "SELECT event_type, run_id, report_digest FROM controller_events"
        ).fetchall()
    finally:
        conn.close()

    assert _audit_row_count(root) == 1
    assert rows[0][0] == "analysis.completed"
    assert rows[0][1] == _identity(document)
    assert rows[0][2] == _identity(document)
