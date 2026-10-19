# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A warm cache never serves a class fact it cannot give back to its class.

Measured 2026-10-19 on ad07f3c9: a module that declares ``class C`` twice is
written to the cache faithfully -- one ``cm`` row per class, and one row per
class in each of the five class sidecars (``cc`` coupled classes, ``bs`` bases
and their opacity, ``de`` decorator evidence, ``sd`` self-dispatch, ``ic``
instantiation candidates) -- but the sidecars are keyed by the qualname alone,
so the reader folded each of them into one ``qualname -> value`` map and gave
BOTH classes the second one's value. Cold ``C@9 coupled [X]``, warm
``C@9 coupled [Y]``, exit 0, no warning; the same silent merge moved a
self-dispatch fact into the dead-code verdict and an instantiation candidate
into the coupling fold.

The maintainer's rule (2026-10-19, 8.2): when the decoder cannot restore the
facts of two same-named classes unambiguously, the cache may not be used for
that population; recomputation is allowed. So the reader decides on the
``cm`` rows themselves, before any sidecar is keyed, and the record's
dependent lane is refused with its own typed reason --
``ambiguous_declaration_identity``, counted like every lane reason, never a
warning -- and the file is walked again with its neutral facts reused. The
writer and the wire are untouched, so records an older build wrote are
refused the same way.

Every tree, cache and store lives under ``tmp_path``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

import orjson
import pytest

import codeclone.core.discovery as core_discovery
from codeclone.cache._wire_decode import _decode_wire_file_entry
from codeclone.cache.store import Cache
from codeclone.core._types import (
    AnalysisResult,
    BootstrapResult,
    DiscoveryResult,
    ProcessingResult,
)
from codeclone.core.parallelism import process
from codeclone.core.pipeline import analyze
from codeclone.models import (
    CacheLaneVerdict,
    CacheReuseDecision,
    ModuleRegistryHandle,
)
from tests._cache_store_fixtures import TABLE_DEPENDENT, read_lane_bytes
from tests._pipeline_fixtures import analysis_boot, payload_mapping, payload_sequence
from tests.conftest import _run_codeclone_cli_exit

_AMBIGUOUS: Final = "cache_lane_dependent_ambiguous_declaration_identity"
_MODULE: Final = "app/mod.py"

#: The controller's population, byte for byte (``cache_cls``): the two
#: classes differ in ``cc`` (X / Y) and the second one also self-dispatches.
_COUPLED: Final = """class X:
    pass


class Y:
    pass


class C:
    def a(self):
        return X()


class C:
    def b(self):
        return Y()

    def c(self):
        return self.b()


def public():
    return C()
"""

#: Only the first class has a ``cc`` row: no sidecar repeats a qualname, so
#: an ambiguity read off the sidecar maps instead of the ``cm`` rows misses it.
_COUPLED_ONE_SIDE: Final = """class X:
    pass


class C:
    def a(self):
        return X()


class C:
    def b(self):
        return 1


def public():
    return C()
"""

#: Only ``bs`` rows: both bases escape the root, so no local coupling edge.
_BASES: Final = """from external_lib import BaseOne, BaseTwo


class C(BaseOne):
    def a(self):
        return 1


class C(BaseTwo):
    def b(self):
        return 2


def public():
    return C()
"""

#: Only ``de`` rows: each class marks a different method, no base at all.
_DECORATOR_EVIDENCE: Final = """from typing import override


class C:
    @override
    def a(self):
        return 1

    def b(self):
        return 1


class C:
    def a(self):
        return 2

    @override
    def b(self):
        return 2


def public():
    return C()
"""

#: Only ``sd`` rows: each class dispatches a different method through self.
_SELF_DISPATCH: Final = """class C:
    def a(self):
        return self.b()

    def b(self):
        return 1


class C:
    def c(self):
        return self.d()

    def d(self):
        return 2


def public():
    return C()
"""

#: Only ``ic`` rows: each class instantiates a different imported class.
_INSTANTIATION: Final = """from app.other import P, Q


class C:
    def a(self):
        return P()


class C:
    def b(self):
        return Q()


def public():
    return C()
"""

