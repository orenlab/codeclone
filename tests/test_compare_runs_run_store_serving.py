# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``compare_runs`` and the review receipt's pair comparison, served from
the run store (consumer migration C3).

The comparison of two runs is the one owner ``compare_runs_on_facts``; it is
computed over the records' facts and, behind ``CODECLONE_SERVE_FROM``, over
the two runs' stored facts through the patch-run door -- the carrier the
patch verification already compares stored runs with.  The store's answer is
served only when it is the memory's byte for byte, and the answer says where
it came from under ``serving`` (the verification's shape: the outcome and
each run's).  The records still name the runs and decide their
comparability; every finding, card and health the comparison states is the
stored one.

Pinned on the pair population of ``tests/_compare_runs_serving.py`` (50
pairs, four focuses, every position of the switch), per field of the answer
(census-3 rows C3.01-C3.10), and per carrier branch: the tool's edge and the
receipt's, each read where it decides.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

import codeclone.surfaces.mcp._session_state_mixin as state_mixin_mod
from codeclone.api.run_store_serving import ServedPatchRun
from codeclone.surfaces.mcp import _session_helpers as _helpers
from codeclone.surfaces.mcp._run_store_serving import served_patch_contract
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest, MCPRunRecord
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.utils.coerce import as_mapping, as_sequence
from tests._compare_runs_serving import COMPARE_FOCUSES, ComparePair, shared_pairs
from tests._run_store_paths import run_store_service_path
from tests._run_summary_serving import (
    _bumped,
    _edited,
    serving_environment,
    store_row_replaced,
)
from tests.test_change_control_run_store_serving import _tree

_GENERATION_1 = Path(__file__).parent / "fixtures" / "run_store_generation_1"


def _wire(answer: Mapping[str, object]) -> str:
    return json.dumps(
        {key: value for key, value in answer.items() if key != "serving"},
        ensure_ascii=False,
        separators=(",", ":"),
    )


@pytest.fixture(scope="module")
def pairs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, ComparePair]:
    return shared_pairs(tmp_path_factory)


@pytest.fixture(scope="module")
def answers(
    pairs: dict[str, ComparePair],
) -> dict[tuple[str, str], tuple[dict[str, object], dict[str, object]]]:
    """Every question twice: (memory switch, run-store switch)."""
    return {
        (name, focus): (
            pair.ask(focus, serve_from="memory"),
            pair.ask(focus, serve_from="run_store"),
        )
        for name, pair in pairs.items()
        for focus in COMPARE_FOCUSES
    }


def _served_block(pair: ComparePair) -> dict[str, object]:
    """The block a served comparison of the pair carries: each run as the
    tool resolves its id (two executions of one content-addressed run id
    resolve to the latest, as the ``invariant`` cycle's do)."""
    links = [
        _helpers._resolve_run_for_optional_root(
            pair.service._runs, record.run_id, pair.root
        ).execution.run_snapshot_link
        for record in (pair.before, pair.after)
    ]
    assert all(link is not None for link in links)
    before, after = (
        {"source": "run_store", "reason": "served", "store_run_id": link.store_run_id}
        for link in links
        if link is not None
    )
    return {
        "source": "run_store",
        "reason": "served",
        "runs": {"before": before, "after": after},
    }


def test_the_population_distinguishes_every_verdict_and_reason(
    answers: dict[tuple[str, str], tuple[dict[str, object], dict[str, object]]],
) -> None:
    """The accounting first: 50 pairs, 200 questions, and the answers reach
    every verdict, every reason and both sides of every nullable field --
    a pin over a population that cannot tell them apart would prove
    nothing."""
    assert len({name for name, _focus in answers}) == 50
    assert len(answers) == 200
    memory = [first for first, _stored in answers.values()]
    assert {str(answer["verdict"]) for answer in memory} == {
        "stable",
        "regressed",
        "improved",
        "mixed",
        "incomparable",
    }
    assert {str(answer.get("reason")) for answer in memory} == {
        "None",
        "different_root",
        "different_analysis_settings",
        "focus_not_analyzed",
    }
    assert {answer["health_delta"] is None for answer in memory} == {True, False}
    assert {answer["unchanged"] is None for answer in memory} == {True, False}
    assert any(as_sequence(answer["regressions"]) for answer in memory)
    assert any(as_sequence(answer["improvements"]) for answer in memory)
    healths = {as_mapping(answer["before"])["health"] for answer in memory}
    assert None in healths and len(healths) >= 3


@pytest.mark.parametrize("focus", COMPARE_FOCUSES)
def test_every_pair_is_served_from_the_store_as_memory_answers_it(
    pairs: dict[str, ComparePair],
    answers: dict[tuple[str, str], tuple[dict[str, object], dict[str, object]]],
    focus: str,
) -> None:
    """On every pair: the store's comparison is served, byte for byte the
    memory's, and the block names both runs; the memory switch reads no
    store and says so."""
    for name, pair in pairs.items():
        memory, stored = answers[(name, focus)]
        assert stored["serving"] == _served_block(pair), name
        assert _wire(stored) == _wire(memory), name
        serving = as_mapping(memory["serving"])
        assert (serving["source"], serving["reason"]) == ("memory", "store_disabled")
        assert list(stored)[-1] == "serving"


