# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The identity bridge: store analysis snapshot <-> evaluated report identity.

RULING-2026-08-24 §7 keeps the two identity domains apart -- no shared name,
no foreign key -- and makes the production bridge wait for the report's
identity generation.  Generation 2 landed, so the relation can be stated.

What is measured here, and why each property needs its own pin:

* The two domains address DIFFERENT things, and the cardinality proves it.
  One store record answered two report identities on one measured corpus
  (same analysis, two gate thresholds), and both zero directions are
  reachable today: a gate-only run stores a snapshot no document evaluates,
  and a flag-off run evaluates a document no snapshot backs.
* A wrong pair is invisible at both endpoints.  ``read_run`` re-derives a
  run id from the run's own scope and membership, so a wrong-but-real run
  verifies perfectly; the falsehood lives in the RELATION, which neither
  endpoint checks.  The bridge therefore carries the store's own scope
  receipt and refuses a pair whose report does not re-derive it.
* Equality of two readings proves consistency, not correctness: both sides
  of that comparison descend from one analyzed-file set, so a mutation of
  the common owner moves both and the equality holds.  ``test_scope_receipt_
  known_answer`` is the independent value pin that such a mutation cannot
  survive.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from codeclone.canonical.identity import FileId
from codeclone.canonical.store import analysis_scope_digest
from codeclone.core._types import ReportArtifacts
from codeclone.core.canonical_snapshot import (
    RunSnapshotBridgeError,
    bridge_run_snapshot,
    report_scope_receipt,
)
from codeclone.models import (
    RUN_SNAPSHOT_LINK_LINKED,
    RUN_SNAPSHOT_LINK_UNEVALUATED,
    RUN_SNAPSHOT_LINK_UNPUBLISHED,
    RUN_SNAPSHOT_PUBLICATION_DISABLED,
    RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
    RUN_SNAPSHOT_PUBLICATION_REFUSED,
    RunSnapshotLink,
    RunSnapshotPublication,
)


def _document(paths: list[str], identity: str) -> dict[str, object]:
    """The two fields the bridge reads out of a report document."""

    return {
        "source_facts": {"analysis_scope": [{"path": path} for path in paths]},
        "integrity": {"digests": {"evaluation": {"value": identity}}},
    }


def _published(scope_digest: str, run_id: str = "a" * 64) -> RunSnapshotPublication:
    return RunSnapshotPublication(
        outcome=RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
        admissible=True,
        target="canonical",
        run_id=run_id,
        generation=1,
        analysis_scope_digest=scope_digest,
    )


_PATHS = ["pkg/a.py", "pkg/b.py"]


# ---------------------------------------------------------------------------
# The independent value pin.  Everything else in this module compares two
# readings that descend from one analyzed-file set; this one pins the VALUE,
# so a mutation of the common owner (the sort, the domain separator, the
# payload encoding) reds here even while every equality above stays green.
# ---------------------------------------------------------------------------


#: Six paths, not two.  Measured 2026-09-01: on a two-path corpus the
#: frozenset's iteration order REVERSED is the sorted order, so a mutant that
#: drops the sort is equivalent there and survives -- which is exactly what
#: happened to the first version of this pin (M3, survive_narrow).  Six makes
#: the coincidence 1-in-720 and the harness aggregates several hash seeds.
_SCOPE_PATHS = [f"pkg/mod_{index}.py" for index in range(6)]


def test_scope_receipt_known_answer() -> None:
    """The store's scope receipt, pinned by its rule AND by its value.

    Both halves are load-bearing and neither is enough alone:

    * The DERIVATION half re-derives ``sha256(domain || canonical(sorted
      paths))`` so the pin holds the rule rather than a magic constant.  On
      its own it is blind to a change that moves the rule, because the test
      moves with it.
    * The VALUE half compares the PRODUCTION function's output against the
      measured literal.  This is the half that survives a mutation of the
      common owner: every other comparison in this module has both of its
      sides descend from one analyzed-file set, so corrupting that owner
      moves both sides together and the equality holds while the answer is
      wrong.  This assertion has only one side that can move.
    """

    from codeclone.canonical.store import _DOMAIN_SCOPE, _payload_bytes

    actual = analysis_scope_digest(frozenset(FileId(p) for p in _SCOPE_PATHS))
    assert (
        actual
        == hashlib.sha256(
            _DOMAIN_SCOPE + _payload_bytes(sorted(_SCOPE_PATHS))
        ).hexdigest()
    )
    # The domain separator carries ``STORAGE_SCHEMA_REVISION``, so this
    # literal moves exactly when that constant moves and never otherwise --
    # which is what makes it a known ANSWER rather than a snapshot.  It was
    # 23f3aa7e… under revision "0"; re-derived outside this process for
    # revision "1" from the stated basis alone (sha256 of
    # b"cc-run-store:1\x00scope\x00" || the compact JSON of the sorted
    # paths), the same recipe reproduces 23f3aa7e… when "1" is put back to
    # "0".  The RULE half above did not move at all.
    assert actual == (
        "05d281af57f692c704951d7f9ae94d302af25d6f83e59e9f4f77b411bbf6302f"
    )