_INSTANTIATION_TARGETS: Final = """class P:
    pass


class Q:
    pass
"""

#: Positive control: the controller's ``cache_cls_ctl``, the same shape under
#: two names.
_UNIQUE: Final = (
    _COUPLED.replace("class C:\n    def a", "class C1:\n    def a", 1)
    .replace("class C:\n    def b", "class C2:\n    def b", 1)
    .replace("return C()", "return C1(), C2()")
)

#: Positive control: same-named classes in different scopes have different
#: qualnames (``A.Inner`` / ``B.Inner``), and function-local classes are not
#: class-metric rows at all.
_NESTED: Final = """class X:
    pass


class Y:
    pass


class A:
    class Inner:
        def a(self):
            return X()


class B:
    class Inner:
        def b(self):
            return Y()

        def c(self):
            return self.b()


def make():
    class Local:
        def m(self):
            return X()

    return Local()


def make2():
    class Local:
        def m(self):
            return Y()

    return Local()


def public():
    return A.Inner(), B.Inner(), make(), make2()
"""

_AMBIGUOUS_TREES: Final[Mapping[str, Mapping[str, str]]] = {
    "coupled_classes": {_MODULE: _COUPLED},
    "coupled_classes_one_side": {_MODULE: _COUPLED_ONE_SIDE},
    "class_bases": {_MODULE: _BASES},
    "decorator_evidence": {_MODULE: _DECORATOR_EVIDENCE},
    "self_dispatch": {_MODULE: _SELF_DISPATCH},
    "instantiation_candidates": {
        _MODULE: _INSTANTIATION,
        "app/other.py": _INSTANTIATION_TARGETS,
    },
}

_UNIQUE_TREES: Final[Mapping[str, Mapping[str, str]]] = {
    "different_names": {_MODULE: _UNIQUE},
    "nested_same_names": {_MODULE: _NESTED},
}

#: The record ad07f3c9 stored for ``_COUPLED`` as ``app/mod.py``, read back
#: from its sqlite cache exactly as a reader is handed it.
_AD07F3C9_ENTRY: Final = (
    Path(__file__).parent
    / "fixtures"
    / "cache_v3"
    / "duplicate_classes_entry_ad07f3c9.json"
)

#: Run counters of one processing result: they say how the facts were
#: obtained, never what they are.
_RUN_COUNTERS: Final = frozenset(
    {
        "analyzed_classes",
        "analyzed_functions",
        "analyzed_lines",
        "analyzed_methods",
        "failed_files",
        "files_analyzed",
        "files_skipped",
        "phase_snapshot",
        "source_read_failures",
    }
)


def _tree(root: Path, files: Mapping[str, str]) -> Path:
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("", "utf-8")
    for relative, text in files.items():
        (root / relative).write_text(text, "utf-8")
    return root


def _boot(root: Path, *, skip_metrics: bool = False) -> BootstrapResult:
    return analysis_boot(root, min_loc=1, min_stmt=1, skip_metrics=skip_metrics)


class _SpanCounters:
    def __init__(self, name: str) -> None:
        self.name = name
        self.counters: dict[str, int] = {}

    def set_counter(self, key: str, value: int) -> None:
        self.counters[key] = value


@dataclass(frozen=True, slots=True)
class _Run:
    discovery: DiscoveryResult
    processing: ProcessingResult
    result: AnalysisResult
    counters: dict[str, int]


def _run(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    cache_path: Path,
    *,
    warm: bool,
    skip_metrics: bool = False,
) -> _Run:
    """One discover/process/analyse pass, with the reuse span's counters."""

    boot = _boot(root, skip_metrics=skip_metrics)
    cache = Cache(cache_path, root=root)
    if warm:
        cache.load()
    observed: list[_SpanCounters] = []

    @contextmanager
    def _recording(*, name: str) -> Iterator[_SpanCounters]:
        observed.append(_SpanCounters(name))
        yield observed[-1]

    with monkeypatch.context() as patch:
        patch.setattr(core_discovery, "span", _recording)
        discovery = core_discovery.discover(boot=boot, cache=cache)
    processing = process(boot=boot, discovery=discovery, cache=cache)
    if not warm:
        cache.save()
    reuse = [span for span in observed if span.name == "cache.profile_reuse"]
    assert len(reuse) == 1
    return _Run(
        discovery=discovery,
        processing=processing,
        result=analyze(boot=boot, discovery=discovery, processing=processing),
        counters=reuse[0].counters,
    )


