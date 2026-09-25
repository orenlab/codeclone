# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Shadow equivalence of the canonical projections (epoch E1, cycle 4).

Every pin here holds a projection built from the run store's rows against
the bytes a consumer actually reads — the rendered document's finding
groups and metric summaries, and the MCP surface's own ``get_run_summary``
/ ``get_production_triage`` answers of an execution the surface published
itself — restricted to the ANALYSIS-tier keys the projection claims, and
compared byte for byte as JSON in the consumer's own key order.

Five populations, each stated before it is compared (Probe Validity Law):
three CLI-documented runs — the E1 corpus, which populates every tracked
family but authority (a family compared at zero groups proves nothing);
the projection corpus of ``tests/conftest.py``, which carries the
dependency cycle, the opaque dynamic load, the multi-row security family
and the three-member clone group the E1 corpus does not; and the
projection-equivalence probe corpus, the one CLI document in this suite
that carries authority violations — and two MCP-published runs, of the
serving corpus and of that same projection corpus, where the surface's
answers are the oracle.
What is NOT compared is named in ``UNPROJECTED_GROUP_KEYS`` and in
``_MEMORY_ONLY_SUMMARY_KEYS`` below, so the claim "store-equivalent" is
exactly as wide as the set this file proves and no wider.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace

import pytest

from codeclone.canonical import (
    PROJECTED_FAMILIES,
    UNPROJECTED_GROUP_KEYS,
    CanonicalModel,
    CoverageJoinRecord,
    projected_finding_groups,
    suppressed_clone_skeletons,
)
from codeclone.canonical import summary_projection as summary
from codeclone.canonical.authority_projection import violation_projection_rows
from codeclone.canonical.finding_projection import (
    CLONE_FACT_KEYS,
    SITE_ITEM_KEYS,
    group_order,
)
from codeclone.canonical.store import RunStore
from codeclone.contracts import CLONE_GROUP_BUCKET_KEYS, FAMILY_CLONES
from codeclone.core.canonical_snapshot import RUN_SNAPSHOT_NAMESPACE
from codeclone.domain.findings import FAMILY_CLONE
from codeclone.findings.ids import authority_group_id
from codeclone.models import CANONICAL_HEAD_TARGET
from codeclone.utils.coerce import as_mapping, as_sequence
from tests._projection_equivalence import build_corpus
from tests._served_run import ServedRunStoreProjection
from tests.conftest import materialize_projection_corpus
from tests.test_canonical_authority_projection import _tying_violation_model
from tests.test_canonical_roundtrip import analysis_facts
from tests.test_run_store_producer_wiring import e1_run

__all__ = ["e1_run"]

_Group = Mapping[str, object]
_DocumentRun = tuple[dict[str, object], CanonicalModel]


@pytest.fixture(scope="module")
def projection_run(tmp_path_factory: pytest.TempPathFactory) -> _DocumentRun:
    """One enabled full run over the projection corpus with the CLI, whose
    rendered document is the oracle for the three cases the E1 corpus
    does not carry (see the corpus note in ``tests/conftest.py``)."""
    from tests.conftest import _run_codeclone_cli

    root = tmp_path_factory.mktemp("projection_corpus").resolve()
    materialize_projection_corpus(root)
    store = root / "runs.sqlite3"
    report_path = root / "report.json"
    _run_codeclone_cli(
        [
            str(root),
            "--no-progress",
            "--baseline",
            str(root / "corpus.baseline.json"),
            "--fail-health",
            "0",
            "--json",
            str(report_path),
        ],
        {
            "CODECLONE_RUN_STORE_FORCE": "1",
            "CODECLONE_RUN_STORE_ENABLED": "1",
            "CODECLONE_RUN_STORE_PATH": str(store),
        },
    )
    document: dict[str, object] = json.loads(report_path.read_text("utf-8"))
    with RunStore(store) as run_store:
        head = run_store.head(
            namespace=RUN_SNAPSHOT_NAMESPACE, target=CANONICAL_HEAD_TARGET
        )
        assert head is not None, "the projection corpus run published nothing"
        return document, run_store.read_run(head.run_id)


@pytest.fixture(scope="module")
def authority_run(tmp_path_factory: pytest.TempPathFactory) -> _DocumentRun:
    """The projection-equivalence probe corpus: the one CLI document of
    this suite that carries authority violations (26 of them, measured
    2026-09-25; the wiring corpus's semantic run carries 0), read back
    through the store so the authority skeletons are held against a
    document rather than against their own builders."""
    base = tmp_path_factory.mktemp("authority_corpus").resolve()
    (base / "tree").mkdir()
    corpus = build_corpus(base / "tree", store_path=base / "runs.sqlite3")
    return dict(corpus.document), corpus.stored_model


