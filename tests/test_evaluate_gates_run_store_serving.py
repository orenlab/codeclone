# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``evaluate_gates`` served from the run store (consumer migration C4).

The tool takes a REQUEST, and the one model it is served by is
recomputation: the one evaluator runs over the run's gate inputs -- the
record's on the memory side, the stored ones (``ServedPatchRun.gate_state``,
read through the patch-run door) on the store side -- under whatever the
request names.  The store states the run's gate inputs, never a verdict for
a request it was not asked, so no request is looked up and none falls back
for being "other than the published one".  The store's answer is served
only when it is the memory's byte for byte, with ``serving`` beside it
(the budget's one-run shape); the session's gate result -- the one the
review receipt and the PR summary read -- is the answer without it.

Pinned on every run of the patch-contract battery and of the run summary's
populations, each under four requests: the request the run was published
with (its document's own ``evaluation.request``), the same with one
threshold moved, another set of gates, and no gate at all.  Under the
published request the recomputed answer is also the outcome the run
published.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import pytest

from codeclone.surfaces.mcp import _session_helpers as _helpers
from codeclone.surfaces.mcp._session_shared import (
    MCPGateRequest,
    MCPRunRecord,
    MCPServiceContractError,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.utils.coerce import as_mapping, as_sequence
from tests._patch_contract_serving import CYCLE_BUILDERS, shared_cycles
from tests._run_summary_serving import (
    SUMMARY_POPULATIONS,
    _bumped,
    _edited,
    serving_environment,
    shared_populations,
    store_row_replaced,
)
from tests.test_compare_runs_run_store_serving import _receipt, receipt_change

_GENERATION_1 = Path(__file__).parent / "fixtures" / "run_store_generation_1"

#: The request fields a published evaluation request carries under the same
#: name (the selectors ``run_id`` and ``root`` are not policy).
_POLICY_FIELDS: tuple[str, ...] = tuple(
    field.name
    for field in fields(MCPGateRequest)
    if field.name not in {"run_id", "root"}
)


@dataclass(frozen=True, slots=True)
class _GatedRun:
    """One published run and the session that holds it."""

    name: str
    service: CodeCloneMCPService
    store_path: Path
    root: Path
    record: MCPRunRecord

    def resolved(self) -> MCPRunRecord:
        """The record the tool resolves the run id to: of two executions of
        one content-addressed run id, the latest."""
        return _helpers._resolve_run_for_optional_root(
            self.service._runs, self.record.run_id, str(self.root)
        )

    def published_request(self) -> dict[str, object]:
        """The policy the run was evaluated under, as its document states."""
        evaluation = as_mapping(self.record.served_report.get("evaluation"))
        stated = as_mapping(evaluation.get("request"))
        return {name: stated[name] for name in _POLICY_FIELDS}

    def ask(self, policy: Mapping[str, Any], *, serve_from: str | None) -> object:
        """``evaluate_gates`` under one policy and one switch; a refusal is
        an answer too, compared as one."""
        request = dataclasses.replace(
            MCPGateRequest(run_id=self.record.run_id, root=str(self.root)),
            **policy,
        )
        with serving_environment(self.store_path, serve_from=serve_from):
            try:
                return self.service.evaluate_gates(request)
            except MCPServiceContractError as refusal:
                return {"__refused__": str(refusal)}


def _gated_runs(factory: pytest.TempPathFactory) -> list[_GatedRun]:
    runs: dict[tuple[int, str], _GatedRun] = {}
    cycles = shared_cycles(factory)
    for name in CYCLE_BUILDERS:
        cycle = cycles[name]
        for side, record in (("before", cycle.before), ("after", cycle.after)):
            if record is None:
                continue
            key = (id(cycle.service), record.run_id)
            runs.setdefault(
                key,
                _GatedRun(
                    f"{name}.{side}",
                    cycle.service,
                    cycle.store_path,
                    cycle.root,
                    record,
                ),
            )
    populations = shared_populations(factory)
    for name in SUMMARY_POPULATIONS:
        population = populations[name]
        record = population.record
        runs[(id(population.service), record.run_id)] = _GatedRun(
            name, population.service, population.store_path, population.root, record
        )
    return list(runs.values())


def _moved_threshold(policy: Mapping[str, object]) -> dict[str, object]:
    """The published policy with ONE threshold moved: a health floor no run
    reaches."""
    return {**policy, "fail_health": 100}


def _other_gates(policy: Mapping[str, object]) -> dict[str, object]:
    """Another set of gates, the published thresholds kept."""
    return {
        **policy,
        "fail_on_new_metrics": True,
        "fail_on_api_break": True,
        "fail_cycles": True,
        "fail_dead_code": True,
        "fail_on_typing_regression": True,
        "fail_on_new": True,
        "fail_threshold": 0,
    }


#: Each request of the population, from the run's published policy.
_REQUESTS: dict[str, Callable[[Mapping[str, object]], dict[str, object]]] = {
    "published": dict,
    "one_threshold_moved": _moved_threshold,
    "other_gates": _other_gates,
    "no_gate": lambda _policy: {},
}


@pytest.fixture(scope="module")
def gated_runs(tmp_path_factory: pytest.TempPathFactory) -> list[_GatedRun]:
    return _gated_runs(tmp_path_factory)


@pytest.fixture(scope="module")
def answers(
    gated_runs: list[_GatedRun],
) -> dict[tuple[str, str], tuple[object, object]]:
    """Every question twice: (memory switch, run-store switch)."""
    asked: dict[tuple[str, str], tuple[object, object]] = {}
    for run in gated_runs:
        published = run.published_request()
        for label, build in _REQUESTS.items():
            policy = build(published)
            asked[(run.name, label)] = (
                run.ask(policy, serve_from="memory"),
                run.ask(policy, serve_from="run_store"),
            )
    return asked


def _wire(answer: object) -> str:
    mapping = as_mapping(answer)
    return json.dumps(
        {key: value for key, value in mapping.items() if key != "serving"},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def test_the_population_moves_every_verdict_under_every_request(
    gated_runs: list[_GatedRun],
    answers: dict[tuple[str, str], tuple[object, object]],
) -> None:
    """The accounting: 49 runs (51 executions, two of them sharing a run id
    with their cycle's other run), four requests each, and the answers reach
    every exit code the evaluator gives; the moved threshold and the other
    gates each move some run's verdict off its published one."""
    assert len(gated_runs) == 49
    assert len(answers) == 49 * 4
    codes = {
        as_mapping(memory).get("exit_code") for memory, _stored in answers.values()
    }
    assert {0, 2, 3} <= codes
    for label in ("one_threshold_moved", "other_gates"):
        moved = [
            run.name
            for run in gated_runs
            if as_mapping(answers[(run.name, label)][0]).get("reasons")
            != as_mapping(answers[(run.name, "published")][0]).get("reasons")
        ]
        assert moved, label


@pytest.mark.parametrize("label", list(_REQUESTS))
def test_every_run_is_served_from_the_store_under_every_request(
    gated_runs: list[_GatedRun],
    answers: dict[tuple[str, str], tuple[object, object]],
    label: str,
) -> None:
    """Under each request, on every run: the store's answer is served, byte
    for byte the memory's; the memory switch reads no store and says so."""
    for run in gated_runs:
        memory, stored = answers[(run.name, label)]
        link = run.resolved().execution.run_snapshot_link
        assert link is not None
        assert as_mapping(stored)["serving"] == {
            "source": "run_store",
            "reason": "served",
            "store_run_id": link.store_run_id,
        }, run.name
        assert _wire(stored) == _wire(memory), run.name
        serving = as_mapping(as_mapping(memory)["serving"])
        assert (serving["source"], serving["reason"]) == ("memory", "store_disabled")


def test_the_published_request_recomputes_the_published_outcome(
    gated_runs: list[_GatedRun],
    answers: dict[tuple[str, str], tuple[object, object]],
) -> None:
    """The request the run was published with: the served answer is the
    outcome the run published -- recomputation over the stored inputs
    reproduces the stored verdict."""
    for run in gated_runs:
        outcome = as_mapping(
            as_mapping(run.record.served_report.get("evaluation")).get("outcome")
        )
        stored = as_mapping(answers[(run.name, "published")][1])
        assert (stored["exit_code"], stored["reasons"]) == (
            outcome["exit_code"],
            list(as_sequence(outcome["reasons"])),
        ), run.name


#: Each field of the answer (census-3 rows), read off one answer.
_FIELDS: dict[str, Callable[[Mapping[str, object]], object]] = {
    "C4.01 run_id": lambda answer: answer["run_id"],
    "C4.02 would_fail": lambda answer: answer["would_fail"],
    "C4.03 exit_code": lambda answer: answer["exit_code"],
    "C4.04 reasons[]": lambda answer: answer["reasons"],
    "C4.05 config.*": lambda answer: answer["config"],
}


@pytest.mark.parametrize("field", list(_FIELDS))
def test_each_field_is_the_memory_bytes_on_every_question(
    answers: dict[tuple[str, str], tuple[object, object]], field: str
) -> None:
    read = _FIELDS[field]
    values = set()
    for key, (memory, stored) in answers.items():
        assert json.dumps(read(as_mapping(stored))) == json.dumps(
            read(as_mapping(memory))
        ), (field, key)
        values.add(json.dumps(read(as_mapping(memory))))
    assert len(values) >= 2, field


def test_the_session_keeps_the_answer_without_its_serving_block(
    gated_runs: list[_GatedRun],
) -> None:
    """The gate result the receipt and the PR summary read is the answer
    itself -- the same bytes under either switch."""
    run = next(run for run in gated_runs if run.name == "regressed.after")
    policy = _other_gates(run.published_request())
    kept = []
    for switch in ("memory", "run_store"):
        answer = as_mapping(run.ask(policy, serve_from=switch))
        held = run.service._session_gate_result(run.record.run_id)
        assert held == {key: value for key, value in answer.items() if key != "serving"}
        kept.append(held)
    assert kept[0] == kept[1]


def test_a_replaced_stored_gate_input_moves_the_stores_answer_and_memory_answers(
    gated_runs: list[_GatedRun],
) -> None:
    """The stored health score bumped: under a health floor at the run's own
    score, the store's verdict moves, so it disagrees and memory is served
    with the moved fields named -- an answer read anywhere but the store
    would stay ``served``."""
    run = next(run for run in gated_runs if run.name == "improved.before")
    score = as_mapping(as_mapping(run.record.summary).get("health")).get("score")
    assert isinstance(score, int)
    policy = {"fail_health": score + 1}
    clean = as_mapping(run.ask(policy, serve_from="run_store"))
    assert clean["exit_code"] == 3
    assert as_mapping(clean["serving"])["reason"] == "served"
    with store_row_replaced(_edited("health_result", _bumped("score"))):
        moved = as_mapping(run.ask(policy, serve_from="run_store"))
    serving = as_mapping(moved["serving"])
    assert (serving["source"], serving["reason"]) == ("memory", "divergent")
    named = str(serving["detail"]).removeprefix("diverging: ").split(", ")
    assert {"would_fail", "exit_code", "reasons"} <= set(named)
    assert _wire(moved) == _wire(clean)


def test_a_coverage_gate_is_refused_alike_on_both_switches(
    gated_runs: list[_GatedRun],
) -> None:
    """A run handed no coverage report: the coverage gate is refused before
    any store is read, the same words under either switch; a run that
    joined one is answered and served."""
    without = next(run for run in gated_runs if run.name == "improved.before")
    joined = next(run for run in gated_runs if run.name == "regressed.before")
    policy = {"fail_on_untested_hotspots": True}
    refused = [
        without.ask(policy, serve_from=switch) for switch in ("memory", "run_store")
    ]
    assert refused[0] == refused[1]
    assert "__refused__" in as_mapping(refused[0])
    served = as_mapping(joined.ask(policy, serve_from="run_store"))
    assert as_mapping(served["serving"])["reason"] == "served"


def test_the_receipt_reads_the_served_gate_answer(
    receipt_change: tuple[CodeCloneMCPService, Path, str, str],
) -> None:
    """The review receipt's patch status reads the session's gate result:
    a failing gate asked under either switch is the same kept answer, and
    the receipt names it a gate failure alike."""
    service, store, run_id, _intent_id = receipt_change
    receipts = []
    for switch in ("memory", "run_store"):
        with serving_environment(store, serve_from=switch):
            answer = service.evaluate_gates(
                MCPGateRequest(run_id=run_id, fail_health=100)
            )
        assert answer["would_fail"] is True
        kept = service._session_gate_result(
            service._runs.resolve_any_root(run_id).run_id
        )
        assert kept == {key: value for key, value in answer.items() if key != "serving"}
        receipt = _receipt(receipt_change, switch)
        assert "gate_failures" in as_sequence(
            as_mapping(receipt["patch_contract"])["contract_violations"]
        )
        receipts.append(receipt["patch_contract"])
    assert receipts[0] == receipts[1]


def _asked_against(run: _GatedRun, store: Path) -> dict[str, object]:
    with serving_environment(store, serve_from="run_store"):
        return run.service.evaluate_gates(
            MCPGateRequest(run_id=run.record.run_id, root=str(run.root))
        )


def test_a_rollout_without_a_store_answers_memory_typed(
    gated_runs: list[_GatedRun], tmp_path: Path
) -> None:
    run = gated_runs[0]
    answer = _asked_against(run, tmp_path / "absent.sqlite3")
    assert _wire(answer) == _wire(run.ask({}, serve_from="memory"))
    serving = as_mapping(answer["serving"])
    assert (serving["source"], serving["reason"]) == ("memory", "store_absent")


def test_a_store_of_another_generation_answers_memory_typed(
    gated_runs: list[_GatedRun], tmp_path: Path
) -> None:
    store = tmp_path / "generation-1.sqlite3"
    shutil.copy(_GENERATION_1 / "runs.sqlite3", store)
    run = gated_runs[0]
    answer = _asked_against(run, store)
    assert _wire(answer) == _wire(run.ask({}, serve_from="memory"))
    serving = as_mapping(answer["serving"])
    assert (serving["source"], serving["reason"]) == (
        "memory",
        "incompatible_generation",
    )


def test_the_switch_unset_reads_no_store_and_says_so(
    gated_runs: list[_GatedRun],
) -> None:
    run = gated_runs[0]
    unset = as_mapping(run.ask({}, serve_from=None))
    assert unset == as_mapping(run.ask({}, serve_from="memory"))
    serving = as_mapping(unset["serving"])
    assert (serving["source"], serving["reason"]) == ("memory", "store_disabled")
    assert "CODECLONE_SERVE_FROM=memory" in str(serving["detail"])


__all__ = ["receipt_change"]