#: Each field of the answer (census-3 rows), read off one answer.
_FIELDS: dict[str, Callable[[Mapping[str, object]], object]] = {
    "C3.01 before.run_id / after.run_id": lambda answer: (
        as_mapping(answer["before"])["run_id"],
        as_mapping(answer["after"])["run_id"],
    ),
    "C3.02 before.health / after.health": lambda answer: (
        as_mapping(answer["before"])["health"],
        as_mapping(answer["after"])["health"],
    ),
    "C3.03 comparable": lambda answer: answer["comparable"],
    "C3.04 reason": lambda answer: answer.get("reason"),
    "C3.05 health_delta": lambda answer: answer["health_delta"],
    "C3.06 verdict": lambda answer: answer["verdict"],
    "C3.07 regressions[] / improvements[]": lambda answer: (
        [as_mapping(card)["id"] for card in as_sequence(answer["regressions"])],
        [as_mapping(card)["id"] for card in as_sequence(answer["improvements"])],
    ),
    "C3.08 unchanged": lambda answer: answer["unchanged"],
    "C3.09 summary": lambda answer: answer["summary"],
    "C3.10 cards": lambda answer: (answer["regressions"], answer["improvements"]),
}


@pytest.mark.parametrize("field", list(_FIELDS))
def test_each_field_is_the_memory_bytes_on_every_question(
    answers: dict[tuple[str, str], tuple[dict[str, object], dict[str, object]]],
    field: str,
) -> None:
    """Per field: the served value is the memory's on all 200 questions, and
    the population moves it off one value."""
    read = _FIELDS[field]
    values = set()
    for key, (memory, stored) in answers.items():
        assert json.dumps(read(stored)) == json.dumps(read(memory)), (field, key)
        values.add(json.dumps(read(memory)))
    assert len(values) >= 2, field


def _first_model_only(
    perturb: Callable[[dict[str, list[object]]], None],
) -> Callable[[dict[str, list[object]]], None]:
    """The perturbation on the first model the store assembles -- the
    before-run's, the door reading the two runs in that order -- and on no
    other: one row of ONE of the two runs replaced."""
    seen: list[bool] = []

    def once(collected: dict[str, list[object]]) -> None:
        if not seen:
            seen.append(True)
            perturb(collected)

    return once


def test_a_replaced_row_of_one_run_moves_the_stores_verdict_and_memory_answers(
    pairs: dict[str, ComparePair],
) -> None:
    """The before-run's stored health bumped by one: the store's comparison
    of a stable pair now states a delta and a regression, so it disagrees,
    memory is served, and the moved fields -- the verdict among them -- are
    named.  A comparison that read its runs anywhere but the store would
    stay ``served`` here."""
    pair = pairs["improved.forward"]
    clean = pair.ask("all", serve_from="run_store")
    assert clean["verdict"] == "stable" and clean["health_delta"] == 0
    with store_row_replaced(
        _first_model_only(_edited("health_result", _bumped("score")))
    ):
        moved = pair.ask("all", serve_from="run_store")
    serving = as_mapping(moved["serving"])
    assert (serving["source"], serving["reason"]) == ("memory", "divergent")
    named = str(serving["detail"]).removeprefix("diverging: ").split(", ")
    assert {"before.health", "health_delta", "verdict", "summary"} <= set(named)
    assert "after.health" not in named
    assert _wire(moved) == _wire(clean)


def test_the_switch_unset_reads_no_store_and_says_so(
    pairs: dict[str, ComparePair],
) -> None:
    pair = pairs["regressed.forward"]
    unset = pair.ask("all", serve_from=None)
    assert unset == pair.ask("all", serve_from="memory")
    serving = as_mapping(unset["serving"])
    assert (serving["source"], serving["reason"]) == ("memory", "store_disabled")
    assert "CODECLONE_SERVE_FROM=memory" in str(serving["detail"])


def _asked_against(pair: ComparePair, store: Path) -> dict[str, object]:
    with serving_environment(store, serve_from="run_store"):
        return pair.service.compare_runs(
            before_run_id=pair.before.run_id,
            after_run_id=pair.after.run_id,
            root=pair.root,
        )


def test_a_rollout_without_a_store_answers_memory_typed(
    pairs: dict[str, ComparePair], tmp_path: Path
) -> None:
    """The store file gone: memory answers, the first run the door could not
    read named, the comparison unchanged."""
    pair = pairs["regressed.forward"]
    answer = _asked_against(pair, tmp_path / "absent.sqlite3")
    assert _wire(answer) == _wire(pair.ask("all", serve_from="memory"))
    serving = as_mapping(answer["serving"])
    assert (serving["source"], serving["reason"]) == ("memory", "store_absent")
    assert str(serving["detail"]).startswith("before: ")
    assert set(as_mapping(serving["runs"])) == {"before", "after"}