@pytest.fixture(params=["e1_run", "projection_run", "authority_run"])
def document_run(request: pytest.FixtureRequest) -> _DocumentRun:
    """The three CLI-documented populations, one at a time."""
    run: _DocumentRun = request.getfixturevalue(request.param)
    return run


@pytest.fixture(params=["served_run_store_projection", "served_projection_corpus"])
def served_run(request: pytest.FixtureRequest) -> ServedRunStoreProjection:
    """Both MCP-published populations, one at a time."""
    served: ServedRunStoreProjection = request.getfixturevalue(request.param)
    return served


def _served_model(served: ServedRunStoreProjection) -> CanonicalModel:
    with RunStore(served.store_path) as store:
        return store.read_run(served.store_run_id)


#: ``get_run_summary`` keys the store does not answer in E1, by the tier the
#: serving census assigned them; they stay with the parent's memory until
#: the tier's own epoch wave.
_MEMORY_ONLY_SUMMARY_KEYS: Mapping[str, str] = {
    "run_id": "evaluation (report identity)",
    "focus": "presentation",
    "health_scope": "presentation",
    "version": "execution",
    "code_provenance": "execution",
    "schema": "analysis contract without a store carrier",
    "baseline": "comparison",
    "metrics_baseline": "comparison",
    "cache": "execution",
    "health": "evaluation",
    "diff": "comparison",
    "warnings": "execution",
    "failures": "execution",
    "drifted_files": "execution",
    "next_tool": "presentation",
}

#: Attached by the surface only when it has something to say (the hygiene
#: block, the gitignore tip); named so the exclusion is complete without
#: asserting a key the answer may not carry.
_MEMORY_ONLY_OPTIONAL_SUMMARY_KEYS: Mapping[str, str] = {
    "workspace_hygiene": "session",
    "tips": "presentation",
}


