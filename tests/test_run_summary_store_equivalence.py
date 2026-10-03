# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The run summary from the store equals the run summary from memory, per field.

Consumer migration C1, the per-field proof (ruling 2026-09-26: "the
consumer loses nothing on the way").  Every field of ``get_run_summary`` is
a row of serving census 3 (``C1.01`` ... ``C1.31``) and is registered here
exactly once: as a STORE field, answered from the run store's rows through
``canonical.serving.read_served_run_summary``, or as a MEMORY field that is
not a store fact by ruling or by nature (identity, execution, presentation,
live disk), with the source it keeps and why.

The proof is held on sixteen live MCP executions, each with its own store
(``tests/_run_summary_serving.py``), and the population is shown to
DISTINGUISH before anything is counted (Probe Validity Law): every store
field takes at least two values across it, and the named states a wrong
projection could hide behind -- the three novelty words, every health
word, both coverage statuses, both inventory branches, the security block's
three shapes -- are each present.

Four (population, field) pairs disagree, measured 2026-10-03, and are
pinned by name rather than fitted (``DECLARED_DIVERGENCES``).  On each of
them the tool answers from memory, says ``divergent`` and names the fields;
the controller's desk decides them.  Every other pair is equal byte for
byte on the wire.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields

import pytest

from codeclone.api.run_store_serving import SERVE_FROM_RUN_STORE, ServedRunSummary
from codeclone.surfaces.mcp._run_store_serving import (
    ENTITY_COUNTS_KEY,
    EXECUTION_BASELINE_KEYS,
    PRESENTATION_SECURITY_KEYS,
    store_summary_payload,
    summary_divergence,
)
from tests._run_summary_serving import (
    SUMMARY_POPULATIONS,
    SummaryPopulations,
    shared_populations,
    stored_blocks,
)

#: The store-carried census rows: each id with the answer paths it owns.
STORE_FIELDS: dict[str, tuple[str, ...]] = {
    "C1.07": ("mode",),
    "C1.08": (
        "baseline.loaded",
        "baseline.status",
        "baseline.trusted",
        "baseline.compared_without_valid_baseline",
        "baseline.baseline_python_tag",
    ),
    "C1.09": ("metrics_baseline",),
    "C1.12": ("inventory.files",),
    "C1.13": ("inventory.lines",),
    "C1.14": ("inventory.functions", "inventory.classes"),
    "C1.15": ("health",),
    "C1.16": ("findings.total",),
    "C1.17": ("findings.new", "findings.known", "findings.unavailable"),
    "C1.18": ("findings.by_family",),
    "C1.19": ("findings.production",),
    "C1.20": ("findings.new_by_source_kind",),
    "C1.21": ("diff.new_clones",),
    "C1.22": ("diff.health_delta",),
    "C1.23": (
        "diff.typing_param_permille_delta",
        "diff.typing_return_permille_delta",
        "diff.docstring_permille_delta",
        "diff.api_breaking_changes",
        "diff.api_signature_changes",
        "diff.new_api_symbols",
    ),
    "C1.25": ("analysis_profile",),
    "C1.26": ("dead_code",),
    "C1.27": ("coverage_join",),
    "C1.28": (
        "security_surfaces.items",
        "security_surfaces.categories",
        "security_surfaces.production",
        "security_surfaces.tests",
        "security_surfaces.available",
        "security_surfaces.reason",
    ),
}

#: The census rows that are not store facts: the paths, and the source each
#: keeps with the reason.
MEMORY_FIELDS: dict[str, tuple[tuple[str, ...], str]] = {
    "C1.01": (("run_id",), "record.run_id: the evaluated report identity"),
    "C1.02": (("focus",), "literal: presentation"),
    "C1.03": (("health_scope",), "literal: presentation"),
    "C1.04": (("version",), "record.summary: execution provenance (ruling 09-18)"),
    "C1.05": (("code_provenance",), "server process: execution (ruling 09-18)"),
    "C1.06": (("schema",), "record.summary: the document's contract version"),
    "C1.10": (("cache.used",), "record.summary: execution (ruling 09-18)"),
    "C1.11": (("cache.freshness",), "record.summary: the cache split (DET-01)"),
    "C1.24": (("warnings", "failures"), "record.summary: execution (ruling 09-18)"),
    "C1.29": (("drifted_files",), "live disk: execution (ruling 09-18)"),
    "C1.30": (("next_tool",), "literal: presentation"),
    "C1.31": (("tips",), "live disk: workspace hygiene (ruling 09-18)"),
}

#: The keys of store-carried blocks that stay with memory, and why.
MEMORY_HELD_KEYS: dict[str, str] = {
    **{
        f"baseline.{key}": "execution: the interpreter that ran"
        for key in EXECUTION_BASELINE_KEYS
    },
    f"inventory.{ENTITY_COUNTS_KEY}": "the report's inventory scope (cache split)",
    **{
        f"security_surfaces.{key}": "presentation" for key in PRESENTATION_SECURITY_KEYS
    },
}

#: The answer's own provenance, added by the serving edge.
SERVING_KEY = "serving"

#: The measured disagreements (2026-10-03), by population: the fields the
#: store answers differently, in the answer's order.  Every one is on the
#: controller's desk; none is fitted.
DECLARED_DIVERGENCES: dict[str, tuple[str, ...]] = {
    # Store more correct: a lane feeding health was recorded under an older
    # schema, so the health comparison is withheld -- the memory's ``diff``
    # says 0 beside its own ``health.baseline_diff_available: false``.
    "older_schema_dead_code_lane": ("diff.health_delta",),
    # Store more correct (desk 2026-09-27): the API lane is not enabled and
    # the memory counts every baseline symbol as a breaking change.
    "api_disabled": ("diff.api_breaking_changes",),
    # Store more correct (desk 2026-09-27): an API comparison over a
    # partial population did not run; the memory states its counts.
    "partial": (
        "diff.api_breaking_changes",
        "diff.api_signature_changes",
        "diff.new_api_symbols",
    ),
    # Store WRONG, a producer defect outside this wave: a clones-only rerun
    # over a warm cache publishes three authority groups its own population
    # declares disabled (a cold run publishes none).
    "clones_only_warm": (
        "findings.total",
        "findings.unavailable",
        "findings.by_family",
    ),
}

_ABSENT = "<absent>"

_Pair = tuple[dict[str, object], dict[str, object]]


@pytest.fixture(scope="module")
def populations(tmp_path_factory: pytest.TempPathFactory) -> SummaryPopulations:
    return shared_populations(tmp_path_factory)


@pytest.fixture(scope="module")
def pairs(populations: SummaryPopulations) -> dict[str, _Pair]:
    """Every population's memory answer beside the answer built from its
    store blocks."""
    built: dict[str, _Pair] = {}
    for name in SUMMARY_POPULATIONS:
        population = populations[name]
        memory = population.memory_answer()
        built[name] = (
            memory,
            store_summary_payload(memory, stored_blocks(population)),
        )
    return built


def _wire(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _at(payload: Mapping[str, object], path: str) -> str:
    """The wire bytes of one answer path, or the absence marker."""
    value: object = payload
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return _ABSENT
        value = value[part]
    return _wire(value)


def _store_cases() -> list[tuple[str, str]]:
    return [(row, name) for row in STORE_FIELDS for name in SUMMARY_POPULATIONS]


def test_the_registry_names_all_thirty_one_census_rows() -> None:
    rows = [*STORE_FIELDS, *MEMORY_FIELDS]
    assert len(rows) == len(set(rows)) == 31
    assert sorted(rows) == [f"C1.{index:02d}" for index in range(1, 32)]


def _owner_paths() -> set[str]:
    paths = {path for owned in STORE_FIELDS.values() for path in owned}
    paths.update(path for owned, _why in MEMORY_FIELDS.values() for path in owned)
    paths.update(MEMORY_HELD_KEYS)
    return paths


def _answer_paths(answer: Mapping[str, object]) -> set[str]:
    """Every top-level key, and every key of a block the registry splits."""
    split = {path.split(".")[0] for path in _owner_paths() if "." in path}
    paths: set[str] = set()
    for key, value in answer.items():
        if key in split and isinstance(value, Mapping):
            paths.update(f"{key}.{inner}" for inner in value)
        else:
            paths.add(key)
    return paths


@pytest.mark.parametrize("name", list(SUMMARY_POPULATIONS))
def test_every_field_of_the_answer_is_registered_once(
    pairs: dict[str, _Pair], name: str
) -> None:
    """The field inventory: no answer field is unregistered, so none can
    reach the store or leave it silently."""
    memory, candidate = pairs[name]
    unregistered = (_answer_paths(memory) | _answer_paths(candidate)) - _owner_paths()
    assert not unregistered, sorted(unregistered)


@pytest.mark.parametrize(("row", "name"), _store_cases())
def test_every_store_field_equals_memory_byte_for_byte(
    pairs: dict[str, _Pair], row: str, name: str
) -> None:
    """One census row on one population: equal on the wire, or exactly a
    declared divergence of that population."""
    memory, candidate = pairs[name]
    declared = set(DECLARED_DIVERGENCES.get(name, ()))
    for path in STORE_FIELDS[row]:
        if path in declared:
            assert _at(candidate, path) != _at(memory, path), (row, name, path)
        else:
            assert _at(candidate, path) == _at(memory, path), (row, name, path)


@pytest.mark.parametrize("name", list(SUMMARY_POPULATIONS))
def test_the_store_answers_no_memory_field(pairs: dict[str, _Pair], name: str) -> None:
    """Every field that is not a store fact is memory's, byte for byte, in
    the answer built from the store."""
    memory, candidate = pairs[name]
    paths = [path for owned, _why in MEMORY_FIELDS.values() for path in owned]
    for path in [*paths, *MEMORY_HELD_KEYS]:
        assert _at(candidate, path) == _at(memory, path), (name, path)


_STORE_BLOCKS = (
    "run_id",
    "mode",
    "baseline",
    "metrics_baseline",
    "inventory",
    "health",
    "findings",
    "diff",
    "analysis_profile",
    "dead_code",
    "coverage_join",
    "security_surfaces",
)


@pytest.mark.parametrize("name", list(SUMMARY_POPULATIONS))
def test_the_store_blocks_carry_no_memory_held_key(
    populations: SummaryPopulations, name: str
) -> None:
    """What the store is asked for is exactly its blocks: no execution key
    in ``baseline``, no inventory refusal, no presentation key."""
    assert tuple(field.name for field in fields(ServedRunSummary)) == _STORE_BLOCKS
    stored = stored_blocks(populations[name])
    for path in MEMORY_HELD_KEYS:
        block, key = path.split(".")
        assert key not in getattr(stored, block), (name, path)


@pytest.mark.parametrize("name", list(SUMMARY_POPULATIONS))
def test_the_served_answer_is_memory_and_names_its_source(
    populations: SummaryPopulations, pairs: dict[str, _Pair], name: str
) -> None:
    """Through the tool: the answer is the memory's byte for byte beside
    ``serving``, which says ``served`` where every field agrees and
    ``divergent`` -- naming exactly the declared fields -- where not."""
    population = populations[name]
    memory, candidate = pairs[name]
    answer = population.answer(serve_from=SERVE_FROM_RUN_STORE)
    serving = answer.pop(SERVING_KEY)
    assert _wire(answer) == _wire(memory)
    declared = DECLARED_DIVERGENCES.get(name, ())
    assert summary_divergence(candidate, memory) == declared
    link = population.record.execution.run_snapshot_link
    assert link is not None
    if declared:
        assert serving == {
            "source": "memory",
            "reason": "divergent",
            "store_run_id": link.store_run_id,
            "detail": "diverging: " + ", ".join(declared),
        }
    else:
        assert serving == {
            "source": "run_store",
            "reason": "served",
            "store_run_id": link.store_run_id,
        }


def _memory_words(pairs: dict[str, _Pair], path: str) -> set[str]:
    return {_at(memory, path) for memory, _candidate in pairs.values()}


def test_the_population_distinguishes_every_store_field(
    pairs: dict[str, _Pair],
) -> None:
    """The accounting behind the equalities (Probe Validity Law): every
    store row takes at least two values across the population, and every
    state a constant-answering projection could hide behind is present."""
    for row, paths in STORE_FIELDS.items():
        values = {
            tuple(_at(memory, path) for path in paths)
            for memory, _candidate in pairs.values()
        }
        assert len(values) >= 2, row
    for word in ("new", "known", "unavailable"):
        assert any(
            json.loads(value) > 0 for value in _memory_words(pairs, f"findings.{word}")
        ), word
    health_words = {
        str(
            dict(json.loads(value)).get(
                "population", dict(json.loads(value)).get("reason")
            )
        )
        for value in _memory_words(pairs, "health")
    }
    assert {
        "complete_nonempty",
        "complete_empty",
        "unmeasured",
        "metrics_skipped",
    } <= health_words
    assert {'"ok"', '"invalid"', _ABSENT} <= _memory_words(
        pairs, "coverage_join.status"
    )
    assert {_ABSENT} < _memory_words(pairs, f"inventory.{ENTITY_COUNTS_KEY}")
    assert {'"metrics_skipped"', _ABSENT} <= _memory_words(
        pairs, "security_surfaces.reason"
    )
    assert {"0", _ABSENT} < _memory_words(pairs, "security_surfaces.items")
    assert _ABSENT in _memory_words(pairs, "dead_code")
    assert {"null"} < _memory_words(pairs, "diff.new_clones")
    assert {"null"} < _memory_words(pairs, "diff.health_delta")
    assert len(_memory_words(pairs, "baseline.status")) >= 3
