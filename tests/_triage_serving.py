# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The populations behind the production-triage serving pins (consumer
migration C2).

The twenty run-summary populations (``tests/_run_summary_serving.py``) are
the triage's too -- each one live MCP execution with its own store -- and the
triage asks of them what the summary does not: the source kind of every
finding and every suggestion, the effort of every suggestion, the short id a
card and a suggestion are shown under, and two limits.  Measured on the
twenty before the edge was written (audit of 2026-10-06, 2d370f30), they
leave three holes a wrong store reading would pass through unseen:

* no finding and no suggestion under ``tests/`` or ``tests/fixtures/`` --
  a reading that answered every source kind ``production`` would agree;
* no structural finding that carries a suggestion -- the effort of the one
  family whose suggestion severity is not its group's severity is never
  read;
* no two findings that share a base short id -- a short-id map built over
  the shown findings instead of the whole universe would agree.

:data:`TRIAGE_KINDS_TREE` closes the three, and the accounting
(:func:`triage_account`, ``tests/test_production_triage_population.py``)
proves on every run of the suite that the populations reach each case before
a single equivalence pin counts.

This module is a helper, not a test module, so it may read the surface's
own helpers beside the canonical store (the Phase 39S test-import law binds
``tests/test_*.py`` only).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from codeclone.api.run_store_serving import ServedTriage, read_run_store_triage
from codeclone.surfaces.mcp import _session_helpers as surface_helpers
from codeclone.surfaces.mcp._run_store_serving import store_triage_payload
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest, MCPRunRecord
from codeclone.surfaces.mcp._session_state_mixin import triage_findings_presenter
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.utils.coerce import as_mapping, as_sequence
from tests import conftest as corpora
from tests._run_store_paths import run_store_service_path
from tests._run_summary_serving import (
    STORE_ROW_PERTURBATIONS,
    SUMMARY_POPULATIONS,
    UNREAD_ROW_PERTURBATIONS,
    SummaryPopulation,
    SummaryPopulations,
    serving_environment,
    shared_populations,
)

#: The populations only the triage needs, by name, and the publication each
#: one states.
TRIAGE_ONLY_POPULATIONS: dict[str, str] = {"triage_kinds": "published"}
#: Every triage population: the run summary's twenty, then the triage's own.
TRIAGE_POPULATIONS: dict[str, str] = {**SUMMARY_POPULATIONS, **TRIAGE_ONLY_POPULATIONS}

_TANGLE = (
    "def {name}(a: int) -> int:\n    t = 0\n"
    + "".join(f"    if a > {i}:\n        t += {i}\n" for i in range(24))
    + "    return t\n"
)
_TALLY = """def {name}(values: list[int]) -> dict[str, int]:
    evens = 0
    odds = 0
    peak = 0
    floor = 10**9
    for value in values:
        if value % 2 == 0:
            evens = evens + 1
        else:
            odds = odds + 1
        if value > peak:
            peak = value
        if value < floor:
            floor = value
    return {{"evens": evens, "odds": odds, "peak": peak, "floor": floor}}
"""
_FOUR_BRANCHES = "def route(kind: str, payload: list[int]) -> str:\n" + (
    "    marker = kind.strip()\n"
    + "".join(
        f"    {'if' if index == 0 else 'elif'} marker == {letter!r}:\n"
        "        for item in payload:\n"
        "            print(item)\n"
        "            print(item + 1)\n"
        f"        return {letter!r}\n"
        for index, letter in enumerate("abcd")
    )
    + "    return marker\n"
)
_ORPHAN = (
    "def _unused_helper(value: int) -> int:\n"
    "    total = value\n    total += {step}\n    return total\n"
)

