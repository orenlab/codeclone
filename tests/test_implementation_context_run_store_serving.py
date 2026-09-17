# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""One implementation-context request, one run-store resolution.

``_relationship_indexes``, ``_relationship_digest_records`` and
``_unit_location_index`` used to read ``record.relationship_facts`` /
``record.unit_inventory`` directly, bypassing ``served_slices()`` -- the same
resolver ``search_graph``'s ``query=`` shape already serves through
(``codeclone/surfaces/mcp/_run_store_serving.py``).  This module pins the fix
at two levels.

**Isolated reverse pins**, one per call site.  Each hands the helper a record
whose own memory is EMPTY together with a threaded ``ServedRunSlices`` that
carries the analyzed facts, so the threaded value is the only possible source
of a non-empty answer; reverting one call site turns exactly that test red
without touching the others.  An end-to-end-only test would stay green with
one of them silently unfixed, because the response is built from all of them
together -- the "success masked by a sibling" hollow-test class.

Two of those pins sit on the CALL SITE rather than on ``_relationship_indexes``
itself, and that is measured rather than stylistic: ``MCPRunRecord`` and
``ServedRunSlices`` both carry a ``relationship_facts`` attribute, so a unit
test that hands the index function a ``ServedRunSlices`` stays GREEN against
the unfixed ``for facts in record.relationship_facts`` -- structural typing
makes the two objects interchangeable inside that body, and the mutant
survives.  The call site is where the choice actually lives.

**One resolution-count pin**, measured at the mechanism.  The obvious
instrument -- wrapping the name ``read_run_store_slices`` in the consumer
module's namespace -- counts an ALIAS, not a resolution: a consumer reaching
the same door through ``from codeclone.api.run_store_serving import
read_run_store_slices`` captures the function OBJECT at import time and never
looks the name up again, so it is invisible to any patch of a module
attribute, and a second, entirely legal resolution survives such a pin.  That
blindness is itself measured here, in
``test_the_alias_instrument_is_blind_where_the_mechanism_is_not``.  The
instrument used instead counts the door's own typed answers on the
``RunStoreServingOutcome`` CLASS -- one object, whatever name reaches it, and
one answer per invocation of the door -- so the pin is keyed on the edge and
not on a spelling.  Enumerating today's aliases would only move the hole to
the next one.

