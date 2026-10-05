# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The blast radius's serving edge: the store's answer, or memory and why.

Consumer migration C7.  Every reader of a blast radius -- ``get_blast_radius``,
the declare and start of a controlled change, the implementation context --
goes through ``_served_blast_radius``: the radius is computed from the
record's document, computed again from the facts the store states for the
same execution, and the store's is served only when the two are the same
bytes over the whole result.  Every other outcome is memory with a typed
reason in ``serving`` -- the serving switch on memory, the rollout off, a
publication that failed, a store that is absent or of another generation, a
store that disagrees.  ``get_blast_radius`` states the outcome; the start of
a controlled change does not (its answer and its blast artifact are not this
wave's), and is held to the same bytes under both switches instead.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import codeclone.api.run_store_serving as door_mod
import codeclone.surfaces.mcp._run_store_serving as serving_mod
import codeclone.surfaces.mcp._session_blast_radius_mixin as mixin_mod
from codeclone.api.run_store_serving import (
    ENV_SERVE_FROM,
    MEMORY_BY_DESIGN_REASONS,
    SERVE_FROM_MEMORY,
    SERVE_FROM_RUN_STORE,
    BlastRadiusFacts,
    RunStoreServingOutcome,
)
from codeclone.surfaces.mcp._blast_radius import BlastRadiusResult
from codeclone.surfaces.mcp._run_store_serving import (
    blast_radius_fields,
    served_blast_radius,
)
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests import conftest as corpora
from tests._blast_radius_serving import (
    FANOUT_TREE,
    BlastPopulations,
    BlastRequest,
    blast_answer,
    forget_answers,
    shared_blast_populations,
)
from tests._run_summary_serving import SummaryPopulation, serving_environment

_GENERATION_1 = Path(__file__).parent / "fixtures" / "run_store_generation_1"

#: The fan-out origin every road is asked about: a high radius, a cut
#: review context, every kind of dependent.
_CORE = BlastRequest(("pkg/core.py",), "transitive")


@pytest.fixture(scope="module")
def populations(tmp_path_factory: pytest.TempPathFactory) -> BlastPopulations:
    return shared_blast_populations(tmp_path_factory)


@pytest.fixture
def fanout(populations: BlastPopulations) -> Iterator[SummaryPopulation]:
    population = populations["fanout"]
    forget_answers(population)
    yield population
    forget_answers(population)


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every rollout counter the serving decision records, in order."""
    names: list[str] = []
    monkeypatch.setattr(serving_mod, "record_counter", names.append)
    return names


def _wire(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _without_serving(answer: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in answer.items() if key != "serving"}


def _store_run_id(population: SummaryPopulation) -> str:
    link = population.record.execution.run_snapshot_link
    assert link is not None and link.store_run_id
    return link.store_run_id


def _memory_result(population: SummaryPopulation) -> BlastRadiusResult:
    with serving_environment(population.store_path, serve_from=SERVE_FROM_MEMORY):
        return population.service._blast_radius_result(
            record=population.record, files=_CORE.files, depth="transitive"
        )


def test_a_published_run_is_served_from_the_store_and_says_so(
    fanout: SummaryPopulation, counted: list[str]
) -> None:
    memory = blast_answer(fanout, _CORE, serve_from=SERVE_FROM_MEMORY)
    answer = blast_answer(fanout, _CORE, serve_from=SERVE_FROM_RUN_STORE)
    assert answer["serving"] == {
        "source": "run_store",
        "reason": "served",
        "store_run_id": _store_run_id(fanout),
    }
    assert list(answer)[-1] == "serving"
    assert answer["radius_level"] == "high"
    assert _wire(_without_serving(answer)) == _wire(_without_serving(memory))
    assert counted == ["run_store_serving_memory", "run_store_serving_store_backed"]


def test_the_switch_on_memory_never_reads_the_store(
    fanout: SummaryPopulation,
    counted: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the store was read under the memory switch")

    monkeypatch.setattr(door_mod, "read_served_blast_radius_facts", _refuse)
    for serve_from in (SERVE_FROM_MEMORY, None):
        forget_answers(fanout)
        answer = blast_answer(fanout, _CORE, serve_from=serve_from)
        assert answer["serving"] == {
            "source": "memory",
            "reason": "store_disabled",
            "store_run_id": _store_run_id(fanout),
            "detail": f"{ENV_SERVE_FROM}=memory",
        }
    assert "store_disabled" in MEMORY_BY_DESIGN_REASONS
    assert counted == ["run_store_serving_memory"] * 2


def test_a_rollout_that_names_no_store_answers_memory_by_design(
    fanout: SummaryPopulation,
    counted: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODECLONE_RUN_STORE_ENABLED", raising=False)
    monkeypatch.setenv(ENV_SERVE_FROM, SERVE_FROM_RUN_STORE)
    answer = fanout.service.get_blast_radius(
        files=list(_CORE.files), root=str(fanout.root), depth=_CORE.depth
    )
    assert answer["serving"] == {
        "source": "memory",
        "reason": "store_disabled",
        "store_run_id": _store_run_id(fanout),
    }
    assert counted == ["run_store_serving_memory"]


def _serve_with_link(
    population: SummaryPopulation,
    store_path: Path,
    edit: Callable[[Any], Any],
    counted: list[str],
    compute: Callable[[BlastRadiusFacts], BlastRadiusResult] | None = None,
) -> tuple[BlastRadiusResult, RunStoreServingOutcome]:
    """The edge on the record with its link edited; the counters start
    after the memory radius is computed."""
    record = population.record
    execution = replace(
        record.execution,
        run_snapshot_link=edit(record.execution.run_snapshot_link),
    )
    memory = _memory_result(population)
    counted.clear()

    def _never(_facts: BlastRadiusFacts) -> BlastRadiusResult:
        raise AssertionError("no store facts were expected on this road")

    with serving_environment(store_path, serve_from=SERVE_FROM_RUN_STORE):
        return served_blast_radius(
            replace(record, execution=execution), memory, compute or _never
        )


def _failed(link: Any) -> Any:
    return replace(
        link,
        state="unpublished",
        outcome="failed",
        store_run_id="",
        report_run_identity="f" * 64,
        failure="OSError",
    )


def test_a_failed_publication_is_a_typed_fallback(
    fanout: SummaryPopulation, counted: list[str]
) -> None:
    result, outcome = _serve_with_link(fanout, fanout.store_path, _failed, counted)
    assert (outcome.source, outcome.reason) == ("memory", "run_not_published")
    assert "ffffffffffff" in outcome.detail
    assert outcome.reason not in MEMORY_BY_DESIGN_REASONS
    assert result == _memory_result(fanout)
    assert counted == ["run_store_serving_fallback"]


def test_an_unpublished_execution_is_memory_by_design(
    fanout: SummaryPopulation, counted: list[str]
) -> None:
    result, outcome = _serve_with_link(
        fanout, fanout.store_path, lambda _link: None, counted
    )
    assert outcome.as_payload() == {"source": "memory", "reason": "not_published"}
    assert result == _memory_result(fanout)
    assert counted == ["run_store_serving_memory"]


def test_a_store_of_another_generation_is_refused_typed(
    fanout: SummaryPopulation, counted: list[str], tmp_path: Path
) -> None:
    provenance = json.loads((_GENERATION_1 / "provenance.json").read_text("utf-8"))
    store = tmp_path / "generation-1.sqlite3"
    shutil.copy(_GENERATION_1 / "runs.sqlite3", store)
    result, outcome = _serve_with_link(
        fanout,
        store,
        lambda link: replace(link, store_run_id=str(provenance["run_id"])),
        counted,
    )
    assert (outcome.source, outcome.reason) == ("memory", "incompatible_generation")
    assert "canonical_model stored '1' declared '3'" in outcome.detail
    assert result == _memory_result(fanout)
    assert counted == ["run_store_serving_fallback"]


def test_an_absent_store_is_a_fallback_and_is_never_created(
    fanout: SummaryPopulation, counted: list[str], tmp_path: Path
) -> None:
    absent = tmp_path / "nowhere" / "runs.sqlite3"
    result, outcome = _serve_with_link(fanout, absent, lambda link: link, counted)
    assert (outcome.source, outcome.reason) == ("memory", "store_absent")
    assert not absent.parent.exists()
    assert result == _memory_result(fanout)
    assert counted == ["run_store_serving_fallback"]


@pytest.fixture
def one_edge_fewer(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The door's reader, answering every fact as stored but one import edge
    into ``pkg.core`` fewer."""
    original = vars(door_mod)["read_served_blast_radius_facts"]

    def _read(store: object, run_id: str) -> BlastRadiusFacts:
        facts: BlastRadiusFacts = original(store, run_id)
        dropped = next(edge for edge in facts.dependency_edges if edge[1] == "pkg.core")
        return replace(
            facts,
            dependency_edges=tuple(
                edge for edge in facts.dependency_edges if edge != dropped
            ),
        )

    monkeypatch.setattr(door_mod, "read_served_blast_radius_facts", _read)
    yield


@pytest.mark.usefixtures("one_edge_fewer")
def test_a_disagreeing_store_is_answered_from_memory_and_named(
    fanout: SummaryPopulation, counted: list[str]
) -> None:
    """The store never wins an argument with the producer's own answer."""
    memory = blast_answer(fanout, _CORE, serve_from=SERVE_FROM_MEMORY)
    counted.clear()
    answer = blast_answer(fanout, _CORE, serve_from=SERVE_FROM_RUN_STORE)
    assert answer["serving"] == {
        "source": "memory",
        "reason": "divergent",
        "store_run_id": _store_run_id(fanout),
        "detail": "diverging: direct_dependents, review_context",
    }
    assert _wire(_without_serving(answer)) == _wire(_without_serving(memory))
    assert counted == ["run_store_serving_divergent"]


def test_list_order_is_part_of_the_agreement(
    fanout: SummaryPopulation, counted: list[str]
) -> None:
    """A store result holding the same entries in another order is not the
    memory's answer: the comparison is on the wire, order included."""
    memory = _memory_result(fanout)
    assert len(memory.direct_dependents) > 1

    def _reordered(_facts: BlastRadiusFacts) -> BlastRadiusResult:
        return replace(memory, direct_dependents=memory.direct_dependents[::-1])

    result, outcome = _serve_with_link(
        fanout, fanout.store_path, lambda link: link, counted, _reordered
    )
    assert (outcome.source, outcome.reason) == ("memory", "divergent")
    assert outcome.detail == "diverging: direct_dependents"
    assert result is memory
    assert counted == ["run_store_serving_divergent"]


def test_the_agreement_covers_the_uncut_context(
    fanout: SummaryPopulation, counted: list[str]
) -> None:
    """An entry past the answer's shown twenty still has to agree: the
    comparison is over the whole result, not over the answer it is cut to."""
    memory = _memory_result(fanout)
    assert len(memory.review_context) > 20
    last = dict(memory.review_context[-1])
    changed = (*memory.review_context[:-1], {**last, "reason": "another reason"})

    result, outcome = _serve_with_link(
        fanout,
        fanout.store_path,
        lambda link: link,
        counted,
        lambda _facts: replace(memory, review_context=changed),
    )
    assert (outcome.source, outcome.reason) == ("memory", "divergent")
    assert outcome.detail == "diverging: review_context"
    assert result is memory


def test_every_result_field_is_compared(fanout: SummaryPopulation) -> None:
    """The agreement's field set is the result's, in the answer's order."""
    assert tuple(blast_radius_fields(_memory_result(fanout))) == tuple(
        BlastRadiusResult.__dataclass_fields__
    )


def test_get_blast_radius_answers_what_the_edge_decides(
    fanout: SummaryPopulation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reverse pin at the call site: the tool's values are the edge's
    result, not a second computation beside it."""
    sentinel = replace(_memory_result(fanout), radius_level="sentinel")
    forget_answers(fanout)
    outcome = RunStoreServingOutcome(source="memory", reason="not_published")
    monkeypatch.setattr(
        mixin_mod,
        "served_blast_radius",
        lambda _record, _memory, _compute: (sentinel, outcome),
    )
    answer = blast_answer(fanout, _CORE, serve_from=SERVE_FROM_RUN_STORE)
    assert answer["radius_level"] == "sentinel"
    assert answer["serving"] == {"source": "memory", "reason": "not_published"}


def test_the_switch_is_part_of_the_cached_question(fanout: SummaryPopulation) -> None:
    """A cached answer never names a switch the caller has since turned."""
    first = blast_answer(fanout, _CORE, serve_from=SERVE_FROM_MEMORY)
    second = blast_answer(fanout, _CORE, serve_from=SERVE_FROM_RUN_STORE)
    third = blast_answer(fanout, _CORE, serve_from=SERVE_FROM_MEMORY)
    assert as_reason(first) == as_reason(third) == "store_disabled"
    assert as_reason(second) == "served"
    assert len(fanout.service._blast_radius_cache) == 2


def as_reason(answer: dict[str, object]) -> object:
    serving = answer["serving"]
    assert isinstance(serving, dict)
    return serving["reason"]


def test_start_reads_the_same_blast_radius_under_both_switches(
    tmp_path: Path, counted: list[str]
) -> None:
    """The start of a controlled change computes its radius through the
    edge (``auto`` escalates this high radius to a transitive summary): its
    answer gains no ``serving``, and its blast payload -- the immutable blast
    artifact's identity included -- is the same bytes whichever source
    served the radius."""
    root = tmp_path / "fanout"
    root.mkdir()
    corpora.materialize_projection_corpus(root)
    corpora._write_tree(root, FANOUT_TREE)
    store_path = tmp_path / "fanout.sqlite3"
    service = CodeCloneMCPService(history_limit=4)
    with serving_environment(store_path, serve_from=None):
        service.analyze_repository(MCPAnalysisRequest(root=str(root)))
    started: dict[str, dict[str, object]] = {}
    counters: dict[str, set[str]] = {}
    for serve_from in (SERVE_FROM_MEMORY, SERVE_FROM_RUN_STORE):
        counted.clear()
        with serving_environment(store_path, serve_from=serve_from):
            answer = service.start_controlled_change(
                root=str(root),
                scope={"allowed_files": ["pkg/core.py"]},
                intent="widen core",
                blast_radius_depth="auto",
                blast_radius_detail="full",
            )
            service.manage_change_intent(
                action="clear", intent_id=str(answer["intent_id"])
            )
        assert answer["edit_allowed"] is True
        assert "serving" not in answer
        started[serve_from] = dict(answer["blast_radius"])  # type: ignore[call-overload]
        counters[serve_from] = set(counted)
    assert counters == {
        SERVE_FROM_MEMORY: {"run_store_serving_memory"},
        SERVE_FROM_RUN_STORE: {"run_store_serving_store_backed"},
    }
    memory, stored = started[SERVE_FROM_MEMORY], started[SERVE_FROM_RUN_STORE]
    assert "serving" not in stored
    assert "transitive_summary" in stored
    assert _wire(stored) == _wire(memory)


def test_the_document_road_never_reads_the_store(
    fanout: SummaryPopulation,
    counted: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The implementation context's radius stays off the store whatever the
    switch says, takes no serving decision, and is the served radius's
    bytes."""

    def _refuse(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the document road read the store")

    served = _memory_result(fanout)
    counted.clear()
    monkeypatch.setattr(door_mod, "read_served_blast_radius_facts", _refuse)
    with serving_environment(fanout.store_path, serve_from=SERVE_FROM_RUN_STORE):
        document = fanout.service._document_blast_radius(
            record=fanout.record, files=_CORE.files, depth="transitive"
        )
    assert counted == []
    assert blast_radius_fields(document) == blast_radius_fields(served)
