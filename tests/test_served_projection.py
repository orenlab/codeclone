# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The MCP session retains an INDEX of the sealed report, never the proof.

The full report document is the proof: ``integrity`` digests the whole of
``source_facts`` into the run's identity, so a document that has lost a lane
is an object whose payload disagrees with its own name.  The served projection
is a different object with its own contract -- it indexes the proof and cannot
be published as one.

Every measurement here rides one real analysis of the wire-freeze corpus, so
the payload under the instrument is a payload the product produced, not a
fixture written to make a number come out.  ``deep_size`` is the instrument;
``_reaches`` is the rule.  A ratio alone would survive any value of the thing
it measures, so the size assertion is derived -- what the record keeps equals
what the proof carries minus the lanes the projection withholds -- and the
positive control below proves the instrument read a large payload before any
reduction is claimed.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, fields, is_dataclass
from importlib import import_module
from pathlib import Path
from sys import getsizeof
from typing import Any, cast

import pytest

import codeclone.surfaces.mcp.session as mcp_session_mod
from codeclone.api.served_projection import (
    WITHHELD_PROOF_SECTIONS,
    ServedProjectionError,
)
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest, MCPRunRecord
from codeclone.surfaces.mcp.session import MCPSession

from .conftest import materialize_wire_freeze_corpus

#: Reached by name, never imported: the sealing owner is ring ``r2`` and the
#: ingest owner ``r2p``, while this module is ``r4``, so an import of either
#: would be a boundary violation the architecture ratchet counts. The
#: precedent for reading an owner by name is ``test_finding_groups_owner``.
_REPORT_BUILDER_MODULE = "codeclone.report.document.builder"
_INGEST_EXTRACTORS_MODULE = "codeclone.memory.ingest.extractors"
_MEMORY_MODELS_MODULE = "codeclone.memory.models"

#: Measured on the wire-freeze corpus, 2026-09-03: ``source_facts`` is
#: 175_165 bytes of a 415_232-byte proof.  The floor is the POSITIVE CONTROL:
#: it fails when the harness analysed a tree whose proof carries no observation
#: lanes worth withholding, so a small retained payload afterwards cannot be
#: the harness never having built a large one.
OBSERVATION_LANE_FLOOR_BYTES = 100_000

#: Measured on the same run: the authority IR under ``project_metrics`` is
#: 34_889 bytes.  Same role as the floor above, for the second withheld lane.
AUTHORITY_IR_FLOOR_BYTES = 20_000


def _referents(obj: object) -> Iterator[object]:
    """Everything ``obj`` holds a reference to, one dispatch for both readers.

    The size instrument and the reachability rule ask the same question of an
    object graph and differ only in what they do with the answer, so the walk
    is written once: two copies of this dispatch would drift, and a size that
    counted a field the reachability walk did not visit would report a
    reduction no consumer could rely on.
    """

    if isinstance(obj, Mapping):
        yield from obj.keys()
        yield from obj.values()
        return
    if isinstance(obj, (list, tuple, set, frozenset)):
        yield from obj
        return
    if is_dataclass(obj) and not isinstance(obj, type):
        for field in fields(obj):
            yield getattr(obj, field.name, None)
        return
    for name in getattr(type(obj), "__slots__", ()) or ():
        yield getattr(obj, name, None)
    held = getattr(obj, "__dict__", None)
    if isinstance(held, dict):
        yield held


def _is_leaf(obj: object) -> bool:
    return obj is None or isinstance(
        obj, (str, bytes, bytearray, int, float, complex, bool)
    )


def deep_size(obj: object, seen: set[int] | None = None) -> int:
    """Bytes retained by ``obj`` and everything it holds alive.

    Shared objects are counted once: two references to one string are one
    string in RAM, and a measurement that counted it twice would report a
    reduction that freeing it does not deliver.
    """

    if seen is None:
        seen = set()
    if id(obj) in seen:
        return 0
    seen.add(id(obj))
    size = getsizeof(obj)
    if _is_leaf(obj):
        return size
    return size + sum(deep_size(ref, seen) for ref in _referents(obj))


def _reaches(root: object, target: object) -> bool:
    """Does ``root`` hold ``target`` -- the exact object -- alive?

    Identity, not equality: the question is whether freeing the proof frees
    the lane, and an equal copy retained elsewhere answers that with ``no``.
    """

    wanted = id(target)
    seen: set[int] = set()
    stack: list[object] = [root]
    while stack:
        current = stack.pop()
        if id(current) == wanted:
            return True
        if id(current) in seen:
            continue
        seen.add(id(current))
        if not _is_leaf(current):
            stack.extend(_referents(current))
    return False


@dataclass(frozen=True, slots=True)
class _SealedRun:
    """One real analysis: what the pipeline sealed, and what the parent kept."""

    record: MCPRunRecord
    proof: Mapping[str, object]
    observation_lanes: Mapping[str, object]
    authority_ir: object
    reachability_facts: tuple[Any, ...]


