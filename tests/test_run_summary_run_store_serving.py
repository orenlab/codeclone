# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The run summary's serving edge: the store's answer, or memory and why.

Consumer migration C1.  ``get_run_summary`` builds its answer through
``_run_store_serving.served_run_summary``: the store's blocks are placed into
the answer the surface built from the record, and that answer is served only
when it is the memory's byte for byte; every other outcome is memory with a
typed reason in ``serving`` -- nothing published, the rollout off, the
serving switch on memory, a store that is absent or of another generation, a
publication that failed, a store that disagrees.  The pins here hold each of
those roads on a live MCP execution with its own store (the populations of
``tests/_run_summary_serving.py``); the per-field equivalence over the whole
population is pinned beside them.
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
import codeclone.surfaces.mcp._session_state_mixin as state_mixin_mod
from codeclone.api.run_store_serving import (
    ENV_SERVE_FROM,
    MEMORY_BY_DESIGN_REASONS,
    SERVE_FROM_DEFAULT,
    SERVE_FROM_MEMORY,
    SERVE_FROM_RUN_STORE,
    RunStoreServingOutcome,
    serving_source,
)
from codeclone.surfaces.mcp._run_store_serving import (
    served_run_summary,
    summary_divergence,
)
from tests._run_summary_serving import (
    SummaryPopulation,
    SummaryPopulations,
    serving_environment,
    shared_populations,
)

_GENERATION_1 = Path(__file__).parent / "fixtures" / "run_store_generation_1"


@pytest.fixture(scope="module")
def populations(tmp_path_factory: pytest.TempPathFactory) -> SummaryPopulations:
    return shared_populations(tmp_path_factory)


@pytest.fixture
def trusted(populations: SummaryPopulations) -> SummaryPopulation:
    """A published run with a trusted baseline: every block populated."""
    return populations["trusted"]


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


def test_a_published_run_is_served_from_the_store_and_says_so(
    trusted: SummaryPopulation, counted: list[str]
) -> None:
    """The store's answer is the memory's answer byte for byte, and the
    ``serving`` block -- the one key this wave adds -- names the store run."""
    answer = trusted.answer(serve_from=SERVE_FROM_RUN_STORE)
    assert answer["serving"] == {
        "source": "run_store",
        "reason": "served",
        "store_run_id": _store_run_id(trusted),
    }
    assert list(answer)[-1] == "serving"
    assert _wire(_without_serving(answer)) == _wire(trusted.memory_answer())
    assert counted == ["run_store_serving_store_backed"]


def test_the_switch_on_memory_never_reads_the_store(
    trusted: SummaryPopulation,
    counted: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the store was read under the memory switch")

    monkeypatch.setattr(door_mod, "read_served_run_summary", _refuse)
    answer = trusted.answer(serve_from=SERVE_FROM_MEMORY)
    assert answer["serving"] == {
        "source": "memory",
        "reason": "store_disabled",
        "store_run_id": _store_run_id(trusted),
        "detail": f"{ENV_SERVE_FROM}=memory",
    }
    assert "store_disabled" in MEMORY_BY_DESIGN_REASONS
    assert _wire(_without_serving(answer)) == _wire(trusted.memory_answer())
    assert counted == ["run_store_serving_memory"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, SERVE_FROM_DEFAULT),
        ("", SERVE_FROM_DEFAULT),
        ("store", SERVE_FROM_DEFAULT),
        (" Run_Store ", SERVE_FROM_RUN_STORE),
        ("MEMORY", SERVE_FROM_MEMORY),
    ],
)
def test_the_switch_reads_two_words_and_defaults_otherwise(
    value: str | None, expected: str
) -> None:
    environ = {} if value is None else {ENV_SERVE_FROM: value}
    assert serving_source(environ) == expected


def test_the_default_source_is_memory_until_the_cutover(
    trusted: SummaryPopulation,
) -> None:
    assert SERVE_FROM_DEFAULT == SERVE_FROM_MEMORY
    serving = trusted.answer(serve_from=None)["serving"]
    assert serving == {
        "source": "memory",
        "reason": "store_disabled",
        "store_run_id": _store_run_id(trusted),
        "detail": f"{ENV_SERVE_FROM}=memory",
    }


