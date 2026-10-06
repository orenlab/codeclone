# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A run held without its payload is answered from the run store, byte for
byte the answer it got while the payload was held.

The five readings with a store road -- the run summary, the blast radius,
the run comparison, the gates and the patch contract (budget and
verification) -- are asked every question of their published populations
twice: with the run whole, under the serving switch on the store, and
again with the run's payload dropped (the test lever: the registry's own
``drop_payload``, then the record put back where it was).  The two answers
must be the same bytes but for the CLOSED list of fields an answer may not
carry across a drop:

* ``serving`` -- it names the payload-evicted road (``detail``);
* ``_audit_sequence`` (patch contract only) -- the audit trail's sequence of
  the event each call writes: an emission fact, already outside the store's
  equality rule (``_run_store_serving._with_emission_facts``).

A run whose store copy cannot answer (published nowhere, or withheld) is
the one typed refusal instead, with the store's reason in ``serving``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

import pytest

from codeclone.api.run_residence import ResidentRun
from codeclone.surfaces.mcp._run_residence import resident_identity
from codeclone.surfaces.mcp._session_shared import (
    MCPGateRequest,
    MCPRunRecord,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.utils.coerce import as_mapping
from tests._blast_radius_serving import (
    BLAST_POPULATIONS,
    blast_answer,
    blast_requests,
    shared_blast_populations,
)
from tests._compare_runs_serving import COMPARE_FOCUSES, shared_pairs
from tests._patch_contract_serving import CYCLE_BUILDERS, shared_cycles
from tests._run_summary_serving import (
    SUMMARY_POPULATIONS,
    serving_environment,
    shared_populations,
)

#: The fields an answer may not carry across a drop -- closed: a field that
#: differs and is not here fails.
UNAVAILABLE_ACROSS_A_DROP: dict[str, frozenset[str]] = {
    "get_run_summary": frozenset({"serving"}),
    "get_blast_radius": frozenset({"serving"}),
    "compare_runs": frozenset({"serving"}),
    "evaluate_gates": frozenset({"serving"}),
    "check_patch_contract": frozenset({"serving", "_audit_sequence"}),
}
_STORE = "run_store"
_EVICTED = "payload_evicted"


@contextmanager
def payload_dropped(service: CodeCloneMCPService, run_id: str) -> Iterator[int]:
    """Every whole execution of ``run_id`` held by its resident identity for
    the block, then put back exactly where it was: the lever, never a flag."""
    runs = service._runs
    dropped: list[MCPRunRecord] = [
        record
        for record in runs.records()
        if record.run_id == run_id and runs.drop_payload(resident_identity(record))
    ]
    try:
        yield len(dropped)
    finally:
        with runs._lock:
            for record in dropped:
                event_id = record.execution.execution_event_id
                assert isinstance(runs._executions[event_id], ResidentRun)
                runs._executions[event_id] = record


def _wire(answer: Mapping[str, object], excluded: frozenset[str]) -> str:
    return json.dumps(
        {key: value for key, value in answer.items() if key not in excluded},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _is_refusal(answer: Mapping[str, object]) -> bool:
    return answer.get("reason") == _EVICTED and answer.get("status") == "unavailable"


def _served_evicted(serving: object) -> bool:
    if not isinstance(serving, Mapping):
        return False
    return serving.get("source") == _STORE and _EVICTED in str(
        serving.get("detail", "")
    )


class _Tally:
    """What the population reached: served across the drop, refused, or
    untouched -- a question that never read the dropped run, whose answer
    must then be the same bytes, ``serving`` included."""

    def __init__(self) -> None:
        self.served = 0
        self.refused = 0
        self.untouched = 0
        self.unequal: list[str] = []

    def accounting(self, tool: str) -> str:
        """The population reached, printed beside the verdict (run with -s)."""
        line = (
            f"{tool}: served={self.served} refused={self.refused} "
            f"untouched={self.untouched} unequal={len(self.unequal)}"
        )
        print(line)
        return line

    def take(
        self,
        name: str,
        tool: str,
        whole: Mapping[str, object],
        evicted: Mapping[str, object],
    ) -> str:
        if _is_refusal(evicted):
            self.refused += 1
            serving = evicted.get("serving")
            assert isinstance(serving, Mapping), (name, evicted)
            assert serving.get("source") == "memory", (name, serving)
            return "refused"
        if not _served_evicted(evicted.get("serving")):
            # Never read the dropped run: the same bytes, ``serving`` too.
            self.untouched += 1
            emitted = UNAVAILABLE_ACROSS_A_DROP[tool] - {"serving"}
            if _wire(whole, emitted) != _wire(evicted, emitted):
                self.unequal.append(name)
            return "untouched"
        self.served += 1
        # An emission fact is not carried across, but it is emitted: the
        # answer without a payload writes its audit event as the whole one did.
        if ("_audit_sequence" in whole) != ("_audit_sequence" in evicted):
            self.unequal.append(f"{name}: audit emission")
        if _wire(whole, UNAVAILABLE_ACROSS_A_DROP[tool]) != _wire(
            evicted, UNAVAILABLE_ACROSS_A_DROP[tool]
        ):
            self.unequal.append(name)
        return "served"


# ── the run summary ──────────────────────────────────────────────────────


def _store_answered(whole: Mapping[str, object]) -> bool:
    """Whether the store answered the question while the run was whole --
    the one fact that decides what a drop leaves: the store's answer, or
    the refusal."""
    serving = whole.get("serving")
    assert isinstance(serving, Mapping), whole
    return serving.get("reason") == "served"


def test_the_run_summary_of_a_run_without_its_payload(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    populations = shared_populations(tmp_path_factory)
    tally = _Tally()
    for name in SUMMARY_POPULATIONS:
        population = populations[name]
        whole = population.answer(serve_from=_STORE)
        with payload_dropped(population.service, population.record.run_id) as n:
            assert n >= 1, name
            evicted = population.answer(serve_from=_STORE)
        tally.take(name, "get_run_summary", whole, evicted)
        assert _is_refusal(evicted) is not _store_answered(whole), (name, evicted)
        if _store_answered(whole):
            assert evicted["serving"] == {
                **as_mapping(whole["serving"]),
                "detail": _EVICTED,
            }

    tally.accounting("get_run_summary")
    assert tally.unequal == []
    assert tally.served == len(SUMMARY_POPULATIONS)


# ── the blast radius ─────────────────────────────────────────────────────


def test_the_blast_radius_of_a_run_without_its_payload(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    populations = shared_blast_populations(tmp_path_factory)
    tally = _Tally()
    for name in BLAST_POPULATIONS:
        population = populations[name]
        for request in blast_requests(population):
            label = f"{name}:{request.key}"
            whole = blast_answer(population, request, serve_from=_STORE)
            with payload_dropped(population.service, population.record.run_id):
                evicted = blast_answer(population, request, serve_from=_STORE)
            tally.take(label, "get_blast_radius", whole, evicted)
            assert _is_refusal(evicted) is not _store_answered(whole), label

    tally.accounting("get_blast_radius")
    assert tally.unequal == []
    assert tally.served > 0


# ── the run comparison ───────────────────────────────────────────────────


def test_a_comparison_of_runs_one_or_both_held_without_payload(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    pairs = shared_pairs(tmp_path_factory)
    tally = _Tally()
    for name, pair in pairs.items():
        for focus in COMPARE_FOCUSES:
            whole = pair.ask(focus, serve_from=_STORE)
            for side, run_id in (
                ("before", pair.before.run_id),
                ("after", pair.after.run_id),
            ):
                with payload_dropped(pair.service, run_id):
                    evicted = pair.ask(focus, serve_from=_STORE)
                label = f"{name}:{focus}:{side}"
                if tally.take(label, "compare_runs", whole, evicted) == "served":
                    # The run without its payload says so in its own block.
                    runs = as_mapping(as_mapping(evicted["serving"]).get("runs"))
                    assert _served_evicted(runs[side]), (label, runs)

    tally.accounting("compare_runs")
    assert tally.unequal == []
    assert tally.served > 0


# ── the gates ────────────────────────────────────────────────────────────


def test_the_gates_of_a_run_without_its_payload(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    cycles = shared_cycles(tmp_path_factory)
    tally = _Tally()
    requests = {
        "default": {},
        "health_floor": {"fail_health": 100},
        "other_gates": {
            "fail_on_new_metrics": True,
            "fail_cycles": True,
            "fail_dead_code": True,
            "fail_on_new": True,
            "fail_threshold": 0,
        },
    }
    for name in CYCLE_BUILDERS:
        cycle = cycles[name]
        for record in (cycle.before, cycle.after):
            if record is None:
                continue
            for label, policy in requests.items():
                request = MCPGateRequest(
                    run_id=record.run_id,
                    root=str(cycle.root),
                    **policy,  # type: ignore[arg-type]
                )
                with serving_environment(cycle.store_path, serve_from=_STORE):
                    whole = cycle.service.evaluate_gates(request)
                    with payload_dropped(cycle.service, record.run_id):
                        evicted = cycle.service.evaluate_gates(request)
                tally.take(
                    f"{name}:{record.run_id[:8]}:{label}",
                    "evaluate_gates",
                    whole,
                    evicted,
                )

    tally.accounting("evaluate_gates")
    assert tally.unequal == []
    assert tally.served > 0


# ── the patch contract ───────────────────────────────────────────────────


def _patch_answers(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[str, dict[str, object], dict[str, object]]]:
    cycles = shared_cycles(tmp_path_factory)
    for name in CYCLE_BUILDERS:
        cycle = cycles[name]
        sides = {"before": cycle.before.run_id}
        if cycle.after is not None:
            sides["after"] = cycle.after.run_id
        for label in cycle.questions:
            whole = cycle.ask(label, serve_from=_STORE)
            for side, run_id in sides.items():
                with payload_dropped(cycle.service, run_id):
                    evicted = cycle.ask(label, serve_from=_STORE)
                yield f"{name}:{label}:{side}", whole, evicted


def test_the_patch_contract_over_runs_held_without_payload(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    tally = _Tally()
    statuses: set[str] = set()
    for label, whole, evicted in _patch_answers(tmp_path_factory):
        if tally.take(label, "check_patch_contract", whole, evicted) == "served":
            statuses.add(str(evicted.get("status", evicted.get("mode"))))

    tally.accounting("check_patch_contract")
    assert tally.unequal == []
    assert tally.served > 0
    # The population carries the verdicts the verifier can reach.
    assert {"accepted", "violated", "unverified"} <= statuses


def test_the_closed_list_is_closed() -> None:
    """Every store-served tool has its entry, and no entry names more than
    the serving block and the one emission fact."""
    assert set(UNAVAILABLE_ACROSS_A_DROP) == {
        "get_run_summary",
        "get_blast_radius",
        "compare_runs",
        "evaluate_gates",
        "check_patch_contract",
    }
    assert set().union(*UNAVAILABLE_ACROSS_A_DROP.values()) == {
        "serving",
        "_audit_sequence",
    }