def test_a_store_of_another_generation_answers_memory_typed(
    pairs: dict[str, ComparePair], tmp_path: Path
) -> None:
    """The REAL generation-1 artifact at the store path: refused at open,
    memory answers with the refusal's words."""
    store = tmp_path / "generation-1.sqlite3"
    shutil.copy(_GENERATION_1 / "runs.sqlite3", store)
    pair = pairs["regressed.forward"]
    answer = _asked_against(pair, store)
    assert _wire(answer) == _wire(pair.ask("all", serve_from="memory"))
    serving = as_mapping(answer["serving"])
    assert (serving["source"], serving["reason"]) == (
        "memory",
        "incompatible_generation",
    )
    assert "canonical_model stored '1' declared '3'" in str(serving["detail"])


# -- the receipt's pair comparison: its own carrier branch ----------------------


class _Decisions:
    """Every decision the run comparison's serving edge took, in order: the
    receipt states no ``serving``, so its comparison is read where it is
    decided."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.taken: list[tuple[str, tuple[str, ...]]] = []
        real = served_patch_contract

        def recorded(
            memory: Mapping[str, object],
            runs: Mapping[str, MCPRunRecord],
            store_answer: Callable[[Mapping[str, ServedPatchRun]], dict[str, object]],
        ) -> tuple[dict[str, object], dict[str, object]]:
            answer, serving = real(memory, runs, store_answer)
            self.taken.append((str(serving["reason"]), tuple(sorted(runs))))
            return answer, serving

        monkeypatch.setattr(state_mixin_mod, "served_patch_contract", recorded)


@pytest.fixture(scope="module")
def receipt_change(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[CodeCloneMCPService, Path, str, str]]:
    """One declared change -- analyse, start, edit, analyse -- left open for
    its receipt: (service, store, after-run id, intent id)."""
    base = tmp_path_factory.mktemp("compare_runs_receipt")
    root = _tree(base / "repo")
    # The root's own store: MCP writes a run store only inside the root's
    # ``.codeclone/`` (its write boundary).
    store = run_store_service_path(root)
    service = CodeCloneMCPService(history_limit=4)
    with serving_environment(store, serve_from="memory"):
        service.analyze_repository(MCPAnalysisRequest(root=str(root)))
        started = service.start_controlled_change(
            root=str(root),
            scope={"allowed_files": ["pkg/core.py"]},
            intent="widen core",
        )
        core = root / "pkg" / "core.py"
        core.write_text(
            core.read_text("utf-8")
            + '\n\ndef widened(value: int) -> int:\n    """Widened."""\n'
            "    if value > 3:\n        return value + 1\n    return value - 1\n",
            "utf-8",
        )
        after = service.analyze_repository(MCPAnalysisRequest(root=str(root)))
        # The receipt reads the changed files off the intent's own check.
        service.manage_change_intent(
            action="check",
            intent_id=str(started["intent_id"]),
            changed_files=["pkg/core.py"],
        )
    yield service, store, str(after["run_id"]), str(started["intent_id"])


def _receipt(
    change: tuple[CodeCloneMCPService, Path, str, str], serve_from: str
) -> dict[str, Any]:
    service, store, run_id, intent_id = change
    with serving_environment(store, serve_from=serve_from):
        receipt = service.create_review_receipt(
            run_id=run_id, intent_id=intent_id, format="json"
        )
    return dict(receipt)


def test_the_receipts_pair_comparison_is_served_from_the_store(
    receipt_change: tuple[CodeCloneMCPService, Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The receipt compares its attested before-run with its run through the
    served comparison: one decision, both runs, ``served`` -- and the
    receipt's delta is the one the memory switch gives (the positive
    control on the same path: ``store_disabled``)."""
    decisions = _Decisions(monkeypatch)
    stored = _receipt(receipt_change, "run_store")
    assert decisions.taken == [("served", ("after", "before"))]
    memory = _receipt(receipt_change, "memory")
    assert decisions.taken[1:] == [("store_disabled", ("after", "before"))]
    delta = as_mapping(stored["structural_delta"])
    assert delta["available"] is True
    assert stored["structural_delta"] == memory["structural_delta"]
    assert stored["patch_contract"] == memory["patch_contract"]


def test_the_receipt_reads_its_pair_off_the_store_rows(
    receipt_change: tuple[CodeCloneMCPService, Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One stored row of the before-run replaced: the receipt's comparison
    disagrees with memory, so its decision is ``divergent`` and the receipt
    states the memory's delta."""
    decisions = _Decisions(monkeypatch)
    clean = _receipt(receipt_change, "run_store")
    with store_row_replaced(
        _first_model_only(_edited("health_result", _bumped("score")))
    ):
        moved = _receipt(receipt_change, "run_store")
    assert [reason for reason, _sides in decisions.taken] == ["served", "divergent"]
    assert moved["structural_delta"] == clean["structural_delta"]