#: The triage's own tree, analysed at the evaluation carrier's unit floor
#: (``min_loc=3``, ``min_stmt=2``), so the four identical branches are a
#: unit's structural finding.  Measured 2026-10-12, every card and every
#: suggestion shown:
#:
#: * a complexity finding and its suggestion under ``tests/`` and another
#:   under ``tests/fixtures/`` (``tests`` and ``fixtures``), beside the
#:   ``mixed`` clone groups the identical bodies make across the trees;
#: * the four identical branches of ``pkg/branchy.py``: a structural finding
#:   of four occurrences, ``warning``, whose suggestion is ``moderate`` -- a
#:   production hotspot shown with that effort;
#: * ``process`` complex in ``pkg/alpha.py`` and in ``tests/test_alpha.py``:
#:   one base short id, so the production one is shown as a suggestion under
#:   its disambiguated id while its twin is neither a production hotspot nor
#:   a production suggestion; and ``_unused_helper`` dead in two production
#:   modules, both shown as hotspot cards under disambiguated ids.
TRIAGE_KINDS_TREE: dict[str, str] = {
    "pyproject.toml": "[tool.codeclone]\n",
    "pkg/__init__.py": "",
    "pkg/alpha.py": _TANGLE.format(name="process") + "\n\n" + _ORPHAN.format(step=3),
    "pkg/beta.py": _ORPHAN.format(step=5),
    "pkg/branchy.py": _FOUR_BRANCHES,
    "tests/test_alpha.py": _TANGLE.format(name="process"),
    "tests/test_tally.py": _TALLY.format(name="tally_one")
    + "\n\n"
    + _TALLY.format(name="tally_two"),
    "tests/fixtures/sample.py": _TANGLE.format(name="fixture_tangle"),
    "tests/fixtures/tally_a.py": _TALLY.format(name="fixture_one"),
    "tests/fixtures/tally_b.py": _TALLY.format(name="fixture_two"),
}

#: The limits a pin asks the triage under when it wants every card and
#: every suggestion the run ranks shown (the surface's ceiling).
SHOW_ALL: int = 10


def triage_answer(
    population: SummaryPopulation,
    *,
    serve_from: str | None,
    max_hotspots: int = 3,
    max_suggestions: int = 3,
) -> dict[str, object]:
    """``get_production_triage`` of the population's execution under the
    rollout that published it and the serving switch named (``None``: the
    switch unset)."""
    with serving_environment(population.store_path, serve_from=serve_from):
        return population.service.get_production_triage(
            run_id=population.record.run_id,
            root=str(population.root),
            max_hotspots=max_hotspots,
            max_suggestions=max_suggestions,
        )


class TriagePopulations:
    """The run summary's populations and the triage's own, each built on
    first use and kept for the session."""

    def __init__(self, summary: SummaryPopulations, base: Path) -> None:
        self._summary = summary
        self._base = base
        self._built: dict[str, SummaryPopulation] = {}

    def __getitem__(self, name: str) -> SummaryPopulation:
        if name in SUMMARY_POPULATIONS:
            return self._summary[name]
        if name not in self._built:
            self._built[name] = self._serve(name)
        return self._built[name]

    def _serve(self, name: str) -> SummaryPopulation:
        """One live MCP execution of the population's tree, published into
        the root's own store: MCP writes a run store only inside the root's
        ``.codeclone/``, so a store beside the root would be withheld and
        the population would state no published run."""
        assert name in TRIAGE_ONLY_POPULATIONS, name
        root = self._base / name
        root.mkdir()
        corpora._write_tree(root, TRIAGE_KINDS_TREE)
        store_path = run_store_service_path(root)
        service = CodeCloneMCPService(history_limit=4)
        with serving_environment(store_path, serve_from=None):
            service.analyze_repository(
                MCPAnalysisRequest(root=str(root), min_loc=3, min_stmt=2)
            )
        population = SummaryPopulation(
            name=name, root=root, store_path=store_path, service=service
        )
        corpora._published_store_run_id(
            population.record, outcome=TRIAGE_ONLY_POPULATIONS[name]
        )
        return population


#: One set of triage-only populations per pytest session, beside the run
#: summary's (which ``shared_populations`` keeps once per session).
_SHARED: dict[str, TriagePopulations] = {}


