# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The production triage from the store equals the triage from memory, per
field (consumer migration C2; ruling 2026-09-26: "the consumer loses nothing
on the way").

Every field of ``get_production_triage`` is a row of the C2 census
(``census-c2-2d370f30.csv``: ``C2.01`` ... ``C2.21`` with ``C2.13a``-``m``
and ``C2.17a``-``f``, the ``serving`` block ``C2.22`` and the two refusals
``C2.R1`` / ``C2.R2``) and is registered here exactly once: as a STORE
field, answered from the run store's rows through
``canonical.serving.read_served_triage`` and the surface's card machine, or
as a MEMORY field that is not a store fact, with the source it keeps and
why.  The text of a shown suggestion (``C2.17f``) is one of those: no store
row carries it (controller decision 2026-10-12, option (a) of the audit).

The proof is held on the twenty-one triage populations
(``tests/_triage_serving.py``) under five limits each -- below the
surface's floor, the floor, the default, the ceiling and past it -- and the
population is shown to distinguish every store field before anything
counts: each takes at least two values across the pairs (Probe Validity
Law; ``tests/test_production_triage_population.py`` holds the named cases).
No divergence is declared: every pair is equal byte for byte on the wire.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from codeclone.api.run_store_serving import SERVE_FROM_RUN_STORE
from codeclone.surfaces.mcp._run_store_serving import (
    EXECUTION_BASELINE_KEYS,
    PRESENTATION_SECURITY_KEYS,
    SUGGESTION_TEXT_KEYS,
)
from tests._triage_serving import (
    ABSENT,
    TRIAGE_LIMITS,
    TRIAGE_POPULATIONS,
    TriagePopulations,
    answer_at,
    shared_triage_populations,
    triage_answer,
    triage_pair,
    without_serving,
)

_CARDS = "top_hotspots.items[]"
_SHOWN = "top_suggestions.items[]"

#: The store-carried census rows: each id with the answer paths it owns.
STORE_FIELDS: dict[str, tuple[str, ...]] = {
    "C2.04": (
        "baseline.loaded",
        "baseline.status",
        "baseline.trusted",
        "baseline.compared_without_valid_baseline",
        "baseline.baseline_python_tag",
    ),
    "C2.05": ("health",),
    "C2.07": ("findings.total",),
    "C2.08": ("findings.by_source_kind",),
    "C2.09": ("findings.new_by_source_kind",),
    "C2.10": ("findings.outside_focus",),
    "C2.12": ("top_hotspots.available",),
    "C2.13a": ("top_hotspots.returned",),
    "C2.13b": (f"{_CARDS}.canonical_id",),
    "C2.13c": (f"{_CARDS}.id",),
    "C2.13d": (f"{_CARDS}.kind",),
    "C2.13e": (f"{_CARDS}.severity",),
    "C2.13f": (f"{_CARDS}.novelty",),
    "C2.13g": (f"{_CARDS}.scope",),
    "C2.13h": (f"{_CARDS}.count", f"{_CARDS}.spread"),
    "C2.13i": (f"{_CARDS}.priority",),
    "C2.13j": (f"{_CARDS}.type",),
    "C2.13k": (f"{_CARDS}.locations",),
    "C2.13l": (f"{_CARDS}.effort",),
    "C2.13m": (f"{_CARDS}.priority_score",),
    "C2.14": ("suggestions.total",),
    "C2.15": ("suggestions.by_source_kind",),
    "C2.16": ("suggestions.outside_focus",),
    "C2.17a": ("top_suggestions.available",),
    "C2.17b": ("top_suggestions.returned",),
    "C2.17c": (f"{_SHOWN}.id", f"{_SHOWN}.finding_id"),
    "C2.17d": (f"{_SHOWN}.source_kind",),
    "C2.17e": (f"{_SHOWN}.effort",),
    "C2.18": ("analysis_profile",),
    "C2.19": ("coverage_join",),
    "C2.20": (
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
    "C2.01": (("run_id",), "record.run_id: the evaluated report identity"),
    "C2.02": (("focus",), "literal: presentation"),
    "C2.03": (("health_scope",), "literal: presentation"),
    "C2.06": (("cache",), "record.summary: execution (ruling 09-18)"),
    "C2.11": (("top_hotspots.kind",), "literal: presentation"),
    "C2.17f": (
        tuple(f"{_SHOWN}.{key}" for key in SUGGESTION_TEXT_KEYS),
        "document text: no store row carries a suggestion's text (decision (a))",
    ),
    "C2.21": (("tips",), "live disk: workspace hygiene (ruling 09-18)"),
}

#: The keys of store-carried blocks that stay with memory, and why.
MEMORY_HELD_KEYS: dict[str, str] = {
    **{
        f"baseline.{key}": "execution: the interpreter that ran"
        for key in EXECUTION_BASELINE_KEYS
    },
    **{
        f"security_surfaces.{key}": "presentation" for key in PRESENTATION_SECURITY_KEYS
    },
}

#: The answer's own provenance, added by the serving edge (``C2.22``), and
#: the two refusals, which are not fields of a served answer: each is pinned
#: where it is decided.
SERVING_ROW: dict[str, str] = {"C2.22": "serving"}
REFUSAL_ROWS: dict[str, str] = {
    "C2.R1": "tests/test_mcp_payload_evicted_refusal.py: a run held without "
    "its payload stays a typed refusal (the text has no store owner)",
    "C2.R2": "tests/test_mcp_service.py: an unknown run, another root, a "
    "relative root -- the resolver's exceptions, as for every tool",
}

_Pair = tuple[dict[str, object], dict[str, object]]
_CASES: list[tuple[str, int]] = [
    (name, limit) for name in TRIAGE_POPULATIONS for limit in TRIAGE_LIMITS
]


def _wire(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@pytest.fixture(scope="module")
def populations(tmp_path_factory: pytest.TempPathFactory) -> TriagePopulations:
    return shared_triage_populations(tmp_path_factory)


@pytest.fixture(scope="module")
def pairs(populations: TriagePopulations) -> dict[tuple[str, int], _Pair]:
    """Every population's memory answer under every limit, beside the
    answer built from its store's facts."""
    return {
        (name, limit): triage_pair(populations[name], limit=limit)
        for name, limit in _CASES
    }


def test_the_registry_names_every_census_row_once() -> None:
    rows = [*STORE_FIELDS, *MEMORY_FIELDS, *SERVING_ROW, *REFUSAL_ROWS]
    assert len(rows) == len(set(rows)) == 41
    expected = {f"C2.{index:02d}" for index in range(1, 23)} - {"C2.13", "C2.17"}
    expected |= {f"C2.13{letter}" for letter in "abcdefghijklm"}
    expected |= {f"C2.17{letter}" for letter in "abcdef"}
    expected |= {"C2.R1", "C2.R2"}
    assert set(rows) == expected


def _owner_paths() -> set[str]:
    paths = {path for owned in STORE_FIELDS.values() for path in owned}
    paths.update(path for owned, _why in MEMORY_FIELDS.values() for path in owned)
    paths.update(MEMORY_HELD_KEYS)
    return paths


def _answer_paths(answer: Mapping[str, object]) -> set[str]:
    """Every top-level key, every key of a block the registry splits, and
    every key of every shown card and suggestion."""
    owners = _owner_paths()
    split = {path.split(".")[0] for path in owners if "." in path}
    paths: set[str] = set()
    for key, value in answer.items():
        if key not in split or not isinstance(value, Mapping):
            paths.add(key)
            continue
        for inner, nested in value.items():
            if isinstance(nested, list) and f"{key}.{inner}[]" in {
                path.rsplit(".", 1)[0] for path in owners
            }:
                paths.update(
                    f"{key}.{inner}[].{field}" for item in nested for field in item
                )
            else:
                paths.add(f"{key}.{inner}")
    return paths


@pytest.mark.parametrize("name", list(TRIAGE_POPULATIONS))
def test_every_field_of_the_answer_is_registered_once(
    pairs: dict[tuple[str, int], _Pair], name: str
) -> None:
    """The field inventory: no answer field is unregistered -- no card key
    and no suggestion key either -- so none can reach the store or leave it
    silently."""
    for limit in TRIAGE_LIMITS:
        memory, candidate = pairs[(name, limit)]
        unregistered = (_answer_paths(memory) | _answer_paths(candidate)) - (
            _owner_paths()
        )
        assert not unregistered, (limit, sorted(unregistered))


@pytest.mark.parametrize("limit", TRIAGE_LIMITS)
@pytest.mark.parametrize("row", list(STORE_FIELDS))
def test_every_store_field_equals_memory_byte_for_byte(
    pairs: dict[tuple[str, int], _Pair], row: str, limit: int
) -> None:
    """One census row under one limit, on every population: equal on the
    wire, present on both sides exactly as often."""
    unequal = [
        (name, path)
        for name in TRIAGE_POPULATIONS
        for path in STORE_FIELDS[row]
        if answer_at(pairs[(name, limit)][1], path)
        != answer_at(pairs[(name, limit)][0], path)
    ]
    assert unequal == []


@pytest.mark.parametrize("limit", TRIAGE_LIMITS)
def test_the_store_answers_no_memory_field(
    pairs: dict[tuple[str, int], _Pair], limit: int
) -> None:
    """Every field that is not a store fact is memory's, byte for byte, in
    the answer built from the store -- the suggestion text included."""
    paths = [path for owned, _why in MEMORY_FIELDS.values() for path in owned]
    unequal = [
        (name, path)
        for name in TRIAGE_POPULATIONS
        for path in [*paths, *MEMORY_HELD_KEYS]
        if answer_at(pairs[(name, limit)][1], path)
        != answer_at(pairs[(name, limit)][0], path)
    ]
    assert unequal == []


@pytest.mark.parametrize(("name", "limit"), _CASES)
def test_the_served_answer_is_memory_and_names_its_source(
    populations: TriagePopulations,
    pairs: dict[tuple[str, int], _Pair],
    name: str,
    limit: int,
) -> None:
    """Through the tool: the answer is the memory's byte for byte beside
    ``serving``, which says ``served`` -- the whole answer agreed."""
    population = populations[name]
    memory, _candidate = pairs[(name, limit)]
    answer = triage_answer(
        population,
        serve_from=SERVE_FROM_RUN_STORE,
        max_hotspots=limit,
        max_suggestions=limit,
    )
    link = population.record.execution.run_snapshot_link
    assert link is not None
    assert answer[SERVING_ROW["C2.22"]] == {
        "source": "run_store",
        "reason": "served",
        "store_run_id": link.store_run_id,
    }
    assert _wire(without_serving(answer)) == _wire(memory)


def test_the_pairs_distinguish_every_store_field(
    pairs: dict[tuple[str, int], _Pair],
) -> None:
    """The accounting behind the equalities: every store row takes at least
    two values across the pairs -- present, absent and empty counted apart."""
    constant = [
        row
        for row, paths in STORE_FIELDS.items()
        if len(
            {
                tuple(answer_at(memory, path) for path in paths)
                for memory, _candidate in pairs.values()
            }
        )
        < 2
    ]
    assert constant == []


def test_the_limits_move_what_the_lists_return(
    pairs: dict[tuple[str, int], _Pair],
) -> None:
    """Each limit is a different question somewhere: the returned counts
    are not one constant over the limits of some population."""
    for path in ("top_hotspots.returned", "top_suggestions.returned"):
        moving = [
            name
            for name in TRIAGE_POPULATIONS
            if len(
                {answer_at(pairs[(name, limit)][0], path) for limit in TRIAGE_LIMITS}
            )
            >= 3
        ]
        assert moving, path


def test_an_absent_path_reads_absent() -> None:
    """The reader the registry compares through tells a missing field from
    any value it could hold."""
    assert answer_at({"a": {"b": 1}}, "a.c") == ABSENT
    assert answer_at({"a": [{"b": 1}, {}]}, "a[].b") == '[1,"<absent>"]'
    assert answer_at({"a": [{"b": 1}]}, "a[1].b") == ABSENT
    assert answer_at({"a": 1}, "a[].b") == ABSENT