``served_slices()`` returns the stored slices only when they already equal the
record's memory (``_agrees``), so mutating the on-disk store can never make
the served answer *move* -- it forces fallback instead.  A store-mutation
reverse probe is structurally vacuous here, which is why the isolated pins
thread the value in directly.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import codeclone.surfaces.mcp._implementation_context as mcp_context_projection_mod
import codeclone.surfaces.mcp._run_store_serving as run_store_serving_mod
from codeclone.api.run_store_serving import (
    SERVING_REASON_DIVERGENT,
    RunStoreServingOutcome,
    ServedRunSlices,
    read_run_store_slices,
)
from codeclone.surfaces.mcp._run_store_serving import memory_slices
from codeclone.surfaces.mcp._session_shared import (
    ExecutionEvent,
    build_served_projection,
    mint_execution_event_id,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest, MCPRunRecord


def _write_two_file_corpus(root: Path) -> None:
    """``pkg.caller:run`` calls ``pkg.callee:target`` through an import.

    The smallest population that carries every distinguishing case these
    pins need: two analyzed units, one RESOLVED production call edge, and
    one tracked module import.
    """
    pkg = root / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", "utf-8")
    (pkg / "callee.py").write_text("def target() -> int:\n    return 1\n", "utf-8")
    (pkg / "caller.py").write_text(
        "from pkg.callee import target\n\n\ndef run() -> int:\n    return target()\n",
        "utf-8",
    )


@pytest.fixture(scope="module")
def analyzed_slices(tmp_path_factory: pytest.TempPathFactory) -> ServedRunSlices:
    """The producer's real answer for that corpus, in served shape.

    Real producer output rather than a hand-built sentinel: the isolated pins
    below assert against facts the analyzer actually emits, so a projection
    that silently stops matching the producer reddens here too.
    """
    root = tmp_path_factory.mktemp("implctx-slices") / "src"
    _write_two_file_corpus(root)
    service = CodeCloneMCPService(history_limit=2)
    service.analyze_repository(
        MCPAnalysisRequest(
            root=str(root), respect_pyproject=False, min_loc=1, min_stmt=1
        )
    )
    slices = memory_slices(service._runs.resolve_any_root())
    assert slices.unit_inventory and slices.relationship_facts
    return slices


def _bare_record(root: Path, run_id: str) -> MCPRunRecord:
    """A record with EMPTY memory slices and no run-store publication.

    The isolated pins' subject: only the ``ServedRunSlices`` threaded into
    the helper under test can populate anything.
    """
    return MCPRunRecord(
        run_id=run_id,
        root=root,
        request=MCPAnalysisRequest(root=str(root), respect_pyproject=False),
        comparison_settings=(),
        served_report=build_served_projection({}),
        summary={"run_id": run_id, "health": {"score": 0, "grade": "N/A"}},
        changed_paths=(),
        changed_projection=None,
        func_clones_count=0,
        block_clones_count=0,
        reachable_qualnames=frozenset(),
        coverage_join=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
        execution=ExecutionEvent(
            execution_event_id=mint_execution_event_id(),
            root=root,
            semantic_report_id=run_id,
        ),
    )


# -- isolated reverse pins: one call site, one mutation target each ---------


def test_call_context_reads_the_threaded_slices(
    tmp_path: Path, analyzed_slices: ServedRunSlices
) -> None:
    """Mutation target: ``_project_call_context``'s ``_relationship_indexes(slices)``.

    Put ``record`` back here and the callers facet empties: this record's
    memory is empty and only the threaded slices carry the call edge.
    """
    record = _bare_record(tmp_path, "relidx0000000001")
    assert record.relationship_facts == ()
    call_context = mcp_context_projection_mod._project_call_context(
        record=record,
        slices=analyzed_slices,
        subject_qualnames=frozenset({"pkg.callee:target"}),
        include_set=frozenset({"callers"}),
        budget=mcp_context_projection_mod._EntryBudget(limit=20, remaining=20),
    )
    items = call_context["callers"]
    assert isinstance(items, list)
    assert [row["source_qualname"] for row in items] == ["pkg.caller:run"]


def test_contract_path_callers_read_the_threaded_slices(
    tmp_path: Path, analyzed_slices: ServedRunSlices
) -> None:
    """Mutation target: ``_project_contracts``'s ``_relationship_indexes(slices)``.

    The second call site of the same index, reached only through a D18
    memory anchor (``module_role`` / ``role_kind=persistence``).  A test that
    merely asserts the facet KEY is present passes with an empty list, so the
    row itself is asserted: swap ``slices`` back for ``record`` and it goes.
    """
    record = _bare_record(tmp_path, "ctrpath0000000001")
    assert record.relationship_facts == ()
    contracts = mcp_context_projection_mod._project_contracts(
        record=record,
        slices=analyzed_slices,
        subject_paths=("pkg/callee.py",),
        subject_qualnames=frozenset({"pkg.callee:target"}),
        memory_result={
            "records": [
                {"type": "module_role", "payload": {"role_kind": "persistence"}}
            ]
        },
        include_set=frozenset({"persistence_path_callers"}),
        budget=mcp_context_projection_mod._EntryBudget(limit=20, remaining=20),
    )
    items = contracts["persistence_path_callers"]
    assert isinstance(items, list)
    assert [row["source_qualname"] for row in items] == ["pkg.caller:run"]


def test_relationship_digest_records_reads_the_threaded_slices(
    tmp_path: Path, analyzed_slices: ServedRunSlices
) -> None:
    """Mutation target: ``_relationship_digest_records``'s ``for facts in ...``.

    This helper takes BOTH objects, so the mutation is expressible in its own
    body and dies here.  The root still comes from the record: relationship
    paths are absolute in the slice and repo-relative in the digest.
    """
    record = _bare_record(tmp_path, "reldig0000000001")
    assert record.relationship_facts == ()
    rows = mcp_context_projection_mod._relationship_digest_records(
        record, slices=analyzed_slices
    )
    assert [
        (row["source_qualname"], row["target_qualname"], row["resolution_rule"])
        for row in rows
    ] == [("pkg.caller:run", "pkg.callee:target", "imported_symbol")]


def test_unit_location_index_reads_the_threaded_slices(
    tmp_path: Path, analyzed_slices: ServedRunSlices
) -> None:
    """Mutation target: ``_unit_location_index``'s ``for location in ...``.

    The api_surface half of this function stays on ``record.served_report``
    (it is not one of the three off-report slices) and is empty here, so only
    the threaded rows can appear.
    """
    record = _bare_record(tmp_path, "unitidx0000000001")
    assert record.unit_inventory == ()
    rows = mcp_context_projection_mod._unit_location_index(
        record, slices=analyzed_slices
    )
    assert [(row["qualname"], row["path"], row["source"]) for row in rows] == [
        ("pkg.callee:target", "pkg/callee.py", "unit_inventory"),
        ("pkg.caller:run", "pkg/caller.py", "unit_inventory"),
    ]


# -- one request, one resolution -------------------------------------------


def _enable_store(monkeypatch: pytest.MonkeyPatch, *, store: Path) -> None:
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(store))


