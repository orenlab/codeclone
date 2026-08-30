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

from pathlib import Path

from codeclone.canonical import (
    ADOPTION_FEATURES,
    AdoptionCountRow,
    DeadCodeObservationRow,
    DependencyCycleRow,
    FileId,
    ModuleId,
    ModuleSymbol,
    OpaqueEntity,
    RunStore,
    SecuritySurfaceRow,
    SymbolId,
    canonical_model_from_legacy_document,
    decode_canonical_json,
    encode_canonical_json,
    signature_variant,
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


def test_f3_canonical_family_carries_the_corpus_adoption_scopes(
    corpus_report: dict[str, object],
) -> None:
    """F3 from the REAL producer document, on the ratified tagged ScopeRef.

    Measured ground truth (2026-08-26): 46 rows over 16 scopes; every
    feature of the closed vocabulary is populated; the hyphenated
    module-less carrier (``pkg/dead-orphan-probe.py``) is the corpus's one
    FILE-headed scope, and its docstring row carries a ZERO numerator —
    zero is measured in this family, never smuggled absence."""
    model = canonical_model_from_legacy_document(corpus_report)
    rows = model.facts.analysis.adoption_counts
    assert len(rows) == 46
    assert len({row.scope for row in rows}) == 16
    assert {row.feature for row in rows} == set(ADOPTION_FEATURES)
    file_scopes = {row.scope.path for row in rows if isinstance(row.scope, FileId)}
    assert file_scopes == {"pkg/dead-orphan-probe.py"}
    assert (
        AdoptionCountRow(
            FileId("pkg/dead-orphan-probe.py"), "docstrings.public_symbols", 0, 1
        )
        in rows
    )
    assert sum(1 for row in rows if row.numerator == 0) == 16


def test_f10_canonical_family_carries_the_s5_corpus_surfaces(
    corpus_s5_report: dict[str, object],
) -> None:
    """F10 from the REAL producer document over the slice-5 stage.

    Measured ground truth (2026-08-26): 11 rows, key (FILE, start_line,
    evidence_symbol) 11/11 distinct; every location scope populated
    (module 4 / callable 6 / class 1); both source-kind verdicts present
    (production 9 / tests 2); TWO evidence symbols share ONE (file, line)
    — the eval+compile datum — and one symbol repeats across two lines of
    one callable."""
    model = canonical_model_from_legacy_document(corpus_s5_report)
    rows = model.facts.analysis.security_surfaces
    assert len(rows) == 11
    keys = {(row.file, row.start_line, row.evidence_symbol) for row in rows}
    assert len(keys) == 11
    by_scope: dict[str, int] = {}
    for row in rows:
        by_scope[row.location_scope] = by_scope.get(row.location_scope, 0) + 1
    assert by_scope == {"module": 4, "callable": 6, "class": 1}
    assert {row.source_kind for row in rows} == {"production", "tests"}
    probe = FileId("pkg/security_probe.py")
    same_line = {
        row.evidence_symbol
        for row in rows
        if row.file == probe and row.start_line == 22
    }
    assert same_line == {"eval", "compile"}
    loads_lines = sorted(
        row.start_line for row in rows if row.evidence_symbol == "pickle.loads"
    )
    assert loads_lines == [26, 27]


def test_f10_s5_corpus_scopes_bind_their_local_names(
    corpus_s5_report: dict[str, object],
) -> None:
    """The scope/local-name binding on REAL rows: the tests-kind carrier
    row verbatim, the one class-scope row, and every module-scope row
    with its local name absent."""
    model = canonical_model_from_legacy_document(corpus_s5_report)
    rows = model.facts.analysis.security_surfaces
    assert (
        SecuritySurfaceRow(
            file=FileId("tests/test_shell_probe.py"),
            start_line=11,
            end_line=11,
            evidence_symbol="subprocess.call",
            qualname="test_shell_probe",
            location_scope="callable",
            category="process_boundary",
            capability="subprocess_call",
            evidence_kind="call",
            classification_mode="exact_call",
            source_kind="tests",
        )
        in rows
    )
    class_rows = [row for row in rows if row.location_scope == "class"]
    assert [(row.qualname, row.evidence_symbol) for row in class_rows] == [
        ("ShellHelper", "subprocess.check_output")
    ]
    module_rows = {row.qualname for row in rows if row.location_scope == "module"}
    assert module_rows == {None}


def test_dead_code_canonical_family_carries_the_tagged_variants(
    corpus_report: dict[str, object],
) -> None:
    """F4 from the REAL producer document, with the three K3 carriers.

    Measured ground truth (2026-08-26): 23 rows; the module-headed carrier
    contributes a ``symbol`` row AND an ``unreachable_statement`` row over
    the same glued head (span suffix ``#14-15``); the hyphenated carrier is
    the ONE FILE-headed entity of this corpus; the external-shim method is
    the one abstention.  The opaque variant stays corpus-unpopulated — a
    fact about the corpus, not the contract (synthetic inputs reach it).
    """
    model = canonical_model_from_legacy_document(corpus_report)
    rows = model.facts.analysis.dead_code_observations
    assert len(rows) == 23
    by_entity = {row.entity: row for row in rows}
    assert (
        by_entity[
            ModuleSymbol(ModuleId("pkg.dead_kinds"), "holds_unreachable")
        ].observation_kind
        == "symbol"
    )
    unreachable = by_entity[
        ModuleSymbol(ModuleId("pkg.dead_kinds"), "holds_unreachable#14-15")
    ]
    assert unreachable.observation_kind == "unreachable_statement"
    assert unreachable.source_markers == (("unreachable_reason", "after_terminator"),)
    file_headed = [row for row in rows if isinstance(row.entity, SymbolId)]
    assert [row.entity for row in file_headed] == [
        SymbolId(FileId("pkg/dead-orphan-probe.py"), "orphan_probe")
    ]
    abstained = [row for row in rows if row.abstained]
    assert [row.entity for row in abstained] == [
        ModuleSymbol(ModuleId("pkg.external_shim"), "ShimOverExternal.maybe_called")
    ]
    assert abstained[0].candidate_kind == "method"
    assert not any(isinstance(row.entity, OpaqueEntity) for row in rows)
    assert (
        DeadCodeObservationRow(
            entity=ModuleSymbol(ModuleId("pkg.external_shim"), "ShimOverExternal"),
            observation_kind="symbol",
            candidate_kind="class",
            reference_count=0,
            reachable=False,
            runtime_marker_count=0,
            source_markers=(),
            live_root_reason=None,
            abstained=False,
        )
        in rows
    )


# ---------------------------------------------------------------------------
# F5 lane-contract migration (ruling 2026-08-26): the api_surface lane row
# names its entity the way the ratified family key does, on REAL producer
# output.  Both wire-freeze stages above carry ZERO api_surface rows
# (measured: api-surface collection is off unless a project asks for it), so
# until this stage existed the lane's identity spelling had never met the
# ingest oracle on a live document.
# ---------------------------------------------------------------------------


def test_f5_canonical_family_carries_the_overload_corpus_symbols(
    corpus_f5_report: dict[str, object],
) -> None:
    """F5 from the REAL producer document over the overload stage.

    Measured ground truth (2026-08-26): 8 api_surface rows; the ratified
    key ``(SYMBOL, canonical_signature_variant)`` is 8/8 distinct while the
    SYMBOL alone is 4/8 and the variant alone is 5/8 — so BOTH halves of
    the key are load-bearing on this fixture, in both directions.  The row
    identity is the FILE-headed SYMBOL: a producer emitting the glued
    ``module:qualname`` spelling is refused by the ingest oracle, which is
    exactly what a full self-repo report used to do.
    """
    model = canonical_model_from_legacy_document(corpus_f5_report)
    rows = model.facts.analysis.api_symbols
    assert len(rows) == 8
    carrier = FileId("pkg/api_overloads.py")
    assert {row.symbol.file for row in rows} == {carrier}
    assert {row.symbol.qualname for row in rows} == {
        "Renderer",
        "Renderer.emit",
        "describe",
        "render",
    }
    # The collapse the ratified key exists to prevent: three declarations
    # of one qualname at module level, three more inside the class.
    by_qualname: dict[str, int] = {}
    for row in rows:
        by_qualname[row.symbol.qualname] = by_qualname.get(row.symbol.qualname, 0) + 1
    assert by_qualname == {
        "Renderer": 1,
        "Renderer.emit": 3,
        "describe": 1,
        "render": 3,
    }
    variants = {
        signature_variant(parameters=row.parameters, returns_digest=row.returns_digest)
        for row in rows
    }
    # 5 distinct variants over 8 rows: ``render`` and ``Renderer.emit``
    # share their three signatures pairwise, so the variant alone cannot
    # name a row either.
    assert len(variants) == 5
    assert {row.symbol_kind for row in rows} == {"class", "function", "method"}
    assert {row.visibility for row in rows} == {"all"}


def test_f5_overload_corpus_ingests_whole_and_satisfies_l8(
    corpus_f5_report: dict[str, object], tmp_path: Path
) -> None:
    """The live-document half of law L8, on a real producer report.

    L8 (``project(store) == project(model)``) was proven on the synthetic
    fixture model and on the corpus families; this pins it end to end from
    a document the CLI actually wrote — the coverage that the glued
    api_surface identity used to make impossible, because the ingest
    refused before a model ever existed.
    """
    model = canonical_model_from_legacy_document(corpus_f5_report)
    model_bytes = encode_canonical_json(model)
    with RunStore(tmp_path / "runs.sqlite") as store:
        receipt = store.write_full_run(
            model,
            namespace="f5-corpus",
            target="overload-stage",
            expected_generation=0,
        )
        assert store.project_run(receipt.run_id) == model_bytes
        assert decode_canonical_json(model_bytes) == model.normalize()
        assert store.read_run(receipt.run_id) == model.normalize()


# ---------------------------------------------------------------------------
# F7 / F8 distinguishing stages (ruling 2026-08-24 §10).  Both families are
# named there as "keys not proven by data (0 rows)"; measured on this HEAD the
# self-repository carries 0 dependency_cycles and 0 emitted clone_groups, and
# the base wire-freeze corpus carries rows whose LOAD-BEARING key components
# are still unexercised.  These stages exist to exercise them.
# ---------------------------------------------------------------------------


def test_f7_family_key_keeps_the_module_member_boundary(
    corpus_f7_report: dict[str, object],
) -> None:
    """F7 on REAL producer output: the key is the MODULE SET, and the set's
    member boundary is load-bearing.

    The stage carries two disjoint strongly connected components of the SAME
    kind whose sorted member names concatenate to one identical dotted text
    (``{a, b.c}`` and ``{a.b, c}`` both flatten to ``a.b.c``).  A key that
    flattened its members into one string — the ``string equality is not
    entity equality`` failure the ratified MODULE domain forbids (ruling
    2026-08-24 §2) — would fold the two rows into one.
    """
    model = canonical_model_from_legacy_document(corpus_f7_report)
    rows = model.facts.analysis.dependency_cycles
    assert len(rows) == 4
    assert len({row.modules for row in rows}) == 4
    flattened = {
        (row.kind, ".".join(sorted(module.module for module in row.modules)))
        for row in rows
    }
    assert len(flattened) == 3
    collided = sorted(
        tuple(sorted(module.module for module in row.modules))
        for row in rows
        if ".".join(sorted(module.module for module in row.modules)) == "a.b.c"
    )
    assert collided == [("a", "b.c"), ("a.b", "c")]
    assert {
        row.kind
        for row in rows
        if ".".join(sorted(module.module for module in row.modules)) == "a.b.c"
    } == {"import_cycle"}


def test_f7_family_classifies_one_row_per_set_across_bindings(
    corpus_f7_report: dict[str, object],
) -> None:
    """The opposite boundary: the key must NOT split one entity.

    ``{f, g}`` carries an import-time cycle AND a deferred back-edge over the
    same pair; the family law is one row per module SET with the kind
    classified exactly once, so a per-binding row would break the 1:1 between
    rows and sets.  ``{d, e}`` pins the other classification verdict, so a
    classifier stuck on either constant reddens here.
    """
    model = canonical_model_from_legacy_document(corpus_f7_report)
    rows = model.facts.analysis.dependency_cycles
    by_set = {row.modules: row.kind for row in rows}
    assert len(by_set) == len(rows)
    assert by_set[frozenset({ModuleId("f"), ModuleId("g")})] == "import_cycle"
    assert by_set[frozenset({ModuleId("d"), ModuleId("e")})] == "deferred_cycle"


def _emitted_clone_keys(document: dict[str, object]) -> set[tuple[str, str]]:
    clones = document["findings"]["groups"]["clones"]  # type: ignore[index]
    return {
        (kind, str(group["facts"]["group_key"]))
        for container, kind in (
            ("functions", "function"),
            ("blocks", "block"),
            ("segments", "segment"),
        )
        for group in clones[container]
    }


def _suppressed_clone_keys(document: dict[str, object]) -> set[tuple[str, str]]:
    clones = document["findings"]["groups"]["clones"]  # type: ignore[index]
    suppressed = clones.get("suppressed") or {}
    return {
        (kind, str(group["facts"]["group_key"]))
        for container, kind in (
            ("functions", "function"),
            ("blocks", "block"),
            ("segments", "segment"),
        )
        for group in suppressed.get(container, ())
    }


def test_f8_family_carries_the_emitted_population_and_not_the_suppressed(
    corpus_f8_report: dict[str, object],
) -> None:
    """F8's named residual, closed: suppressed is a DIFFERENT population.

    Until this stage no available input carried both populations at once —
    the self-repository measured 17 suppressed groups beside 0 emitted, and
    every wire-freeze stage carried emitted groups with the ``suppressed``
    container absent, so ``clones.suppressed`` never entered the oracle in
    ANY configuration and the family's exclusion of it could not fire.
    """
    emitted = _emitted_clone_keys(corpus_f8_report)
    suppressed = _suppressed_clone_keys(corpus_f8_report)
    assert emitted, "the stage must carry a non-empty EMITTED clone population"
    assert suppressed, "the stage must carry a non-empty SUPPRESSED clone population"
    assert not (emitted & suppressed)
    model = canonical_model_from_legacy_document(corpus_f8_report)
    rows = model.facts.analysis.clone_groups
    assert {(row.clone_kind, row.group_key) for row in rows} == emitted
    assert len(rows) == 6
    # The policy-held lane is shaped by ``merge_segment_report_groups`` and is
    # no longer re-judged by the ACTIVE lane's low-value filter, so the
    # container now publishes every group the user rule withheld.  Under the
    # double filter this corpus reported 3: the filter deleted half of the
    # evidence the document had promised to publish, and dropped the count of
    # what it deleted at the same time.
    assert len(suppressed) == 6


def test_f8_family_witnesses_every_emitted_container(
    corpus_f8_report: dict[str, object],
) -> None:
    """Every entry of the emitted-container tuple is reached by a row, and the
    block group's members keep their spans.

    The segment container had never carried a row on any corpus, so dropping
    it changed nothing observable; here it carries three.  The block group
    repeats one SYMBOL at two spans, so a span-blind member identity collapses
    its arity from three to two.
    """
    model = canonical_model_from_legacy_document(corpus_f8_report)
    rows = model.facts.analysis.clone_groups
    per_kind: dict[str, int] = {}
    for row in rows:
        per_kind[row.clone_kind] = per_kind.get(row.clone_kind, 0) + 1
    assert per_kind == {"function": 1, "block": 2, "segment": 3}
    host_one = SymbolId(FileId("pkg/emit_host_one.py"), "emit_host_one")
    host_two = SymbolId(FileId("pkg/emit_host_two.py"), "emit_host_two")
    (widest,) = [
        row for row in rows if row.clone_kind == "block" and len(row.items) == 3
    ]
    assert {(item.symbol, item.start_line, item.end_line) for item in widest.items} == {
        (host_one, 5, 40),
        (host_one, 45, 59),
        (host_two, 5, 40),
    }
