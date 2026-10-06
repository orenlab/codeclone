# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Every tool without a store road answers a run held without its payload
with ONE typed outcome -- never a raw error, never an empty answer.

The answer names the run, the reason word ``payload_evicted`` and the step
that brings the run back: run ids are content-addressed, so analysing the
same tree again registers the same run, whole.  A tool WITH a store road
answers the same outcome when the store cannot stand in for the payload,
with the store's reason in ``serving``.

Driven on a temporary repository with its own store (the rollout and the
serving switch set inside the test, never a production store); the payload
is dropped with the registry's own lever, never a production flag.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeclone.surfaces.mcp._run_residence import (
    payload_evicted_answer,
    resident_identity,
)
from codeclone.surfaces.mcp._session_shared import (
    MCPGateRequest,
    MCPRunIdentity,
    MCPRunRecord,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@e.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@e.com",
        },
    )


@dataclass
class _Evicted:
    root: Path
    store: Path
    service: CodeCloneMCPService
    record: MCPRunRecord
    identity: MCPRunIdentity

    @property
    def run_id(self) -> str:
        return self.record.run_id

    def expected(self) -> dict[str, object]:
        return payload_evicted_answer(self.identity)


@pytest.fixture
def evicted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Evicted]:
    root = tmp_path / "repo"
    root.joinpath("pkg").mkdir(parents=True)
    root.joinpath("pkg", "__init__.py").write_text("", "utf-8")
    root.joinpath("pkg", "m.py").write_text(
        "def f(x: int) -> int:\n    if x:\n        return x\n    return -x\n",
        "utf-8",
    )
    root.joinpath("README.md").write_text("stable\n", "utf-8")
    for args in (("init", "-q"), ("add", "."), ("commit", "-qm", "init")):
        _git(root, *args)
    store = tmp_path / "runs.sqlite3"
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(store))
    monkeypatch.setenv("CODECLONE_SERVE_FROM", "run_store")
    service = CodeCloneMCPService(history_limit=2)
    service.analyze_repository(
        MCPAnalysisRequest(root=str(root), respect_pyproject=False)
    )
    record = service._runs.records()[-1]
    identity = resident_identity(record)
    assert service._runs.drop_payload(identity)
    yield _Evicted(root, store, service, record, identity)


def _scoped(state: _Evicted) -> dict[str, object]:
    return {"run_id": state.run_id, "root": str(state.root)}


#: Every tool that reads a run and has no store road, asked about the run.
_NO_STORE_ROAD: dict[str, Callable[[_Evicted], dict[str, object]]] = {
    "get_production_triage": lambda s: s.service.get_production_triage(**_scoped(s)),
    "get_report_section": lambda s: s.service.get_report_section(
        section="meta", **_scoped(s)
    ),
    "generate_pr_summary": lambda s: s.service.generate_pr_summary(**_scoped(s)),
    "list_findings": lambda s: s.service.list_findings(**_scoped(s)),
    "get_finding": lambda s: s.service.get_finding(finding_id="x", **_scoped(s)),
    "get_remediation": lambda s: s.service.get_remediation(
        finding_id="x", **_scoped(s)
    ),
    "list_hotspots": lambda s: s.service.list_hotspots(
        kind="highest_spread", **_scoped(s)
    ),
    "mark_finding_reviewed": lambda s: s.service.mark_finding_reviewed(
        finding_id="x", **_scoped(s)
    ),
    "list_reviewed_findings": lambda s: s.service.list_reviewed_findings(**_scoped(s)),
    "check_complexity": lambda s: s.service.check_complexity(**_scoped(s)),
    "check_clones": lambda s: s.service.check_clones(**_scoped(s)),
    "check_coupling": lambda s: s.service.check_coupling(**_scoped(s)),
    "check_cohesion": lambda s: s.service.check_cohesion(**_scoped(s)),
    "check_dead_code": lambda s: s.service.check_dead_code(**_scoped(s)),
    "check_authority": lambda s: s.service.check_authority(**_scoped(s)),
    "validate_review_claims": lambda s: s.service.validate_review_claims(
        text="No new findings.", **_scoped(s)
    ),
    "create_review_receipt": lambda s: s.service.create_review_receipt(**_scoped(s)),
    "get_implementation_context": lambda s: s.service.get_implementation_context(
        root=str(s.root), run_id=s.run_id, paths=["pkg/m.py"]
    ),
    "start_controlled_change": lambda s: s.service.start_controlled_change(
        root=str(s.root),
        scope={"allowed_files": ["README.md"]},
        intent="edit the readme",
    ),
}


