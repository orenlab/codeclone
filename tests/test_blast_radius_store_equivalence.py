# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Every field of ``get_blast_radius``, served from the store, is memory's.

Consumer migration C7, the per-field registry.  On every population of
``tests/_blast_radius_serving.py`` every question is asked twice of the same
execution -- the serving switch on memory, then on the store -- and the two
answers are held byte for byte, field by field, under the census row each
field stands for (``census-c7-ade7d398.csv``).  A served answer is the
memory's bytes by construction of the edge, so equality alone would prove
nothing about the store; what the store adds is the ``serving`` block, and it
must say ``served`` on every question: the edge compared the WHOLE store
result with the whole memory result, uncut lists and list order included,
and found them the same bytes.  That a field is READ from the store is the
carriers' pin (``tests/test_blast_radius_store_carriers.py``).

The population must distinguish before it counts (Probe Validity Law): the
accounting test states, per field, how many questions reached it and how many
distinct values it took, and refuses a population on which a field is one
constant.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from codeclone.api.run_store_serving import (
    ENV_SERVE_FROM,
    SERVE_FROM_MEMORY,
    SERVE_FROM_RUN_STORE,
)
from codeclone.utils.coerce import as_mapping, as_sequence
from tests._blast_radius_serving import (
    BLAST_POPULATIONS,
    BlastPopulations,
    BlastRequest,
    PolicyRequest,
    blast_answer,
    blast_requests,
    policy_answer,
    policy_requests,
    shared_blast_populations,
)

#: The census rows of C7, each with the answer path it stands for.
FIELD_REGISTRY: dict[str, tuple[str, ...]] = {
    "C7.01": ("run_id",),
    "C7.02": ("origin",),
    "C7.03": ("depth",),
    "C7.04": ("radius_level",),
    "C7.05": ("direct_dependents",),
    "C7.06": ("transitive_dependents",),
    "C7.07": ("clone_cohort_members",),
    "C7.08": ("in_dependency_cycle",),
    "C7.09": ("structural_risk", "high_complexity_in_blast_zone"),
    "C7.10": ("structural_risk", "high_coupling_in_blast_zone"),
    "C7.11": ("structural_risk", "overloaded_modules_in_blast_zone"),
    "C7.12": ("structural_risk", "low_coverage_in_blast_zone"),
    "C7.13": ("do_not_touch",),
    "C7.14": ("do_not_touch_summary",),
    "C7.15": ("review_context",),
    "C7.16": ("review_context_summary",),
    "C7.17": ("guardrails",),
}

#: The answer's keys before this wave, in order; ``serving`` follows them.
ANSWER_KEYS: tuple[str, ...] = (
    "run_id",
    "origin",
    "depth",
    "radius_level",
    "direct_dependents",
    "transitive_dependents",
    "clone_cohort_members",
    "in_dependency_cycle",
    "structural_risk",
    "do_not_touch",
    "do_not_touch_summary",
    "review_context",
    "review_context_summary",
    "guardrails",
)


