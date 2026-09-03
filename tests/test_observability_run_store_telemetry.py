# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Session run-store telemetry: the LRU that silently drops another agent's run.

``mcp.run_store.register`` / ``mcp.run_store.resolve_artifact`` and the
``run_store_*`` counters were declared in the closed vocabulary and pinned by a
test, but no code emitted them — so a run evicted between two subagents left no
trace at all. These tests pin the emission, not the declaration.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import orjson
import pytest

from codeclone.observability import bootstrap, operation, shutdown
from codeclone.surfaces.mcp._session_shared import (
    CodeCloneMCPRunStore,
    ExecutionEvent,
    MCPAnalysisRequest,
    MCPRunNotFoundError,
    MCPRunRecord,
    build_served_projection,
    mint_execution_event_id,
)

# The subject here is the MCP session run store (ring r4), so this module may
# not reach into r2/r2p for a config dataclass or the store-path helper — the
# architecture ratchet is shrink-only and a new edge is a new violation.
# Observability is configured through its documented environment contract and
# the store is located by name, which is also closer to how an operator meets
# this telemetry.


@pytest.fixture
def observed_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("CODECLONE_OBSERVABILITY_ENABLED", "1")
    monkeypatch.delenv("CODECLONE_OBSERVABILITY_PROFILE", raising=False)
    bootstrap(root=tmp_path)
    try:
        yield tmp_path
    finally:
        shutdown()


def _record(root: Path, run_id: str) -> MCPRunRecord:
    return MCPRunRecord(
        run_id=run_id,
        root=root,
        request=MCPAnalysisRequest(root=str(root), respect_pyproject=False),
        comparison_settings=(),
        served_report=build_served_projection({}),
        summary={"run_id": run_id},
        changed_paths=(),
        changed_projection=None,
        func_clones_count=0,
        block_clones_count=0,
        reachable_qualnames=frozenset(),
        coverage_join=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
        execution=ExecutionEvent(
            execution_event_id=mint_execution_event_id(),
            root=root,
            semantic_report_id=run_id,
        ),
    )


def _span_rows(root: Path, name: str) -> list[dict[str, int]]:
    """Counters of every span with this name, in the order they were written."""
    store = next(root.rglob("platform_observability.sqlite3"))
    conn = sqlite3.connect(store)
    try:
        rows = conn.execute(
            "SELECT counters_json FROM platform_spans WHERE name=? ORDER BY rowid",
            (name,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {str(k): int(v) for k, v in (orjson.loads(raw) if raw else {}).items()}
        for (raw,) in rows
    ]


def _totals(rows: list[dict[str, int]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for row in rows:
        for key, value in row.items():
            merged[key] = merged.get(key, 0) + value
    return merged


def test_run_store_registration_is_recorded(observed_root: Path) -> None:
    store = CodeCloneMCPRunStore(history_limit=4)
    with operation(name="mcp.analyze_repository", surface="mcp"):
        store.register(_record(observed_root, "run0"))
        store.register(_record(observed_root, "run1"))
    shutdown()

    rows = _span_rows(observed_root, "mcp.run_store.register")
    assert len(rows) == 2
    assert rows[-1]["run_store_runs_retained"] == 2
    assert _totals(rows).get("run_store_runs_evicted", 0) == 0


def test_run_store_eviction_between_agents_is_visible(observed_root: Path) -> None:
    # The live story: history_limit=2, four runs registered, and the first two
    # are gone. Before this wiring the eviction happened with no telemetry.
    store = CodeCloneMCPRunStore(history_limit=2)
    with operation(name="mcp.analyze_repository", surface="mcp"):
        for ordinal in range(4):
            store.register(_record(observed_root, f"run{ordinal}"))
        with pytest.raises(MCPRunNotFoundError):
            store.get_for_root("run0", root=observed_root)
    shutdown()

    rows = _span_rows(observed_root, "mcp.run_store.register")
    assert _totals(rows)["run_store_runs_evicted"] == 2
    assert rows[-1]["run_store_runs_retained"] == 2
    assert [row.get("run_store_runs_evicted", 0) for row in rows] == [0, 0, 1, 1]


def test_run_store_selector_hits_and_misses_are_counted(observed_root: Path) -> None:
    from codeclone.observability import span

    store = CodeCloneMCPRunStore(history_limit=4)
    with (
        operation(name="mcp.get_run_summary", surface="mcp"),
        span(name="mcp.get_run_summary"),
    ):
        store.register(_record(observed_root, "present"))
        store.get_for_root("present", root=observed_root)
        store.get_for_root(None, root=observed_root)
        # resolve_any_root answers without reaching the shared funnel, and it
        # is the call that runs when a caller omits run_id — the shape behind
        # "an omitted run_id silently resolves to somebody else's run".
        store.resolve_any_root()
        with pytest.raises(MCPRunNotFoundError):
            store.get_for_root("absent", root=observed_root)
        with pytest.raises(MCPRunNotFoundError):
            store.resolve_any_root("absent")
    shutdown()

    counters = _span_rows(observed_root, "mcp.get_run_summary")[0]
    assert counters["run_store_selector_hits"] == 3
    assert counters["run_store_selector_misses"] == 2


def test_unconstrained_lookup_on_an_empty_store_is_counted_a_miss(
    observed_root: Path,
) -> None:
    from codeclone.observability import span

    store = CodeCloneMCPRunStore(history_limit=4)
    with (
        operation(name="mcp.get_run_summary", surface="mcp"),
        span(name="mcp.get_run_summary"),
        pytest.raises(MCPRunNotFoundError),
    ):
        store.resolve_any_root()
    shutdown()

    assert _span_rows(observed_root, "mcp.get_run_summary")[0] == {
        "run_store_selector_misses": 1
    }


def test_artifact_resolution_records_outcome_and_size(observed_root: Path) -> None:
    from codeclone.surfaces.mcp import _session_audit_artifact_mixin as mixin

    def _found(
        _path: Path, _run_id: str | None, _digest: str | None
    ) -> tuple[str, int, object | None]:
        return "ok", 1, {"receipt": "payload"}

    def _missing(
        _path: Path, _run_id: str | None, _digest: str | None
    ) -> tuple[str, int, object | None]:
        return "not_found", 0, None

    def _drifted(
        _path: Path, _run_id: str | None, _digest: str | None
    ) -> tuple[str, int, object | None]:
        return "digest_mismatch", 1, None

    with operation(name="mcp.get_review_receipt", surface="mcp"):
        for lookup in (_found, _missing, _drifted):
            mixin._durable_artifact_response(
                root=str(observed_root),
                run_id="run0",
                artifact_digest=None,
                digest_key="receipt_digest",
                output_format="structured",
                supported_formats=frozenset({"structured"}),
                require_message="needs run_id",
                lookup=lookup,
                render=lambda artifact, _fmt: cast("dict[str, object]", artifact),
                envelope=lambda payload: payload,
            )
    shutdown()

    # Per span, not summed: summing keeps a missing/drifted swap invisible,
    # because the totals are identical either way. Each lookup gets its own
    # span, in the order they were called, and each must carry its own outcome.
    found, missing, drifted = _span_rows(
        observed_root, "mcp.run_store.resolve_artifact"
    )
    assert found["run_store_artifacts_retained"] == 1
    assert found["run_store_artifact_bytes"] > 0
    assert "run_store_artifacts_missing" not in found
    assert "run_store_artifacts_drifted" not in found

    assert missing == {"run_store_artifacts_missing": 1}
    assert drifted == {"run_store_artifacts_drifted": 1}