def test_report_scope_receipt_reads_the_analysis_scope() -> None:
    """The report's own analyzed scope re-derives the store's receipt."""

    document = _document(_PATHS, "e" * 64)
    assert report_scope_receipt(document) == analysis_scope_digest(
        frozenset(FileId(p) for p in _PATHS)
    )


def test_report_scope_receipt_ignores_the_found_file_registry() -> None:
    """The registry is a DIFFERENT universe, and the receipt must not read it.

    Measured on the probe corpus 2026-09-01: ``inventory.file_registry`` is
    the found list anchored on the scan root (7 rows, ``canon.py``);
    ``source_facts.analysis_scope`` is the analyzed set anchored on the
    analysis root (6 rows, ``pkg/canon.py``), and only the latter is the
    universe the store digests.  They coincide on a single-package corpus
    with nothing skipped, which is exactly why an agreeing sample proves
    nothing -- this document makes them disagree on purpose.
    """

    document = _document(_PATHS, "e" * 64)
    document["inventory"] = {
        "file_registry": {"encoding": "utf-8", "items": ["a.py", "b.py", "skipped.py"]}
    }
    assert report_scope_receipt(document) == analysis_scope_digest(
        frozenset(FileId(p) for p in _PATHS)
    )


# ---------------------------------------------------------------------------
# The relation itself
# ---------------------------------------------------------------------------


def test_bridge_links_the_pair_it_was_given() -> None:
    scope = analysis_scope_digest(frozenset(FileId(p) for p in _PATHS))
    link = bridge_run_snapshot(
        publication=_published(scope),
        report_document=_document(_PATHS, "e" * 64),
    )
    assert link.state == RUN_SNAPSHOT_LINK_LINKED
    assert link.store_run_id == "a" * 64
    assert link.report_run_identity == "e" * 64
    assert link.analysis_scope_digest == scope


def test_bridge_refuses_a_pair_whose_scope_disagrees() -> None:
    """GUARD 1 -- the wrong pair.

    Reachable input: a publication whose stored scope receipt is not the
    one the report's own registry re-derives.  This is exactly the shape a
    mis-addressed bridge produces, and neither endpoint can detect it
    alone.
    """

    other = analysis_scope_digest(frozenset({FileId("pkg/other.py")}))
    with pytest.raises(RunSnapshotBridgeError, match="scope receipt"):
        bridge_run_snapshot(
            publication=_published(other),
            report_document=_document(_PATHS, "e" * 64),
        )


def test_bridge_refuses_a_report_that_carries_no_identity() -> None:
    """GUARD 2 -- the lost pair.

    Reachable input: a stored publication and a finalized document that
    names no run.  Degrading this to ``unevaluated`` would spell "no
    document was produced" over "a document was produced and the bridge
    dropped it", which is the absence-collapse the run-identity reader
    already refuses on its own side.
    """

    document = _document(_PATHS, "e" * 64)
    document["integrity"] = {"digests": {}}
    scope = analysis_scope_digest(frozenset(FileId(p) for p in _PATHS))
    with pytest.raises(RunSnapshotBridgeError, match="no run identity"):
        bridge_run_snapshot(publication=_published(scope), report_document=document)


# ---------------------------------------------------------------------------
# The two measured zeros.  Both are facts, not noise, so both get a state.
# ---------------------------------------------------------------------------


def test_bridge_expresses_the_unpublished_zero() -> None:
    """A report with no snapshot behind it: the flag-off default."""

    link = bridge_run_snapshot(
        publication=RunSnapshotPublication(
            outcome=RUN_SNAPSHOT_PUBLICATION_DISABLED, admissible=False
        ),
        report_document=_document(_PATHS, "e" * 64),
    )
    assert link.state == RUN_SNAPSHOT_LINK_UNPUBLISHED
    assert link.store_run_id == ""
    assert link.report_run_identity == "e" * 64