def shared_triage_populations(factory: pytest.TempPathFactory) -> TriagePopulations:
    """The session's triage populations, under the session's temporary root."""
    key = str(factory.getbasetemp())
    if key not in _SHARED:
        _SHARED[key] = TriagePopulations(
            shared_populations(factory),
            factory.mktemp("triage_populations").resolve(),
        )
    return _SHARED[key]


@dataclass(frozen=True, slots=True)
class TriageAccount:
    """What one population's memory answer can tell apart, every card and
    suggestion shown (:data:`SHOW_ALL`) unless named otherwise.

    ``card_efforts`` holds ``""`` for a card shown without an effort.
    ``hotspots_cut`` / ``suggestions_cut``: the default limits return fewer
    than the run ranks.  ``discriminating_collisions``: short ids shown
    disambiguated, whose base short id another finding of the universe
    shares while that finding is neither a production hotspot nor a
    production suggestion -- the case where a map built over the shown or
    selected findings alone would answer the base id.
    """

    finding_kinds: frozenset[str]
    suggestion_kinds: frozenset[str]
    card_efforts: frozenset[str]
    item_efforts: frozenset[str]
    card_novelty: frozenset[str]
    card_severities: frozenset[str]
    hotspots_cut: bool
    suggestions_cut: bool
    discriminating_collisions: tuple[str, ...]


def _counted(block: object) -> frozenset[str]:
    return frozenset(
        kind for kind, count in as_mapping(block).items() if int(str(count)) > 0
    )


def _selected_ids(record: MCPRunRecord, production: frozenset[str]) -> set[str]:
    """The production hotspots the document ranked and the findings its
    production suggestions name, by canonical id."""
    derived = as_mapping(record.served_report.get("derived"))
    hotlists = as_mapping(derived.get("hotlists"))
    selected = {
        str(item) for item in as_sequence(hotlists.get("production_hotspot_ids"))
    }
    selected.update(
        str(as_mapping(row).get("finding_id", ""))
        for row in as_sequence(derived.get("suggestions"))
        if str(as_mapping(row).get("finding_id", "")) in production
    )
    return selected


def _discriminating_collisions(
    population: SummaryPopulation, shown: list[str]
) -> tuple[str, ...]:
    record = population.record
    findings = population.service._base_findings(record)
    _to_short, to_canonical = population.service._finding_id_maps_for_findings(findings)
    production = frozenset(
        str(finding.get("id", ""))
        for finding in findings
        if surface_helpers._finding_source_kind(finding) == "production"
    )
    by_base: dict[str, set[str]] = {}
    for finding in findings:
        canonical = str(finding.get("id", ""))
        by_base.setdefault(
            surface_helpers._base_short_finding_id(canonical), set()
        ).add(canonical)
    selected = _selected_ids(record, production)
    collisions: list[str] = []
    for short in shown:
        canonical = to_canonical.get(short, "")
        base = surface_helpers._base_short_finding_id(canonical)
        if short != base and by_base[base] - selected:
            collisions.append(short)
    return tuple(sorted(set(collisions)))


def triage_account(population: SummaryPopulation) -> TriageAccount:
    """The account of one population's memory answer (the switch unset)."""
    shown = triage_answer(
        population, serve_from=None, max_hotspots=SHOW_ALL, max_suggestions=SHOW_ALL
    )
    default = triage_answer(population, serve_from=None)
    cards = [
        as_mapping(card)
        for card in as_sequence(as_mapping(shown["top_hotspots"]).get("items"))
    ]
    items = [
        as_mapping(item)
        for item in as_sequence(as_mapping(shown["top_suggestions"]).get("items"))
    ]
    hotspots = as_mapping(default["top_hotspots"])
    suggestions = as_mapping(default["top_suggestions"])
    return TriageAccount(
        finding_kinds=_counted(as_mapping(shown["findings"]).get("by_source_kind")),
        suggestion_kinds=_counted(
            as_mapping(shown["suggestions"]).get("by_source_kind")
        ),
        card_efforts=frozenset(str(card.get("effort", "")) for card in cards),
        item_efforts=frozenset(str(item.get("effort", "")) for item in items),
        card_novelty=frozenset(str(card.get("novelty", "")) for card in cards),
        card_severities=frozenset(str(card.get("severity", "")) for card in cards),
        hotspots_cut=int(str(hotspots["returned"])) < int(str(hotspots["available"])),
        suggestions_cut=int(str(suggestions["returned"]))
        < int(str(suggestions["available"])),
        discriminating_collisions=_discriminating_collisions(
            population,
            [str(card.get("id", "")) for card in cards]
            + [str(item.get("finding_id", "")) for item in items],
        ),
    )


