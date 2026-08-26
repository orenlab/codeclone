# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Wave-3 export laws: authoritative bytes from the store, one-snapshot
pinning (§11.1), the artifact digest against the run identity (§5), and
bounded working memory (law 11).

Storage forgeries below recompute membership and run identity through the
store's own formulas: they produce self-consistent *different* runs, which
is exactly what a content-addressed store cannot distinguish from honest
ones.  The pinned division of labour: the export proves storage integrity
(content addresses, membership, scope, run identity) before the first
byte; model laws (logical keys, roles) belong to publish-time
normalization and to the decoder's typed refusals — a forged run exports
bytes the decoder refuses loudly, never a silently different model.
"""

from __future__ import annotations

import hashlib
import io
import sqlite3
import tracemalloc
from dataclasses import replace
from pathlib import Path

import pytest

import codeclone.canonical.codec as codec_module
import codeclone.canonical.store as store_module
from codeclone.canonical import (
    CandidateRow,
    CanonicalModel,
    CanonicalModelError,
    ContractRow,
    DependencyOccurrenceRow,
    DependencyRelationRow,
    EffectLabelRoot,
    EffectRoot,
    ExportEnvelope,
    ExportIntegrityError,
    FileId,
    GraphNodeRow,
    ModuleId,
    ProducerRoot,
    RunStore,
    SemanticEdge,
    SinkRoleRow,
    StoreIntegrityError,
    SymbolId,
    UnknownRunError,
    UnresolvedRoot,
    ViolationRow,
    WireDecodeError,
    canonical_artifact_digest,
    decode_canonical_json,
    export_head,
    export_run,
    verify_export_artifact,
)
from codeclone.canonical.store import (
    _membership_digest,
    _object_id,
    _payload_bytes,
    _run_id,
)
from tests.test_canonical_roundtrip import analysis_facts, fixture_model

_NS = "lineage-alpha"
_TARGET = "worktree-a"

# Contract sentinels for the fixture model published under _NS. The run
# identity hashes the analysis witness layers, the scope receipt, and the
# membership; the artifact digest hashes the wire bytes under the
# wire-revision domain. Refreshing either literal to make the test pass is
# forbidden: a change here IS an identity-contract change (run identity or
# artifact domain) and needs its own review.  Wave 4 replaced the wave-3
# literals (run 591477af..., artifact 53f65a70...) deliberately: the fixture
# gained the F2 ``coupling_cohesion_observations`` family.  The ratified
# dependency split (ruling 2026-08-24 §2) then replaced the wave-4 literals
# (run 174ed52d..., artifact fde28610...) deliberately: ``dependency_edges``
# was rebuilt into ``dependency_relations`` + ``dependency_occurrences``,
# which moves the membership (the storage families changed) and the bytes.
# The F5 ``api_symbols`` family replaced the split literals (run
# 08900b4d..., artifact dc22f46b...) deliberately: the fixture gained five
# api_symbol objects under the api_surface_signature namespace.  The F9
# ``run_scalars`` record replaced the F5 literals (run f4a7c24b..., artifact
# 2072e742...) deliberately: the fixture gained its one run_scalar object.
# The F1 ``risk_observations`` family (ruling 2026-08-26, fork (b))
# replaced the F9 literals (run c3e2d21c..., artifact 642922b3...)
# deliberately: the fixture gained four declaration-site keyed
# risk_observation objects under the complexity_metrics namespace.  The F7
# ``dependency_cycles`` family (slice 4, K1) replaced the F1 literals (run
# 22bd2c6d..., artifact e8d701a8...) deliberately: the fixture gained two
# module-set keyed dependency_cycle objects under the canonical_model
# namespace.  The F8 ``clone_groups`` family (slice 4, K2) replaced the K1
# literals (run 167aadde..., artifact 5b939274...) deliberately: the
# fixture gained three emitted clone_group objects under the
# clone_fingerprint namespace, which moves the membership and the bytes.
_FIXTURE_RUN_ID = "b23b09120911b8d6af81bf4825d5e269b28a7cf6acb6ef5759073e38631ad13c"
_FIXTURE_ARTIFACT = "706330d93503db019ef4d711807c5ce0fe4241bb231f2e78e7e052fde32f1b79"


def _store(tmp_path: Path, name: str = "runs.sqlite") -> RunStore:
    return RunStore(tmp_path / name)


def _publish(
    store: RunStore, model: CanonicalModel, *, expected_generation: int = 0
) -> str:
    receipt = store.write_full_run(
        model,
        namespace=_NS,
        target=_TARGET,
        expected_generation=expected_generation,
    )
    return receipt.run_id


def _export(store: RunStore, run_id: str) -> tuple[bytes, ExportEnvelope]:
    sink = io.BytesIO()
    envelope = export_run(store, run_id, sink)
    return sink.getvalue(), envelope


def _implant(connection: sqlite3.Connection, family: str, payload: bytes) -> None:
    """Insert one correctly content-addressed object into the single run."""
    run_pk, namespace_pk = connection.execute(
        "SELECT run_pk, namespace_pk FROM runs"
    ).fetchone()
    cursor = connection.execute(
        "INSERT INTO objects (namespace_pk, object_id, family, payload) "
        "VALUES (?, ?, ?, ?)",
        (namespace_pk, _object_id(_NS, family, payload), family, payload),
    )
    connection.execute(
        "INSERT INTO run_members (run_pk, object_pk) VALUES (?, ?)",
        (run_pk, cursor.lastrowid),
    )


def _refit(
    connection: sqlite3.Connection,
    *,
    update_membership: bool,
    update_run_id: bool,
) -> str:
    """Recompute membership and run identity from the (mutated) rows.

    Returns the self-consistent run id; the caller decides which columns to
    move, so each storage-integrity guard gets its own reachable probe.
    """
    run_pk, scope_digest = connection.execute(
        "SELECT run_pk, analysis_scope_digest FROM runs"
    ).fetchone()
    object_ids = [
        str(row[0])
        for row in connection.execute(
            "SELECT o.object_id FROM run_members m "
            "JOIN objects o ON o.object_pk = m.object_pk WHERE m.run_pk = ?",
            (run_pk,),
        )
    ]
    membership = _membership_digest(object_ids)
    forged_run_id = _run_id(_NS, str(scope_digest), membership)
    if update_membership:
        connection.execute(
            "UPDATE runs SET membership_digest = ? WHERE run_pk = ?",
            (membership, run_pk),
        )
    if update_run_id:
        connection.execute(
            "UPDATE runs SET run_id = ? WHERE run_pk = ?", (forged_run_id, run_pk)
        )
    return forged_run_id


# -- Authoritative bytes: the store births the projection --------------------


def test_export_bytes_are_the_projected_bytes(tmp_path: Path) -> None:
    """The streamed export is byte-identical to the materialized projection
    — one wire, two row sources — and the envelope accounts for it."""
    model = fixture_model()
    with _store(tmp_path) as store:
        run_id = _publish(store, model)
        data, envelope = _export(store, run_id)
        assert data == store.project_run(run_id)
        assert envelope.run_id == run_id
        assert envelope.byte_count == len(data)
        assert decode_canonical_json(data) == model.normalize()
        verify_export_artifact(data, envelope)


def test_export_of_the_empty_model_state(tmp_path: Path) -> None:
    """The opposite boundary: an empty run exports its (non-empty) document
    with every family table measured empty, byte-identically."""
    with _store(tmp_path) as store:
        run_id = _publish(store, CanonicalModel())
        data, envelope = _export(store, run_id)
        assert data == store.project_run(run_id)
        assert envelope.byte_count == len(data) > 0


def test_known_answer_run_and_artifact_identity(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        run_id = _publish(store, fixture_model())
        data, envelope = _export(store, run_id)
    assert run_id == _FIXTURE_RUN_ID
    assert envelope.artifact_digest == _FIXTURE_ARTIFACT
    # The independent recompute spells the domain out: the wire revision is
    # inside the artifact preimage and nowhere inside the run identity.
    assert (
        envelope.artifact_digest
        == hashlib.sha256(b"cc-canonical-artifact:0\x00" + data).hexdigest()
    )
    assert envelope.artifact_digest != envelope.run_id


def test_projection_layer_stays_out_of_run_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brief §5: the wire revision must never reach back into ``run_id`` —
    and must move the artifact digest, which names the projection."""
    patched = tuple(
        (layer, "99" if layer == "canonical_wire" else revision, role)
        for layer, revision, role in store_module._WITNESS_LAYERS
    )
    monkeypatch.setattr(store_module, "_WITNESS_LAYERS", patched)
    with _store(tmp_path, "patched.sqlite") as store:
        run_id = _publish(store, fixture_model())
        data, _envelope = _export(store, run_id)
    assert run_id == _FIXTURE_RUN_ID  # identity did not move
    assert canonical_artifact_digest(
        data, wire_revision="99"
    ) != canonical_artifact_digest(data)  # the artifact domain did


