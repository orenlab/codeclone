# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""An artifact of the previous generation is REFUSED, never reinterpreted.

The epoch boundary of 2026-09-07 moved two constants together —
``CANONICAL_MODEL_REVISION`` 1 -> 2 and ``CANONICAL_WIRE_REVISION`` 0 -> 1 —
and the honesty law of a boundary is that the old generation's artifacts
say typed what they are and how to move on.  The artifacts here are REAL:
``tests/fixtures/run_store_generation_1`` was produced by the revision-1
build at commit f117a8ad, on a clean tree, over the serving corpus, and its
provenance file records the constants that build declared, the run it
published and the digests of the files (a hand-written store would only
prove that the tests agree with themselves).

Both constants are held separately: the store's refusal names every
diverging witness layer with both revisions, so reverting either constant
alone changes the named set, and the wire's refusal names the wire
generation on both sides.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

import pytest

from codeclone.canonical import (
    STORE_GENERATION_NEXT_STEP,
    ExportEnvelope,
    ExportIntegrityError,
    RunStore,
    StoreCompatibilityError,
    WireDecodeError,
    WitnessLayer,
    decode_canonical_json,
    verify_export_artifact,
)
from codeclone.canonical.store import migrate_store_schema
from codeclone.contracts import CANONICAL_MODEL_REVISION, CANONICAL_WIRE_REVISION
from tests._run_store_schema_evidence import byte_state
from tests.test_canonical_roundtrip import fixture_model

_FIXTURES = Path(__file__).parent / "fixtures" / "run_store_generation_1"
_MANIFEST_NAME = "provenance.json"
# The revision-1 build left exactly these artifacts behind, and this module
# consumes every one of them: ``runs.sqlite3`` is opened as a store,
# ``run.wire.json`` is decoded, ``run.envelope.json`` is verified.  The
# manifest cannot witness its own bytes, so it is not a member of the set.
_MANIFESTED_ARTIFACTS = frozenset(
    {"run.envelope.json", "run.wire.json", "runs.sqlite3"}
)


def _artifacts_the_manifest_does_not_own(
    directory: Path, recorded: dict[str, str]
) -> tuple[frozenset[str], frozenset[str]]:
    """(files carrying no digest, digests naming no file) for one directory."""
    on_disk = frozenset(
        entry.name for entry in directory.iterdir() if entry.name != _MANIFEST_NAME
    )
    named = frozenset(recorded)
    return on_disk - named, named - on_disk


def _unnamed_layers(refusal: StoreCompatibilityError) -> list[str]:
    """The diverging layers whose own words -- the layer with BOTH
    revisions -- the refusal's message leaves out; ``[]`` when it names
    every one.  The layers themselves are pinned on ``refusal.diverging``."""
    words = [
        f"{layer} stored '{stored}' declared '{declared}'"
        for layer, stored, declared in refusal.diverging
    ]
    return [line for line in words if line not in str(refusal)]


def _refused_copy(
    fixtures: Path, tmp_path: Path
) -> tuple[Path, dict[str, object], StoreCompatibilityError]:
    """Open a copy of one generation's store; hand back the copy, its byte
    state measured before any connection touched it, and the refusal -- the
    file proven left exactly as it was."""
    store = tmp_path / "runs.sqlite3"
    shutil.copy(fixtures / "runs.sqlite3", store)
    before = byte_state(store)
    with pytest.raises(StoreCompatibilityError) as caught:
        RunStore(store, create=False)
    assert byte_state(store) == before
    return store, before, caught.value


@pytest.fixture(scope="module")
def provenance() -> dict[str, object]:
    return cast(
        "dict[str, object]",
        json.loads((_FIXTURES / "provenance.json").read_text("utf-8")),
    )


def test_the_artifacts_are_the_ones_the_revision_one_build_produced(
    provenance: dict[str, object],
) -> None:
    """Fixture integrity: the files are byte-identical to what the
    provenance records, and the build that produced them declared the
    previous generation of exactly the two constants that moved."""
    produced_by = cast("dict[str, str]", provenance["produced_by"])
    assert (
        produced_by["CANONICAL_MODEL_REVISION"],
        produced_by["CANONICAL_WIRE_REVISION"],
        produced_by["git_status_porcelain"],
    ) == ("1", "0", "")
    assert (CANONICAL_MODEL_REVISION, CANONICAL_WIRE_REVISION) == ("3", "2")
    recorded = cast("dict[str, str]", provenance["sha256"])
    measured = {
        name: hashlib.sha256((_FIXTURES / name).read_bytes()).hexdigest()
        for name in recorded
    }
    assert measured == recorded
    # The store really is a generation-1 store: its own witness table says so.
    with sqlite3.connect(_FIXTURES / "runs.sqlite3") as connection:
        witness = dict(connection.execute("SELECT layer, revision FROM witness"))
        objects = connection.execute("SELECT count(*) FROM objects").fetchone()[0]
    assert witness["canonical_model"] == "1" and witness["canonical_wire"] == "0"
    assert objects > 0 and objects == provenance["objects"]


