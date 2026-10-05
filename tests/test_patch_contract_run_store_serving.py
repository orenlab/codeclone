# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``check_patch_contract`` served from the run store (consumer migration C6).

The verifier is written once over the facts of the runs it reads and is
computed twice: over the records (the answer, its audit events written) and
over the runs' stored facts (the shadow).  The store's answer is served only
when the whole answer is the memory's byte for byte; otherwise memory is
served and the fields that differ are named.  The pins below hold that on
every verdict the verifier distinguishes, reached by a battery of
change-control cycles in temporary roots (``tests/_patch_contract_serving``):

* the accounting first -- every verdict, every reason, every verification
  profile and every contract violation kind is REACHED (Probe Validity Law),
  each question at exactly the verdict recorded for it;
* per verdict: the answer under the store is the answer under memory on the
  wire, serving aside, and says where it came from;
* per field: one stored row replaced moves exactly the fields it carries --
  the verdict included -- and the moved fields are named while memory is
  served;
* the switch: unset, the store is not read; ``memory`` names itself;
* the eviction rule of today holds: an evicted before-run is refused, and
  the store does not make it available.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Mapping
from typing import cast

import pytest

from codeclone.surfaces.mcp._patch_contract_runs import (
    PatchSession,
    RecordPatchRun,
    StorePatchRun,
)
from codeclone.surfaces.mcp._session_shared import (
    MCPGateRequest,
    MCPServiceContractError,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests._patch_contract_serving import (
    CYCLE_BUILDERS,
    PATCH_ROW_PERTURBATIONS,
    PATCH_STORE_REFUSAL,
    PatchCycles,
    RecordingAuditWriter,
    shared_cycles,
    stored_patch_run,
)
from tests._run_summary_serving import serving_environment, store_row_replaced

#: Every question of the battery, the verdict the verifier answers it with
#: (``mode:status:reason:profile``, or the refusal) and the serving reason
#: under the store (``None``: the tool refused, so there is no answer).
#: Measured 2026-10-03 on the base tip and on this edge: identical.
EXPECTED: dict[str, tuple[str, str | None]] = {
    "improved/budget:ci": ("budget:-:-:-", "served"),
    "improved/budget:strict": ("refused:MCPServiceContractError", None),
    "improved/budget:relaxed": ("budget:-:-:-", "served"),
    "improved/structural:ci": ("verify:accepted:-:python_structural", "served"),
    "improved/structural:strict": ("refused:MCPServiceContractError", None),
    "improved/structural:relaxed": ("verify:accepted:-:python_structural", "served"),
    "improved/no_intent:ci": ("verify:accepted:-:python_structural", "served"),
    "improved/no_intent:strict": ("refused:MCPServiceContractError", None),
    "improved/no_intent:relaxed": ("verify:accepted:-:python_structural", "served"),
    "improved/no_after_run": ("verify:unverified:no_after_run:-", "served"),
    "improved/python_without_after": (
        "verify:unverified:no_after_run:python_structural",
        "served",
    ),
    "improved/after_not_new": (
        "verify:unverified:after_run_not_new:python_structural",
        "served",
    ),
    "improved/missing_after_id": (
        "verify:unverified:no_after_run:python_structural",
        "served",
    ),
    "improved/no_before_run": ("verify:unverified:no_before_run:-", "not_published"),
    "improved/no_runs_at_all": ("verify:unverified:no_before_run:-", "not_published"),
    "improved/documentation_only": (
        "verify:violated:scope_violation:documentation_only",
        "served",
    ),
    "improved/documentation_only_with_after": (
        "verify:violated:-:documentation_only",
        "served",
    ),
    "improved/non_python": (
        "verify:violated:scope_violation:non_python_patch",
        "served",
    ),
    "improved/governance_without_after": (
        "verify:violated:scope_violation:governance_config",
        "served",
    ),
    "improved/governance_with_after": ("verify:violated:-:governance_config", "served"),
    "improved/state_artifact": (
        "verify:violated:state_artifact_mutation:state_artifact_change",
        "served",
    ),
    "improved/state_artifact_with_after": (
        "verify:violated:state_artifact_mutation:state_artifact_change",
        "served",
    ),
    "external/structural:ci": (
        "verify:accepted_with_external_changes:-:python_structural",
        "served",
    ),
    "external/structural:strict": (
        "verify:accepted_with_external_changes:-:python_structural",
        "served",
    ),
    "external/structural:relaxed": (
        "verify:accepted_with_external_changes:-:python_structural",
        "served",
    ),
    "left_scope/structural:ci": ("verify:violated:-:python_structural", "served"),
    "left_scope/structural:strict": ("verify:violated:-:python_structural", "served"),
    "left_scope/structural:relaxed": ("verify:accepted:-:python_structural", "served"),
    "left_scope/fast_path_scope": (
        "verify:violated:scope_violation:python_structural",
        "served",
    ),
    "forbidden/structural:ci": ("verify:violated:-:python_structural", "served"),
    "forbidden/structural:strict": ("verify:violated:-:python_structural", "served"),
    "forbidden/structural:relaxed": ("verify:accepted:-:python_structural", "served"),
    "regressed/structural:ci": ("verify:violated:-:python_structural", "served"),
    "regressed/structural:strict": ("verify:violated:-:python_structural", "served"),
    "regressed/structural:relaxed": ("verify:accepted:-:python_structural", "served"),
    "gate_caused/budget:ci": ("budget:-:-:-", "served"),
    "gate_caused/budget:strict": ("budget:-:-:-", "served"),
    "gate_caused/budget:relaxed": ("budget:-:-:-", "served"),
    "gate_caused/structural:ci": ("verify:violated:-:python_structural", "served"),
    "gate_caused/structural:strict": ("verify:violated:-:python_structural", "served"),
    "gate_caused/structural:relaxed": ("verify:accepted:-:python_structural", "served"),
    "gate_caused/no_intent:ci": ("verify:violated:-:python_structural", "served"),
    "gate_caused/no_intent:strict": ("verify:violated:-:python_structural", "served"),
    "gate_caused/no_intent:relaxed": ("verify:accepted:-:python_structural", "served"),
    "harder_only/budget:ci": ("budget:-:-:-", "served"),
    "harder_only/budget:strict": ("budget:-:-:-", "served"),
    "harder_only/budget:relaxed": ("budget:-:-:-", "served"),
    "harder_only/structural:ci": ("verify:violated:-:python_structural", "served"),
    "harder_only/structural:strict": ("verify:violated:-:python_structural", "served"),
    "harder_only/structural:relaxed": ("verify:accepted:-:python_structural", "served"),
    "incomparable/structural:ci": (
        "verify:unverified:incomparable_runs:python_structural",
        "served",
    ),
    "incomparable/structural:strict": (
        "verify:unverified:incomparable_runs:python_structural",
        "served",
    ),
    "incomparable/structural:relaxed": (
        "verify:unverified:incomparable_runs:python_structural",
        "served",
    ),
    "invariant/structural:ci": (
        "verify:accepted:analyzer_invariant:python_structural",
        "served",
    ),
    "invariant/structural:strict": (
        "verify:accepted:analyzer_invariant:python_structural",
        "served",
    ),
    "invariant/structural:relaxed": (
        "verify:accepted:analyzer_invariant:python_structural",
        "served",
    ),
    "queued/queued": ("verify:unverified:intent_not_active:-", "served"),
    "queued/budget:ci": ("budget:-:-:-", "served"),
    "queued/budget:strict": ("budget:-:-:-", "served"),
    "queued/budget:relaxed": ("budget:-:-:-", "served"),
    "profiles/documentation_only:fast": (
        "verify:accepted:-:documentation_only",
        "served",
    ),
    "profiles/documentation_only:after": (
        "verify:accepted:-:documentation_only",
        "served",
    ),
    "profiles/non_python:fast": ("verify:accepted:-:non_python_patch", "served"),
    "profiles/non_python:after": ("verify:accepted:-:non_python_patch", "served"),
    "profiles/governance:fast": (
        "verify:unverified:after_run_required_for_governance:governance_config",
        "served",
    ),
    "profiles/governance:after": ("verify:accepted:-:governance_config", "served"),
    "profiles/python:fast": (
        "verify:unverified:no_after_run:python_structural",
        "served",
    ),
    "profiles/python:after": ("verify:accepted:-:python_structural", "served"),
    "profiles/mixed:fast": (
        "verify:unverified:no_after_run:python_structural",
        "served",
    ),
    "profiles/mixed:after": ("verify:accepted:-:python_structural", "served"),
    "profiles/state_artifact:fast": (
        "verify:violated:state_artifact_mutation:state_artifact_change",
        "served",
    ),
    "profiles/state_artifact:after": (
        "verify:violated:state_artifact_mutation:state_artifact_change",
        "served",
    ),
    "profiles/documentation_only:diff_ref": ("refused:MCPGitDiffError", None),
    "profiles/budget:ci": ("budget:-:-:-", "served"),
    "profiles/budget:strict": ("budget:-:-:-", "served"),
    "profiles/budget:relaxed": ("budget:-:-:-", "served"),
    "expired/structural:ci": ("verify:expired:report_digest_mismatch:-", "served"),
    "expired/structural:strict": ("verify:expired:report_digest_mismatch:-", "served"),
    "expired/structural:relaxed": ("verify:expired:report_digest_mismatch:-", "served"),
    "predates/structural:ci": (
        "verify:unverified:change_predates_declaration:python_structural",
        "served",
    ),
    "predates/structural:strict": (
        "verify:unverified:change_predates_declaration:python_structural",
        "served",
    ),
    "predates/structural:relaxed": (
        "verify:unverified:change_predates_declaration:python_structural",
        "served",
    ),
    "api_lane_off/budget:ci": ("budget:-:-:-", "served"),
    "api_lane_off/budget:strict": ("budget:-:-:-", "served"),
    "api_lane_off/budget:relaxed": ("budget:-:-:-", "served"),
    "api_lane_off/structural:ci": ("verify:accepted:-:python_structural", "served"),
    "api_lane_off/structural:strict": ("verify:accepted:-:python_structural", "served"),
    "api_lane_off/structural:relaxed": (
        "verify:accepted:-:python_structural",
        "served",
    ),
    "truncated_api/budget:ci": ("budget:-:-:-", "served"),
    "truncated_api/budget:strict": ("budget:-:-:-", "divergent"),
    "truncated_api/budget:relaxed": ("budget:-:-:-", "served"),
    "truncated_api/structural:ci": ("verify:accepted:-:python_structural", "served"),
    "truncated_api/structural:strict": (
        "verify:accepted:-:python_structural",
        "divergent",
    ),
    "truncated_api/structural:relaxed": (
        "verify:accepted:-:python_structural",
        "served",
    ),
    "deferred_cycle/structural:ci": ("verify:violated:-:python_structural", "served"),
    "deferred_cycle/structural:strict": (
        "verify:violated:-:python_structural",
        "served",
    ),
    "deferred_cycle/structural:relaxed": (
        "verify:accepted:-:python_structural",
        "served",
    ),
}


@pytest.fixture(scope="module")
def cycles(tmp_path_factory: pytest.TempPathFactory) -> PatchCycles:
    return shared_cycles(tmp_path_factory)


def _word(answer: Mapping[str, object]) -> str:
    if "__refused__" in answer:
        return f"refused:{answer['__refused__']}"
    return (
        f"{answer.get('mode')}:{answer.get('status', '-')}:"
        f"{answer.get('reason') or '-'}:{answer.get('verification_profile', '-')}"
    )


def _wire(answer: Mapping[str, object]) -> str:
    return json.dumps(
        {key: value for key, value in answer.items() if key != "serving"},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _question(key: str) -> tuple[str, str]:
    name, label = key.split("/", 1)
    return name, label


def test_the_battery_asks_every_question_the_table_names(cycles: PatchCycles) -> None:
    asked = {
        f"{name}/{label}" for name in CYCLE_BUILDERS for label in cycles[name].questions
    }
    assert asked == set(EXPECTED)


@pytest.fixture(scope="module")
def memory_answers(cycles: PatchCycles) -> dict[str, dict[str, object]]:
    """Every question answered under the memory switch, once."""
    return {
        key: cycles[_question(key)[0]].ask(_question(key)[1], serve_from="memory")
        for key in EXPECTED
    }


def test_every_question_reaches_exactly_its_recorded_verdict(
    memory_answers: dict[str, dict[str, object]],
) -> None:
    assert {key: _word(answer) for key, answer in memory_answers.items()} == {
        key: word for key, (word, _reason) in EXPECTED.items()
    }


#: What the battery must REACH before anything it compares counts: every
#: verdict, every unverified and violated reason, every verification profile
#: and every contract violation kind (Probe Validity Law).
_REACHED: tuple[tuple[str, str], ...] = (
    *(
        ("status", word)
        for word in (
            "accepted",
            "accepted_with_external_changes",
            "violated",
            "unverified",
            "expired",
        )
    ),
    *(
        ("reason", word)
        for word in (
            "scope_violation",
            "state_artifact_mutation",
            "no_after_run",
            "after_run_not_new",
            "after_run_required_for_governance",
            "incomparable_runs",
            "intent_not_active",
            "no_before_run",
            "report_digest_mismatch",
            "analyzer_invariant",
            "change_predates_declaration",
        )
    ),
    *(
        ("verification_profile", word)
        for word in (
            "python_structural",
            "governance_config",
            "documentation_only",
            "non_python_patch",
            "state_artifact_change",
        )
    ),
    *(
        ("contract_violations", word)
        for word in (
            "scope_violation",
            "structural_regressions",
            "gate_failures",
            "state_artifact_mutation",
        )
    ),
    ("present", "health_regression_advisory"),
    ("present", "external_regressions"),
    ("present", "intent_worsened"),
)


def _reached(answer: Mapping[str, object], field: str, word: str) -> bool:
    if field == "present":
        return bool(answer.get(word))
    value = answer.get(field)
    if isinstance(value, list):
        return word in value
    return value == word


@pytest.mark.parametrize(
    ("field", "word"), _REACHED, ids=[f"{field}={word}" for field, word in _REACHED]
)
def test_the_battery_reaches_every_outcome_before_anything_is_counted(
    memory_answers: dict[str, dict[str, object]], field: str, word: str
) -> None:
    assert any(_reached(answer, field, word) for answer in memory_answers.values())


def test_the_forbidden_path_is_touched_and_violates(
    memory_answers: dict[str, dict[str, object]],
) -> None:
    forbidden = memory_answers["forbidden/structural:ci"]
    scope_check = forbidden["scope_check"]
    assert isinstance(scope_check, dict)
    assert scope_check["forbidden_touched"] == ["pkg/eval_split.py"]
    assert forbidden["status"] == "violated"


@pytest.mark.parametrize("key", list(EXPECTED))
def test_the_store_answers_every_question_as_memory_does(
    cycles: PatchCycles, key: str
) -> None:
    """Per verdict: the store's answer is memory's on the wire -- every
    field, its key order, its JSON type -- and says where it came from."""
    name, label = _question(key)
    cycle = cycles[name]
    memory = cycle.ask(label, serve_from="memory")
    stored = cycle.ask(label, serve_from="run_store")
    assert _wire(stored) == _wire(memory)
    word, reason = EXPECTED[key]
    assert _word(stored) == word
    serving = stored.get("serving")
    if reason is None:
        assert "__refused__" in stored and serving is None
        return
    assert isinstance(serving, dict)
    assert serving["reason"] == reason
    assert serving["source"] == ("run_store" if reason == "served" else "memory")
    runs = serving.get("runs")
    if runs is not None and reason == "served":
        assert runs and all(run["reason"] == "served" for run in runs.values())
    memory_serving = memory.get("serving")
    assert isinstance(memory_serving, dict)
    assert memory_serving["source"] == "memory"
    assert memory_serving["reason"] in {"store_disabled", "not_published"}


def test_the_store_disagreement_on_a_truncated_run_serves_memory_named(
    cycles: PatchCycles,
) -> None:
    """The one natural disagreement of the battery: a truncated run's API
    delta, gated by the strict budget -- memory is served, both runs read,
    the gate fields named."""
    stored = cycles["truncated_api"].ask("structural:strict", serve_from="run_store")
    serving = stored["serving"]
    assert isinstance(serving, dict)
    assert serving["source"] == "memory" and serving["reason"] == "divergent"
    assert serving["detail"] == "diverging: before_gate.reasons, gate_preview.reasons"
    assert {run["reason"] for run in serving["runs"].values()} == {"served"}


@pytest.mark.parametrize("carrier", list(PATCH_ROW_PERTURBATIONS))
def test_each_stored_carrier_moves_its_fields(
    cycles: PatchCycles, carrier: str
) -> None:
    """Per field: replacing the stored rows of one carrier moves exactly
    the fields that carrier holds -- the verdict when it holds one -- the
    answer stays memory's, and the moved fields are named."""
    name, label, perturb, fields = PATCH_ROW_PERTURBATIONS[carrier]
    cycle = cycles[name]
    clean = cycle.ask(label, serve_from="run_store")
    assert clean["serving"]["reason"] == "served"  # type: ignore[index]
    with store_row_replaced(perturb):
        moved = cycle.ask(label, serve_from="run_store")
    serving = moved["serving"]
    assert isinstance(serving, dict)
    assert serving["source"] == "memory" and serving["reason"] == "divergent"
    named = str(serving["detail"]).removeprefix("diverging: ").split(", ")
    assert set(fields) <= set(named), named
    assert _wire(moved) == _wire(clean)


def test_a_store_refusal_of_a_question_memory_answered_is_a_disagreement(
    cycles: PatchCycles,
) -> None:
    name, label, perturb = PATCH_STORE_REFUSAL
    cycle = cycles[name]
    clean = cycle.ask(label, serve_from="run_store")
    with store_row_replaced(perturb):
        refused = cycle.ask(label, serve_from="run_store")
    serving = refused["serving"]
    assert isinstance(serving, dict)
    assert serving["source"] == "memory" and serving["reason"] == "divergent"
    assert str(serving["detail"]).startswith(
        "the store refused: Coverage gating requires a run created with coverage_xml"
    )
    assert _wire(refused) == _wire(clean)


def test_the_switch_unset_reads_no_store_and_says_so(cycles: PatchCycles) -> None:
    cycle = cycles["improved"]
    for label in ("budget:ci", "structural:ci"):
        unset = cycle.ask(label, serve_from=None)
        named = cycle.ask(label, serve_from="memory")
        assert unset == named
        serving = unset["serving"]
        assert isinstance(serving, dict)
        assert serving["source"] == "memory"
        assert serving["reason"] == "store_disabled"
        assert "CODECLONE_SERVE_FROM=memory" in str(serving["detail"])


def test_the_budget_block_is_the_run_summary_shape_and_a_verify_names_its_runs(
    cycles: PatchCycles,
) -> None:
    cycle = cycles["improved"]
    assert cycle.after is not None
    budget = cycle.ask("budget:ci", serve_from="run_store")["serving"]
    before_link = cycle.before.execution.run_snapshot_link
    after_link = cycle.after.execution.run_snapshot_link
    assert before_link is not None and after_link is not None
    assert budget == {
        "source": "run_store",
        "reason": "served",
        "store_run_id": before_link.store_run_id,
    }
    verify = cycle.ask("structural:ci", serve_from="run_store")["serving"]
    assert verify == {
        "source": "run_store",
        "reason": "served",
        "runs": {
            "before": {
                "source": "run_store",
                "reason": "served",
                "store_run_id": before_link.store_run_id,
            },
            "after": {
                "source": "run_store",
                "reason": "served",
                "store_run_id": after_link.store_run_id,
            },
        },
    }
    fast = cycle.ask("documentation_only", serve_from="run_store")["serving"]
    assert isinstance(fast, dict)
    assert set(fast["runs"]) == {"before"}
    none = cycle.ask("no_runs_at_all", serve_from="run_store")["serving"]
    assert none == {
        "source": "memory",
        "reason": "not_published",
        "detail": "no_run_read",
        "runs": {},
    }


def test_a_rollout_without_a_store_answers_memory_typed(cycles: PatchCycles) -> None:
    """The store file gone: the before-run is answered from memory with the
    door's reason, the verdict unchanged."""
    cycle = cycles["improved"]
    memory = cycle.ask("structural:ci", serve_from="memory")
    with serving_environment(
        cycle.store_path.with_name("absent.sqlite3"), serve_from="run_store"
    ):
        answer = cycle.service.check_patch_contract(**cycle.questions["structural:ci"])
    assert _wire(answer) == _wire(memory)
    serving = answer["serving"]
    assert isinstance(serving, dict)
    assert serving["source"] == "memory"
    assert serving["reason"] == "store_absent"
    assert str(serving["detail"]).startswith("before: ")


def test_the_workflow_embeds_the_answer_without_serving(cycles: PatchCycles) -> None:
    """``finish_controlled_change`` runs the same served verification and
    embeds it as it always did: no ``serving`` inside."""
    cycle = cycles["improved"]
    with serving_environment(cycle.store_path, serve_from="run_store"):
        verify = cycle.service._patch_contract_verify(
            before_run_id=None,
            after_run_id=cycle.after.run_id if cycle.after else None,
            intent_id=cycle.intent_id,
            strictness="ci",
            diff_ref=None,
            changed_files=["pkg/eval_graded.py"],
        )
        budget = cycle.service._patch_contract_budget(
            run_id=cycle.before.run_id, intent_id=cycle.intent_id, strictness="ci"
        )
    assert "serving" not in verify and "serving" not in budget
    asked = cycle.ask("structural:ci", serve_from="run_store")
    assert _wire(verify) == _wire(asked)


@pytest.mark.parametrize("label", ["structural:ci", "budget:ci", "documentation_only"])
def test_the_audit_events_are_written_once_and_ride_a_served_answer(
    cycles: PatchCycles, monkeypatch: pytest.MonkeyPatch, label: str
) -> None:
    """The verifier runs twice and writes its events once: the store's run
    is a shadow.  The audit sequence the written event got is an emission
    fact, carried into the store's answer as the memory answer has it."""
    cycle = cycles["improved"]
    writer = RecordingAuditWriter()
    monkeypatch.setattr(cycle.service, "_audit_writer_override", writer)
    memory = cycle.ask(label, serve_from="memory")
    written_by_memory = len(writer.events)
    stored = cycle.ask(label, serve_from="run_store")
    assert written_by_memory == 1
    assert len(writer.events) == 2
    assert stored["serving"]["reason"] == "served"  # type: ignore[index]
    if label == "structural:ci":
        assert memory["_audit_sequence"] == 1
        assert stored["_audit_sequence"] == 2
    else:
        assert "_audit_sequence" not in memory and "_audit_sequence" not in stored
    assert _wire({**stored, "_audit_sequence": 0}) == _wire(
        {**memory, "_audit_sequence": 0}
    )


def test_an_evicted_before_run_stays_refused_with_the_store_on(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Today's contract, held through this wave: a before-run evicted from
    memory is ``no_before_run`` even though the store still holds it -- the
    store is read only for runs the session holds (eviction recovery is a
    later wave).  The positive control: before the eviction the same
    question is served from the store.  The intent is cleared first: an
    intent pins its before-run, which is never evicted while it holds."""
    cycles = PatchCycles(tmp_path_factory.mktemp("evicted").resolve())
    cycle = cycles["improved"]
    served = cycle.ask("no_intent:ci", serve_from="run_store")
    assert served["serving"]["reason"] == "served"  # type: ignore[index]
    assert served["status"] == "accepted"
    service = cycle.service
    assert isinstance(service, CodeCloneMCPService)
    cleared = service.manage_change_intent(action="clear", intent_id=cycle.intent_id)
    assert cleared["cleared"] == 1, cleared
    for index in range(5):
        cycle.root.joinpath("pkg", f"evict_filler_{index}.py").write_text(
            f"def filler_{index}() -> int:\n    return {index}\n", "utf-8"
        )
        cycles.reanalyze(cycle)
    held = {record.run_id for record in service._runs.records()}
    assert cycle.before.run_id not in held
    link = cycle.before.execution.run_snapshot_link
    assert link is not None and link.store_run_id
    with serving_environment(cycle.store_path, serve_from="run_store"):
        evicted = service.check_patch_contract(**cycle.questions["no_intent:ci"])
    assert evicted["status"] == "unverified"
    assert evicted["reason"] == "no_before_run"
    assert evicted["serving"] == {
        "source": "memory",
        "reason": "not_published",
        "detail": "no_run_read",
        "runs": {},
    }


# -- the store view reads every fact from the store ---------------------------
#
# One case per carrier branch of ``StorePatchRun``: the stored facts of one run
# are altered to values no record holds, and the store view must answer the
# altered value while the record's view answers its own.  A branch that read
# the record would answer the record's value here, and only here is that
# visible on a population where the two always agree.

_SENTINEL_ITEM = ("pkg/sentinel.py", "pkg.sentinel:sentinel")


def _altered_items(served: object) -> dict[str, dict[tuple[str, str], int]]:
    return {
        family: {**items, _SENTINEL_ITEM: 900 + index}
        for index, (family, items) in enumerate(
            sorted(served.metric_items.items())  # type: ignore[attr-defined]
        )
    }


def _first_group(findings: Mapping[str, tuple[Mapping[str, object], ...]]) -> str:
    return next(family for family in sorted(findings) if findings[family])


def _altered_findings(
    served: object, edit: Callable[[Mapping[str, object]], Mapping[str, object]]
) -> dict[str, tuple[Mapping[str, object], ...]]:
    findings = served.findings  # type: ignore[attr-defined]
    family = _first_group(findings)
    first, *rest = findings[family]
    return {**findings, family: (edit(first), *rest)}


_FACTS: dict[str, Callable[[StorePatchRun, RecordPatchRun], tuple[object, object]]] = {
    "health": lambda store, memory: (store.health(), memory.health()),
    "current_state.health_score": lambda store, memory: (
        store.current_state()["health_score"],
        memory.current_state()["health_score"],
    ),
    "current_state.complexity_max": lambda store, memory: (
        store.current_state()["complexity_max"],
        memory.current_state()["complexity_max"],
    ),
    "current_state.coupling_max": lambda store, memory: (
        store.current_state()["coupling_max"],
        memory.current_state()["coupling_max"],
    ),
    "current_state.cohesion_max": lambda store, memory: (
        store.current_state()["cohesion_max"],
        memory.current_state()["cohesion_max"],
    ),
    "current_state.dependency_cycles": lambda store, memory: (
        store.current_state()["dependency_cycles"],
        memory.current_state()["dependency_cycles"],
    ),
    "current_state.clone_groups": lambda store, memory: (
        store.current_state()["clone_groups"],
        memory.current_state()["clone_groups"],
    ),
    "current_state.dead_code_high_confidence": lambda store, memory: (
        store.current_state()["dead_code_high_confidence"],
        memory.current_state()["dead_code_high_confidence"],
    ),
    "metric_item_index": lambda store, memory: (
        store.metric_item_index("coupling"),
        memory.metric_item_index("coupling"),
    ),
    "baseline_status": lambda store, memory: (
        store.baseline_status(),
        memory.baseline_status(),
    ),
    "comparison_index": lambda store, memory: (
        sorted(store.comparison_index("all")),
        sorted(memory.comparison_index("all")),
    ),
    "comparison_card": lambda store, memory: (
        [
            store.comparison_card(f)
            for _i, f in sorted(store.comparison_index("all").items())
        ],
        [
            memory.comparison_card(f)
            for _i, f in sorted(memory.comparison_index("all").items())
        ],
    ),
    "finding_path_index": lambda store, memory: (
        store.finding_path_index(),
        memory.finding_path_index(),
    ),
    "gate": lambda store, memory: (
        store.gate(MCPGateRequest(fail_on_new=True, fail_health=200)).reasons,
        memory.gate(MCPGateRequest(fail_on_new=True, fail_health=200)).reasons,
    ),
}


def _altered(served: object) -> object:
    """Every stored fact of one run moved to a value no record holds."""
    gate_state = served.gate_state  # type: ignore[attr-defined]
    return dataclasses.replace(
        served,  # type: ignore[type-var]
        health_score=-7,
        metric_items=_altered_items(served),
        dependency_cycles=-11,
        clone_groups=-12,
        dead_code_high_confidence=-13,
        baseline_status="sentinel",
        findings=_altered_findings(
            served,
            lambda group: {
                **group,
                "id": "clone:function:sentinel|0-19",
                "severity": "sentinel",
                "items": [{"relative_path": "pkg/sentinel.py"}],
            },
        ),
        gate_state=dataclasses.replace(
            gate_state, clone_new_count=0, health_score=gate_state.health_score + 50
        ),
    )


@pytest.mark.parametrize("fact", list(_FACTS))
def test_the_store_view_reads_each_fact_from_the_store(
    cycles: PatchCycles, fact: str
) -> None:
    cycle = cycles["improved"]
    session = cast("PatchSession", cycle.service)
    served = stored_patch_run(cycle.store_path, cycle.before)
    memory = RecordPatchRun(session, cycle.before)
    honest_store, honest_memory = _FACTS[fact](
        StorePatchRun(session, cycle.before, served), memory
    )
    assert honest_store == honest_memory
    moved, memory_value = _FACTS[fact](
        StorePatchRun(session, cycle.before, _altered(served)),  # type: ignore[arg-type]
        memory,
    )
    assert moved != memory_value, fact
    assert memory_value == honest_memory


def test_the_store_view_refuses_a_coverage_gate_its_run_cannot_answer(
    cycles: PatchCycles,
) -> None:
    """The coverage refusal is the STORED join's: the record joined a
    report, the stored run (altered) states none."""
    cycle = cycles["profiles"]
    session = cast("PatchSession", cycle.service)
    served = stored_patch_run(cycle.store_path, cycle.before)
    request = MCPGateRequest(fail_on_untested_hotspots=True)
    RecordPatchRun(session, cycle.before).gate(request)
    StorePatchRun(session, cycle.before, served).gate(request)
    without = dataclasses.replace(served, coverage_join_status=None)
    with pytest.raises(MCPServiceContractError, match="created with coverage_xml"):
        StorePatchRun(session, cycle.before, without).gate(request)
    invalid = dataclasses.replace(
        served, coverage_join_status="invalid", coverage_invalid_reason="sentinel"
    )
    with pytest.raises(MCPServiceContractError, match="Reason: sentinel"):
        StorePatchRun(session, cycle.before, invalid).gate(request)


def test_the_store_view_shortens_ids_over_the_stored_universe(
    cycles: PatchCycles,
) -> None:
    """A card's short id is drawn from the STORED finding universe: a stored
    group the record never held gets its short form, not its canonical id
    (the record's id map has no entry for it)."""
    cycle = cycles["improved"]
    session = cast("PatchSession", cycle.service)
    served = stored_patch_run(cycle.store_path, cycle.before)
    store = StorePatchRun(session, cycle.before, _altered(served))  # type: ignore[arg-type]
    index = store.comparison_index("all")
    sentinel = index["clone:function:sentinel|0-19"]
    card = store.comparison_card(sentinel)
    assert card["id"] != "clone:function:sentinel|0-19"
    assert str(card["id"]).endswith("|0-19")
    assert card["severity"] == "sentinel"


#: The regressions each structural question names, by finding kind: every
#: family the verifier compares is reached -- a clone group, a complexity
#: hotspot, a cycle of deferred imports -- so a comparison that left a family
#: out would leave its question without the regression.
_REGRESSION_KINDS: dict[str, list[str]] = {
    "gate_caused/structural:ci": ["function_clone"],
    "harder_only/structural:ci": ["function_hotspot"],
    "deferred_cycle/structural:ci": ["deferred_cycle"],
}


@pytest.mark.parametrize("key", list(_REGRESSION_KINDS))
def test_the_verifier_compares_every_finding_family(
    memory_answers: dict[str, dict[str, object]], key: str
) -> None:
    delta = memory_answers[key]["structural_delta"]
    assert isinstance(delta, dict)
    kinds = [str(card["kind"]) for card in delta["regressions"]]
    assert kinds == _REGRESSION_KINDS[key]