def _class_facts(run: _Run) -> list[str]:
    """Every fact of every class, one line per declaration."""

    return sorted(map(repr, run.processing.class_metrics))


def _dependent_facts(run: _Run) -> dict[str, object]:
    """Every fact the run holds and every verdict it derives from them."""

    facts: dict[str, object] = {}
    for name in sorted(type(run.processing).__dataclass_fields__):
        if name in _RUN_COUNTERS:
            continue
        value = getattr(run.processing, name)
        facts[name] = (
            sorted(map(repr, value))
            if isinstance(value, tuple | frozenset)
            else repr(value)
        )
    facts["project_metrics"] = repr(run.result.project_metrics)
    facts["metrics_payload"] = json.dumps(
        run.result.metrics_payload, sort_keys=True, default=repr
    )
    facts["suggestions"] = repr(run.result.suggestions)
    facts["structural_findings"] = repr(run.result.structural_findings)
    return facts


def _cold_then_warm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, files: Mapping[str, str]
) -> tuple[Path, _Run, _Run]:
    root = _tree(tmp_path / "tree", files)
    cache_path = tmp_path / "cache.sqlite3"
    cold = _run(monkeypatch, root, cache_path, warm=False)
    assert cold.processing.files_analyzed == len(files) + 1
    return root, cold, _run(monkeypatch, root, cache_path, warm=True)


@pytest.mark.parametrize("population", sorted(_AMBIGUOUS_TREES))
def test_a_warm_run_over_two_same_named_classes_equals_the_cold_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, population: str
) -> None:
    """Every class fact and every verdict built on them: warm IS cold.

    Each population isolates the sidecars it is named for; between them they
    cover all five, and the one-sided ``cc`` case has no sidecar that repeats
    a qualname, so only the ``cm`` rows can tell the reader the record is
    ambiguous.
    """

    files = _AMBIGUOUS_TREES[population]
    root, cold, warm = _cold_then_warm(monkeypatch, tmp_path, files)

    assert _class_facts(warm) == _class_facts(cold)
    assert _dependent_facts(warm) == _dependent_facts(cold)
    # Refused by its own reason, counted, and recomputed -- that file only.
    assert warm.counters.get(_AMBIGUOUS, 0) == 1
    assert warm.discovery.files_to_process == (str(root / _MODULE),)
    assert warm.processing.files_analyzed == 1
    # Its neutral lane is still served: only the dependent lane was refused.
    assert warm.counters["cache_lane_neutral_hit"] == len(files) + 1
    assert [path for path, _ in warm.discovery.neutral_reuse_by_file] == [
        str(root / _MODULE)
    ]
    # Every other file comes off the cache whole.
    assert warm.counters["cache_lane_dependent_hit"] == len(files)
    assert warm.discovery.cache_hits == len(files)
    # A lane reason, not a damaged record: no refusal, no warning.
    assert warm.counters["cache_lane_dependent_malformed_payload"] == 0
    assert {
        key: value
        for key, value in warm.counters.items()
        if key.startswith("cache_refused_")
    } == dict.fromkeys(
        (
            "cache_refused_corrupt",
            "cache_refused_incompatible",
            "cache_refused_undecodable",
            "cache_refused_unreadable",
        ),
        0,
    )
    assert warm.discovery.skipped_warnings == ()