@pytest.fixture(scope="module")
def sealed_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> _SealedRun:
    """Analyse the corpus once and keep both objects side by side."""

    root = tmp_path_factory.mktemp("served_projection_corpus")
    materialize_wire_freeze_corpus(root, post_baseline=True)
    monkeypatch = pytest.MonkeyPatch()
    sealed: list[Mapping[str, object]] = []
    analyses: list[Any] = []
    report_builder_mod = import_module(_REPORT_BUILDER_MODULE)
    # Both producers are read out of their module namespaces rather than
    # imported or attribute-accessed: the session bound ``analyze`` at import
    # time, so the entry on THAT module is the one the run will call, and the
    # sealing owner is a ring this module may not import.
    finalize: Any = vars(report_builder_mod)["finalize_report_document"]
    analyze: Any = vars(mcp_session_mod)["analyze"]

    def _capture_document(*args: object, **kwargs: object) -> Any:
        document = finalize(*args, **kwargs)
        sealed.append(document)
        return document

    def _capture_analysis(*args: object, **kwargs: object) -> Any:
        result = analyze(*args, **kwargs)
        analyses.append(result)
        return result

    try:
        monkeypatch.setattr(
            report_builder_mod, "finalize_report_document", _capture_document
        )
        monkeypatch.setattr(mcp_session_mod, "analyze", _capture_analysis)
        session = MCPSession(history_limit=4)
        session.analyze_repository(MCPAnalysisRequest(root=str(root)))
    finally:
        monkeypatch.undo()
    record = session._runs.records()[-1]
    proof = sealed[-1]
    project_metrics = analyses[-1].project_metrics
    return _SealedRun(
        record=record,
        proof=proof,
        observation_lanes=cast("Mapping[str, object]", proof["source_facts"]),
        authority_ir=project_metrics.semantic_authority,
        reachability_facts=tuple(project_metrics.runtime_reachability),
    )


def test_the_instrument_read_a_proof_that_carries_the_withheld_lanes(
    sealed_run: _SealedRun,
) -> None:
    """POSITIVE CONTROL: the payload this run sealed is genuinely large.

    Read this before any reduction figure below.  A projection that retains
    nothing looks identical to a harness that never built anything, so the
    lanes the projection withholds are measured here first, on the sealed
    proof, and a run whose proof does not carry them fails here rather than
    quietly certifying a reduction of nothing.
    """

    observation_lane_bytes = deep_size(sealed_run.observation_lanes)
    authority_ir_bytes = deep_size(sealed_run.authority_ir)
    assert observation_lane_bytes > OBSERVATION_LANE_FLOOR_BYTES, (
        "the sealed proof carries no observation lanes worth withholding: "
        f"{observation_lane_bytes} bytes"
    )
    assert authority_ir_bytes > AUTHORITY_IR_FLOOR_BYTES, (
        f"the sealed run built no authority IR: {authority_ir_bytes} bytes"
    )
    assert deep_size(sealed_run.proof) > observation_lane_bytes


def test_the_run_store_does_not_retain_the_observation_lanes(
    sealed_run: _SealedRun,
) -> None:
    """The parent holds the index; the lanes it does not serve are released."""

    assert not _reaches(sealed_run.record, sealed_run.observation_lanes), (
        "the retained record still holds the sealed observation lanes alive"
    )


def test_the_run_store_does_not_retain_the_authority_ir(
    sealed_run: _SealedRun,
) -> None:
    """The authority IR has no reader on the record and must not reach it.

    ``metrics.families.semantic_authority`` -- the served surface -- is a
    different object and stays.  This is the IR behind it, whose only claimed
    reader was refuted by measurement.
    """

    assert not _reaches(sealed_run.record, sealed_run.authority_ir), (
        "the retained record still holds the authority IR alive"
    )


def test_the_retained_payload_is_smaller_than_the_proof_it_indexes(
    sealed_run: _SealedRun,
) -> None:
    """The measured consequence of the two rules above.

    Not a tuned ratio: an index that withholds two lanes the proof carries
    cannot be as large as the proof, and a record that kept either lane is
    larger than the proof because it also carries the per-execution facts.
    """

    retained = deep_size(sealed_run.record)
    proof = deep_size(sealed_run.proof)
    assert retained < proof, (
        f"the parent retains {retained} bytes for a {proof}-byte proof"
    )


def test_the_served_sections_are_the_proof_minus_the_withheld_lanes(
    sealed_run: _SealedRun,
) -> None:
    """The derivation, pinned: served == proof - withheld, key for key.

    A ceiling constant would survive any projection; this survives only the
    one projection that keeps every served section byte for byte and drops
    exactly the lanes the contract says it withholds.
    """

    served = sealed_run.record.served_report
    withheld = WITHHELD_PROOF_SECTIONS
    assert set(served) == set(sealed_run.proof) - set(withheld)
    for key in served:
        assert served[key] is sealed_run.proof[key], key