def test_bridge_expresses_the_unevaluated_zero() -> None:
    """A snapshot no document evaluated: the gate-only run."""

    scope = analysis_scope_digest(frozenset(FileId(p) for p in _PATHS))
    link = bridge_run_snapshot(publication=_published(scope), report_document=None)
    assert link.state == RUN_SNAPSHOT_LINK_UNEVALUATED
    assert link.store_run_id == "a" * 64
    assert link.report_run_identity == ""


def test_bridge_keeps_the_refusal_reason() -> None:
    """A refused publish is unpublished WITH its reason, not a bare zero."""

    link = bridge_run_snapshot(
        publication=RunSnapshotPublication(
            outcome=RUN_SNAPSHOT_PUBLICATION_REFUSED,
            admissible=False,
            reason="the snapshot carries no population",
        ),
        report_document=_document(_PATHS, "e" * 64),
    )
    assert link.state == RUN_SNAPSHOT_LINK_UNPUBLISHED
    assert link.outcome == RUN_SNAPSHOT_PUBLICATION_REFUSED


# ---------------------------------------------------------------------------
# Model invariants: the relation cannot be half-stated.
# ---------------------------------------------------------------------------


def test_stored_publication_must_carry_its_scope_receipt() -> None:
    with pytest.raises(ValueError, match="scope receipt"):
        RunSnapshotPublication(
            outcome=RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
            admissible=True,
            target="canonical",
            run_id="a" * 64,
            generation=1,
        )


def test_unstored_publication_carries_no_scope_receipt() -> None:
    with pytest.raises(ValueError, match="scope receipt"):
        RunSnapshotPublication(
            outcome=RUN_SNAPSHOT_PUBLICATION_DISABLED,
            admissible=False,
            analysis_scope_digest="a" * 64,
        )


def test_linked_state_needs_both_addresses() -> None:
    with pytest.raises(ValueError, match="both addresses"):
        RunSnapshotLink(
            state=RUN_SNAPSHOT_LINK_LINKED,
            outcome=RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
            store_run_id="a" * 64,
            analysis_scope_digest="b" * 64,
            report_run_identity="",
        )


# ---------------------------------------------------------------------------
# End to end, on a real published run.
# ---------------------------------------------------------------------------


def test_bridge_links_a_real_published_run(tmp_path: Path) -> None:
    from tests._projection_equivalence import build_corpus

    tree = tmp_path / "tree"
    tree.mkdir()
    corpus = build_corpus(tree, store_path=tmp_path / "runs.sqlite3")
    document = dict(corpus.document)

    scope = report_scope_receipt(document)
    link = bridge_run_snapshot(
        publication=_published(scope, run_id=corpus.run_id),
        report_document=document,
    )
    assert link.state == RUN_SNAPSHOT_LINK_LINKED
    assert link.store_run_id == corpus.run_id
    # The two addresses are different values from different domains: the
    # ruling's "no shared name" is a measurable property, not a comment.
    assert link.store_run_id != link.report_run_identity


# ---------------------------------------------------------------------------
# End to end through the real producer edge.
#
# Without these the bridge would be a function nobody calls: dropping
# ``run_snapshot_link=`` from the ``ReportArtifacts`` in ``core/reporting.py``
# leaves every unit test above green.  Each measured cardinality gets its own
# reachable input here.
# ---------------------------------------------------------------------------


def _report_case(
    root: Path,
    *,
    json_out: Path | None,
    store: Path | None,
    fail_complexity: int = -1,
) -> ReportArtifacts:
    """Drive the real pipeline to the producer edge, one rollout state."""

    from argparse import Namespace

    import codeclone.core.discovery as core_discovery
    from codeclone.analysis.normalizer import NormalizationConfig
    from codeclone.cache.store import Cache
    from codeclone.core._types import BootstrapResult, OutputPaths
    from codeclone.core.parallelism import process
    from codeclone.core.pipeline import analyze
    from codeclone.core.reporting import report
    from tests._projection_equivalence import write_probe_tree

    write_probe_tree(root)
    boot = BootstrapResult(
        root=root,
        config=NormalizationConfig(),
        args=Namespace(
            processes=1,
            min_loc=6,
            min_stmt=4,
            block_min_loc=20,
            block_min_stmt=8,
            segment_min_loc=20,
            segment_min_stmt=10,
            skip_metrics=False,
            skip_dependencies=False,
            skip_dead_code=False,
            near_miss=False,
            renamed_structure=False,
            semantic_authority=False,
            authority=[],
            api_surface=False,
        ),
        output_paths=OutputPaths(html=None, json=json_out, text=None),
        cache_path=root / "cache.json",
    )
    cache = Cache(root / "cache.json", root=root)
    discovery = core_discovery.discover(boot=boot, cache=cache)
    processing = process(boot=boot, discovery=discovery, cache=cache)
    analysis = analyze(boot=boot, discovery=discovery, processing=processing)
    from codeclone.core.reporting import gate_with_config
    from codeclone.report.gates.evaluator import MetricGateConfig

    gate_config = MetricGateConfig(
        fail_complexity=fail_complexity,
        fail_coupling=-1,
        fail_cohesion=-1,
        fail_cycles=False,
        fail_dead_code=False,
        fail_health=-1,
        fail_on_new_metrics=False,
    )
    _, gate_result = gate_with_config(
        boot=boot,
        analysis=analysis,
        new_func=(),
        new_block=(),
        metrics_diff=None,
        baseline_trust=None,
        files_skipped=processing.files_skipped,
        gate_config=gate_config,
    )
    return report(
        boot=boot,
        discovery=discovery,
        processing=processing,
        analysis=analysis,
        report_meta={},
        new_func=(),
        new_block=(),
        html_builder=None,
        metrics_diff=None,
        gate_config=gate_config,
        gate_result=gate_result,
    )


