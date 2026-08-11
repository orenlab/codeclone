# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Engineering Memory must ask the run whether it was fit to be believed.

A run already carries typed facts about its own fitness — the health
population tri-state (``complete``/``partial``/``unmeasured``) and the
baseline lane verdict projected as ``baseline.state``. Ingest used to consult
neither: a run that opened no file still produced ``status='active'``
``confidence='supported'`` records asserting that modules it never read were
"analyzed", and nothing on the stored record told a later reader which kind of
run had produced it.

Both directions are pinned here, as in ``test_no_data_no_debt``: a refusal
that reached a fully measured run would be the same defect with the opposite
sign, so every guard has a sibling that reds when the refusal over-reaches.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args
from uuid import UUID

import pytest

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
from tests._report_fixtures import (
    build_test_report_document,
    health_family_for_population,
    single_module_baseline_container,
)
from tests.memory_fixtures import (
    git_repo_with_cached_report,
    memory_application_context,
    memory_project_db_paths,
)

_SCOPE_ID = UUID("018f4b8e-5a5f-7d35-9c21-4af5d18df420")
_MODULE_SOURCE = "def f():\n    return 1\n"
_REGISTRY = ["pkg/mod.py"]


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
    found: int,
    analyzed: int,
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
        found=found,
        analyzed=analyzed,
        container=container,
        trust=trust,
    )
    return root, document


def _run_document(
    root: Path,
    *,
    found: int,
    analyzed: int,
    container: BaselineContainerV3 | None = None,
    trust: TrustVector | None = None,
) -> dict[str, object]:
    return build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": str(root.resolve())},
        inventory={
            "file_list": list(_REGISTRY),
            "files": {
                "total_found": found,
                "analyzed": analyzed,
                "skipped": max(0, found - analyzed),
            },
        },
        metrics={
            "health": health_family_for_population(found=found, analyzed=analyzed)
        },
        baseline_container=container,
        baseline_trust=trust,
    )


def _mapping(value: object) -> dict[str, object]:
    """A JSON object from an ``object``-typed payload slot.

    Extracted rather than repeated: ``x = payload[k]`` followed by
    ``assert isinstance(x, dict)`` is the single most common statement pair in
    this test suite, and repeating it here reproduced a block-clone group
    against two unrelated modules.
    """

    assert isinstance(value, dict), f"expected a JSON object, got {type(value)}"
    return value


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


# ── refusal: a run that measured nothing ────────────────────────────


def test_run_that_measured_nothing_is_refused_by_ingest(tmp_path: Path) -> None:
    """Zero files read is zero evidence — memory must not absorb it.

    The extractors do not need a single analysed file to speak: module roles
    are built from ``inventory.file_registry``, the list of files that were
    *found*. On a run whose every file failed to open, memory therefore used
    to store "pkg.mod is an analyzed Python module" about a file nobody read,
    at ``active``/``supported``, indistinguishable from the truth.
    """

    root, document = _repo_with_run(tmp_path, found=2, analyzed=0)
    assert read_run_fitness(document).population == "unmeasured"

    with pytest.raises(UnfitAnalysisRunError) as excinfo:
        _ingest(root, document)

    assert "unmeasured" in str(excinfo.value)
    _project, db_path = memory_project_db_paths(root)
    assert not db_path.exists()


def test_refusal_carries_a_next_step_the_operator_can_run(tmp_path: Path) -> None:
    """A typed outcome ships with an executable next step, not just a cause.

    "Your run measured nothing" tells an operator what happened and leaves
    them with no move. The refusal must name the command that shows *why*
    nothing was read and the command to retry once that is fixed, both
    spelled with the real subcommand and flag names.
    """

    root, document = _repo_with_run(tmp_path, found=2, analyzed=0)

    with pytest.raises(UnfitAnalysisRunError) as excinfo:
        _ingest(root, document)

    message = str(excinfo.value)
    assert "Next step:" in message, message
    # The analysis command that reports found against analyzed, plus the
    # skip counters that name the cause.
    assert f"codeclone {root}" in message, message
    # The retry, spelled with the flag `memory init` actually takes.
    assert f"codeclone memory init --root {root}" in message, message


