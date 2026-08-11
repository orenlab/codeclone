# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Engineering Memory must ask the run whether it was fit to be believed.

A run already carries typed facts about its own fitness — the health
population state owned by ``codeclone.contracts`` and the baseline lane
verdict projected as ``baseline.state``. Ingest used to consult neither: a run
that opened no file still produced ``status='active'``
``confidence='supported'`` records asserting that modules it never read were
"analyzed", and nothing on the stored record told a later reader which kind of
run had produced it.

Both directions are pinned here, as in ``test_no_data_no_debt``: a refusal
that reached a fully measured run would be the same defect with the opposite
sign, so every guard has a sibling that reds when the refusal over-reaches.

Nothing here spells a population state. This file's subject is a *relation* —
the mark a record carries must repeat the population the report declared — and
it once stated that relation as four copies of one value (``population=
complete``). Splitting the enum then reddened four tests that had no opinion
about the split, while the fact they existed to pin was never in question. The
vocabulary is therefore read from the type that owns it, and each state this
file needs by name is selected by *what its run did* — found and read, found
and partly read, found and read nothing, nothing to find. Renaming a member
cannot reach these tests; removing one, or adding a fifth, reds
``test_every_population_state_has_a_run_that_realises_it`` with the state
named, which is the failure a reader can act on.

Which state means what is not restated here either: that rule is pinned by its
owner in ``tests/test_no_data_no_debt.py`` and
``tests/test_empty_analysis_scope.py``, and its wire spelling in
``tests/test_report_honest_population.py``. One fact, one place.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Final, get_args
from uuid import UUID

import pytest

from codeclone.contracts import HealthPopulation, observed_population
from codeclone.memory.application import execute_memory_query
from codeclone.memory.enums import EVIDENCE_KIND_VALUES
from codeclone.memory.exceptions import UnfitAnalysisRunError
from codeclone.memory.ingest import InitOptions
from codeclone.memory.ingest.mcp_sync import execute_mcp_memory_sync
from codeclone.memory.ingest.run_fitness import (
    RUN_FITNESS_EVIDENCE_KIND,
    read_run_fitness,
)
from codeclone.memory.ingest.runner import run_memory_init
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.models import (
    BaselineContainerV3,
    LaneTrust,
    LaneTrustReason,
    LaneTrustStatus,
    ObservationLaneName,
    TrustVector,
)
from tests._report_fixtures import single_module_baseline_container
from tests.memory_fixtures import (
    git_repo_with_cached_report,
    memory_application_context,
    memory_project_db_paths,
    report_document_for_counters,
)

_SCOPE_ID = UUID("018f4b8e-5a5f-7d35-9c21-4af5d18df420")
_MODULE_SOURCE = "def f():\n    return 1\n"
_REGISTRY = ["pkg/mod.py"]

#: One run per population state, described by the only two numbers that decide
#: it: files found, files read. Written as inputs rather than as names, and
#: labelled by the contract's own classifier, so this file keeps no copy of the
#: vocabulary to go stale.
_RUNS: Final[tuple[tuple[int, int], ...]] = ((0, 0), (2, 0), (2, 1), (2, 2))

#: The run that realises each state, keyed by the state its own owner gives it.
#: A collision (two runs classified alike) silently shrinks this mapping, which
#: is why its size is asserted, not assumed.
_COUNTERS_FOR_POPULATION: Final[dict[HealthPopulation, tuple[int, int]]] = {
    observed_population(files_found=found, files_analyzed_or_cached=analyzed): (
        found,
        analyzed,
    )
    for found, analyzed in _RUNS
}


def _the_run_that(predicate: Callable[[int, int], bool]) -> HealthPopulation:
    """The one state whose run answers ``predicate(found, analyzed)``.

    Selection by behaviour, not by spelling: the tests below need to say "the
    run that read everything it found" without naming the word for it. Exactly
    one match is required, so a table that stopped being one-to-one fails at
    import with the ambiguity shown rather than silently picking a state.
    """

    matches = sorted(
        population
        for population, (found, analyzed) in _COUNTERS_FOR_POPULATION.items()
        if predicate(found, analyzed)
    )
    assert len(matches) == 1, f"expected exactly one population, got {matches}"
    return matches[0]