class _MechanismMeter:
    """Every run-store resolution one request made, in order, by reason.

    The count is taken on the ``RunStoreServingOutcome`` CLASS OBJECT, which
    the process holds exactly one of, so every binding that reaches the door
    is counted: the consumer module's re-import, the owner module's own name,
    and any future alias alike.  That is what makes this a pin on the edge
    rather than on a spelling -- see the module docstring and
    ``test_the_alias_instrument_is_blind_where_the_mechanism_is_not``.

    The door mints exactly one outcome per invocation, on every branch
    (``codeclone/api/run_store_serving.py``: ``_memory`` and the served
    return, the only two construction sites in the package).  ``divergent``
    is excluded because the door never mints it: it is the shadow-comparison
    layer's verdict, produced by ``replace()`` on an outcome the door already
    returned, so counting it would count one resolution twice.

    ``reasons == ["served"]`` therefore says two things at once: the store
    was resolved exactly once, and that one resolution physically read the
    store -- ``served`` is the single store-backed reason the outcome
    contract admits, enforced in ``RunStoreServingOutcome.__post_init__``.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.reasons: list[str] = []
        real = RunStoreServingOutcome.__post_init__

        def counting(inner: RunStoreServingOutcome) -> None:
            real(inner)
            if inner.reason != SERVING_REASON_DIVERGENT:
                self.reasons.append(inner.reason)

        monkeypatch.setattr(RunStoreServingOutcome, "__post_init__", counting)

    def reset(self) -> None:
        self.reasons.clear()


def _served_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[CodeCloneMCPService, Path, MCPRunRecord, dict[str, object], ServedRunSlices]:
    """A published execution, with its probe validity already proven.

    The precondition is part of the fixture and not of each test, so no count
    below can be read before it holds: the resolver REACHED the store and
    SERVED it (not a fallback), and the population carries the distinguishing
    cases the shapes read -- a resolvable unit and a resolved call edge.
    """
    root = tmp_path / "store"
    _write_two_file_corpus(root)
    _enable_store(monkeypatch, store=tmp_path / "runs.sqlite3")
    service = CodeCloneMCPService(history_limit=2)
    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(root), respect_pyproject=False, min_loc=1, min_stmt=1
        )
    )
    record = service._runs.resolve_any_root()
    slices, outcome = run_store_serving_mod.served_slices(record)
    assert (outcome.source, outcome.reason) == ("run_store", "served")
    assert slices.unit_inventory, "the symbols shape needs a resolvable unit"
    assert slices.relationship_facts, "the callers facet needs a resolved call edge"
    return service, root, record, summary, slices


def test_one_request_resolves_the_run_store_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every ``get_implementation_context`` shape resolves the store ONCE.

    Mutation target: the threading itself.  Give any consumer back its own
    resolution -- ``_relationship_indexes``, ``_relationship_digest_records``,
    ``_unit_location_index`` or ``resolve_context_symbols`` calling the door
    for itself, by ANY import path -- and the count for the shape that reaches
    it rises above one.

    Two harms this pins, not one: the ``run_store_serving_*`` counters are a
    per-request rollout instrument (a rollout is real only while divergent and
    fallback read zero against a non-zero store_backed), and
    ``_context_artifact_digest`` promises to bind the facts the response was
    built from -- a promise several independent reads can only hope to keep.
    """
    service, root, record, _summary, _slices = _served_run(tmp_path, monkeypatch)
    meter = _MechanismMeter(monkeypatch)
    shapes: dict[str, dict[str, object]] = {
        "paths": {"paths": ["pkg/callee.py"], "include": ["callers"]},
        "symbols": {"symbols": ["pkg.callee:target"], "include": ["callers"]},
        "query": {"query": "target"},
    }
    for label, kwargs in shapes.items():
        meter.reset()
        answer = service.get_implementation_context(root=str(root), **kwargs)
        assert answer["status"] == "ok", label
        assert meter.reasons == ["served"], (label, meter.reasons)

    # Positive control on the SAME causal path: the meter is not an
    # instrument that can only ever report one.  Two resolutions read two.
    meter.reset()
    run_store_serving_mod.served_slices(record)
    run_store_serving_mod.served_slices(record)
    assert meter.reasons == ["served", "served"]