@pytest.mark.parametrize("population", sorted(_UNIQUE_TREES))
def test_unique_declarations_are_served_whole_from_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, population: str
) -> None:
    """Positive control: nothing ambiguous, nothing recomputed.

    Without it, the bypass above could be the bypass of every class.
    """

    files = _UNIQUE_TREES[population]
    _root, cold, warm = _cold_then_warm(monkeypatch, tmp_path, files)

    assert warm.processing.files_analyzed == 0
    assert warm.discovery.files_to_process == ()
    assert warm.discovery.cache_hits == len(files) + 1
    assert warm.counters.get(_AMBIGUOUS, 0) == 0
    assert _class_facts(warm) == _class_facts(cold)
    assert _dependent_facts(warm) == _dependent_facts(cold)


def _ad07f3c9_entry() -> dict[str, object]:
    wire = json.loads(_AD07F3C9_ENTRY.read_text("utf-8"))
    assert isinstance(wire, dict)
    return wire


def test_a_record_written_before_the_bypass_is_refused_by_the_reader() -> None:
    """The decision is read off the old bytes: no new mark, no new generation.

    The fixture is what ad07f3c9 -- the build before the bypass -- stored for
    the controller's population. Its two ``C`` rows each carry a ``cc`` row,
    and the second an ``sd`` row; none of those values may reach either
    class, and the lane verdict names the reason.
    """

    wire = _ad07f3c9_entry()
    dependent = payload_mapping(wire["d"])
    assert [payload_sequence(row)[0] for row in payload_sequence(dependent["cc"])] == [
        "app.mod:C",
        "app.mod:C",
    ]
    entry = _decode_wire_file_entry(wire, _MODULE, analysed_filepath=_MODULE)
    assert entry is not None

    payload = entry.module_dependent
    assert payload.ambiguous_declaration_identity is True
    same_named = [
        row for row in payload.class_metrics if row["qualname"] == "app.mod:C"
    ]
    assert len(same_named) == 2
    for row in same_named:
        for sidecar in (
            "coupled_classes",
            "base_names",
            "has_unresolved_external_base",
            "decorator_evidenced_methods",
            "self_dispatched_methods",
            "instantiation_candidates",
        ):
            assert sidecar not in row, (row["start_line"], sidecar)

    hit = CacheLaneVerdict(hit=True, reason="hit")
    decision, facts = core_discovery._judge_cached_row(
        CacheReuseDecision(neutral=hit, dependent=hit),
        entry,
        filepath=_MODULE,
        # Never consulted: an ambiguous record is refused before any row is
        # rebuilt, which is what this test also pins.
        module_registry=cast("ModuleRegistryHandle", None),
        metrics_consumed=True,
    )
    assert decision.neutral == hit
    assert decision.dependent == CacheLaneVerdict(
        hit=False, reason="ambiguous_declaration_identity"
    )
    assert facts is None


def test_this_build_writes_the_ad07f3c9_record_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The writer did not move: the record a user's cache already holds and
    the record this build writes are one record.

    So the reader's decision above is the only thing between an old record
    and a warm run -- no writer-side mark could be relied on, because an old
    record does not carry it.
    """

    root = _tree(tmp_path / "tree", {_MODULE: _COUPLED})
    cache_path = tmp_path / "cache.sqlite3"
    _run(monkeypatch, root, cache_path, warm=False)

    stored = read_lane_bytes(cache_path, _MODULE, TABLE_DEPENDENT)
    expected = orjson.dumps(_ad07f3c9_entry()["d"], option=orjson.OPT_SORT_KEYS)
    assert stored == expected


def test_a_malformed_sidecar_still_refuses_the_whole_record() -> None:
    """Ambiguity is a lane verdict on a READABLE record, never a way around
    the refusal of one this build cannot read."""

    wire = _ad07f3c9_entry()
    dependent = dict(payload_mapping(wire["d"]))
    dependent["cc"] = [["app.mod:C", "X"], ["app.mod:C", ["Y"]]]
    entry = _decode_wire_file_entry(
        {**wire, "d": dependent}, _MODULE, analysed_filepath=_MODULE
    )
    assert entry is None


def test_a_metrics_skipping_run_reads_no_class_fact_and_bypasses_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bypass guards the facts a run serves; a run that serves none of
    them has nothing to recompute.

    The cache is written by a metrics run, so the record really is ambiguous;
    a clone-only run over it reads the same lanes the cold clone-only run
    would have written and walks nothing again.
    """

    root = _tree(tmp_path / "tree", {_MODULE: _COUPLED})
    cache_path = tmp_path / "cache.sqlite3"
    _run(monkeypatch, root, cache_path, warm=False)
    clones = _run(monkeypatch, root, cache_path, warm=True, skip_metrics=True)

    assert clones.counters.get(_AMBIGUOUS, 0) == 0
    assert clones.processing.files_analyzed == 0