@pytest.mark.parametrize("tool", sorted(_NO_STORE_ROAD))
def test_a_tool_without_a_store_road_answers_the_one_typed_outcome(
    evicted: _Evicted, tool: str
) -> None:
    assert _NO_STORE_ROAD[tool](evicted) == evicted.expected()


@pytest.mark.parametrize(
    "uri",
    ["codeclone://latest/summary", "codeclone://runs/{run_id}/summary"],
)
def test_a_resource_of_the_run_answers_the_one_typed_outcome(
    evicted: _Evicted, uri: str
) -> None:
    text = evicted.service.read_resource(uri.format(run_id=evicted.run_id[:8]))

    assert json.loads(text) == json.loads(json.dumps(evicted.expected()))


def test_the_typed_outcome_names_the_run_and_the_step_that_brings_it_back(
    evicted: _Evicted,
) -> None:
    answer = evicted.expected()

    assert answer["run_id"] == evicted.run_id[:8]
    assert answer["status"] == "unavailable"
    assert answer["reason"] == "payload_evicted"
    assert f"analyze_repository(root='{evicted.root}')" in str(answer["next_step"])
    assert "serving" not in answer


def test_analysing_the_same_tree_again_brings_the_run_back_whole(
    evicted: _Evicted,
) -> None:
    evicted.service.analyze_repository(
        MCPAnalysisRequest(root=str(evicted.root), respect_pyproject=False)
    )

    answer = evicted.service.list_findings(**_scoped(evicted))

    assert answer.get("reason") != "payload_evicted"
    assert answer["run_id"] == evicted.run_id[:8]


#: Every tool with a store road, asked about the run.
_STORE_ROAD: dict[str, Callable[[_Evicted], dict[str, object]]] = {
    "get_run_summary": lambda s: s.service.get_run_summary(s.run_id, root=str(s.root)),
    "get_blast_radius": lambda s: s.service.get_blast_radius(
        files=["pkg/m.py"], **_scoped(s)
    ),
    "compare_runs": lambda s: s.service.compare_runs(
        before_run_id=s.run_id, after_run_id=s.run_id, root=str(s.root)
    ),
    "evaluate_gates": lambda s: s.service.evaluate_gates(
        MCPGateRequest(run_id=s.run_id, root=str(s.root))
    ),
    "check_patch_contract": lambda s: s.service.check_patch_contract(
        mode="budget", **_scoped(s)
    ),
}


@pytest.mark.parametrize("tool", sorted(_STORE_ROAD))
def test_a_store_road_answers_from_the_store_without_the_payload(
    evicted: _Evicted, tool: str
) -> None:
    answer = _STORE_ROAD[tool](evicted)

    serving = answer["serving"]
    assert isinstance(serving, dict)
    assert serving["source"] == "run_store", answer
    assert "payload_evicted" in str(serving["detail"])


@pytest.mark.parametrize("tool", sorted(_STORE_ROAD))
def test_a_store_road_the_store_refuses_answers_the_typed_outcome(
    evicted: _Evicted, tool: str
) -> None:
    evicted.store.unlink()

    answer = _STORE_ROAD[tool](evicted)

    serving = answer.pop("serving")
    assert answer == evicted.expected()
    assert isinstance(serving, dict)
    assert serving["source"] == "memory"
    assert serving["reason"] == "store_absent"


@pytest.mark.parametrize("tool", sorted(_STORE_ROAD))
def test_with_the_switch_on_memory_a_store_road_answers_the_typed_outcome(
    evicted: _Evicted, tool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODECLONE_SERVE_FROM", "memory")

    answer = _STORE_ROAD[tool](evicted)

    serving = answer.pop("serving")
    assert answer == evicted.expected()
    assert isinstance(serving, dict)
    assert serving["reason"] == "store_disabled"
