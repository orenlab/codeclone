# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The store's analysis witness and the wire's ``revisions`` member are ONE
list (contract audit F-05, 2026-09-24).

Two hand-written lists name the analysis generations a run is published
under: the run store's ``_WITNESS_LAYERS`` (the layers with role
``analysis`` enter ``run_id``) and the codec's ``_REVISION_KEYS`` /
``_SUPPORTED_REVISIONS`` (the wire's ``revisions`` member).  Nothing tied
them: the audit added a layer to the store, ``run_id`` moved, the export
went through, and the wire declared nothing about the new layer.  These
pins read both lists off the MECHANISM -- the witness rows a published
store carries and the ``revisions`` member a wire document carries -- and
hold them equal, so a generation added to one side without the other reds
here instead of surfacing only as a moved known-answer digest.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from codeclone.canonical import RunStore, encode_canonical_json
from codeclone.canonical import store as store_module
from tests.test_canonical_roundtrip import fixture_model


def _analysis_witness_declared() -> dict[str, str]:
    """What this build declares it publishes under, analysis role only."""
    return {
        layer: revision
        for layer, revision, role in store_module._WITNESS_LAYERS
        if role == "analysis"
    }


def test_the_wire_revisions_member_is_the_analysis_witness(tmp_path: Path) -> None:
    """Both ends of the edge are read as PUBLISHED: the witness rows the
    store wrote, and the ``revisions`` member the wire document carries."""
    model = fixture_model()
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        store.write_full_run(model, namespace="ns", target="t", expected_generation=0)
    with sqlite3.connect(path) as connection:
        stored = {
            str(layer): str(revision)
            for layer, revision, role in connection.execute(
                "SELECT layer, revision, role FROM witness"
            )
            if str(role) == "analysis"
        }
    wire = json.loads(encode_canonical_json(model))["revisions"]
    assert stored == _analysis_witness_declared()
    assert wire == stored, (
        "the wire's revisions member must name exactly the analysis-role "
        f"witness layers the store publishes under: wire {wire!r}, "
        f"store {stored!r}"
    )
    # The member is a sorted table, like every other wire table.
    assert list(wire) == sorted(wire)


def test_every_analysis_witness_layer_reaches_the_run_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The complementary half: a layer with role ``analysis`` moves
    ``run_id`` when it moves, so the equality above is about the
    identity-bearing layers and not about a label."""
    model = fixture_model()
    with RunStore(tmp_path / "a.sqlite3") as store:
        run_id = store.write_full_run(
            model, namespace="ns", target="t", expected_generation=0
        ).run_id
    declared = store_module._WITNESS_LAYERS
    for layer, revision, role in declared:
        if role != "analysis":
            continue
        moved = tuple(
            (name, "99" if name == layer else value, layer_role)
            for name, value, layer_role in declared
        )
        with monkeypatch.context() as patched:
            patched.setattr(store_module, "_WITNESS_LAYERS", moved)
            with RunStore(tmp_path / f"{layer}.sqlite3") as store:
                shifted = store.write_full_run(
                    model, namespace="ns", target="t", expected_generation=0
                ).run_id
        assert shifted != run_id, f"layer {layer} ({revision}) did not reach run_id"