# -- the real CLI, report bytes, gates and the run store ----------------------

_SCOPE: Final = (
    '[tool.codeclone]\nbaseline_scope_id = "8a3c1f62-4b7e-4d19-9c55-0e2f6a7b1d93"\n'
)


@dataclass(frozen=True, slots=True)
class _Reading:
    exit_code: int
    report: dict[str, object]
    published: tuple[str, ...]

    def files(self) -> dict[str, object]:
        inventory = payload_mapping(self.report["inventory"])
        return payload_mapping(inventory["files"])

    def digests(self) -> dict[str, object]:
        """Every report digest but the envelope, which carries run timing."""

        integrity = payload_mapping(self.report["integrity"])
        return {
            name: value
            for name, value in payload_mapping(integrity["digests"]).items()
            if name != "envelope"
        }


def _published(store: Path) -> tuple[str, ...]:
    import sqlite3
    from contextlib import closing

    if not store.exists():
        return ()
    with closing(sqlite3.connect(store)) as connection:
        rows = connection.execute(
            "SELECT run_id FROM runs WHERE published = 1 ORDER BY run_pk"
        ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _cli(root: Path, work: Path, label: str, *, cache: Path) -> _Reading:
    report = work / f"{label}.json"
    store = work / f"{label}.runs.sqlite3"
    code = _run_codeclone_cli_exit(
        [
            str(root),
            "--no-progress",
            "--baseline",
            str(root / "codeclone.baseline.json"),
            "--cache-path",
            str(cache),
            "--json",
            str(report),
            "--fail-dead-code",
            "--fail-on-unresolved-dead-code",
        ],
        {
            "CODECLONE_RUN_STORE_ENABLED": "1",
            "CODECLONE_RUN_STORE_FORCE": "1",
            "CODECLONE_RUN_STORE_PATH": str(store),
        },
    )
    assert code in (None, 0, 3), code
    document = json.loads(report.read_text("utf-8"))
    assert isinstance(document, dict)
    return _Reading(int(code or 0), document, _published(store))


@pytest.mark.parametrize(
    ("population", "ambiguous"),
    [
        ("coupled_classes", True),
        ("self_dispatch", True),
        ("instantiation_candidates", True),
        ("different_names", False),
    ],
)
def test_the_cli_publishes_the_cold_run_from_a_warm_cache(
    tmp_path: Path, population: str, ambiguous: bool
) -> None:
    """Report digests, gate exit and run-store publication: warm IS cold.

    Two same-named classes share one stored fact key, so the store refuses
    the publication on both sides (``DeclarationCollisionError``); the
    unique control publishes, and publishes one run id twice -- the
    instrument can see a run id.
    """

    files = {**_AMBIGUOUS_TREES, **_UNIQUE_TREES}[population]
    root = _tree(tmp_path / "tree", files)
    (root / "pyproject.toml").write_text(_SCOPE, "utf-8")
    cache = tmp_path / "cache.sqlite3"
    cold = _cli(root, tmp_path, "cold", cache=cache)
    warm = _cli(root, tmp_path, "warm", cache=cache)

    assert cold.files()["cached"] == 0
    assert warm.digests() == cold.digests()
    assert warm.exit_code == cold.exit_code
    assert warm.published == cold.published
    assert len(cold.published) == (0 if ambiguous else 1)
    # Recomputed exactly where the record was ambiguous, served elsewhere.
    assert warm.files()["analyzed"] == (1 if ambiguous else 0)