#: Every file found was read, and there were files to read.
_ALL_READ: Final = _the_run_that(lambda found, analyzed: 0 < found == analyzed)
#: Some of what was found was read; the rest was never opened.
_SOME_READ: Final = _the_run_that(lambda found, analyzed: 0 < analyzed < found)
#: Files were found and none were opened — the run that measured nothing.
_NONE_READ: Final = _the_run_that(lambda found, analyzed: found > 0 and analyzed == 0)


def _all_lanes(status: LaneTrustStatus, reason: LaneTrustReason) -> TrustVector:
    """One verdict applied to every declared observation lane.

    The lane vocabulary is enumerated from the type that owns it, so a lane
    added to the contract is covered here without anyone remembering to.
    """

    return TrustVector(
        root_verified=True,
        lanes=tuple(
            LaneTrust(name=name, status=status, reason=reason)
            for name in get_args(ObservationLaneName)
        ),
    )


def _repo_with_run(
    tmp_path: Path,
    *,
    population: HealthPopulation,
    container: BaselineContainerV3 | None = None,
    trust: TrustVector | None = None,
) -> tuple[Path, dict[str, object]]:
    """A real git repo plus a report document built by the real builder."""

    root, _report_path, _document = git_repo_with_cached_report(
        tmp_path,
        py_sources={_REGISTRY[0]: _MODULE_SOURCE},
        registry_items=list(_REGISTRY),
    )
    document = _run_document(
        root,
        population=population,
        container=container,
        trust=trust,
    )
    return root, document


def _run_document(
    root: Path,
    *,
    population: HealthPopulation,
    container: BaselineContainerV3 | None = None,
    trust: TrustVector | None = None,
) -> dict[str, object]:
    """A report of a run that observed exactly ``population`` of its scope.

    The state is *asked for*, and the fixture is then held to it: every
    assertion below compares the stamped mark against the state this document
    was built to declare, so a builder that drifted to a neighbouring state
    has to red here instead of moving both sides of the comparison together.
    """

    found, analyzed = _COUNTERS_FOR_POPULATION[population]
    # The assembly is shared with the memory-sync tests, which need the same
    # kind of run described by the same two numbers; only the question asked
    # of it differs, and that question — the state — stays here.
    document = report_document_for_counters(
        root,
        found=found,
        analyzed=analyzed,
        registry_items=_REGISTRY,
        baseline_container=container,
        baseline_trust=trust,
    )
    declared = _declared_population(document)
    assert declared == population, (
        f"the fixture was asked for {population!r} and declared {declared!r}"
    )
    return document


def _mapping(value: object) -> dict[str, object]:
    """A JSON object from an ``object``-typed payload slot.

    Extracted rather than repeated: ``x = payload[k]`` followed by
    ``assert isinstance(x, dict)`` is the single most common statement pair in
    this test suite, and repeating it here reproduced a block-clone group
    against two unrelated modules.
    """

    assert isinstance(value, dict), f"expected a JSON object, got {type(value)}"
    return value


def _declared_population(document: dict[str, object]) -> str:
    """What the report says about itself — the input side of every echo below.

    Navigated by hand rather than through the accessor the reader under test
    uses: a test that reached the fact the same way the code does would agree
    with it about a wrong path as readily as about a right one.
    """

    families = _mapping(_mapping(document["metrics"])["families"])
    return str(_mapping(_mapping(families["health"])["summary"])["population"])


def _expected_mark(*, baseline: str, population: str) -> str:
    """The mark as its reader parses it: two ``key=value`` fields, one line.

    The shape is a contract of the stored record, so it is written out once
    here instead of being copied into each assertion — and never taken from
    the producer, which would make every assertion agree with itself.
    """

    return f"baseline={baseline};population={population}"