def test_mcp_sync_skips_the_run_that_measured_nothing(tmp_path: Path) -> None:
    """The MCP auto-bootstrap path refuses too, and says why.

    ``_open_memory_store`` bootstraps memory on the first memory call of a
    repository's life, so this path — not ``memory init`` — is where a bad
    run usually lands.
    """

    root, document = _repo_with_run(tmp_path, found=2, analyzed=0)
    payload = execute_mcp_memory_sync(
        root_path=root,
        report_document=document,
        trigger="auto",
        run_id="run-unmeasured",
        force=False,
    )

    fitness = _mapping(payload["run_fitness"])
    assert payload["status"] == "skipped"
    assert payload["reason"] == "unfit_run:health_population_unmeasured"
    assert fitness["population"] == "unmeasured"
    assert fitness["ingestible"] is False
    _project, db_path = memory_project_db_paths(root)
    assert not db_path.exists()


# ── the opposite sign: a measured run must not be refused ───────────


def test_fully_measured_run_is_ingested_and_marked_fit(tmp_path: Path) -> None:
    """A run that read everything it found keeps working, and says so."""

    root, document = _repo_with_run(tmp_path, found=2, analyzed=2)
    assert read_run_fitness(document).population == "complete"

    _ingest(root, document)

    provenance = _stored_fitness_provenance(root)
    assert provenance, "a measured run must still ingest records"
    assert set(provenance) == {"baseline=missing;population=complete"}


def test_partially_measured_run_is_ingested_and_marked_partial(
    tmp_path: Path,
) -> None:
    """A truncated run is believed about what it read, and marked as truncated.

    Refusing here would throw away real measurements; accepting silently is
    the defect. The record is stored and carries the fact that some of the
    found population was never opened.
    """

    root, document = _repo_with_run(tmp_path, found=2, analyzed=1)
    assert read_run_fitness(document).population == "partial"

    _ingest(root, document)

    assert set(_stored_fitness_provenance(root)) == {
        "baseline=missing;population=partial"
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
        found=2,
        analyzed=2,
        container=single_module_baseline_container(_SCOPE_ID),
        trust=_all_lanes("unavailable", "payload_schema_outdated"),
    )
    assert _mapping(document["baseline"])["state"] == "untrusted"

    _ingest(root, document)

    assert set(_stored_fitness_provenance(root)) == {
        "baseline=untrusted;population=complete"
    }


def test_trusted_baseline_run_is_not_marked_untrusted(tmp_path: Path) -> None:
    """The opposite sign of the baseline axis: a good baseline stays good."""

    root, document = _repo_with_run(
        tmp_path,
        found=2,
        analyzed=2,
        container=single_module_baseline_container(_SCOPE_ID),
        trust=_all_lanes("trusted", "compatible"),
    )
    assert _mapping(document["baseline"])["state"] == "trusted"

    _ingest(root, document)

    assert set(_stored_fitness_provenance(root)) == {
        "baseline=trusted;population=complete"
    }


def test_refresh_replaces_the_mark_rather_than_stacking_marks(
    tmp_path: Path,
) -> None:
    """One record, one current fitness — a refresh corrects it, not appends.

    The mark is keyed on record identity precisely so that re-ingesting the
    same subject from a worse (or better) run overwrites the claim. A fresh
    id per run would leave a record carrying both ``complete`` and ``partial``
    with no rule for choosing, which is worse than carrying neither.
    """

    root, complete = _repo_with_run(tmp_path, found=2, analyzed=2)
    _ingest(root, complete)
    assert set(_stored_fitness_provenance(root)) == {
        "baseline=missing;population=complete"
    }

    _ingest(root, _run_document(root, found=2, analyzed=1), refresh=True)

    assert set(_stored_fitness_provenance(root)) == {
        "baseline=missing;population=partial"
    }


# ── the provenance has to reach a reader ────────────────────────────


def test_fitness_provenance_reaches_a_memory_consumer(tmp_path: Path) -> None:
    """Stored is not enough — a consumer must be able to read the mark.

    A provenance no retrieval path returns is theatre: the reader would still
    have no way to tell a truncated-run fact from a measured one.
    """

    root, document = _repo_with_run(tmp_path, found=2, analyzed=1)
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
    assert marks == ["baseline=missing;population=partial"]
