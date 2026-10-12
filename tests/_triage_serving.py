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

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeclone.surfaces.mcp import _session_helpers as surface_helpers
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest, MCPRunRecord
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.utils.coerce import as_mapping, as_sequence
from tests import conftest as corpora
from tests._run_summary_serving import (
    SUMMARY_POPULATIONS,
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
        assert name in TRIAGE_ONLY_POPULATIONS, name
        root = self._base / name
        root.mkdir()
        corpora._write_tree(root, TRIAGE_KINDS_TREE)
        store_path = self._base / f"{name}.sqlite3"
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
