# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest

import codeclone.memory.finish_workflow as finish_workflow
from codeclone.memory.coverage import ScopeCoverageReport
from codeclone.memory.models import MemoryProject
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.memory.staleness import StalenessReport


def _store() -> SqliteEngineeringMemoryStore:
    return cast("SqliteEngineeringMemoryStore", object())


def _project() -> MemoryProject:
    return cast("MemoryProject", type("Project", (), {"id": "proj-1"})())


def _patch_workflow_steps(
    monkeypatch: pytest.MonkeyPatch,
    *,
    coverage: Callable[..., object],
    proposal: Callable[..., object],
    staleness: Callable[..., object],
    delta: Callable[..., object],
) -> None:
    for name, replacement in (
        ("compute_scope_coverage", coverage),
        ("propose_memory_from_changed_paths", proposal),
        ("apply_scope_staleness", staleness),
        ("coverage_delta", delta),
    ):
        monkeypatch.setattr(finish_workflow, name, replacement)


def test_finish_memory_workflow_preserves_order_and_typed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    before = ScopeCoverageReport(("pkg/mod.py",), 0, 1, 0, ("pkg/mod.py",))
    after = ScopeCoverageReport(("pkg/mod.py",), 1, 1, 100, ())
    staleness = StalenessReport(2, 0, 0, {"scope_changed": 2})
    candidates: list[dict[str, object]] = [{"id": "mem-1", "status": "draft"}]
    delta: dict[str, object] = {
        "scope_coverage_before": 0,
        "scope_coverage_after": 100,
        "new_uncovered_paths": ["pkg/mod.py"],
    }
    coverage_results = iter((before, after))

    def _coverage(*args: Any, **kwargs: Any) -> ScopeCoverageReport:
        events.append("coverage")
        assert kwargs == {
            "project_id": "proj-1",
            "scope_paths": ("pkg/mod.py",),
        }
        return next(coverage_results)

    def _propose(*args: Any, **kwargs: Any) -> list[dict[str, object]]:
        events.append("proposal")
        assert kwargs["changed_paths"] == ("pkg/mod.py",)
        return candidates

    def _staleness(*args: Any, **kwargs: Any) -> StalenessReport:
        events.append("staleness")
        assert kwargs == {
            "project_id": "proj-1",
            "changed_paths": ("pkg/mod.py",),
        }
        return staleness

    def _delta(
        actual_before: ScopeCoverageReport,
        actual_after: ScopeCoverageReport,
    ) -> dict[str, object]:
        events.append("delta")
        assert actual_before is before
        assert actual_after is after
        return delta

    _patch_workflow_steps(
        monkeypatch,
        coverage=_coverage,
        proposal=_propose,
        staleness=_staleness,
        delta=_delta,
    )

    result = finish_workflow.execute_finish_memory_workflow(
        _store(),
        project=_project(),
        changed_paths=("pkg/mod.py",),
        claims_text="claim",
        review_text="review",
        verification_profile="python_structural",
        max_candidates=10,
        max_statement_chars=200,
    )

    assert events == ["coverage", "proposal", "staleness", "coverage", "delta"]
    assert result.candidates is candidates
    assert result.staleness is staleness
    assert result.coverage_before is before
    assert result.coverage_after is after
    assert result.coverage_delta is delta


def test_finish_memory_workflow_propagates_proposal_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    failure = RuntimeError("proposal failed")
    before = ScopeCoverageReport(("pkg/mod.py",), 0, 1, 0, ("pkg/mod.py",))

    def _coverage(*args: Any, **kwargs: Any) -> ScopeCoverageReport:
        events.append("coverage")
        return before

    def _propose(*args: Any, **kwargs: Any) -> list[dict[str, object]]:
        events.append("proposal")
        raise failure

    def _unexpected(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("workflow continued after proposal failure")

    _patch_workflow_steps(
        monkeypatch,
        coverage=_coverage,
        proposal=_propose,
        staleness=_unexpected,
        delta=_unexpected,
    )

    with pytest.raises(RuntimeError) as caught:
        finish_workflow.execute_finish_memory_workflow(
            _store(),
            project=_project(),
            changed_paths=("pkg/mod.py",),
            claims_text=None,
            review_text=None,
            verification_profile=None,
            max_candidates=10,
            max_statement_chars=200,
        )

    assert caught.value is failure
    assert events == ["coverage", "proposal"]