def test_export_envelope_witness_is_read_from_the_store(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        run_id = _publish(store, fixture_model())
        _data, envelope = _export(store, run_id)
    with sqlite3.connect(path) as connection:
        stored = [
            (str(layer), str(revision), str(role))
            for layer, revision, role in connection.execute(
                "SELECT layer, revision, role FROM witness ORDER BY layer"
            )
        ]
    assert [(w.layer, w.revision, w.role) for w in envelope.witness] == stored
    assert {w.role for w in envelope.witness} == {"analysis", "projection", "storage"}


# -- Envelope verification ---------------------------------------------------


def test_verify_refuses_a_corrupted_artifact_byte(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        data, envelope = _export(store, _publish(store, fixture_model()))
    corrupt = bytearray(data)
    corrupt[len(corrupt) // 2] ^= 0x01
    with pytest.raises(ExportIntegrityError, match="hash to the envelope digest"):
        verify_export_artifact(bytes(corrupt), envelope)


def test_verify_refuses_a_wrong_byte_count(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        data, envelope = _export(store, _publish(store, fixture_model()))
    with pytest.raises(ExportIntegrityError, match="the envelope declares"):
        verify_export_artifact(data, replace(envelope, byte_count=len(data) - 1))


def test_verify_refuses_a_foreign_wire_revision(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        data, envelope = _export(store, _publish(store, fixture_model()))
    with pytest.raises(ExportIntegrityError, match="verifies revision"):
        verify_export_artifact(data, replace(envelope, wire_revision="99"))


# -- One snapshot (§11.1) ----------------------------------------------------


def _grown_model() -> CanonicalModel:
    """The fixture plus one candidate and one coupled set: the growth is
    visible both in the projection plan and in a pass-two fact family, so
    an exporter mixing generations cannot reproduce the pinned bytes."""
    model = fixture_model()
    sa = SymbolId(FileId("pkg/a.py"), "A.run")
    candidates = set(model.facts.analysis.candidates)
    candidates.add(CandidateRow("exact", "grown", frozenset({sa})))
    coupled = set(model.coupled_sets)
    coupled.add(frozenset({"OnlyInSecond"}))
    return replace(
        model,
        facts=replace(
            model.facts,
            analysis=replace(model.facts.analysis, candidates=frozenset(candidates)),
        ),
        coupled_sets=frozenset(coupled),
    )


def test_export_head_is_pinned_to_the_resolved_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A publication landing mid-export advances the head and does not mix
    a single byte into the running export (§11.1)."""
    with _store(tmp_path) as store:
        first_run = _publish(store, fixture_model())
        baseline = store.project_run(first_run)
        published: list[str] = []

        def _publish_mid_export(run_id: str) -> None:
            published.append(run_id)
            _publish(store, _grown_model(), expected_generation=1)

        monkeypatch.setattr(store, "_pin_export", _publish_mid_export)
        sink = io.BytesIO()
        envelope = export_head(store, namespace=_NS, target=_TARGET, sink=sink)
        # The world really moved under the export...
        head = store.head(namespace=_NS, target=_TARGET)
        assert head is not None and head.run_id != first_run
        assert published == [first_run]
        # ...and the export never noticed: one snapshot, zero mixing.
        assert envelope.run_id == first_run
        assert sink.getvalue() == baseline


def test_export_head_without_a_head_is_a_typed_refusal(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        sink = io.BytesIO()
        with pytest.raises(UnknownRunError, match="has no published head"):
            export_head(store, namespace=_NS, target="nowhere", sink=sink)
        assert sink.getvalue() == b""


def test_export_of_an_unknown_run_is_a_typed_refusal(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        _publish(store, fixture_model())
        sink = io.BytesIO()
        with pytest.raises(UnknownRunError, match="not a published run"):
            export_run(store, "0" * 64, sink)
        assert sink.getvalue() == b""


# -- Storage integrity before the first byte ---------------------------------


def test_export_refuses_a_corrupted_payload_before_the_first_byte(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        run_id = _publish(store, fixture_model())
    with sqlite3.connect(path) as connection:
        object_pk, payload = connection.execute(
            "SELECT object_pk, payload FROM objects ORDER BY object_id LIMIT 1"
        ).fetchone()
        corrupt = bytearray(payload)
        corrupt[-2] ^= 0x01
        connection.execute(
            "UPDATE objects SET payload = ? WHERE object_pk = ?",
            (bytes(corrupt), object_pk),
        )
        connection.commit()
    with RunStore(path) as store:
        sink = io.BytesIO()
        with pytest.raises(StoreIntegrityError, match="content address"):
            export_run(store, run_id, sink)
        assert sink.getvalue() == b""


def test_export_refuses_an_unknown_stored_family(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        run_id = _publish(store, fixture_model())
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE objects SET family = 'mystery' WHERE object_pk = "
            "(SELECT object_pk FROM objects WHERE family = 'coupled_set' LIMIT 1)"
        )
        connection.commit()
    with RunStore(path) as store:
        sink = io.BytesIO()
        with pytest.raises(StoreIntegrityError, match="unknown families"):
            export_run(store, run_id, sink)
        assert sink.getvalue() == b""
        # The materializing read path refuses the same row, singular.
        with pytest.raises(StoreIntegrityError, match="unknown family"):
            store.read_run(run_id)


def test_export_refuses_membership_that_does_not_reproduce(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        run_id = _publish(store, fixture_model())
    with sqlite3.connect(path) as connection:
        _implant(connection, "coupled_set", _payload_bytes({"labels": ["Ghost"]}))
        connection.commit()
    with RunStore(path) as store:
        with pytest.raises(StoreIntegrityError, match="membership does not reproduce"):
            export_run(store, run_id, io.BytesIO())
        # The materializing read path refuses the same forgery.
        with pytest.raises(StoreIntegrityError, match="membership does not reproduce"):
            store.read_run(run_id)


def test_export_refuses_a_scope_receipt_that_does_not_reproduce(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        _publish(store, fixture_model())
    with sqlite3.connect(path) as connection:
        _implant(connection, "analyzed_file", _payload_bytes({"path": "pkg/ghost.py"}))
        forged = _refit(connection, update_membership=True, update_run_id=True)
        connection.commit()
    with RunStore(path) as store:
        with pytest.raises(StoreIntegrityError, match="scope receipt"):
            export_run(store, forged, io.BytesIO())
        with pytest.raises(StoreIntegrityError, match="scope receipt"):
            store.read_run(forged)


def test_export_refuses_a_run_identity_that_does_not_recompute(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        run_id = _publish(store, fixture_model())
    with sqlite3.connect(path) as connection:
        _implant(connection, "coupled_set", _payload_bytes({"labels": ["Ghost"]}))
        _refit(connection, update_membership=True, update_run_id=False)
        connection.commit()
    with RunStore(path) as store:
        with pytest.raises(StoreIntegrityError, match="identity does not recompute"):
            export_run(store, run_id, io.BytesIO())
        with pytest.raises(StoreIntegrityError, match="identity does not recompute"):
            store.read_run(run_id)


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        # Hashes to its address but is not JSON: reaches the JSON guard.
        (b"not-json", "not\\s+storage JSON"),
        # Valid JSON that is not a row object: reaches the shape guard
        # behind it (one probe per sub-guard; a sibling catching the probe
        # would otherwise mask a dropped one).
        (b"[]", "not a row"),
    ],
    ids=["not-json", "not-a-row"],
)
def test_export_refuses_a_well_addressed_non_row_payload(
    tmp_path: Path, payload: bytes, match: str
) -> None:
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        _publish(store, fixture_model())
    with sqlite3.connect(path) as connection:
        object_pk = connection.execute(
            "SELECT object_pk FROM objects WHERE family = 'coupled_set' "
            "ORDER BY object_id LIMIT 1"
        ).fetchone()[0]
        connection.execute(
            "UPDATE objects SET payload = ?, object_id = ? WHERE object_pk = ?",
            (payload, _object_id(_NS, "coupled_set", payload), object_pk),
        )
        forged = _refit(connection, update_membership=True, update_run_id=True)
        connection.commit()
    with RunStore(path) as store:
        with pytest.raises(StoreIntegrityError, match=match):
            export_run(store, forged, io.BytesIO())
        with pytest.raises(StoreIntegrityError, match=match):
            store.read_run(forged)


# -- Forged model states: the decoder is the refusal owner -------------------


def test_forged_role_breach_exports_bytes_the_decoder_refuses(
    tmp_path: Path,
) -> None:
    """A self-consistent forged run whose candidate producer has no
    FUNCTION role: the export succeeds (storage integrity holds), the
    decoder refuses W16, and the materializing read path refuses at
    normalization — no consumer sees a silently different model."""
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        _publish(store, fixture_model())
    forged_candidate = _payload_bytes(
        {
            "level": "exact",
            "producer_set": [["tools/b.py", "zz"]],  # zz has no contract
            "shared_fact": "forged",
        }
    )
    with sqlite3.connect(path) as connection:
        _implant(connection, "candidate", forged_candidate)
        forged = _refit(connection, update_membership=True, update_run_id=True)
        connection.commit()
    with RunStore(path) as store:
        data, _envelope = _export(store, forged)
        with pytest.raises(WireDecodeError, match="W16"):
            decode_canonical_json(data)
        with pytest.raises(CanonicalModelError, match="FUNCTION role"):
            store.read_run(forged)


def test_forged_duplicate_key_exports_bytes_the_decoder_refuses(
    tmp_path: Path,
) -> None:
    """Two contract facts under one logical key: the decoder's strictly
    increasing key check refuses (W13), the read path refuses the key law."""
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        _publish(store, fixture_model())
    forged_contract = _payload_bytes(
        {
            "effect_signature": "forged",
            "function": ["pkg/a.py", "A.run"],
            "root_set": [],
        }
    )
    with sqlite3.connect(path) as connection:
        _implant(connection, "contract", forged_contract)
        forged = _refit(connection, update_membership=True, update_run_id=True)
        connection.commit()
    with RunStore(path) as store:
        data, _envelope = _export(store, forged)
        with pytest.raises(WireDecodeError, match=r"W1[23]"):
            decode_canonical_json(data)
        with pytest.raises(CanonicalModelError, match="logical key"):
            store.read_run(forged)


# -- Bounded working memory (law 11) -----------------------------------------


class _NullSink:
    """Discards the stream so only working memory is measured."""

    def write(self, data: bytes) -> int:
        return len(data)


def _bulk_model(rows: int = 1500) -> CanonicalModel:
    """Every fact family populated with ``rows`` rows: full materialization
    must hold all seven at once, the bounded export at most one."""
    files = [FileId(f"pkg/m{i:03d}.py") for i in range(40)]
    modules = [ModuleId(f"pkg.m{i:03d}") for i in range(40)]
    symbols = [SymbolId(files[i % 40], f"f{i:04d}") for i in range(rows)]
    pool: list[frozenset[EffectRoot]] = [
        frozenset(
            {
                EffectLabelRoot("artifact_write", f"op.label{j}"),
                ProducerRoot(symbols[j]),
                UnresolvedRoot(),
            }
        )
        for j in range(24)
    ]
    return CanonicalModel(
        analyzed_files=frozenset(files),
        facts=analysis_facts(
            contracts=frozenset(
                ContractRow(symbols[i], f"sig{i}", pool[i % 24]) for i in range(rows)
            ),
            graph_nodes=frozenset(
                GraphNodeRow(
                    symbols[i],
                    f"g{i}",
                    pool[(i * 7) % 24],
                    (f"out{i}", "unresolved"),
                    "resolved",
                )
                for i in range(rows)
            ),
            sink_roles=frozenset(
                SinkRoleRow(symbols[i], "unavailable") for i in range(rows)
            ),
            candidates=frozenset(
                CandidateRow(
                    "exact",
                    f"fact{i}",
                    frozenset({symbols[i], symbols[(i + 3) % rows]}),
                )
                for i in range(rows)
            ),
            semantic_edges=frozenset(
                SemanticEdge(symbols[i], symbols[(i + 1) % rows]) for i in range(rows)
            ),
            dependency_relations=frozenset(
                DependencyRelationRow(modules[i % 40], modules[(i + 1) % 40], "import")
                for i in range(rows)
            ),
            dependency_occurrences=frozenset(
                DependencyOccurrenceRow(
                    DependencyRelationRow(
                        modules[i % 40], modules[(i + 1) % 40], "import"
                    ),
                    i,
                    "import_time",
                    False,
                )
                for i in range(rows)
            ),
            violations=frozenset(
                ViolationRow(
                    contract_id=f"governance.v{i}",
                    kind="owner_bypass",
                    sink_identity=symbols[i],
                    canonical_owner=symbols[(i + 1) % rows],
                    authority_status="shadow",
                    effect_signature=f"asig{i}",
                    resolution_state="resolved",
                    root_set=pool[i % 24],
                    producer_set=frozenset({symbols[i]}),
                    suppressed=False,
                )
                for i in range(rows)
            ),
        ),
    )


def test_export_does_not_open_the_full_materialization_doors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Structural half of the bounded-memory pin: the export succeeds with
    both full-materialization doors poisoned, byte-identically."""
    with _store(tmp_path) as store:
        run_id = _publish(store, fixture_model())
        baseline = store.project_run(run_id)

        def _door(*_args: object, **_kwargs: object) -> bytes:
            raise AssertionError("full-materialization door opened during export")

        monkeypatch.setattr(store_module, "encode_canonical_json", _door)
        monkeypatch.setattr(codec_module, "encode_canonical_json", _door)
        monkeypatch.setattr(RunStore, "read_run", _door)
        data, _envelope = _export(store, run_id)
        assert data == baseline


def test_export_peak_allocation_is_bounded_below_materialization(
    tmp_path: Path,
) -> None:
    """Comparative half of the bounded-memory pin (law 11): the relative
    invariant IS the claim — a bounded reader must peak well below the
    materializing projection on the same run.  Measured on this fixture the
    ratio is ~1.8-1.9 (seven equal families; the plan and the largest
    single family bound the export); the 1.5 boundary keeps deterministic
    margin, and a materializing mutant lands at ~1.0."""
    with _store(tmp_path) as store:
        run_id = _publish(store, _bulk_model())
        tracemalloc.start()
        materialized = store.project_run(run_id)
        _, peak_full = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        tracemalloc.start()
        export_run(store, run_id, _NullSink())
        _, peak_export = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert len(materialized) > 100_000  # the fixture distinguishes (§6.2)
    assert peak_export > 0 and peak_full > 0
    assert peak_export * 1.5 <= peak_full