def accounts(populations: TriagePopulations) -> Mapping[str, TriageAccount]:
    """Every triage population's account, by name, in registry order."""
    return {name: triage_account(populations[name]) for name in TRIAGE_POPULATIONS}


__all__ = [
    "SHOW_ALL",
    "TRIAGE_KINDS_TREE",
    "TRIAGE_ONLY_POPULATIONS",
    "TRIAGE_POPULATIONS",
    "TriageAccount",
    "TriagePopulations",
    "accounts",
    "shared_triage_populations",
    "triage_account",
    "triage_answer",
]


# -- the two producers of a suggestion's effort ------------------------------
#
# The document prices every finding group ``severity rank / effort weight``
# under the effort its builder names (``report.document._findings_groups``,
# ``_design_groups``), and the suggestion of the same finding states an
# effort of its own (``report.suggestions``).  The store carries the price,
# never the suggestion: the effort it answers is the price read backwards
# (``canonical.evaluation_rows.finding_effort``), which is the suggestion's
# effort exactly while the two producers name the same effort.


@dataclass(frozen=True, slots=True)
class SuggestionPricing:
    """One suggestion of one population, beside the price of its finding.

    ``severity`` / ``priority`` are the finding group's as the document
    publishes them; ``suggested_effort`` is the suggestion's own
    (``report.suggestions``) and ``published_effort`` the one the document's
    ``derived.suggestions`` row states for it.
    """

    population: str
    finding_id: str
    category: str
    severity: str
    priority: float
    suggested_effort: str
    published_effort: str


def suggestion_pricings(population: SummaryPopulation) -> tuple[SuggestionPricing, ...]:
    """Every suggestion of the population's execution, priced."""
    record = population.record
    groups = {
        str(finding.get("id", "")): finding
        for finding in population.service._base_findings(record)
    }
    derived = as_mapping(record.served_report.get("derived"))
    published = {
        str(as_mapping(row).get("finding_id", "")): str(
            as_mapping(as_mapping(row).get("action")).get("effort", "")
        )
        for row in as_sequence(derived.get("suggestions"))
    }
    pricings: list[SuggestionPricing] = []
    for suggestion in record.suggestions:
        finding_id = surface_helpers._suggestion_finding_id(suggestion)
        group = as_mapping(groups.get(finding_id))
        pricings.append(
            SuggestionPricing(
                population=population.name,
                finding_id=finding_id,
                category=suggestion.category,
                severity=str(group.get("severity", "")),
                priority=float(str(group.get("priority", "nan"))),
                suggested_effort=suggestion.effort,
                published_effort=published.get(finding_id, ""),
            )
        )
    return tuple(pricings)


__all__ += ["SuggestionPricing", "suggestion_pricings"]


# -- the memory answer --------------------------------------------------------


def without_serving(answer: Mapping[str, object]) -> dict[str, object]:
    """An answer without the one block the serving edge adds."""
    return {key: value for key, value in answer.items() if key != "serving"}


def memory_triage(
    population: SummaryPopulation, *, max_hotspots: int = 3, max_suggestions: int = 3
) -> dict[str, object]:
    """The answer the surface builds from the record alone: the triage
    under the memory switch, without its ``serving`` block."""
    return without_serving(
        triage_answer(
            population,
            serve_from="memory",
            max_hotspots=max_hotspots,
            max_suggestions=max_suggestions,
        )
    )