def test_a_rollout_that_names_no_store_answers_memory_by_design(
    trusted: SummaryPopulation,
    counted: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The publication flag stays the kill switch: an execution that
    published is answered from memory, unread, once the rollout is off."""
    monkeypatch.delenv("CODECLONE_RUN_STORE_ENABLED", raising=False)
    monkeypatch.setenv(ENV_SERVE_FROM, SERVE_FROM_RUN_STORE)
    answer = trusted.service.get_run_summary(root=str(trusted.root))
    assert answer["serving"] == {
        "source": "memory",
        "reason": "store_disabled",
        "store_run_id": _store_run_id(trusted),
    }
    assert counted == ["run_store_serving_memory"]


def _serve_with_link(
    population: SummaryPopulation,
    store_path: Path,
    edit: Callable[[Any], Any],
) -> tuple[dict[str, object], RunStoreServingOutcome]:
    record = population.record
    execution = replace(
        record.execution,
        run_snapshot_link=edit(record.execution.run_snapshot_link),
    )
    with serving_environment(store_path, serve_from=SERVE_FROM_RUN_STORE):
        return served_run_summary(
            replace(record, execution=execution), population.memory_answer()
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
    trusted: SummaryPopulation, counted: list[str]
) -> None:
    """A publication that failed left no store run and no index row for its
    report: the door looks the report up and answers why there is none."""
    payload, outcome = _serve_with_link(trusted, trusted.store_path, _failed)
    assert (outcome.source, outcome.reason) == ("memory", "run_not_published")
    assert "ffffffffffff" in outcome.detail
    assert outcome.reason not in MEMORY_BY_DESIGN_REASONS
    assert _wire(payload) == _wire(trusted.memory_answer())
    assert counted == ["run_store_serving_fallback"]


def test_a_store_of_another_generation_is_refused_typed(
    trusted: SummaryPopulation, counted: list[str], tmp_path: Path
) -> None:
    """The REAL generation-1 artifact is refused at open and memory
    answers, with the refusal's own words."""
    provenance = json.loads((_GENERATION_1 / "provenance.json").read_text("utf-8"))
    store = tmp_path / "generation-1.sqlite3"
    shutil.copy(_GENERATION_1 / "runs.sqlite3", store)
    payload, outcome = _serve_with_link(
        trusted,
        store,
        lambda link: replace(link, store_run_id=str(provenance["run_id"])),
    )
    assert (outcome.source, outcome.reason) == ("memory", "incompatible_generation")
    assert "canonical_model stored '1' declared '3'" in outcome.detail
    assert _wire(payload) == _wire(trusted.memory_answer())
    assert counted == ["run_store_serving_fallback"]


def test_an_absent_store_is_a_fallback_and_is_never_created(
    trusted: SummaryPopulation, counted: list[str], tmp_path: Path
) -> None:
    absent = tmp_path / "nowhere" / "runs.sqlite3"
    payload, outcome = _serve_with_link(trusted, absent, lambda link: link)
    assert (outcome.source, outcome.reason) == ("memory", "store_absent")
    assert not absent.parent.exists()
    assert _wire(payload) == _wire(trusted.memory_answer())
    assert counted == ["run_store_serving_fallback"]


@pytest.fixture
def disagreeing_health(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The door's reader, answering every block as stored but the health
    score one point off."""
    original = vars(door_mod)["read_served_run_summary"]

    def _read(store: object, run_id: str) -> object:
        stored = original(store, run_id)
        health = {**stored.health, "score": int(str(stored.health["score"])) - 1}
        return replace(stored, health=health)

    monkeypatch.setattr(door_mod, "read_served_run_summary", _read)
    yield


@pytest.mark.usefixtures("disagreeing_health")
def test_a_disagreeing_store_is_answered_from_memory_and_named(
    trusted: SummaryPopulation, counted: list[str]
) -> None:
    """The store never wins an argument with the producer's own answer: the
    values stay memory's, the reason says divergent, the detail names the
    field."""
    answer = trusted.answer(serve_from=SERVE_FROM_RUN_STORE)
    assert answer["serving"] == {
        "source": "memory",
        "reason": "divergent",
        "store_run_id": _store_run_id(trusted),
        "detail": "diverging: health.score",
    }
    assert _wire(_without_serving(answer)) == _wire(trusted.memory_answer())
    assert counted == ["run_store_serving_divergent"]


def test_get_run_summary_answers_what_the_edge_decides(
    trusted: SummaryPopulation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reverse pin at the call site: the tool's values are the edge's
    payload, not a second reading of the record beside it."""
    outcome = RunStoreServingOutcome(source="memory", reason="not_published")
    monkeypatch.setattr(
        state_mixin_mod,
        "served_run_summary",
        lambda _record, _memory: ({"sentinel": True}, outcome),
    )
    answer = trusted.service.get_run_summary(root=str(trusted.root))
    assert answer == {
        "sentinel": True,
        "serving": {"source": "memory", "reason": "not_published"},
    }


@pytest.mark.parametrize(
    ("stored", "memory", "fields"),
    [
        ({"a": 1, "b": 2}, {"a": 1, "b": 2}, ()),
        ({"a": 1, "b": {"x": 1, "y": 2}}, {"a": 1, "b": {"x": 1, "y": 3}}, ("b.y",)),
        ({"b": {"y": 2, "x": 1}}, {"b": {"x": 1, "y": 2}}, ("b",)),
        ({"a": 1}, {"a": 1, "b": None}, ("b",)),
        ({"a": {"x": 1, "z": 0}}, {"a": {"x": 1}}, ("a.z",)),
        ({"b": 2, "a": 1}, {"a": 1, "b": 2}, ("<field order>",)),
        ({"a": 1}, {"a": True}, ("a",)),
    ],
    ids=[
        "agree",
        "nested_value",
        "nested_order",
        "missing_key",
        "extra_nested_key",
        "top_level_order",
        "json_type",
    ],
)
def test_the_divergence_names_every_differing_field(
    stored: dict[str, object], memory: dict[str, object], fields: tuple[str, ...]
) -> None:
    assert summary_divergence(stored, memory) == fields
