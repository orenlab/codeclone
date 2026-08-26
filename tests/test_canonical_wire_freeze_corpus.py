# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical-family pins over the wire-freeze distinguishing corpus.

The corpus (ruling 2026-08-24 §10, step 2b) exists so that families whose
keys carried zero rows on the frozen self-repo corpus are proven on real
producer output.  ``tests/conftest.py`` runs the corpus once through the
real CLI; this module ingests the resulting report document through the
canonical full-run oracle and pins the family rows the wave-4 substrate
carries — the ingest is the measurement, never a re-derivation.

This module's subject is ``codeclone.canonical`` (ring r2); the
report-shape pins over the same corpus run live in
``test_wire_freeze_corpus`` (ring r4) — one ring per test module, per the
Phase 39S test-import law.
"""

from __future__ import annotations

from codeclone.canonical import (
    DependencyCycleRow,
    FileId,
    ModuleId,
    SymbolId,
    canonical_model_from_legacy_document,
)


def test_f7_canonical_family_carries_the_corpus_cycles_end_to_end(
    corpus_report: dict[str, object],
) -> None:
    """F7 canonical family from the REAL producer document: the ingest
    oracle maps the corpus's three cycle rows onto MODULE-domain sets with
    the kind classified once — and the deferred back-edge over the
    import-cycle pair still yields no fourth row (the family law would
    refuse the ingest loudly if the producer ever emitted one)."""
    model = canonical_model_from_legacy_document(corpus_report)
    assert model.facts.analysis.dependency_cycles == frozenset(
        {
            DependencyCycleRow(
                "import_cycle",
                frozenset({ModuleId("pkg.cycle_a"), ModuleId("pkg.cycle_b")}),
            ),
            DependencyCycleRow(
                "deferred_cycle",
                frozenset({ModuleId("pkg.lazy_x"), ModuleId("pkg.lazy_y")}),
            ),
            DependencyCycleRow(
                "import_cycle",
                frozenset(
                    {
                        ModuleId("pkg.tri_a"),
                        ModuleId("pkg.tri_b"),
                        ModuleId("pkg.tri_c"),
                    }
                ),
            ),
        }
    )


def test_f8_canonical_family_carries_the_emitted_corpus_groups(
    corpus_report: dict[str, object],
) -> None:
    """F8 from the REAL producer document: four emitted groups in two
    kinds, keys distinct, and the block group's three items spanning TWO
    symbols — the intra-function pair is two members of one symbol.  The
    segment population stays zero (the corpus's named residual), and the
    suppressed population never enters the family by construction."""
    model = canonical_model_from_legacy_document(corpus_report)
    groups = model.facts.analysis.clone_groups
    keys = {(row.clone_kind, row.group_key) for row in groups}
    assert len(groups) == 4
    assert len(keys) == 4
    assert sorted(kind for kind, _key in keys) == [
        "block",
        "function",
        "function",
        "function",
    ]
    (block,) = [row for row in groups if row.clone_kind == "block"]
    host_one = SymbolId(FileId("pkg/run_host_one.py"), "run_host_one")
    host_two = SymbolId(FileId("pkg/run_host_two.py"), "run_host_two")
    assert {(item.symbol, item.start_line, item.end_line) for item in block.items} == {
        (host_one, 13, 48),
        (host_one, 53, 67),
        (host_two, 9, 41),
    }