__all__ += ["memory_triage", "without_serving"]


# -- the store's answer, built beside the memory's ---------------------------

#: The limits the equivalence asks under: below the surface's floor, its
#: floor, its default, its ceiling and past it.
TRIAGE_LIMITS: tuple[int, ...] = (0, 1, 3, 10, 99)


def _clamped(limit: int) -> int:
    """The surface's limit (``get_production_triage``: one to ten), so a
    candidate built here is cut as the tool cuts it; the tool's own clamp is
    held through the tool (``test_a_limit_is_clamped_once_for_both_answers``)."""
    return max(1, min(limit, 10))


def stored_triage(population: SummaryPopulation) -> ServedTriage:
    """The store's triage facts of one execution's run, read through the
    door the surface reads through -- never a reading of the test's own."""
    record = population.record
    with serving_environment(population.store_path, serve_from="run_store"):
        stored, outcome = read_run_store_triage(
            root=record.root, link=record.execution.run_snapshot_link
        )
    assert stored is not None, outcome
    return stored


def triage_pair(
    population: SummaryPopulation, *, limit: int
) -> tuple[dict[str, object], dict[str, object]]:
    """One population's memory answer under ``limit`` (both lists), beside
    the answer the serving edge builds from the store's facts."""
    memory = memory_triage(population, max_hotspots=limit, max_suggestions=limit)
    candidate = store_triage_payload(
        memory,
        stored_triage(population),
        present=triage_findings_presenter(population.service, population.record),
        hotspot_limit=_clamped(limit),
        suggestion_limit=_clamped(limit),
    )
    return memory, candidate


#: The absence of an answer path, on the wire.
ABSENT = "<absent>"