def _wire(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _at(answer: dict[str, object], path: tuple[str, ...]) -> object:
    value: object = answer
    for key in path:
        value = as_mapping(value).get(key)
    return value


@dataclass(frozen=True, slots=True)
class _Asked:
    population: str
    store_run_id: str
    request: BlastRequest | PolicyRequest
    memory: dict[str, object]
    memory_serving: object
    stored: dict[str, object]
    stored_serving: object


def _ask_twice(
    populations: BlastPopulations, name: str
) -> tuple[list[_Asked], list[_Asked]]:
    population = populations[name]
    link = population.record.execution.run_snapshot_link
    assert link is not None and link.store_run_id
    asked: list[_Asked] = []
    for request in blast_requests(population):
        memory = blast_answer(population, request, serve_from=SERVE_FROM_MEMORY)
        stored = blast_answer(population, request, serve_from=SERVE_FROM_RUN_STORE)
        asked.append(
            _Asked(
                name,
                link.store_run_id,
                request,
                memory,
                memory.pop("serving"),
                stored,
                stored.pop("serving"),
            )
        )
    policy: list[_Asked] = []
    for shaped in policy_requests(population):
        memory, memory_serving = policy_answer(
            population, shaped, serve_from=SERVE_FROM_MEMORY
        )
        stored, stored_serving = policy_answer(
            population, shaped, serve_from=SERVE_FROM_RUN_STORE
        )
        policy.append(
            _Asked(
                name,
                link.store_run_id,
                shaped,
                memory,
                memory_serving,
                stored,
                stored_serving,
            )
        )
    return asked, policy


@pytest.fixture(scope="module")
def answers(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[list[_Asked], list[_Asked]]:
    """Every question of every population, asked under both switches."""
    populations = shared_blast_populations(tmp_path_factory)
    tool: list[_Asked] = []
    policy: list[_Asked] = []
    for name in BLAST_POPULATIONS:
        asked, shaped = _ask_twice(populations, name)
        tool.extend(asked)
        policy.extend(shaped)
    return tool, policy


def _every(answers: tuple[list[_Asked], list[_Asked]]) -> list[_Asked]:
    tool, policy = answers
    return [*tool, *policy]


def test_every_question_is_served_from_the_store(
    answers: tuple[list[_Asked], list[_Asked]],
) -> None:
    """The store's whole result equalled memory's on every question of
    every population, and memory's answers say which switch held them."""
    for asked in _every(answers):
        assert asked.stored_serving == {
            "source": "run_store",
            "reason": "served",
            "store_run_id": asked.store_run_id,
        }, (asked.population, asked.request)
        assert asked.memory_serving == {
            "source": "memory",
            "reason": "store_disabled",
            "store_run_id": asked.store_run_id,
            "detail": f"{ENV_SERVE_FROM}=memory",
        }


def test_the_answer_keys_are_unchanged_but_for_serving(
    answers: tuple[list[_Asked], list[_Asked]],
) -> None:
    tool, policy = answers
    for asked in tool:
        assert tuple(asked.stored) == ANSWER_KEYS
        assert tuple(asked.memory) == ANSWER_KEYS
    for asked in policy:
        assert tuple(asked.stored) == ANSWER_KEYS


@pytest.mark.parametrize("row", list(FIELD_REGISTRY))
def test_each_field_is_the_memory_bytes_on_every_question(
    answers: tuple[list[_Asked], list[_Asked]], row: str
) -> None:
    """One census row: its field, serialized, is memory's on every question
    -- list order, truncation summaries and JSON types included."""
    path = FIELD_REGISTRY[row]
    reached = 0
    for asked in _every(answers):
        assert _wire(_at(asked.stored, path)) == _wire(_at(asked.memory, path)), (
            row,
            asked.population,
            asked.request,
        )
        reached += 1
    assert reached == len(_every(answers))


def _distinct(asked: list[_Asked], path: tuple[str, ...]) -> set[str]:
    return {_wire(_at(item.stored, path)) for item in asked}


def _categories(asked: list[_Asked], field: str) -> set[str]:
    return {
        str(as_mapping(entry)["category"])
        for item in asked
        for entry in as_sequence(item.stored[field])
    }


# -- Probe Validity: the population distinguishes before it counts -----------


def test_every_field_takes_more_than_one_value(
    answers: tuple[list[_Asked], list[_Asked]],
) -> None:
    every = _every(answers)
    accounting = {
        row: len(_distinct(every, path)) for row, path in FIELD_REGISTRY.items()
    }
    assert all(count >= 2 for count in accounting.values()), accounting


def test_every_radius_level_and_guardrail_count_occurs(
    answers: tuple[list[_Asked], list[_Asked]],
) -> None:
    tool, _policy = answers
    assert {str(item.stored["radius_level"]) for item in tool} == {
        "low",
        "medium",
        "high",
    }
    assert {len(as_sequence(item.stored["guardrails"])) for item in tool} == {3, 4}


def test_every_review_and_boundary_category_occurs(
    answers: tuple[list[_Asked], list[_Asked]],
) -> None:
    tool, policy = answers
    assert _categories(tool, "review_context") == {
        "dynamic_frontier_boundary",
        "golden_fixture_surface",
        "known_baseline_debt",
        "report_only_context",
        "security_boundary_context",
    }
    assert _categories(policy, "do_not_touch") == {
        "affected_but_not_allowed",
        "baseline_or_generated_state",
        "explicit_forbidden",
    }


@pytest.mark.parametrize("summary", ["do_not_touch_summary", "review_context_summary"])
def test_each_summary_is_both_cut_and_whole(
    answers: tuple[list[_Asked], list[_Asked]], summary: str
) -> None:
    cut = {
        bool(as_mapping(item.stored[summary])["truncated"]) for item in _every(answers)
    }
    assert cut == {True, False}


@pytest.mark.parametrize("row", ["C7.09", "C7.10", "C7.11", "C7.12"])
def test_each_risk_signal_is_reached(
    answers: tuple[list[_Asked], list[_Asked]], row: str
) -> None:
    tool, _policy = answers
    assert any(as_sequence(_at(item.stored, FIELD_REGISTRY[row])) for item in tool)


def test_the_questions_vary_depth_origins_and_publication(
    answers: tuple[list[_Asked], list[_Asked]],
) -> None:
    tool, _policy = answers
    assert {item.request.depth for item in tool} == {"direct", "transitive"}
    assert any(len(item.request.files) > 1 for item in tool)
    assert {BLAST_POPULATIONS[item.population] for item in tool} == {
        "published",
        "head_withheld",
    }