def _canonical(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _restricted(group: _Group, family: str) -> dict[str, object]:
    """The document group with the unprojected keys and, for the clone
    family, the unprojected item metrics and facts removed — nothing else
    touched, key order kept."""
    restricted: dict[str, object] = {}
    for key, value in group.items():
        if key in UNPROJECTED_GROUP_KEYS:
            continue
        if family == FAMILY_CLONE and key == "items":
            value = [
                {name: as_mapping(item)[name] for name in SITE_ITEM_KEYS}
                for item in as_sequence(value)
            ]
        if family == FAMILY_CLONE and key == "facts":
            value = {name: as_mapping(value)[name] for name in CLONE_FACT_KEYS}
        restricted[key] = value
    return restricted


def _document_family(groups_root: Mapping[str, object], family: str) -> list[_Group]:
    container = as_mapping(
        groups_root.get(FAMILY_CLONES if family == FAMILY_CLONE else family)
    )
    if family == FAMILY_CLONE:
        raw: list[object] = [
            group
            for bucket in CLONE_GROUP_BUCKET_KEYS
            for group in as_sequence(container.get(bucket))
        ]
    else:
        raw = list(as_sequence(container.get("groups")))
    return sorted(
        (_restricted(as_mapping(group), family) for group in raw), key=group_order
    )


def _document_suppressed(groups_root: Mapping[str, object]) -> list[_Group]:
    suppressed = as_mapping(
        as_mapping(groups_root.get(FAMILY_CLONES)).get("suppressed")
    )
    raw = [
        group
        for bucket in CLONE_GROUP_BUCKET_KEYS
        for group in as_sequence(suppressed.get(bucket))
    ]
    return sorted(
        (_restricted(as_mapping(group), FAMILY_CLONE) for group in raw), key=group_order
    )


# -- the rendered document of the E1 corpus ----------------------------------


def test_every_projected_family_matches_the_document_byte_for_byte(
    document_run: _DocumentRun,
) -> None:
    """A2/A3: the projected skeleton of each group equals the document's
    group with the unprojected keys removed — same keys, same order, same
    bytes — on both documented populations (their distinguishing cases are
    accounted for in ``test_the_populations_carry_the_distinguishing_cases``)."""
    document, model = document_run
    groups_root = as_mapping(as_mapping(document.get("findings")).get("groups"))
    projected = projected_finding_groups(model)
    assert set(projected) == set(PROJECTED_FAMILIES)
    for family in PROJECTED_FAMILIES:
        expected = _document_family(groups_root, family)
        assert _canonical(projected[family]) == _canonical(expected), family
    # A1: the suppressed population, apart from the emitted one.
    suppressed = _document_suppressed(groups_root)
    assert _canonical(suppressed_clone_skeletons(model)) == _canonical(suppressed)
    assert {group["id"] for group in suppressed}.isdisjoint(
        group["id"] for group in projected[FAMILY_CLONE]
    )


def test_the_unprojected_keys_are_exactly_what_the_document_carries_beyond_the_skeleton(
    e1_run: tuple[dict[str, object], CanonicalModel],
) -> None:
    """The exclusion list is a measurement, both directions: every listed
    key is one the document really publishes on some group (an exclusion
    nothing carries is narration), and no document key is left unnamed."""
    document, _model = e1_run
    groups_root = as_mapping(as_mapping(document.get("findings")).get("groups"))
    published: set[str] = set()
    projected_keys: set[str] = set()
    projected = projected_finding_groups(_model)
    for family in PROJECTED_FAMILIES:
        for group in _document_family(groups_root, family):
            projected_keys.update(group)
        container = as_mapping(
            groups_root.get(FAMILY_CLONES if family == FAMILY_CLONE else family)
        )
        raw = (
            [g for b in CLONE_GROUP_BUCKET_KEYS for g in as_sequence(container.get(b))]
            if family == FAMILY_CLONE
            else list(as_sequence(container.get("groups")))
        )
        for raw_group in raw:
            published.update(as_mapping(raw_group))
        for group in projected[family]:
            projected_keys.update(group)
    # ``display_facts`` rides only a block group with machine facts, which
    # this corpus does not produce; every other exclusion is carried here.
    assert set(UNPROJECTED_GROUP_KEYS) - published == {"display_facts"}
    assert published - set(UNPROJECTED_GROUP_KEYS) == projected_keys


def test_the_summary_projections_match_the_document(
    document_run: _DocumentRun,
) -> None:
    """A6/A7 and the run-summary analysis fields against the document's
    own sections: the profile, the inventory scalars, the family counts,
    the dead-code and coverage summaries, the three design maxima, the
    authority counters and the dynamic boundaries."""
    document, model = document_run
    meta = as_mapping(document.get("meta"))
    families = as_mapping(as_mapping(document.get("metrics")).get("families"))
    assert summary.analysis_mode(model) == meta["analysis_mode"]
    assert summary.analysis_profile(model) == meta["analysis_profile"]
    inventory = as_mapping(document.get("inventory"))
    code = as_mapping(inventory.get("code"))
    assert summary.inventory(model) == {
        "files": as_mapping(inventory.get("files"))["total_found"],
        "lines": code["parsed_lines"],
        "functions": int(str(code["functions"])) + int(str(code["methods"])),
        "classes": code["classes"],
    }
    counts = summary.finding_counts(model)
    findings_summary = as_mapping(as_mapping(document.get("findings")).get("summary"))
    assert counts["total"] == findings_summary["total"]
    assert counts["by_family"] == dict(
        sorted(as_mapping(findings_summary["families"]).items())
    )
    dead = summary.dead_code(model)
    dead_summary = as_mapping(as_mapping(families.get("dead_code")).get("summary"))
    assert dead == {key: dead_summary[key] for key in dead}
    coverage = summary.coverage_join(model)
    coverage_summary = as_mapping(
        as_mapping(families.get("coverage_join")).get("summary")
    )
    assert coverage == {key: coverage_summary[key] for key in coverage}
    maxima = summary.design_maxima(model.facts.analysis)
    assert maxima == {
        f"{category}_max": as_mapping(
            as_mapping(families.get(category)).get("summary")
        )["max"]
        for category in ("complexity", "coupling", "cohesion")
    }
    security_summary = as_mapping(
        as_mapping(families.get("security_surfaces")).get("summary")
    )
    assert summary.security_surface_modules(model) == security_summary.get("modules", 0)
    authority_summary = as_mapping(
        as_mapping(families.get("semantic_authority")).get("summary")
    )
    assert summary.authority_counts(model.facts.analysis) == {
        key: authority_summary[key]
        for key in ("violations", "active_violations", "suppressed_violations")
    }
    boundaries = as_sequence(
        as_mapping(families.get("dependencies")).get("dynamic_boundaries")
    )
    assert summary.dynamic_boundaries(model) == [
        {
            "source": {
                "file": {
                    "path": as_mapping(
                        as_mapping(as_mapping(site).get("source")).get("file")
                    )["path"]
                }
            },
            "syntax_kind": as_mapping(site)["syntax_kind"],
            "reason": as_mapping(site)["reason"],
        }
        for site in boundaries
    ]


# -- an MCP-published run: the surface's own answers are the oracle ---------


def _projected_summary_fields(model: CanonicalModel) -> dict[str, object]:
    fields: dict[str, object] = {
        "mode": summary.analysis_mode(model),
        "inventory": summary.inventory(model),
    }
    profile = summary.analysis_profile(model)
    if profile:
        fields["analysis_profile"] = profile
    dead = summary.dead_code(model)
    if dead:
        fields["dead_code"] = dead
    coverage = summary.coverage_join(model)
    if coverage:
        fields["coverage_join"] = coverage
    surfaces = summary.security_surfaces(model)
    if surfaces:
        fields["security_surfaces"] = surfaces
    return fields


def test_the_run_summary_analysis_fields_match_the_mcp_surface(
    served_run: ServedRunStoreProjection,
) -> None:
    """The MCP execution's own ``get_run_summary`` against the projection
    of the run that execution published (measured 2026-09-25 on the
    serving and the projection corpora: mode, profile, inventory, findings
    counts, dead-code block, security surfaces; coverage absent on both
    sides).  The keys the store does not answer are named, not silently
    skipped."""
    payload = served_run.run_summary
    assert set(_MEMORY_ONLY_SUMMARY_KEYS) <= set(payload), sorted(
        set(_MEMORY_ONLY_SUMMARY_KEYS) - set(payload)
    )
    model = _served_model(served_run)
    assert set(payload) - set(
        projected_keys := set(_projected_summary_fields(model))
    ) <= (
        set(_MEMORY_ONLY_SUMMARY_KEYS)
        | set(_MEMORY_ONLY_OPTIONAL_SUMMARY_KEYS)
        | {"findings"}
    ), "an answer key neither projected nor named as memory-only"
    projected = _projected_summary_fields(model)
    assert projected_keys == set(projected)
    for key, value in projected.items():
        _assert_summary_field(payload, key, value)
    assert "coverage_join" not in payload
    assert "coverage_join" not in projected
    findings = as_mapping(payload["findings"])
    counts = summary.finding_counts(model)
    assert counts["total"] == findings["total"]
    # One fact, two spellings (measured 2026-09-25): the document's
    # ``findings.summary.families`` names all five families, the surface's
    # ``by_family`` only those that carry a group.  The projection answers
    # the total spelling; the surface's is its non-zero restriction.
    assert _non_zero(counts["by_family"]) == findings["by_family"]
    assert counts["production"] == findings["production"]
    assert as_mapping(payload["security_surfaces"])["items"], "no surface rows"
    assert counts["total"], "no finding groups"


def _assert_summary_field(
    payload: Mapping[str, object], key: str, value: object
) -> None:
    """One projected field against the surface's answer: the security
    block on the analysis half the projection claims (the surface adds
    ``report_only`` and ``note``), everything else byte for byte."""
    if key != "security_surfaces":
        assert _canonical(value) == _canonical(payload[key]), key
        return
    surface_block = as_mapping(payload[key])
    expected = as_mapping(value)
    assert expected == {name: surface_block[name] for name in expected}, key
    assert surface_block["report_only"] is True


def _non_zero(counts: object) -> dict[str, object]:
    return {family: count for family, count in as_mapping(counts).items() if count}


def test_the_production_triage_analysis_fields_match_the_mcp_surface(
    served_run: ServedRunStoreProjection,
) -> None:
    payload = served_run.production_triage
    model = _served_model(served_run)
    counts = summary.finding_counts(model)
    findings = as_mapping(payload["findings"])
    assert counts["total"] == findings["total"]
    assert counts["by_source_kind"] == findings["by_source_kind"]
    assert summary.analysis_profile(model) == payload["analysis_profile"]
    surface_block = as_mapping(payload["security_surfaces"])
    surfaces = summary.security_surfaces(model)
    assert surfaces == {name: surface_block[name] for name in surfaces}
    assert "coverage_join" not in payload
    for key in ("top_hotspots", "suggestions", "top_suggestions", "health"):
        assert key in payload, "memory-only keys the store does not answer"


def test_the_e1_corpus_carries_every_projected_family(e1_run: _DocumentRun) -> None:
    """The accounting behind the equalities above (Probe Validity Law): a
    family compared at zero groups would let a wrong projection pass, so
    the E1 population is shown to carry what its pins need before the pins
    count."""
    document, model = e1_run
    groups_root = as_mapping(as_mapping(document.get("findings")).get("groups"))
    empty = {
        family
        for family in PROJECTED_FAMILIES
        if not _document_family(groups_root, family)
    }
    assert empty == {"authority"}, "every tracked family but authority has a group"
    assert _document_suppressed(groups_root)
    dead = summary.dead_code(model)
    assert (dead["total"], dead["high_confidence"]) == (2, 2)
    assert summary.coverage_join(model)["coverage_hotspots"] == 1
    assert summary.design_maxima(model.facts.analysis)["complexity_max"] == 22
    assert summary.dynamic_boundaries(model) == []
    assert summary.security_surfaces(model) == {}


@pytest.fixture(params=["cli_document", "mcp_published"])
def projection_population(
    request: pytest.FixtureRequest,
    projection_run: _DocumentRun,
    served_projection_corpus: ServedRunStoreProjection,
) -> CanonicalModel:
    """The projection corpus as the CLI documented it and as the MCP
    surface published it — the same tree, two executions."""
    if request.param == "cli_document":
        return projection_run[1]
    return _served_model(served_projection_corpus)


def test_the_projection_corpus_carries_the_cases_the_e1_corpus_lacks(
    projection_population: CanonicalModel,
) -> None:
    """A cycle of one member, a boundary list of none, a security family
    with one row per category or a clone group of two would let a wrong
    projection pass; this population carries the distinguishing shape of
    each, on both executions."""
    population = projection_population
    cycles = [
        group
        for group in projected_finding_groups(population)["design"]
        if group["category"] == "dependency"
    ]
    assert [group["count"] for group in cycles] == [2]
    members = [as_mapping(item)["module"] for item in as_sequence(cycles[0]["items"])]
    assert members == ["pkg.cyc_a", "pkg.cyc_b"]
    assert summary.dynamic_boundaries(population) == [
        {
            "source": {"file": {"path": "pkg/loader.py"}},
            "syntax_kind": "import",
            "reason": "dynamic_load_argument_opaque",
        }
    ]
    # Five rows over two categories: the three ``eval`` sites, plus the
    # ``import importlib`` statement and the ``import_module`` call the
    # detector both files as dynamic loading — so a category count that
    # counted rows, or a split that was a constant, cannot pass.
    assert summary.security_surfaces(population) == {
        "items": 5,
        "categories": 2,
        "production": 4,
        "tests": 1,
    }
    arities = [
        as_mapping(group["facts"])["group_arity"]
        for group in projected_finding_groups(population)[FAMILY_CLONE]
    ]
    assert arities == [3], "the one clone group has three members"
    assert summary.security_surface_modules(population) == 3


def test_the_authority_corpus_carries_violations(authority_run: _DocumentRun) -> None:
    """The population the authority pin rides: unsuppressed violation
    groups, so a skeleton that never reached the row loop would show."""
    document, model = authority_run
    groups_root = as_mapping(as_mapping(document.get("findings")).get("groups"))
    assert len(_document_family(groups_root, "authority")) == 26
    assert len(projected_finding_groups(model)["authority"]) == 26
    assert summary.authority_counts(model.facts.analysis) == {
        "violations": 26,
        "active_violations": 26,
        "suppressed_violations": 0,
    }


def test_a_suppressed_violation_is_not_a_published_group() -> None:
    """The document publishes one authority group per UNSUPPRESSED
    violation and counts the suppressed ones apart (``findings.py``,
    ``_build_authority_groups``); no CLI corpus of this suite carries a
    suppressed violation, so the skip is reached here on a synthetic row."""
    model = _tying_violation_model()
    rows = sorted(
        model.facts.analysis.violations,
        key=lambda row: sorted(producer.qualname for producer in row.producer_set),
    )
    suppressed = replace(rows[0], suppressed=True)
    model = replace(
        model, facts=analysis_facts(violations=frozenset([suppressed, *rows[1:]]))
    )
    published = {
        str(group["id"]) for group in projected_finding_groups(model)["authority"]
    }
    hidden = {
        authority_group_id(str(row["contract_id"]), str(row["violation_id"]))
        for row in violation_projection_rows(model)
        if row["suppressed"]
    }
    assert len(hidden) == 1
    assert len(published) == len(rows) - 1
    assert hidden.isdisjoint(published)
    assert summary.authority_counts(model.facts.analysis) == {
        "violations": len(rows),
        "active_violations": len(rows) - 1,
        "suppressed_violations": 1,
    }


def test_absent_records_answer_the_empty_block_and_an_invalid_join_its_reason() -> None:
    """Four-state law on the summary side: a run that carries no
    population, no scalars, no dead-code record and no coverage join
    answers the EMPTY block — the surface's own absence spelling — never
    a zero-filled one; an invalid join carries its source and reason and
    projects zero hotspots over no units."""
    bare = CanonicalModel()
    assert summary.analysis_mode(bare) == ""
    assert summary.analysis_profile(bare) == {}
    assert summary.inventory(bare) == {}
    assert summary.dead_code(bare) == {}
    assert summary.coverage_join(bare) == {}
    assert summary.security_surfaces(bare) == {}
    assert summary.security_surface_modules(bare) == 0
    assert summary.dynamic_boundaries(bare) == []
    invalid = CanonicalModel(
        facts=analysis_facts(
            coverage_join=CoverageJoinRecord(
                status="invalid",
                source="coverage.xml",
                files=0,
                hotspot_threshold_percent=50,
                invalid_reason="bad xml",
            )
        )
    )
    assert summary.coverage_join(invalid) == {
        "status": "invalid",
        "overall_permille": 0,
        "coverage_hotspots": 0,
        "scope_gap_hotspots": 0,
        "hotspot_threshold_percent": 50,
        "source": "coverage.xml",
        "invalid_reason": "bad xml",
    }


# -- the projection alone: order, identity and the E1 corpus shapes ----------


def test_family_lists_are_in_the_total_analysis_order(
    e1_run: tuple[dict[str, object], CanonicalModel],
) -> None:
    _document, model = e1_run
    for family, groups in projected_finding_groups(model).items():
        keys = [group_order(group) for group in groups]
        assert keys == sorted(keys), family
        assert len(keys) == len(set(keys)), family


@pytest.mark.parametrize(
    ("family", "identities"),
    [
        ("structural", {"structural:duplicated_branches:"}),
        (
            "dead_code",
            {
                "dead_code:pkg.hub:_orphan",
                "dead_code:pkg.hub:_tested_helper",
                "dead_code:pkg.hub:stop#",
            },
        ),
        (
            "design",
            {
                "design:complexity:pkg.hub:maze",
                "design:coupling:pkg.hub:Hub",
                "design:cohesion:pkg.hub:Scattered",
                "design:coverage:pkg.hub:maze",
            },
        ),
    ],
)
def test_the_finding_identities_are_spelled_through_the_one_owner(
    e1_run: tuple[dict[str, object], CanonicalModel],
    family: str,
    identities: set[str],
) -> None:
    """A3: every identity is the document's (glued producer key, the
    ``findings.ids`` spelling), stated by literal on the E1 corpus."""
    _document, model = e1_run
    published = [str(group["id"]) for group in projected_finding_groups(model)[family]]
    for identity in identities:
        assert any(candidate.startswith(identity) for candidate in published), identity


def _paths(groups: Sequence[_Group]) -> set[str]:
    return {
        str(as_mapping(item)["relative_path"])
        for group in groups
        for item in as_sequence(group["items"])
    }


def test_source_scope_and_spread_are_derived_from_the_sites(
    e1_run: tuple[dict[str, object], CanonicalModel],
) -> None:
    _document, model = e1_run
    projected = projected_finding_groups(model)
    suppressed = suppressed_clone_skeletons(model)
    assert _paths(suppressed) == {
        "tests/fixtures/golden_a/dup.py",
        "tests/fixtures/golden_b/dup.py",
    }
    (group,) = suppressed
    assert as_mapping(group["source_scope"])["dominant_kind"] == "fixtures"
    # Two files, two GLUED qualnames (``…golden_a.dup:sample`` and
    # ``…golden_b.dup:sample``): the document's spread counts producer keys.
    assert group["spread"] == {"files": 2, "functions": 2}
    for group in projected["dead_code"]:
        assert as_mapping(group["source_scope"])["dominant_kind"] == "production"
        assert group["spread"] == {"files": 1, "functions": 1}