def answer_at(payload: Mapping[str, object], path: str) -> str:
    """The wire bytes of one answer path, or :data:`ABSENT`.

    ``a.b`` walks mappings; ``items[].x`` maps the rest of the path over
    every item of a list, so a card field is one value per shown card;
    ``items[1].x`` takes one item."""
    value: object = payload
    parts = path.split(".")
    for index, part in enumerate(parts):
        name, _bracket, position = part.partition("[")
        if not isinstance(value, Mapping) or name not in value:
            return ABSENT
        value = value[name]
        if not _bracket:
            continue
        if not isinstance(value, list):
            return ABSENT
        rest = ".".join(parts[index + 1 :])
        if position == "]":
            return json.dumps(
                [json.loads(_item_at(item, rest)) for item in value],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        offset = int(position.rstrip("]"))
        if offset >= len(value):
            return ABSENT
        return _item_at(value[offset], rest)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _item_at(item: object, rest: str) -> str:
    if not rest:
        return json.dumps(item, ensure_ascii=False, separators=(",", ":"))
    found = answer_at(item, rest) if isinstance(item, Mapping) else ABSENT
    return found if found != ABSENT else json.dumps(ABSENT)


# -- one store row replaced: the triage's carriers ---------------------------
#
# Each perturbation replaces rows of one run as the store decodes them (the
# run summary's instrument, ``store_row_replaced``), within the laws of the
# model: a selection keeps its ranks gapless and a verdict keeps a priority
# some effort prices, so the store still EXPRESSES the run and the field the
# rows carry has to move.  A grosser edit (a skipped rank, a priority no
# effort prices) is refused by the model before any field is read
# (``unexpressible``), which proves the law, not the carrier.

_Rows = dict[str, list[Any]]
_Perturb = Callable[[_Rows], None]


def _ranked(rows: list[Any], hotlist: str) -> list[int]:
    """The indexes of one selection's rows, in rank order."""
    return sorted(
        (index for index, row in enumerate(rows) if row.hotlist == hotlist),
        key=lambda index: rows[index].rank,
    )


def _swapped(hotlist: str, first_rank: int, second_rank: int) -> _Perturb:
    """Two ranks of one selection exchanged: still gapless, another order."""

    def perturb(collected: _Rows) -> None:
        rows = collected.get("hotlist_selection")
        if rows is not None:
            ranked = _ranked(rows, hotlist)
            first, second = ranked[first_rank - 1], ranked[second_rank - 1]
            rows[first], rows[second] = (
                replace(rows[first], rank=rows[second].rank),
                replace(rows[second], rank=rows[first].rank),
            )

    return perturb


def _last_rank_dropped(hotlist: str) -> _Perturb:
    def perturb(collected: _Rows) -> None:
        rows = collected.get("hotlist_selection")
        if rows is not None:
            del rows[_ranked(rows, hotlist)[-1]]

    return perturb


def _verdict_of_rank(rank: int, **change: object) -> _Perturb:
    """The verdict on the finding the production-hotspot selection ranks at
    ``rank``, replaced by ``change`` (which must keep the price lawful)."""

    def perturb(collected: _Rows) -> None:
        selected = collected.get("hotlist_selection")
        verdicts = collected.get("finding_evaluation")
        if selected is None or verdicts is None:
            return
        target = selected[_ranked(selected, "production_hotspot")[rank - 1]].finding_id
        index = next(
            index for index, row in enumerate(verdicts) if row.finding_id == target
        )
        verdicts[index] = replace(verdicts[index], **change)

    return perturb


def _first_novelty(family: str, word: str, becomes: str) -> _Perturb:
    def perturb(collected: _Rows) -> None:
        rows = collected.get(family)
        if rows is not None:
            index = min(
                (index for index, row in enumerate(rows) if row.novelty == word),
                key=lambda index: repr(rows[index]),
            )
            rows[index] = replace(rows[index], novelty=becomes)

    return perturb


def _first_dropped(family: str) -> _Perturb:
    """The first row of one family, in a content-derived order, taken away."""

    def perturb(collected: _Rows) -> None:
        rows = collected.get(family)
        if rows is not None:
            del rows[min(range(len(rows)), key=lambda index: repr(rows[index]))]

    return perturb


def _summary_carrier(carrier: str) -> tuple[str, _Perturb]:
    """One of the run summary's carriers: the triage shares that block."""
    name, perturb, _fields = STORE_ROW_PERTURBATIONS[carrier]
    return name, perturb


#: Each carrier: (population, rows replaced within the model's laws, the
#: answer paths the replacement must move in the store's answer).  The paths
#: are a floor -- one row may carry more -- never "something moved".
TRIAGE_ROW_PERTURBATIONS: dict[str, tuple[str, _Perturb, tuple[str, ...]]] = {
    "hotspot_ranks_swapped": (
        "trusted",
        _swapped("production_hotspot", 1, 2),
        ("top_hotspots.items[0].canonical_id", "top_hotspots.items[1].canonical_id"),
    ),
    "hotspot_last_rank_dropped": (
        "trusted",
        _last_rank_dropped("production_hotspot"),
        ("top_hotspots.available",),
    ),
    "hotspot_verdict_critical": (
        "trusted",
        _verdict_of_rank(1, severity="critical", priority=3.0),
        (
            "top_hotspots.items[0].severity",
            "top_hotspots.items[0].priority",
            "top_hotspots.items[0].priority_score",
        ),
    ),
    "hotspot_verdict_repriced": (
        "trusted",
        _verdict_of_rank(2, priority=1.0),
        (
            "top_hotspots.items[1].effort",
            "top_hotspots.items[1].priority",
            "top_hotspots.items[1].priority_score",
            "top_suggestions.items[0].effort",
        ),
    ),
    "suggestion_last_rank_dropped": (
        "trusted",
        _last_rank_dropped("suggestions"),
        ("suggestions.total", "suggestions.by_source_kind"),
    ),
    # Ranks 2 and 3: the two production suggestions the triage shows first
    # (rank 1 is the population's one ``mixed`` suggestion, which the
    # production list does not show -- exchanging it moves nothing shown).
    "suggestion_ranks_swapped": (
        "trusted",
        _swapped("suggestions", 2, 3),
        (
            "top_suggestions.items[0].finding_id",
            "top_suggestions.items[1].finding_id",
        ),
    ),
    "clone_novelty": (
        "trusted",
        _first_novelty("clone_novelty", "new", "known"),
        ("findings.new_by_source_kind", "top_hotspots.items[0].novelty"),
    ),
    # An authority violation: a finding group no selection names, so the
    # universe's counts move and nothing shown does.
    "unselected_group_dropped": (
        "trusted",
        _first_dropped("violation"),
        ("findings.total", "findings.by_source_kind", "findings.outside_focus"),
    ),
    # The blocks the triage shares with the run summary, each by its own row.
    "baseline_witness": (
        *_summary_carrier("baseline_witness"),
        ("baseline.baseline_python_tag",),
    ),
    "health_result": (*_summary_carrier("health_result"), ("health.score",)),
    "analysis_profile": (
        *_summary_carrier("analysis_profile"),
        ("analysis_profile.min_loc",),
    ),
    "coverage_join": (
        *_summary_carrier("coverage_join"),
        ("coverage_join.hotspot_threshold_percent",),
    ),
    "security_surface": (
        *_summary_carrier("security_surface"),
        ("security_surfaces.items",),
    ),
}


def _verdict_dropped(match: Callable[[_Rows, Any], bool]) -> _Perturb:
    """The first verdict ``match`` picks, in a content-derived order, taken
    away."""

    def perturb(collected: _Rows) -> None:
        verdicts = collected.get("finding_evaluation")
        if verdicts is not None:
            index = min(
                (index for index, row in enumerate(verdicts) if match(collected, row)),
                key=lambda index: repr(verdicts[index]),
            )
            del verdicts[index]

    return perturb


def _selected_by(hotlist: str, rank: int) -> Callable[[_Rows, Any], bool]:
    def match(collected: _Rows, row: Any) -> bool:
        selected = collected["hotlist_selection"]
        target = str(selected[_ranked(selected, hotlist)[rank - 1]].finding_id)
        return str(row.finding_id) == target

    return match


def _unselected(collected: _Rows, row: Any) -> bool:
    """A finding neither selection names: nothing the triage shows."""
    named = {item.finding_id for item in collected["hotlist_selection"]}
    return row.finding_id not in named


#: A finding a selection names left without its group or its verdict: the
#: store can no longer express what the triage shows, and refuses typed --
#: never a card or a suggestion silently dropped.  (population, rows
#: replaced, a fragment of the refusal's detail.)
TRIAGE_REFUSING_PERTURBATIONS: dict[str, tuple[str, _Perturb, str]] = {
    "hotspot_verdict_dropped": (
        "trusted",
        _verdict_dropped(_selected_by("production_hotspot", 1)),
        "the production_hotspot selection names 'clone:",
    ),
    "suggestion_verdict_dropped": (
        "trusted",
        _verdict_dropped(_selected_by("suggestions", 1)),
        "selection names",
    ),
    "suggestion_group_dropped": (
        "trusted",
        STORE_ROW_PERTURBATIONS["dead_symbol_group"][1],
        "names 'dead_code:",
    ),
}

#: Rows the triage reads but shows nothing of, replaced the same way: the
#: answer must not move and must stay served.  A verdict on a finding no
#: selection names is read (the family is declared) and never shown.
TRIAGE_UNMOVED_PERTURBATIONS: dict[str, tuple[str, _Perturb]] = {
    "unselected_verdict_dropped": ("trusted", _verdict_dropped(_unselected)),
    **{
        family: (name, perturb)
        for family, (name, perturb) in UNREAD_ROW_PERTURBATIONS.items()
    },
}


__all__ += [
    "ABSENT",
    "TRIAGE_LIMITS",
    "TRIAGE_REFUSING_PERTURBATIONS",
    "TRIAGE_ROW_PERTURBATIONS",
    "TRIAGE_UNMOVED_PERTURBATIONS",
    "answer_at",
    "stored_triage",
    "triage_pair",
]
