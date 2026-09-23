# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``check_authority(section="candidates")``, served out of the run store.

The candidate page used to read ``record.served_report`` -- the RAM document --
and nothing else.  It now takes the rights ``search_graph`` and
``get_implementation_context`` hold: ONE resolution of the run store per
request through the same door and the same shadow read, the candidate rows
rebuilt by the one canonical owner of that reconstruction
(``canonical.authority_projection``) out of bounded family reads, the store
never winning an argument with the producer's own rows, and the provenance of
the answer at its root as ``serving``.

The pins, each with its own mutation target:

* **equivalence on a distinguishing population** -- the store's rows are the
  document's rows byte for byte (values, key order, row order) on a corpus
  whose population carries every term the ordering and the class-B columns
  read: five levels (five scores), groups of two to seven producers, two
  source kinds under one score, unresolved producers (``unavailable``),
  ``shadow`` and ``mixed`` statuses, and both values of ``independence`` and
  ``semantic_divergence``.  The census is asserted, not assumed: an
  equivalence on an empty or one-level population proves nothing;
* **serving is observable** -- store-backed, over the identity bridge, memory
  by design, divergent, and unavailable each project their own outcome
  verbatim, and the page beside it is byte-identical to the memory-served
  page (the user-facing contract did not move);
* **one resolution per request**, counted on the ``RunStoreServingOutcome``
  CLASS (wave A's meter), for the first page and a cursor page alike;
* **unavailable is not empty** -- a run whose semantic lane did not execute
  is published with six empty authority families, and the store refuses to
  call that a measured empty candidate population: typed ``unexpressible``,
  memory serves, and the door never hands back an empty tuple;
* **the page is built from the served value** -- an isolated call-site pin,
  because ``_agrees`` makes a store-backed answer byte-identical to memory:
  an end-to-end test cannot tell which of the two the page was cut from.

Everything reaches the engine through the ``r3`` door and the ``r4`` surface;
the corpus tree comes from the shared projection-equivalence helper.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import codeclone.api.run_store_serving as door_mod
import codeclone.surfaces.mcp._run_store_serving as run_store_serving_mod
import codeclone.surfaces.mcp._session_finding_mixin as finding_mixin_mod
from codeclone.api.run_store_serving import RunStoreServingOutcome
from codeclone.surfaces.mcp._authority_candidates import authority_candidate_items
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest, MCPRunRecord
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests._projection_equivalence import write_probe_tree
from tests.test_implementation_context_run_store_serving import (
    _bare_record,
    _enable_store,
    _MechanismMeter,
)

_ROLLOUT_KEYS = (
    "CODECLONE_RUN_STORE_ENABLED",
    "CODECLONE_RUN_STORE_FORCE",
    "CODECLONE_RUN_STORE_PATH",
)

#: The semantic lane is switched on the way a user switches it on.
_LANE_ON = "[tool.codeclone]\nsemantic_authority = true\n"

#: Two identical helpers under ``tests/``: a candidate group whose every
#: producer is test code, so one score carries two source kinds and the
#: ``source_kind`` term of the document order is a distinguishing case.
_TEST_TWIN = """import hashlib


def {name}(value: str, extra: str) -> str:
    first = value.lower()
    second = extra.lower()
    payload = second + first
    return hashlib.md5(payload.encode()).hexdigest()
"""

#: A page size that divides nothing in the population: every boundary and a
#: short final page are walked.
_PAGE = 4


def _write_corpus(root: Path, *, lane: bool) -> None:
    write_probe_tree(root)
    tests = root / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    (tests / "test_twin_a.py").write_text(_TEST_TWIN.format(name="helper_a"), "utf-8")
    (tests / "test_twin_b.py").write_text(_TEST_TWIN.format(name="helper_b"), "utf-8")
    if lane:
        (root / "pyproject.toml").write_text(_LANE_ON, "utf-8")


def _rollout_off(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ROLLOUT_KEYS:
        monkeypatch.delenv(key, raising=False)


def _analyze(root: Path) -> tuple[CodeCloneMCPService, MCPRunRecord]:
    service = CodeCloneMCPService(history_limit=2)
    service.analyze_repository(
        MCPAnalysisRequest(
            root=str(root), respect_pyproject=True, min_loc=1, min_stmt=1
        )
    )
    return service, service._runs.resolve_any_root()


def _memory_items(record: MCPRunRecord) -> list[dict[str, object]]:
    return [dict(item) for item in authority_candidate_items(record.served_report)]


def _wire(items: Sequence[Mapping[str, object]]) -> bytes:
    """Rows as the page serializes them: key order and JSON types included."""
    return json.dumps([dict(item) for item in items], ensure_ascii=False).encode()


def _assert_distinguishing(items: Sequence[Mapping[str, object]]) -> None:
    """Probe validity: the population carries every case the comparison reads."""
    assert items, "an empty population proves nothing"
    assert len({str(row["level"]) for row in items}) >= 3, "one level, one score"
    sizes = {len(row["producers"]) for row in items}  # type: ignore[arg-type]
    assert min(sizes) >= 2 and max(sizes) > 2, sizes
    statuses = {
        str(status)
        for row in items
        for status in row["sink_statuses"]  # type: ignore[attr-defined]
    }
    assert {"unavailable", "shadow", "mixed"} <= statuses, statuses
    assert {row["semantic_divergence"] for row in items} == {True, False}
    assert {row["independence"] for row in items} == {True, False}
    by_score = Counter((row["score"], row["source_kind"]) for row in items)
    scores_with_two_kinds = {
        score
        for score, _kind in by_score
        if len({kind for other, kind in by_score if other == score}) > 1
    }
    assert scores_with_two_kinds, "no score carries two source kinds"


def _served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, lane: bool = True
) -> tuple[CodeCloneMCPService, Path, MCPRunRecord, str]:
    """A published execution with the rollout on; the store run it names."""
    root = tmp_path / "src"
    _write_corpus(root, lane=lane)
    _enable_store(monkeypatch, store=tmp_path / "runs.sqlite3")
    service, record = _analyze(root)
    link = record.execution.run_snapshot_link
    assert link is not None and link.store_run_id, link
    return service, root, record, link.store_run_id


def _served_block(store_run_id: str, *, detail: str = "") -> dict[str, object]:
    block: dict[str, object] = {
        "source": "run_store",
        "reason": "served",
        "store_run_id": store_run_id,
    }
    if detail:
        block["detail"] = detail
    return block


def _walk(service: CodeCloneMCPService, *, root: Path) -> list[dict[str, object]]:
    """Every candidate page the tool serves, cursor-driven, to exhaustion."""
    pages: list[dict[str, object]] = []
    cursor: str | None = None
    while True:
        page = service.check_authority(
            root=str(root), section="candidates", cursor=cursor, page_size=_PAGE
        )
        pages.append(page)
        continuation = page["continuation"]
        assert isinstance(continuation, dict)
        cursor = continuation.get("cursor")
        if cursor is None:
            return pages


def _without_serving(pages: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {key: value for key, value in page.items() if key != "serving"}
        for page in pages
    ]


# -- equivalence on a distinguishing population ------------------------------


def test_the_store_rows_are_the_document_rows_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """legacy (``record.served_report``) == store-served, on the population
    that can tell them apart.

    Mutation targets: the class-B derivation (``score`` from another owner
    than the document's) and the store-side row order -- either moves bytes
    here, and the census above the comparison is what makes a green result
    mean something.
    """
    _service, _root, record, store_run_id = _served(tmp_path, monkeypatch)
    memory = _memory_items(record)
    _assert_distinguishing(memory)
    served, outcome = door_mod.read_run_store_authority_candidates(
        root=record.root, link=record.execution.run_snapshot_link
    )
    assert outcome.as_payload() == _served_block(store_run_id)
    assert served is not None
    assert served.run_id == store_run_id
    assert _wire(served.items) == _wire(memory)


# -- serving observable, same user-facing contract ---------------------------


def test_the_store_backed_pages_are_the_memory_pages_plus_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every page, store-backed, equals the memory-served page but for
    ``serving``: items, totals, continuation, identity and request digests,
    and the cursors themselves.

    The memory walk is the same record with the rollout turned off at the
    request -- memory by design (``store_disabled``), never a fallback.
    Mutation targets: ``serving`` dropped from the response; the store never
    consulted (every answer memory) while the rollout is on.
    """
    service, root, _record, store_run_id = _served(tmp_path, monkeypatch)
    from_store = _walk(service, root=root)
    assert len(from_store) > 2, "the walk must cross page boundaries"
    for page in from_store:
        assert page["serving"] == _served_block(store_run_id)

    _rollout_off(monkeypatch)
    from_memory = _walk(service, root=root)
    for page in from_memory:
        assert page["serving"] == {
            "source": "memory",
            "reason": "store_disabled",
            "store_run_id": store_run_id,
        }
    assert _without_serving(from_store) == _without_serving(from_memory)
    assert json.dumps(_without_serving(from_store)) == json.dumps(
        _without_serving(from_memory)
    )


def test_a_record_that_never_published_is_memory_by_design(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rollout off at analysis and at the request: nothing to read, and the
    answer says so rather than looking like a store that fell back."""
    _rollout_off(monkeypatch)
    root = tmp_path / "src"
    _write_corpus(root, lane=True)
    service, record = _analyze(root)
    answer = service.check_authority(root=str(root), section="candidates")
    assert answer["serving"] == {
        "source": "memory",
        "reason": "not_published",
        "detail": "disabled",
    }
    assert answer["total"] == len(_memory_items(record)) > 0


def test_a_new_record_is_served_over_the_identity_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A record that holds only the report half -- analysed with the rollout
    off by a service that never published -- reaches the snapshot another
    service published through the store's persisted index, and says so.

    Mutation target: the bridge road of the door.
    """
    _publisher, root, published, store_run_id = _served(tmp_path, monkeypatch)
    _rollout_off(monkeypatch)
    reader, record = _analyze(root)
    link = record.execution.run_snapshot_link
    assert link is not None and link.store_run_id == "", link
    assert link.report_run_identity == published.run_id

    _enable_store(monkeypatch, store=tmp_path / "runs.sqlite3")
    meter = _MechanismMeter(monkeypatch)
    answer = reader.check_authority(root=str(root), section="candidates", page_size=50)
    assert answer["serving"] == _served_block(store_run_id, detail="identity_bridge")
    assert meter.reasons == ["served"]
    served_rows: Any = answer["items"]
    assert _wire(served_rows) == _wire(_memory_items(record))


# -- one resolution per request ----------------------------------------------


def test_one_candidate_request_resolves_the_run_store_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First page and cursor page: one door answer each, and it was ``served``.

    Mutation target: a second resolution anywhere on the request path, by
    any import path -- the meter counts outcomes on the class object.
    """
    service, root, record, _store_run_id = _served(tmp_path, monkeypatch)
    meter = _MechanismMeter(monkeypatch)
    first = service.check_authority(
        root=str(root), section="candidates", page_size=_PAGE
    )
    assert meter.reasons == ["served"]
    continuation = first["continuation"]
    assert isinstance(continuation, dict) and continuation["cursor"]

    meter.reset()
    service.check_authority(
        root=str(root),
        section="candidates",
        cursor=str(continuation["cursor"]),
        page_size=_PAGE,
    )
    assert meter.reasons == ["served"]

    # Positive control on the SAME causal path: two resolutions read two.
    meter.reset()
    run_store_serving_mod.served_authority_candidates(record)
    run_store_serving_mod.served_authority_candidates(record)
    assert meter.reasons == ["served", "served"]


# -- the store never wins an argument ----------------------------------------


def _reordered(
    items: tuple[Mapping[str, object], ...],
) -> tuple[Mapping[str, object], ...]:
    return (items[1], items[0], *items[2:])


def _keys_reversed(
    items: tuple[Mapping[str, object], ...],
) -> tuple[Mapping[str, object], ...]:
    first = dict(reversed(list(items[0].items())))
    return (first, *items[1:])


def _bool_as_int(
    items: tuple[Mapping[str, object], ...],
) -> tuple[Mapping[str, object], ...]:
    first = dict(items[0])
    first["independence"] = int(bool(first["independence"]))
    return (first, *items[1:])


def _rescored(
    items: tuple[Mapping[str, object], ...],
) -> tuple[Mapping[str, object], ...]:
    first = dict(items[0])
    first["score"] = int(str(first["score"])) + 1
    return (first, *items[1:])


@pytest.mark.parametrize(
    "disagree",
    [_reordered, _keys_reversed, _bool_as_int, _rescored],
    ids=["row_order", "key_order", "json_type", "class_b_value"],
)
def test_a_disagreeing_store_is_never_served(
    disagree: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shadow read is byte-exact, and memory wins every disagreement.

    Each disagreement is one the page would serialize differently -- a row
    order, a key order, a JSON type (``1`` is not ``true`` on the wire though
    Python calls them equal), a class-B value -- so each must come back
    ``divergent`` with the memory rows, and with the SAME population identity
    the store-backed answer carried: provenance is not identity.

    Mutation targets: disagreement served from the store; an agreement weaker
    than the wire (``==`` over dicts ignores key order and ``True == 1``).
    """
    service, root, record, store_run_id = _served(tmp_path, monkeypatch)
    agreed = service.check_authority(root=str(root), section="candidates", page_size=50)
    assert agreed["serving"] == _served_block(store_run_id)
    served, _outcome = door_mod.read_run_store_authority_candidates(
        root=record.root, link=record.execution.run_snapshot_link
    )
    assert served is not None
    disagreeing = replace(served, items=disagree(served.items))
    assert _wire(disagreeing.items) != _wire(served.items)

    def diverging_door(
        *, root: Path, link: object
    ) -> tuple[Any, RunStoreServingOutcome]:
        return disagreeing, RunStoreServingOutcome(
            source="run_store", reason="served", store_run_id=store_run_id
        )

    monkeypatch.setattr(
        run_store_serving_mod, "read_run_store_authority_candidates", diverging_door
    )
    meter = _MechanismMeter(monkeypatch)
    answer = service.check_authority(root=str(root), section="candidates", page_size=50)
    assert answer["serving"] == {
        "source": "memory",
        "reason": "divergent",
        "store_run_id": store_run_id,
    }
    assert meter.reasons == ["served"]
    served_rows: Any = answer["items"]
    assert _wire(served_rows) == _wire(_memory_items(record))
    assert {key: value for key, value in answer.items() if key != "serving"} == {
        key: value for key, value in agreed.items() if key != "serving"
    }


# -- unavailable is not empty -------------------------------------------------


def test_a_run_whose_lane_did_not_execute_is_refused_not_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Six empty authority families beside ``semantic_authority:
    not_executed`` are not a measured empty candidate population.

    The store IS reached and DOES hold the run -- the served slices of the
    same record come back store-backed, the positive control on the same
    door -- and only the candidate carrier refuses, typed.  Mutation target:
    the population witness; without it the store answers ``()`` and a
    never-measured family is served as "no candidates".
    """
    service, root, record, store_run_id = _served(tmp_path, monkeypatch, lane=False)
    _slices, slice_outcome = run_store_serving_mod.served_slices(record)
    assert slice_outcome.as_payload() == _served_block(store_run_id)

    served, outcome = door_mod.read_run_store_authority_candidates(
        root=record.root, link=record.execution.run_snapshot_link
    )
    assert served is None
    assert (outcome.source, outcome.reason, outcome.store_run_id) == (
        "memory",
        "unexpressible",
        store_run_id,
    )
    assert "semantic_authority" in outcome.detail
    assert "not_executed" in outcome.detail

    answer = service.check_authority(root=str(root), section="candidates")
    assert answer["serving"] == outcome.as_payload()
    assert answer["items"] == [] and answer["total"] == 0


# -- the page is cut from the served value -----------------------------------


def test_the_page_is_cut_from_the_served_value_not_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Isolated call-site pin: the record's memory holds NO candidates, the
    resolution hands back two, and the page carries those two.

    ``_agrees`` makes every store-backed answer byte-identical to memory, so
    no end-to-end test can tell which of the two the page was cut from; the
    choice lives at the call site and is pinned there.  Mutation target:
    ``check_authority`` paging ``record.served_report`` again.
    """
    record = _bare_record(tmp_path, "threadedcandidates01")
    assert _memory_items(record) == []
    service = CodeCloneMCPService(history_limit=2)
    service._runs.register(record)
    rows: tuple[Mapping[str, object], ...] = (
        {"item_kind": "candidate", "candidate_id": "threaded-1"},
        {"item_kind": "candidate", "candidate_id": "threaded-2"},
    )
    outcome = RunStoreServingOutcome(
        source="run_store", reason="served", store_run_id="storerun"
    )
    calls: list[str] = []

    def threaded(given: MCPRunRecord) -> tuple[Any, RunStoreServingOutcome]:
        calls.append(given.run_id)
        return door_mod.ServedAuthorityCandidates(
            run_id="storerun", items=rows
        ), outcome

    monkeypatch.setattr(finding_mixin_mod, "served_authority_candidates", threaded)
    answer = service.check_authority(
        run_id="threadedcandidates01", section="candidates"
    )
    assert calls == ["threadedcandidates01"]
    assert answer["items"] == [dict(row) for row in rows]
    assert answer["total"] == 2
    assert answer["serving"] == outcome.as_payload()
