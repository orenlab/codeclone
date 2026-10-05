# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The producer half of the publication's cheaper road, pinned per change.

Three changes live on the producer side of the edge, each with its own pin:

* the cyclic garbage collector is paused for one publication and handed
  back in the state the caller left it, on every way out;
* the model is normalized once per publication -- by the store -- and the
  producer builder no longer closes it a second time;
* the authority tier asks the identity grammar each question once per
  publication, and the answers die with the publication.

The stored bytes these changes may not move are held by
``test_run_store_publication_byte_identity``.
"""

from __future__ import annotations

import gc
from collections.abc import Iterator, Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

import codeclone.core.canonical_snapshot as snapshot_module
from codeclone.canonical.identity import VIOLATION_KINDS, EffectRoot, SymbolId
from codeclone.canonical.model import CanonicalModel
from codeclone.canonical.semantic_grammar import (
    IdentityIndex,
    build_identity_index,
    parse_root_set,
    parse_symbol,
    parse_symbol_set,
)
from codeclone.core._types import AnalysisResult, DiscoveryResult, ProcessingResult
from codeclone.core.canonical_snapshot import (
    _semantic_families,
    publish_run_snapshot,
)
from codeclone.models import (
    RUN_SNAPSHOT_PUBLICATION_FAILED,
    RUN_SNAPSHOT_PUBLICATION_UNSTORED,
    RunSnapshotPublication,
    RunStoreConfig,
)
from tests._ast_metrics_helpers import module_registry_context
from tests.test_observation_contract import TEST_OBSERVATION_BUNDLE


def _enabled(tmp_path: Path) -> RunStoreConfig:
    return RunStoreConfig(enabled=True, path=tmp_path / "db" / "runs.sqlite3")


@pytest.fixture
def collector_restored() -> Iterator[None]:
    """Whatever a test does to the collector, the suite gets it back on."""
    try:
        yield
    finally:
        gc.enable()


# -- the cyclic collector ----------------------------------------------------


_FULL_RUN_META: dict[str, object] = {"analysis_mode": "full", "metrics_computed": []}


def _publish(tmp_path: Path) -> RunSnapshotPublication:
    """One real enabled publication of a one-file run into a temporary store:
    real producer results that parsed one file and produced nothing else."""
    discovery = DiscoveryResult(
        files_found=1,
        cache_hits=0,
        files_skipped=0,
        all_file_paths=(),
        cached_units=(),
        cached_blocks=(),
        cached_segments=(),
        cached_class_metrics=(),
        cached_module_deps=(),
        cached_dead_candidates=(),
        cached_referenced_names=frozenset(),
        files_to_process=(),
        skipped_warnings=(),
        module_registry=module_registry_context(
            filepath="placeholder.py", module_name="placeholder"
        )[1],
    )
    analysis = AnalysisResult(
        func_groups={},
        block_groups={},
        block_groups_report={},
        segment_groups={},
        low_value_segment_groups=0,
        block_group_facts={},
        func_clones_count=0,
        block_clones_count=0,
        segment_clones_count=0,
        files_analyzed_or_cached=1,
        project_metrics=None,
        metrics_payload=None,
        suggestions=(),
        segment_groups_raw_digest="",
        observation_bundle=TEST_OBSERVATION_BUNDLE,
        near_miss_pairs=None,
        renamed_structure_groups=None,
    )
    processing = ProcessingResult(
        units=(),
        blocks=(),
        segments=(),
        class_metrics=(),
        module_deps=(),
        dead_candidates=(),
        referenced_names=frozenset(),
        files_analyzed=1,
        files_skipped=0,
        analyzed_lines=0,
        analyzed_functions=0,
        analyzed_methods=0,
        analyzed_classes=0,
        failed_files=(),
        source_read_failures=(),
    )
    return publish_run_snapshot(
        config=_enabled(tmp_path),
        discovery=discovery,
        processing=processing,
        analysis=analysis,
        report_meta=_FULL_RUN_META,
    )


def _publish_watching_the_collector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, raises: bool
) -> tuple[RunSnapshotPublication, list[bool]]:
    """Publish with a probe on the first step of the enabled half that
    records whether the collector ran there, then carries on or raises."""
    seen: list[bool] = []
    original = snapshot_module.producer_execution_population

    def probe(**kwargs: object) -> object:
        seen.append(gc.isenabled())
        if raises:
            raise RuntimeError("the publication came apart")
        return original(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(snapshot_module, "producer_execution_population", probe)
    return _publish(tmp_path), seen


@pytest.mark.usefixtures("collector_restored")
def test_the_collector_is_paused_for_the_publication_and_handed_back_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gc.enable()
    publication, seen = _publish_watching_the_collector(
        tmp_path, monkeypatch, raises=False
    )
    assert publication.outcome not in RUN_SNAPSHOT_PUBLICATION_UNSTORED, publication
    assert seen == [False], "the publication ran with the collector on"
    assert gc.isenabled(), "the publication left the collector off"


@pytest.mark.usefixtures("collector_restored")
def test_a_caller_that_had_the_collector_off_keeps_it_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gc.disable()
    publication, seen = _publish_watching_the_collector(
        tmp_path, monkeypatch, raises=False
    )
    assert publication.outcome not in RUN_SNAPSHOT_PUBLICATION_UNSTORED, publication
    assert seen == [False]
    assert not gc.isenabled(), "the publication switched the caller's collector on"


@pytest.mark.usefixtures("collector_restored")
def test_a_publication_that_raises_hands_the_collector_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gc.enable()
    publication, seen = _publish_watching_the_collector(
        tmp_path, monkeypatch, raises=True
    )
    assert seen == [False]
    assert publication.outcome == RUN_SNAPSHOT_PUBLICATION_FAILED
    assert gc.isenabled(), "a failed publication left the collector off"


# -- one normalization per publication ---------------------------------------


def test_a_publication_normalizes_its_model_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The builder hands the store its model as built and the store closes
    it: one pass per publication, on the store's side of the edge."""
    calls: list[str] = []
    original = CanonicalModel.normalize

    def counted(model: CanonicalModel) -> CanonicalModel:
        calls.append("normalize")
        return original(model)

    monkeypatch.setattr(CanonicalModel, "normalize", counted)
    publication = _publish(tmp_path)
    assert publication.outcome not in RUN_SNAPSHOT_PUBLICATION_UNSTORED, publication
    assert calls == ["normalize"]