def test_asking_the_projection_for_a_withheld_lane_is_loud(
    sealed_run: _SealedRun,
) -> None:
    """A withheld lane refuses; it never answers ``None``.

    ``as_mapping(document.get(key))`` answers a missing key with an empty
    mapping, so a silent hole here would reach a gate as "no lanes enabled"
    and be published as a verdict.  The projection refuses instead.
    """

    served = sealed_run.record.served_report
    assert "source_facts" not in served
    with pytest.raises(ServedProjectionError):
        served.get("source_facts")
    with pytest.raises(ServedProjectionError):
        served["source_facts"]


def test_the_projection_cannot_be_published_as_a_report(
    sealed_run: _SealedRun,
) -> None:
    """The index is not a document: no serializer will emit it as one."""

    served = sealed_run.record.served_report
    with pytest.raises(TypeError):
        json.dumps(served)


def test_the_serving_contract_carries_what_the_proof_declared(
    sealed_run: _SealedRun,
) -> None:
    """Every fact the contract carries is the proof's own, not a re-derivation."""

    lanes = sealed_run.observation_lanes
    contract = sealed_run.record.served_report.contract
    observation = lanes["observation_contract"]
    assert isinstance(observation, Mapping)
    declared = observation["enabled_lanes"]
    assert isinstance(declared, tuple)
    assert contract.enabled_lanes == declared
    assert contract.design_thresholds == lanes["analysis_contract"]
    integrity = sealed_run.proof["integrity"]
    assert isinstance(integrity, Mapping)
    digests = integrity["digests"]
    assert isinstance(digests, Mapping)
    analysis_facts = digests["analysis_facts"]
    assert isinstance(analysis_facts, Mapping)
    assert contract.analysis_facts_digest == analysis_facts["value"]
    assert contract.report_schema_version == sealed_run.proof["report_schema_version"]


def test_the_declared_thresholds_have_one_producer(
    sealed_run: _SealedRun,
) -> None:
    """``meta.analysis_thresholds`` is the producer; the lane copy derives from it.

    The serving contract carries the design thresholds so a consumer need not
    hold the observation lanes to read them, and memory ingest now reads the
    ``meta`` spelling for the same reason. Both rest on the two spellings being
    one value, which is a claim about the builder -- so it is executed here
    against a real sealed document rather than left in a comment to rot.
    """

    meta = sealed_run.proof["meta"]
    assert isinstance(meta, Mapping)
    declared = meta["analysis_thresholds"]
    assert declared == sealed_run.observation_lanes["analysis_contract"]
    assert sealed_run.record.served_report.contract.design_thresholds == declared
    assert declared


def test_memory_ingest_reads_the_threshold_off_a_served_run(
    tmp_path: Path,
) -> None:
    """Ingest can still name the declared threshold when the run is an index.

    The MCP memory sync hands ingest whatever the session holds, and the
    threshold it quotes used to be addressed inside the observation lanes.
    Reading a withheld lane off the index refuses -- loudly, by design -- so
    this is the pin that the reader was moved to the spelling a served run
    carries, not merely that some document somewhere carries both.
    """

    # A tree carrying one genuinely high-risk function, because this reader
    # consumes only the rows the family classified ``high``: a pin over an
    # empty family would pass for a reader that names no threshold at all.
    root = tmp_path / "tangled"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", "utf-8")
    branches = "\n".join(
        f"    if value == {index}:\n        return {index}" for index in range(40)
    )
    (root / "pkg" / "tangled.py").write_text(
        f"def tangled(value: int) -> int:\n{branches}\n    return -1\n", "utf-8"
    )
    session = MCPSession(history_limit=2)
    session.analyze_repository(MCPAnalysisRequest(root=str(root)))
    served = session._runs.records()[-1].served_report
    extractors = import_module(_INGEST_EXTRACTORS_MODULE)
    models = import_module(_MEMORY_MODELS_MODULE)
    project = models.MemoryProject(
        id="proj-served",
        root=str(tmp_path),
        git_remote=None,
        git_branch=None,
        git_head=None,
        python_tag="cp314",
        created_at_utc="2026-01-01T00:00:00Z",
        updated_at_utc="2026-01-01T00:00:00Z",
    )
    git = extractors.GitProvenance(
        remote=None, branch="main", head="deadbeef", available=True
    )
    batch = extractors.extract_risk_notes(
        project=project,
        root_path=tmp_path,
        report_document=served,
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
    )
    declared = served.contract.design_thresholds
    assert isinstance(declared, Mapping)
    complexity = cast(
        "Mapping[str, object]",
        cast("Mapping[str, object]", declared["design_findings"])["complexity"],
    )
    assert batch.records
    thresholds = {
        record.payload["threshold"]
        for record in batch.records
        if record.payload is not None
        and record.payload.get("risk_kind") == "high_complexity"
    }
    assert thresholds == {complexity["value"]}


def test_the_record_keeps_only_the_reachability_facts_it_serves(
    sealed_run: _SealedRun,
) -> None:
    """``project_metrics`` does not reach the parent; the one fact it serves does."""

    assert not hasattr(sealed_run.record, "project_metrics")
    assert sealed_run.record.reachable_qualnames == frozenset(
        fact.target_qualname for fact in sealed_run.reachability_facts
    )