def _mark_fields(mark: str) -> dict[str, str]:
    """The mark read field by field, without assuming an order or a shape."""

    fields: dict[str, str] = {}
    for part in mark.split(";"):
        key, _, value = part.partition("=")
        fields[key] = value
    return fields


def _ingest(root: Path, document: dict[str, object], *, refresh: bool = False) -> None:
    run_memory_init(
        root_path=root,
        report_document=document,
        options=InitOptions(refresh=refresh, include_docs=True, include_tests=True),
    )


def _stored_fitness_provenance(root: Path) -> list[str]:
    """Every stored record's run-fitness provenance, one string per record."""

    project, db_path = memory_project_db_paths(root)
    store = SqliteEngineeringMemoryStore(db_path)
    try:
        records = store.list_records_for_project(project.id)
        provenance: list[str] = []
        for record in records:
            marks = [
                str(item.locator)
                for item in store.list_evidence_for_memory(record.id)
                if item.evidence_kind == RUN_FITNESS_EVIDENCE_KIND
            ]
            assert len(marks) == 1, (
                f"record {record.identity_key} carries {len(marks)} run-fitness "
                "marks; exactly one is the contract"
            )
            provenance.append(marks[0])
        return provenance
    finally:
        store.close()


# ── the lane the mark rides in ──────────────────────────────────────


def test_mark_rides_the_analysis_report_evidence_lane() -> None:
    """The lane value itself is the contract, so state it once, here.

    Every other test in this file reads ``RUN_FITNESS_EVIDENCE_KIND`` rather
    than a literal, which keeps them honest about *where* the mark is — and
    leaves them green for any value of the constant. Without this test a
    silent re-lane (say to ``cache``) would pass the whole suite while
    telling every consumer that these records came out of a cache.
    """

    assert RUN_FITNESS_EVIDENCE_KIND == "report"
    assert RUN_FITNESS_EVIDENCE_KIND in EVIDENCE_KIND_VALUES
    # Must not collide with the lanes ingest already writes, or the mark
    # becomes indistinguishable from git provenance and file evidence.
    assert RUN_FITNESS_EVIDENCE_KIND not in {"git_commit", "code"}


# ── the mark echoes the report, whatever the report says ────────────


def test_every_population_state_has_a_run_that_realises_it() -> None:
    """The state table must cover the contract, and cover it one-to-one.

    This is what makes the two parametrised tests below true tomorrow rather
    than on the day they were written: they range over the live type, so a
    state with no run to realise it would silently drop out of both. Read from
    ``get_args`` for the same reason — a member added to the contract arrives
    here as a named failure instead of as a gap nobody is looking at.
    """

    assert set(_COUNTERS_FOR_POPULATION) == set(get_args(HealthPopulation))
    assert len(_COUNTERS_FOR_POPULATION) == len(_RUNS)


@pytest.mark.parametrize("population", sorted(get_args(HealthPopulation)))
def test_the_mark_echoes_the_population_the_report_declared(
    tmp_path: Path, population: HealthPopulation
) -> None:
    """The mark repeats the report's own word for what the run observed.

    The relation, not the word: whichever state the fixture was built to
    declare is the state the record must carry. A producer that hardwired one
    value, or reached for a neighbouring field, reds on the states it is not
    hardwired to; a producer that echoes stays green through a rename.
    """

    fitness = read_run_fitness(_run_document(tmp_path, population=population))

    assert fitness.population == population
    assert _mark_fields(fitness.provenance)["population"] == population


@pytest.mark.parametrize("population", sorted(get_args(HealthPopulation)))
def test_only_the_run_that_read_none_of_what_it_found_is_refused(
    tmp_path: Path, population: HealthPopulation
) -> None:
    """Both signs of the refusal, over every state the contract can name.

    The expectation is derived from the run's two counters rather than from
    the refused state's name: a run has nothing to contribute exactly when it
    found files and opened none of them. An empty scope is not that run — it
    lost nothing — and it needs the opposite answer *and* a different remedy,
    which is the whole reason the two stopped sharing a word. Deriving the
    expectation from the counters is also what keeps this honest: reading it
    off the same constant the reader branches on would agree with any value of
    that constant, including a wrong one.
    """

    found, analyzed = _COUNTERS_FOR_POPULATION[population]
    nothing_to_believe = found > 0 and analyzed == 0

    fitness = read_run_fitness(_run_document(tmp_path, population=population))

    assert fitness.ingestible is not nothing_to_believe
    assert (fitness.refusal_reason is not None) is nothing_to_believe