def test_the_alias_instrument_is_blind_where_the_mechanism_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The accounting behind the pin above, pinned so it cannot be undone.

    A resolution reached through ``from codeclone.api.run_store_serving import
    read_run_store_slices`` -- the owner door, bound at import time -- is a
    real resolution and is legal.  An instrument that wraps the consumer
    module's ``read_run_store_slices`` attribute cannot see it, because the
    caller never looks that name up.  The mechanism instrument does see it.

    Both halves carry their own control: the alias instrument is then shown
    to count a call that DOES go through the alias, so its zero above is
    blindness and not a dead wrapper.
    """
    _service, _root, record, _summary, _slices = _served_run(tmp_path, monkeypatch)
    alias_calls: list[str] = []
    # The consumer module's ``read_run_store_slices`` IS the owner's function
    # object -- an import binds the object, not a view of the name.  That
    # identity is what makes the alias hole possible, so it is asserted
    # rather than assumed.  Read out of the consumer's own namespace mapping:
    # the name is a re-import there, not an export.
    assert vars(run_store_serving_mod)["read_run_store_slices"] is read_run_store_slices
    real_door: Any = read_run_store_slices

    def counting_alias(
        *, root: Path, link: object
    ) -> tuple[ServedRunSlices | None, RunStoreServingOutcome]:
        alias_calls.append("door")
        result: tuple[ServedRunSlices | None, RunStoreServingOutcome] = real_door(
            root=root, link=link
        )
        return result

    monkeypatch.setattr(run_store_serving_mod, "read_run_store_slices", counting_alias)
    meter = _MechanismMeter(monkeypatch)

    # A second, legal resolution through the OWNER module's own binding.
    read_run_store_slices(root=record.root, link=record.execution.run_snapshot_link)
    assert alias_calls == [], "the alias instrument cannot see the owner door"
    assert meter.reasons == ["served"]

    # Positive control for the alias instrument: it is live, and counts what
    # actually passes through the alias.
    run_store_serving_mod.served_slices(record)
    assert alias_calls == ["door"]
    assert meter.reasons == ["served", "served"]


def test_a_divergent_answer_is_still_one_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The meter's ``divergent`` exclusion has an input that reaches it.

    ``divergent`` is the shadow-comparison layer's verdict, minted by
    ``replace()`` on an outcome the door has ALREADY returned -- so counting
    it would read one resolution as two.  A guard no input can reach is
    theatre, so this drives a real disagreement through ``served_slices()``
    and pins that the count stays at one.  Remove the exclusion and this test
    reads ``["served", "divergent"]``.
    """
    _service, _root, record, _summary, stored = _served_run(tmp_path, monkeypatch)
    disagreeing = replace(stored, unit_inventory=())
    store_run_id = record.execution.run_snapshot_link.store_run_id  # type: ignore[union-attr]

    def diverging_door(
        *, root: Path, link: object
    ) -> tuple[ServedRunSlices, RunStoreServingOutcome]:
        # Minted INSIDE the door, as the real one mints it: this is the one
        # answer the resolution produced.
        return disagreeing, RunStoreServingOutcome(
            source="run_store", reason="served", store_run_id=store_run_id
        )

    monkeypatch.setattr(run_store_serving_mod, "read_run_store_slices", diverging_door)
    meter = _MechanismMeter(monkeypatch)
    served, verdict = run_store_serving_mod.served_slices(record)
    assert verdict.reason == SERVING_REASON_DIVERGENT
    assert served.unit_inventory, "memory wins the argument, so rows come back"
    assert meter.reasons == ["served"]