@pytest.fixture
def rollout(monkeypatch: pytest.MonkeyPatch) -> Callable[[Path | None], None]:
    """Apply one rollout environment; the flag is CI-neutral by design."""

    def _apply(store: Path | None) -> None:
        monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
        if store is None:
            monkeypatch.delenv("CODECLONE_RUN_STORE_ENABLED", raising=False)
            monkeypatch.delenv("CODECLONE_RUN_STORE_PATH", raising=False)
        else:
            monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
            monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(store))

    return _apply


def test_producer_edge_states_the_link_on_a_published_run(
    tmp_path: Path, rollout: Callable[[Path | None], None]
) -> None:
    store = tmp_path / "runs.sqlite3"
    rollout(store)
    artifacts = _report_case(
        tmp_path / "tree", json_out=tmp_path / "out.json", store=store
    )
    link = artifacts.run_snapshot_link
    assert link is not None, "the producer edge dropped the bridge"
    assert link.state == RUN_SNAPSHOT_LINK_LINKED
    assert link.store_run_id and link.report_run_identity
    assert link.store_run_id != link.report_run_identity


def test_producer_edge_states_the_unpublished_zero(
    tmp_path: Path, rollout: Callable[[Path | None], None]
) -> None:
    """The default: a document with no snapshot behind it."""

    rollout(None)
    artifacts = _report_case(
        tmp_path / "tree", json_out=tmp_path / "out.json", store=None
    )
    link = artifacts.run_snapshot_link
    assert link is not None
    assert link.state == RUN_SNAPSHOT_LINK_UNPUBLISHED
    assert link.outcome == RUN_SNAPSHOT_PUBLICATION_DISABLED


def test_producer_edge_states_the_unevaluated_zero(
    tmp_path: Path, rollout: Callable[[Path | None], None]
) -> None:
    """A gate-only run stores a snapshot no document evaluates."""

    store = tmp_path / "runs.sqlite3"
    rollout(store)
    artifacts = _report_case(tmp_path / "tree", json_out=None, store=store)
    assert artifacts.report_document is None
    link = artifacts.run_snapshot_link
    assert link is not None
    assert link.state == RUN_SNAPSHOT_LINK_UNEVALUATED
    assert link.store_run_id and not link.report_run_identity


def test_one_store_record_answers_many_report_identities(
    tmp_path: Path, rollout: Callable[[Path | None], None]
) -> None:
    """The measured one-to-many, end to end.

    Two runs over one tree that differ ONLY in the gate request share a
    store record -- the store's id covers the analysis, and a threshold is
    not analysis -- while their report identities differ, because the
    evaluation tier seals the gate request.  This is the cardinality the
    ruling's "do not connect" rests on: a bridge that assumed 1:1 would
    have to pick one of the two documents and be wrong about the other.
    """

    store = tmp_path / "runs.sqlite3"
    rollout(store)
    links = []
    for index, threshold in enumerate((-1, 1)):
        links.append(
            _report_case(
                tmp_path / "tree",
                json_out=tmp_path / f"out{index}.json",
                store=store,
                fail_complexity=threshold,
            ).run_snapshot_link
        )
    first, second = links
    assert first is not None and second is not None
    assert first.state == second.state == RUN_SNAPSHOT_LINK_LINKED
    # One analysis: one store record, one scope receipt.
    assert first.store_run_id == second.store_run_id
    assert first.analysis_scope_digest == second.analysis_scope_digest
    # Two evaluations: two report identities.
    assert first.report_run_identity != second.report_run_identity