# ── refusal: a run that measured nothing ────────────────────────────


def test_run_that_measured_nothing_is_refused_by_ingest(tmp_path: Path) -> None:
    """Zero files read is zero evidence — memory must not absorb it.

    The extractors do not need a single analysed file to speak: module roles
    are built from ``inventory.file_registry``, the list of files that were
    *found*. On a run whose every file failed to open, memory therefore used
    to store "pkg.mod is an analyzed Python module" about a file nobody read,
    at ``active``/``supported``, indistinguishable from the truth.
    """

    root, document = _repo_with_run(tmp_path, population=_NONE_READ)

    with pytest.raises(UnfitAnalysisRunError) as excinfo:
        _ingest(root, document)

    # The refusal must name the state it refused, or an operator cannot tell
    # which of the two absences they are looking at.
    assert _NONE_READ in str(excinfo.value)
    _project, db_path = memory_project_db_paths(root)
    assert not db_path.exists()


def test_refusal_carries_a_next_step_the_operator_can_run(tmp_path: Path) -> None:
    """A typed outcome ships with an executable next step, not just a cause.

    "Your run measured nothing" tells an operator what happened and leaves
    them with no move. The refusal must name the command that shows *why*
    nothing was read and the command to retry once that is fixed, both
    spelled with the real subcommand and flag names.
    """

    root, document = _repo_with_run(tmp_path, population=_NONE_READ)

    with pytest.raises(UnfitAnalysisRunError) as excinfo:
        _ingest(root, document)

    message = str(excinfo.value)
    assert "Next step:" in message, message
    # The analysis command that reports found against analyzed, plus the
    # skip counters that name the cause.
    assert f"codeclone {root}" in message, message
    # The retry, spelled with the flag `memory init` actually takes.
    assert f"codeclone memory init --root {root}" in message, message
    # The substance, not just the two commands: what to look at once the
    # analysis has run. The MCP surface pins this same sentence against its
    # own spelling, so gutting the remedy reds both audiences, not one.
    assert "inventory.files" in message, message


def test_mcp_sync_skips_the_run_that_measured_nothing(tmp_path: Path) -> None:
    """The MCP auto-bootstrap path refuses too, and says why.

    ``_open_memory_store`` bootstraps memory on the first memory call of a
    repository's life, so this path — not ``memory init`` — is where a bad
    run usually lands.
    """

    root, document = _repo_with_run(tmp_path, population=_NONE_READ)
    payload = execute_mcp_memory_sync(
        root_path=root,
        report_document=document,
        trigger="auto",
        run_id="run-unmeasured",
        force=False,
    )

    fitness = _mapping(payload["run_fitness"])
    assert payload["status"] == "skipped"
    # The reason *code* is a separate wire vocabulary from the population
    # enum — MCP consumers switch on this exact string — so it is pinned
    # verbatim rather than composed from the state name it happens to echo.
    assert payload["reason"] == "unfit_run:health_population_unmeasured"
    assert fitness["population"] == _NONE_READ
    assert fitness["ingestible"] is False
    _project, db_path = memory_project_db_paths(root)
    assert not db_path.exists()


# ── the opposite sign: a measured run must not be refused ───────────


def test_fully_measured_run_is_ingested_and_marked_fit(tmp_path: Path) -> None:
    """A run that read everything it found keeps working, and says so."""

    root, document = _repo_with_run(tmp_path, population=_ALL_READ)

    _ingest(root, document)

    provenance = _stored_fitness_provenance(root)
    assert provenance, "a measured run must still ingest records"
    assert set(provenance) == {_expected_mark(baseline="missing", population=_ALL_READ)}


