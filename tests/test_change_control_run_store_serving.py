# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""One controlled change, start to finish, served from the run store.

Consumer migrations C6 and C7 meet only here: ``start_controlled_change``
computes its blast radius through the blast-radius edge
(``_run_store_serving.served_blast_radius``), and ``finish_controlled_change``
verifies the patch through the patch-contract edge
(``_run_store_serving.served_patch_contract``).  The workflow answers embed
both results without a ``serving`` block, so each edge's own decision is read
where it is made: each edge is wrapped at its call site, and the decision it
returned is recorded.

Under ``CODECLONE_SERVE_FROM=run_store`` every decision of both edges must be
``served`` -- the store's answer was the memory's, byte for byte, at the
start and at the finish.  The same change under the memory switch is the
positive control on the same causal path: the same wrappers record
``store_disabled`` at both edges, and the change reaches the same verdicts.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

import codeclone.surfaces.mcp._patch_contract_runs as patch_runs_mod
import codeclone.surfaces.mcp._session_blast_radius_mixin as blast_mixin_mod
from codeclone.api.run_store_serving import (
    SERVE_FROM_MEMORY,
    SERVE_FROM_RUN_STORE,
    BlastRadiusFacts,
    RunStoreServingOutcome,
    ServedPatchRun,
)
from codeclone.surfaces.mcp._blast_radius import BlastRadiusResult
from codeclone.surfaces.mcp._run_store_serving import (
    served_blast_radius,
    served_patch_contract,
)
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest, MCPRunRecord
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.utils.coerce import as_mapping
from tests import conftest as corpora
from tests._blast_radius_serving import FANOUT_TREE
from tests._run_summary_serving import serving_environment

#: The edit the change makes: one new function in the high-radius module.
_EDIT = (
    '\n\ndef widened(value: int) -> int:\n    """Widened."""\n    return value + 1\n'
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _tree(root: Path) -> Path:
    root.mkdir()
    corpora.materialize_projection_corpus(root)
    corpora._write_tree(root, FANOUT_TREE)
    (root / ".gitignore").write_text(".codeclone/\n", "utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "tree")
    return root


class _Decisions:
    """Every decision each edge took, by edge, in order."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.blast: list[str] = []
        self.patch: list[tuple[str, tuple[str, ...]]] = []
        real_blast = served_blast_radius
        real_patch = served_patch_contract

        def blast(
            record: MCPRunRecord,
            memory: BlastRadiusResult,
            compute: Callable[[BlastRadiusFacts], BlastRadiusResult],
        ) -> tuple[BlastRadiusResult, RunStoreServingOutcome]:
            result, outcome = real_blast(record, memory, compute)
            self.blast.append(outcome.reason)
            return result, outcome

        def patch(
            memory: Mapping[str, object],
            runs: Mapping[str, MCPRunRecord],
            store_answer: Callable[[Mapping[str, ServedPatchRun]], dict[str, object]],
        ) -> tuple[dict[str, object], dict[str, object]]:
            answer, serving = real_patch(memory, runs, store_answer)
            self.patch.append((str(serving["reason"]), tuple(sorted(runs))))
            return answer, serving

        monkeypatch.setattr(blast_mixin_mod, "served_blast_radius", blast)
        monkeypatch.setattr(patch_runs_mod, "served_patch_contract", patch)


def _change(
    root: Path, store_path: Path, serve_from: str
) -> tuple[dict[str, object], dict[str, object]]:
    """Analyse, start, edit, re-analyse, finish -- one controlled change."""
    service = CodeCloneMCPService(history_limit=4)
    with serving_environment(store_path, serve_from=serve_from):
        service.analyze_repository(MCPAnalysisRequest(root=str(root)))
        started = service.start_controlled_change(
            root=str(root),
            scope={"allowed_files": ["pkg/core.py"]},
            intent="widen core",
            blast_radius_depth="auto",
        )
        core = root / "pkg" / "core.py"
        core.write_text(core.read_text("utf-8") + _EDIT, "utf-8")
        after = service.analyze_repository(MCPAnalysisRequest(root=str(root)))
        finished = service.finish_controlled_change(
            intent_id=str(started["intent_id"]),
            after_run_id=str(after["run_id"]),
            changed_files=["pkg/core.py"],
        )
    return started, finished


def _verdict(
    started: dict[str, object], finished: dict[str, object]
) -> dict[str, object]:
    blast = as_mapping(started["blast_radius"])
    verification = as_mapping(finished["verification"])
    return {
        "edit_allowed": started["edit_allowed"],
        "radius_level": blast["radius_level"],
        "transitive": as_mapping(blast.get("transitive_dependents_summary")),
        "status": finished["status"],
        "verification": verification["status"],
        "structural_delta": verification["structural_delta"],
        "worsened": verification["worsened"],
    }


def test_a_controlled_change_reads_both_edges_from_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decisions = _Decisions(monkeypatch)
    started, finished = _change(
        _tree(tmp_path / "store"), tmp_path / "store.sqlite3", SERVE_FROM_RUN_STORE
    )
    assert started["edit_allowed"] is True, started
    assert finished["status"] == "accepted", finished
    # The start declares against a high radius: the direct radius and the
    # transitive summary ``auto`` escalates to, each one store decision.
    assert decisions.blast and set(decisions.blast) == {"served"}, decisions.blast
    assert ("served", ("after", "before")) in decisions.patch, decisions.patch
    assert {reason for reason, _sides in decisions.patch} == {"served"}


def test_the_same_change_under_the_memory_switch_is_the_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wrappers sit on the causal path (they record the memory switch at
    both edges), and the change reaches the same verdicts either way."""
    decisions = _Decisions(monkeypatch)
    memory = _change(
        _tree(tmp_path / "memory"), tmp_path / "memory.sqlite3", SERVE_FROM_MEMORY
    )
    assert decisions.blast and set(decisions.blast) == {"store_disabled"}
    assert ("store_disabled", ("after", "before")) in decisions.patch
    assert {reason for reason, _sides in decisions.patch} == {"store_disabled"}
    stored = _change(
        _tree(tmp_path / "store"), tmp_path / "store.sqlite3", SERVE_FROM_RUN_STORE
    )
    assert _verdict(*stored) == _verdict(*memory)