# -- the grammar's answers, once per publication -----------------------------

_PAIRS = (("pkg/a.py", "pkg.a"), ("tools/b.py", "tools.b"))
_ANALYZED = frozenset({"pkg/a.py", "tools/b.py", "pkg/c.py"})
_KEYS = ("pkg.a:A.run", "pkg.a:A.stop", "tools.b:helper", "pkg/c.py:direct")


def _index(pairs: Sequence[tuple[str, str]] = _PAIRS) -> IdentityIndex:
    return build_identity_index(pairs, analyzed_paths=_ANALYZED)


def _roots(key: str) -> tuple[str, ...]:
    return ("unresolved", f"producer:{key}", "effect:artifact_write:report")


def _semantic() -> SimpleNamespace:
    """An authority result whose rows repeat their identities many times,
    the way the producer's do, with keys that share a prefix."""
    rows = [_KEYS[n % len(_KEYS)] for n in range(24)]
    return SimpleNamespace(
        contract_ir=SimpleNamespace(
            contracts=tuple(
                SimpleNamespace(
                    function=key,
                    effect_signature=f"sig{n}",
                    provenance_roots=_roots(key),
                )
                for n, key in enumerate(rows)
            )
        ),
        graph=SimpleNamespace(
            nodes=tuple(
                SimpleNamespace(
                    function=key,
                    effect_signature=f"sig{n}",
                    producer_root_ids=_roots(key),
                    output_facts=("fact",),
                    resolution_state="resolved",
                )
                for n, key in enumerate(rows)
            ),
            edges=tuple(
                SimpleNamespace(source=key, target=rows[(n + 1) % len(rows)])
                for n, key in enumerate(rows)
            ),
        ),
        sinks=tuple(
            SimpleNamespace(sink_identity=key, authority_status=f"s{n % 2}")
            for n, key in enumerate(rows)
        ),
        candidates=tuple(
            SimpleNamespace(level=n, shared_fact=f"f{n}", producers=(key, _KEYS[0]))
            for n, key in enumerate(rows)
        ),
        violations=tuple(
            SimpleNamespace(
                contract_id=f"c{n}",
                kind=VIOLATION_KINDS[n % len(VIOLATION_KINDS)],
                sink_identity=key,
                canonical_owner=_KEYS[1],
                authority_status="s",
                effect_signature="e",
                resolution_state="resolved",
                producer_root_ids=_roots(key),
                producers=(key,),
                suppressed=False,
                locations=(
                    SimpleNamespace(relative_path="pkg/a.py", start_line=n + 1),
                ),
            )
            for n, key in enumerate(rows)
        ),
    )


class _AskedEveryTime:
    """The grammar asked on every row, as before the memory existed."""

    def __init__(self, index: IdentityIndex) -> None:
        self._index = index

    def symbol(self, key: str, where: str) -> SymbolId:
        return parse_symbol(self._index, key, where)

    def root_set(self, values: Sequence[str], where: str) -> frozenset[EffectRoot]:
        return parse_root_set(self._index, values, where)

    def symbol_set(self, values: Sequence[str], where: str) -> frozenset[SymbolId]:
        return parse_symbol_set(self._index, values, where)


def test_the_remembered_answers_are_the_grammars_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    semantic, index = _semantic(), _index()
    remembered = _semantic_families(semantic, index)  # type: ignore[arg-type]
    monkeypatch.setattr(snapshot_module, "_GrammarParses", _AskedEveryTime)
    asked = _semantic_families(semantic, index)  # type: ignore[arg-type]
    assert remembered == asked
    assert all(family for family in remembered), "every family must hold rows"


def test_each_identity_is_asked_of_the_grammar_once_per_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []
    original = parse_symbol

    def counted(index: IdentityIndex, key: str, where: str) -> SymbolId:
        asked.append(key)
        return original(index, key, where)

    monkeypatch.setattr(snapshot_module, "parse_symbol", counted)
    _semantic_families(_semantic(), _index())  # type: ignore[arg-type]
    assert sorted(asked) == sorted(_KEYS)


def test_the_answers_die_with_the_publication_that_asked() -> None:
    """The same text under another run's registry is another identity: an
    answer kept beyond its own index would hand this run the other's."""
    semantic = _semantic()
    moved = _index((("src/pkg/a.py", "pkg.a"), ("tools/b.py", "tools.b")))
    first = _semantic_families(semantic, _index())  # type: ignore[arg-type]
    second = _semantic_families(semantic, moved)  # type: ignore[arg-type]
    first_files = {row.function.file.path for row in first.contracts}
    second_files = {row.function.file.path for row in second.contracts}
    assert "pkg/a.py" in first_files and "src/pkg/a.py" not in first_files
    assert "src/pkg/a.py" in second_files and "pkg/a.py" not in second_files
