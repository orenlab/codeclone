# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.api.execution_event import (
    EXECUTION_PROVENANCE_KEY,
    semantic_projection,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest, MCPGateRequest
from tests.memory_fixtures import cli_memory_repo


def _write_semantic_config(root: Path, *, enabled: bool) -> None:
    value = "true" if enabled else "false"
    (root / "pyproject.toml").write_text(
        f"[tool.codeclone.memory.semantic]\nenabled = {value}\ndimension = 64\n",
        encoding="utf-8",
    )


def _write_python_source(root: Path) -> None:
    package = root / "pkg"
    package.mkdir(exist_ok=True)
    (package / "mod.py").write_text(
        "\n".join(
            [
                "def compute(value: int) -> int:",
                "    total = value + 1",
                "    total += 2",
                "    total += 3",
                "    total += 4",
                "    total += 5",
                "    return total",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _deterministic_snapshot(
    service: CodeCloneMCPService, root: Path
) -> dict[str, object]:
    """One snapshot, taken from a run whose cache state is already settled.

    The measured run is the second, because the first warms the analysis cache
    this surface writes. Cache state is a property of run order, not of the
    semantic setting under test, and comparing a cold run against a warm one
    would let that ordering answer for the setting. Both snapshots are taken
    warm, so what remains between them is the configuration.
    """

    request = MCPAnalysisRequest(
        root=str(root),
        respect_pyproject=True,
    )
    service.analyze_repository(request)
    summary = service.analyze_repository(request)
    run_id = str(summary["run_id"])
    return {
        "run_id": run_id,
        "summary": summary,
        "gates": service.evaluate_gates(MCPGateRequest(run_id=run_id)),
        "receipt": service.create_review_receipt(run_id=run_id, format="json"),
        "memory": service.get_relevant_memory(
            root=str(root),
            scope=["pkg/mod.py"],
            max_records=5,
            detail_level="compact",
        ),
    }


def _both_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, object], dict[str, object]]:
    """The A/B pair: same source, same clock, semantic memory off then on."""

    monkeypatch.setattr(
        "codeclone.surfaces.mcp.session._current_report_timestamp_utc",
        lambda: "2026-06-03T00:00:00Z",
    )
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        _write_python_source(root)
        service = CodeCloneMCPService(history_limit=4)

        _write_semantic_config(root, enabled=False)
        disabled = _deterministic_snapshot(service, root)

        _write_semantic_config(root, enabled=True)
        enabled = _deterministic_snapshot(service, root)
    return disabled, enabled


def test_semantic_enabled_does_not_change_deterministic_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Determinism of what the run STATES, over the semantic projection.

    The comparator knows one symbol from the execution domain --
    :func:`semantic_projection` -- and none of its field names. Two
    executions are two events and their witnesses differ by contract; the
    question this gate asks is whether the CONFIGURATION changed the
    statements, and that question can only be asked of the semantic half.
    A comparison taken over both halves answers a different question and was
    measured red on ``execution_event_id`` alone (2026-09-04).
    """

    disabled, enabled = _both_snapshots(tmp_path, monkeypatch)

    assert semantic_projection(enabled) == semantic_projection(disabled)


def test_the_projection_reaches_the_execution_block_it_removes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Probe validity for the gate above: it must have had something to remove.

    A projection that silently stopped finding the block would leave the gate
    green for the wrong reason -- comparing two payloads that never carried
    the domain at all. So: the raw snapshots DIFFER, the block is present
    before the projection and absent after it, and only then does the
    equality above mean anything.
    """

    disabled, enabled = _both_snapshots(tmp_path, monkeypatch)

    assert enabled != disabled, "the raw pair agreed; the projection is unprobed"

    raw_provenance = _receipt_provenance(disabled)
    assert EXECUTION_PROVENANCE_KEY in raw_provenance
    projected = semantic_projection(disabled)
    assert isinstance(projected, dict)
    assert EXECUTION_PROVENANCE_KEY not in _receipt_provenance(projected)


def test_two_executions_do_not_share_an_execution_event_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The execution id is allowed -- required -- to differ.

    Pinned so no later optimisation can make execution identity deterministic
    in order to satisfy a determinism test: an event that two executions
    share is not an event, it is a second name for the report.
    """

    disabled, enabled = _both_snapshots(tmp_path, monkeypatch)

    left = _receipt_provenance(disabled)[EXECUTION_PROVENANCE_KEY]
    right = _receipt_provenance(enabled)[EXECUTION_PROVENANCE_KEY]
    assert isinstance(left, dict)
    assert isinstance(right, dict)
    assert left["execution_event_id"] != right["execution_event_id"]


def _receipt_provenance(snapshot: object) -> dict[str, object]:
    assert isinstance(snapshot, dict)
    receipt = snapshot["receipt"]
    assert isinstance(receipt, dict)
    provenance = receipt["provenance"]
    assert isinstance(provenance, dict)
    return provenance


def test_a_new_execution_witness_needs_no_change_to_the_comparator() -> None:
    """The ownership property, and the reason this is not a denylist.

    A witness nobody has written yet -- here a name this repository has never
    used -- is removed because it lives inside the declared block, not
    because the projection was taught its name. A denylist would need editing
    the day the witness is added; this needs nothing.
    """

    payload = {
        "run_id": "abcd1234",
        "provenance": {
            "report_digest": "sha256:report",
            EXECUTION_PROVENANCE_KEY: {
                "generation": "sha256:engine",
                "a_witness_no_release_has_ever_carried": "0xdeadbeef",
            },
        },
    }

    assert semantic_projection(payload) == {
        "run_id": "abcd1234",
        "provenance": {"report_digest": "sha256:report"},
    }


def test_the_projection_keeps_every_semantic_fact_it_is_handed() -> None:
    """The other boundary: the projection prunes ONE thing and nothing else.

    Nesting, list members and container types are all preserved, so a
    semantic difference at any depth still diverges. A projection that
    removed a semantic key would leave the gate green on a real regression.
    """

    payload = {
        "run_id": "abcd1234",
        "gates": [{"name": "clones", "passed": True}],
        "shape": ("a", ["b", {"c": 1}]),
        EXECUTION_PROVENANCE_KEY: {"generation": "sha256:engine"},
    }
    projected = semantic_projection(payload)

    assert projected == {
        "run_id": "abcd1234",
        "gates": [{"name": "clones", "passed": True}],
        "shape": ("a", ["b", {"c": 1}]),
    }
    assert isinstance(projected, dict)
    assert isinstance(projected["shape"], tuple)
    assert semantic_projection({"run_id": "abcd1234"}) != semantic_projection(
        {"run_id": "different"}
    )