def test_the_provenance_manifest_owns_every_revision_one_artifact(
    provenance: dict[str, object], tmp_path: Path
) -> None:
    """Completeness, not one more assert on one name: the manifest is a closed
    world over the fixture directory, so an artifact dropped in without a
    digest — or a digest quietly dropped from the manifest — reds here, and the
    set it owns is exactly the set this module consumes."""
    recorded = cast("dict[str, str]", provenance["sha256"])
    assert _artifacts_the_manifest_does_not_own(_FIXTURES, recorded) == (
        frozenset(),
        frozenset(),
    )
    assert frozenset(recorded) == _MANIFESTED_ARTIFACTS
    # The closed world is what carries the proof, so show an input that trips
    # it: a mutant that drops a file INTO the fixture directory cannot be
    # written as an edit to a tracked file, and a pin no input reaches is
    # theatre.
    intruder = tmp_path / "run_store_generation_1"
    shutil.copytree(_FIXTURES, intruder)
    (intruder / "extra.json").write_text("{}", encoding="utf-8")
    assert _artifacts_the_manifest_does_not_own(intruder, recorded) == (
        frozenset({"extra.json"}),
        frozenset(),
    )


def test_a_generation_one_store_is_refused_at_open_with_its_migration_path(
    tmp_path: Path,
) -> None:
    """Law 7 on a real file: refused before a single address is read, naming
    each diverging layer with BOTH revisions, the refused path and the one
    step a reader can take.  The file is left as it was -- its ``-wal`` and
    ``-shm`` and its journal mode included, measured before any other
    connection touches it."""
    store, before, refusal = _refused_copy(_FIXTURES, tmp_path)
    assert (before["-wal"], before["-shm"], before["journal"]) == (
        None,
        None,
        b"\x02\x02",
    )
    # Witness first: the generation-1 store also lacks this build's index,
    # and it is named for its generation, never for its schema.
    assert type(refusal) is StoreCompatibilityError
    assert refusal.diverging == (
        ("canonical_model", "1", "3"),
        ("canonical_wire", "0", "2"),
        ("storage_schema", "1", "2"),
    )
    assert refusal.path == str(store)
    assert refusal.next_step == STORE_GENERATION_NEXT_STEP
    assert _unnamed_layers(refusal) == []
    message = str(refusal)
    assert "(law 7)" in message and STORE_GENERATION_NEXT_STEP in message
    with sqlite3.connect(store) as connection:
        assert dict(connection.execute("SELECT layer, revision FROM witness")) == {
            "authority_analysis": "1",
            "canonical_model": "1",
            "canonical_object_identity": "1",
            "canonical_wire": "0",
            "contract_ir": "1",
            "module_identity": "2",
            "storage_schema": "1",
        }
    # Positive control on the same door: a store THIS build writes opens.
    with RunStore(tmp_path / "current.sqlite3") as current:
        current.write_full_run(
            fixture_model(), namespace="control", target="t", expected_generation=0
        )
    with RunStore(tmp_path / "current.sqlite3", create=False):
        pass


def test_a_generation_zero_wire_document_is_refused_at_the_revision_fence() -> None:
    """W21 on a real document, naming the generation it declares and the one
    this build reads, with the migration path — never decoded under the
    new grammar."""
    data = (_FIXTURES / "run.wire.json").read_bytes()
    assert b'"wire":"0"' in data and b'"canonical_model":"1"' in data
    with pytest.raises(WireDecodeError) as caught:
        decode_canonical_json(data)
    assert caught.value.code == "W21"
    assert "declares wire generation '0'" in caught.value.detail
    assert "this build reads '2' only" in caught.value.detail
    assert "next_step" in caught.value.detail


def test_a_generation_zero_export_envelope_is_refused_by_this_verifier() -> None:
    data = (_FIXTURES / "run.wire.json").read_bytes()
    raw = json.loads((_FIXTURES / "run.envelope.json").read_text("utf-8"))
    envelope = ExportEnvelope(
        run_id=str(raw["run_id"]),
        artifact_digest=str(raw["artifact_digest"]),
        byte_count=int(raw["byte_count"]),
        wire_revision=str(raw["wire_revision"]),
        witness=tuple(
            WitnessLayer(
                layer=str(w["layer"]), revision=str(w["revision"]), role=str(w["role"])
            )
            for w in raw["witness"]
        ),
    )
    assert envelope.wire_revision == "0" and len(data) == envelope.byte_count
    with pytest.raises(ExportIntegrityError, match="declares wire revision '0'"):
        verify_export_artifact(data, envelope)