def test_partially_measured_run_is_ingested_and_marked_partial(
    tmp_path: Path,
) -> None:
    """A truncated run is believed about what it read, and marked as truncated.

    Refusing here would throw away real measurements; accepting silently is
    the defect. The record is stored and carries the fact that some of the
    found population was never opened.
    """

    root, document = _repo_with_run(tmp_path, population=_SOME_READ)

    _ingest(root, document)

    assert set(_stored_fitness_provenance(root)) == {
        _expected_mark(baseline="missing", population=_SOME_READ)
    }


# ── the baseline axis ───────────────────────────────────────────────


def test_untrusted_baseline_run_is_ingested_and_marked_untrusted(
    tmp_path: Path,
) -> None:
    """An untrusted baseline downgrades the provenance, it does not refuse.

    A missing or unusable baseline is the ordinary state of a fresh
    repository, and the default sync policy bootstraps memory exactly there.
    Refusing would leave every un-baselined repository with no memory at all,
    which is a worse answer than a marked one.
    """

    root, document = _repo_with_run(
        tmp_path,
        population=_ALL_READ,
        container=single_module_baseline_container(_SCOPE_ID),
        trust=_all_lanes("unavailable", "payload_schema_outdated"),
    )
    assert _mapping(document["baseline"])["state"] == "untrusted"

    _ingest(root, document)

    assert set(_stored_fitness_provenance(root)) == {
        _expected_mark(baseline="untrusted", population=_ALL_READ)
    }


def test_trusted_baseline_run_is_not_marked_untrusted(tmp_path: Path) -> None:
    """The opposite sign of the baseline axis: a good baseline stays good."""

    root, document = _repo_with_run(
        tmp_path,
        population=_ALL_READ,
        container=single_module_baseline_container(_SCOPE_ID),
        trust=_all_lanes("trusted", "compatible"),
    )
    assert _mapping(document["baseline"])["state"] == "trusted"

    _ingest(root, document)

    assert set(_stored_fitness_provenance(root)) == {
        _expected_mark(baseline="trusted", population=_ALL_READ)
    }


def test_refresh_replaces_the_mark_rather_than_stacking_marks(
    tmp_path: Path,
) -> None:
    """One record, one current fitness — a refresh corrects it, not appends.

    The mark is keyed on record identity precisely so that re-ingesting the
    same subject from a worse (or better) run overwrites the claim. A fresh
    id per run would leave one record carrying two different populations with
    no rule for choosing, which is worse than carrying neither.
    """

    root, whole_run = _repo_with_run(tmp_path, population=_ALL_READ)
    _ingest(root, whole_run)
    assert set(_stored_fitness_provenance(root)) == {
        _expected_mark(baseline="missing", population=_ALL_READ)
    }

    _ingest(root, _run_document(root, population=_SOME_READ), refresh=True)

    assert set(_stored_fitness_provenance(root)) == {
        _expected_mark(baseline="missing", population=_SOME_READ)
    }


# ── the provenance has to reach a reader ────────────────────────────


def test_fitness_provenance_reaches_a_memory_consumer(tmp_path: Path) -> None:
    """Stored is not enough — a consumer must be able to read the mark.

    A provenance no retrieval path returns is theatre: the reader would still
    have no way to tell a truncated-run fact from a measured one.
    """

    root, document = _repo_with_run(tmp_path, population=_SOME_READ)
    _ingest(root, document)

    context = memory_application_context(root)
    store = SqliteEngineeringMemoryStore(context.db_path)
    try:
        record = store.list_records_for_project(context.project.id)[0]
        payload = execute_memory_query(
            store,
            context=context,
            root_path=root,
            mode="get",
            record_id=record.id,
        )
    finally:
        store.close()

    evidence = _mapping(payload["payload"])["evidence"]
    assert isinstance(evidence, list)
    marks = [
        str(item["locator"])
        for item in evidence
        if isinstance(item, dict) and item["evidence_kind"] == RUN_FITNESS_EVIDENCE_KIND
    ]
    assert marks == [_expected_mark(baseline="missing", population=_SOME_READ)]