# -- real, end-to-end forward equivalence -----------------------------------


def _without_run_identity_digests(payload: dict[str, object]) -> dict[str, object]:
    """Strip the three fields traced to run IDENTITY rather than content.

    ``analysis.context_artifact_digest`` -> ``analysis.context_projection_digest``
    -> ``context_governance.response.projection_digest`` is a hash chain that
    binds run-scoped material; each differs whenever two records carry
    different run_ids regardless of content.
    """
    clone = copy.deepcopy(payload)
    analysis = clone.get("analysis")
    if isinstance(analysis, dict):
        analysis.pop("context_artifact_digest", None)
        analysis.pop("context_projection_digest", None)
    governance = clone.get("context_governance")
    if isinstance(governance, dict):
        response = governance.get("response")
        if isinstance(response, dict):
            response.pop("projection_digest", None)
    return clone


def test_paths_shape_is_served_from_the_run_store_and_matches_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real store-backed path, not a monkeypatch.

    With the store enabled the execution publishes, the default (``paths=``)
    shape is answered OUT OF THE STORE, and the content matches the
    memory-served answer field for field (excluding the run-identity digest
    chain), on a population that contains the distinguishing case: a resolved
    call edge.
    """
    _write_two_file_corpus(tmp_path / "memory")

    monkeypatch.delenv("CODECLONE_RUN_STORE_ENABLED", raising=False)
    monkeypatch.delenv("CODECLONE_RUN_STORE_FORCE", raising=False)
    monkeypatch.delenv("CODECLONE_RUN_STORE_PATH", raising=False)
    memory_service = CodeCloneMCPService(history_limit=2)
    memory_summary = memory_service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path / "memory"),
            respect_pyproject=False,
            min_loc=1,
            min_stmt=1,
        )
    )

    store_service, store_root, store_record, store_summary, _slices = _served_run(
        tmp_path, monkeypatch
    )
    assert memory_summary["run_id"] == store_summary["run_id"]
    link = store_record.execution.run_snapshot_link
    assert link is not None and link.store_run_id, link

    memory_answer = memory_service.get_implementation_context(
        root=str(tmp_path / "memory"), paths=["pkg/callee.py"], include=["callers"]
    )
    store_answer = store_service.get_implementation_context(
        root=str(store_root), paths=["pkg/callee.py"], include=["callers"]
    )
    assert memory_answer["status"] == store_answer["status"] == "ok"
    call_context = memory_answer["call_context"]
    assert isinstance(call_context, dict)
    assert call_context["callers"], "the population must contain a caller"

    assert _without_run_identity_digests(store_answer) == _without_run_identity_digests(
        memory_answer
    )