# ---------------------------------------------------------------------------
# Generation 2 (canonical epoch E4): the artifacts the revision-2 build left
# behind, refused by the revision-3 build the same way generation 1 is.
# ``tests/fixtures/run_store_generation_2`` was produced by the build at
# 02262334 (the last commit before the E4 series), from a ``git archive`` of
# that commit, over the same serving corpus; its provenance records the
# constants that build declared and the sha256 of every artifact.
# ---------------------------------------------------------------------------

_FIXTURES_2 = Path(__file__).parent / "fixtures" / "run_store_generation_2"


@pytest.fixture(scope="module")
def provenance_2() -> dict[str, object]:
    return cast(
        "dict[str, object]",
        json.loads((_FIXTURES_2 / _MANIFEST_NAME).read_text("utf-8")),
    )


def test_the_artifacts_are_the_ones_the_revision_two_build_produced(
    provenance_2: dict[str, object], tmp_path: Path
) -> None:
    produced_by = cast("dict[str, str]", provenance_2["produced_by"])
    assert (
        produced_by["CANONICAL_MODEL_REVISION"],
        produced_by["CANONICAL_WIRE_REVISION"],
        produced_by["git_status_porcelain"],
    ) == ("2", "1", "")
    recorded = cast("dict[str, str]", provenance_2["sha256"])
    assert _artifacts_the_manifest_does_not_own(_FIXTURES_2, recorded) == (
        frozenset(),
        frozenset(),
    )
    assert frozenset(recorded) == _MANIFESTED_ARTIFACTS
    measured = {
        name: hashlib.sha256((_FIXTURES_2 / name).read_bytes()).hexdigest()
        for name in recorded
    }
    assert measured == recorded
    # Read a copy: a read-only connection to a WAL file leaves -wal/-shm
    # beside it, which would put two artifacts into the fixture directory.
    copy = tmp_path / "runs.sqlite3"
    shutil.copy(_FIXTURES_2 / "runs.sqlite3", copy)
    with closing(sqlite3.connect(copy)) as raw:
        witness = dict(raw.execute("SELECT layer, revision FROM witness"))
        objects = raw.execute("SELECT count(*) FROM objects").fetchone()[0]
        columns = [str(row[1]) for row in raw.execute("PRAGMA table_info(objects)")]
    assert witness["canonical_model"] == "2" and witness["canonical_wire"] == "1"
    assert objects == provenance_2["objects"]
    # The container the audit changed: a generation-2 object row names its
    # family by text and its address by hex -- the shape this build refuses.
    assert columns == ["object_pk", "namespace_pk", "object_id", "family", "payload"]


def test_a_generation_two_store_is_refused_at_open_by_its_witness(
    tmp_path: Path,
) -> None:
    """The witness decides before the schema: the generation-2 file also
    lacks this build's ``families`` table and family index, and it is named
    for its generation, never offered the migration verb."""
    store, before, refusal = _refused_copy(_FIXTURES_2, tmp_path)
    assert type(refusal) is StoreCompatibilityError
    assert refusal.diverging == (
        ("canonical_model", "2", "3"),
        ("canonical_wire", "1", "2"),
        ("storage_schema", "1", "2"),
    )
    assert refusal.next_step == STORE_GENERATION_NEXT_STEP
    # The container moved in this generation too, and the refusal says so.
    assert _unnamed_layers(refusal) == []
    with pytest.raises(StoreCompatibilityError) as migrated:
        migrate_store_schema(store)
    assert migrated.value.diverging == refusal.diverging
    assert byte_state(store) == before


def test_a_generation_one_wire_document_is_refused_at_the_revision_fence() -> None:
    data = (_FIXTURES_2 / "run.wire.json").read_bytes()
    assert b'"wire":"1"' in data and b'"canonical_model":"2"' in data
    with pytest.raises(WireDecodeError) as caught:
        decode_canonical_json(data)
    assert caught.value.code == "W21"
    assert "declares wire generation '1'" in caught.value.detail
    assert "this build reads '2' only" in caught.value.detail


def test_a_generation_one_export_envelope_is_refused_by_this_verifier() -> None:
    data = (_FIXTURES_2 / "run.wire.json").read_bytes()
    raw = json.loads((_FIXTURES_2 / "run.envelope.json").read_text("utf-8"))
    envelope = ExportEnvelope(
        run_id=str(raw["run_id"]),
        artifact_digest=str(raw["artifact_digest"]),
        byte_count=int(raw["byte_count"]),
        wire_revision=str(raw["wire_revision"]),
        witness=tuple(
            WitnessLayer(
                layer=str(w["layer"]), revision=str(w["revision"]), role=str(w["role"])
            )
            for w in raw["witness"]
        ),
    )
    assert envelope.wire_revision == "1" and len(data) == envelope.byte_count
    with pytest.raises(ExportIntegrityError, match="declares wire revision '1'"):
        verify_export_artifact(data, envelope)
