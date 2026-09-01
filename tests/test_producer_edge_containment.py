# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The producer edge of the run-store rollout, as a BOUNDARY.

Two properties, and the second is the reason this module exists.

**The instance.**  A security surface is the only per-file family whose
live producer stamps the ANALYSED spelling of its path
(``SemanticEvent.location``, repo-relative) while every sibling family in
the same pass is stamped with the runtime path.  The cache re-stamped the
whole entry with the runtime path on the way back in, so the second run
over one tree handed the canonical builder a path the identity index had
never heard of and the analysis died.  The pin below is cold-equals-warm
on the published rows, not "the string is relative": a literal spelling
would survive the next producer that picks the wrong domain.

**The class.**  "A rollout flag may not fail an analysis" was held by an
``except ProducerSnapshotUnavailable`` — an enumeration of what had already
gone wrong once.  Two different failures have since walked past it, from
two different directions: a ``SemanticGrammarError`` out of the identity
grammar on a warm cache, and a ``StoreCompatibilityError`` out of the store
meeting a file from a previous ``STORAGE_SCHEMA_REVISION``.  Both are
pinned below, and the point of having both is that the third one will
arrive from somewhere nobody has looked.  The rule here is that the enabled
half of ``publish_run_snapshot`` is a CONTAINMENT BOUNDARY: whatever it
raises becomes "flag off", typed and counted, and no list of exception
types stands between the failure and the analysis.

A boundary has two ways to rot and each has its own test here, failing for
its own reason.  It rots by TYPE when somebody enumerates the failures they
have met — pinned by an exception class this repository has never raised.
It rots by EXTENT when somebody adds a step beside the ``try`` instead of
behind it — pinned structurally, off the syntax tree.  And a containment
that says nothing would be worse than the crash it replaced, so the typed
outcome and the counter are pinned apart from both.
"""

from __future__ import annotations

import ast
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import orjson
import pytest

from codeclone.cache.projection import runtime_filepath_from_wire
from codeclone.cache.store import Cache
from codeclone.canonical.model import CanonicalModel
from codeclone.canonical.store import RunStore
from codeclone.core.canonical_snapshot import (
    RUN_SNAPSHOT_NAMESPACE,
    ProducerSnapshotUnavailable,
    publish_run_snapshot,
)
from codeclone.core.discovery_cache import load_cached_metrics_extended
from codeclone.models import (
    CANONICAL_HEAD_TARGET,
    RUN_SNAPSHOT_PUBLICATION_FAILED,
    RUN_SNAPSHOT_PUBLICATION_REFUSED,
    CacheEntryV3,
    DigestObject,
    FileMetrics,
    ModuleRegistryHandle,
    RunStoreConfig,
    SecuritySurface,
)
from codeclone.observability import bootstrap, operation, shutdown
from codeclone.paths.workspace import REL_CACHE_PATH
from tests._ast_metrics_helpers import module_registry_context
from tests.conftest import RunStoreCorpusRunner
from tests.test_run_store_producer_wiring import (  # noqa: F401
    _FULL_METRICS_ARGS,
    corpus,
)

_SOURCE_CONTENT_DIGEST = DigestObject(
    domain="codeclone.source-content.v1",
    algorithm="sha256",
    value="0" * 64,
)

_ROOT = Path(__file__).resolve().parents[1]
_SURFACE_MODULE = "pkg.reader"
_SURFACE_WIRE_PATH = "pkg/reader.py"


# ---------------------------------------------------------------------------
# The instance: one path, two domains
# ---------------------------------------------------------------------------


def _published(store: Path) -> CanonicalModel:
    with RunStore(store) as run_store:
        head = run_store.head(
            namespace=RUN_SNAPSHOT_NAMESPACE, target=CANONICAL_HEAD_TARGET
        )
        assert head is not None, f"{store.name} carries no canonical head"
        return run_store.read_run(head.run_id)


def test_a_warm_cache_publishes_the_same_security_surfaces_as_a_cold_one(
    corpus: Path,  # noqa: F811
    run_store_cli: RunStoreCorpusRunner,
) -> None:
    """Cold and warm are two readings of ONE tree, so they publish one set.

    Pinned as an equality between two real runs rather than as a claim
    about the shape of a string: the defect is a producer and a cache
    disagreeing about which domain ``filepath`` is in, and only a
    comparison of the two readings can see that.
    """
    cold_store = corpus / "cold.sqlite3"
    warm_store = corpus / "warm.sqlite3"

    run_store_cli(corpus, *_FULL_METRICS_ARGS, store=cold_store)
    run_store_cli(corpus, *_FULL_METRICS_ARGS, store=warm_store)

    cold = _published(cold_store)
    warm = _published(warm_store)

    # The instrument is proven on before anything is compared: the second
    # run has to have actually reused the cache, and the first must not
    # have. Without this the equality could hold because neither run ever
    # touched the lane under test.
    cold_scalars = cold.facts.analysis.run_scalars
    warm_scalars = warm.facts.analysis.run_scalars
    assert cold_scalars is not None and warm_scalars is not None
    assert cold_scalars.files_cached == 0
    assert warm_scalars.files_cached > 0

    surfaces = cold.facts.analysis.security_surfaces
    assert surfaces, "the corpus carries no security surface; the pin is hollow"
    assert warm.facts.analysis.security_surfaces == surfaces
    # And the rows resolve inside the run's own analysed universe — the
    # invariant the identity grammar enforces, stated positively.
    analysed = {identity.path for identity in warm.analyzed_files}
    assert {row.file.path for row in surfaces} <= analysed


def _entry_with_one_surface(
    cache_path: Path,
) -> tuple[Cache, Cache, ModuleRegistryHandle, str]:
    """Write one cached file entry carrying one security surface.

    Returns the cache that WROTE it, the cache that read it back off disk,
    the registry both are bound to, and the RUNTIME spelling of the file —
    so a reader can tell which domain each side chose, and whether the two
    sides chose the same one.
    """

    root = cache_path.parent
    runtime_path = runtime_filepath_from_wire(_SURFACE_WIRE_PATH, root=root)
    assert runtime_path != _SURFACE_WIRE_PATH, (
        "the two domains coincide here, so this probe could not tell them apart"
    )

    registry = module_registry_context(
        filepath=_SURFACE_WIRE_PATH, module_name=_SURFACE_MODULE
    )[1]
    cache = Cache(cache_path, root=root)
    cache.bind_module_registry(registry)
    cache.put_file_entry(
        _SURFACE_WIRE_PATH,
        {"mtime_ns": 1, "size": 10},
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
        file_metrics=FileMetrics(
            class_metrics=(),
            module_deps=(),
            dead_candidates=(),
            referenced_names=frozenset(),
            import_names=frozenset(),
            class_names=frozenset(),
            security_surfaces=(
                SecuritySurface(
                    category="process_boundary",
                    capability="subprocess_call",
                    module=_SURFACE_MODULE,
                    # The producer's own spelling: the analysed path.
                    filepath=_SURFACE_WIRE_PATH,
                    qualname=f"{_SURFACE_MODULE}:read",
                    start_line=4,
                    end_line=4,
                    location_scope="callable",
                    classification_mode="exact_call",
                    evidence_kind="call",
                    evidence_symbol="subprocess.call",
                ),
            ),
        ),
    )
    cache.save()

    reloaded = Cache(cache_path, root=root)
    reloaded.load()
    return cache, reloaded, registry, runtime_path


def test_the_cache_returns_a_security_surface_in_the_analysed_domain(
    tmp_path: Path,
) -> None:
    """A cached row may not change which domain its path is in.

    The wire drops the surface's ``filepath`` and the decoder re-stamps it,
    so the decoder decides the domain.  Every sibling family is a runtime
    path and this one is not; a decoder that stamps the entry's runtime
    path onto it hands the canonical builder a path the identity index has
    never seen.
    """
    _, reloaded, registry, runtime_path = _entry_with_one_surface(
        tmp_path / "cache.json"
    )
    entry = reloaded.get_file_entry(runtime_path)
    assert entry is not None
    surfaces = _decoded_surfaces(entry, registry, runtime_path)

    assert [surface.filepath for surface in surfaces] == [_SURFACE_WIRE_PATH]


def test_a_cached_surface_reads_the_same_before_and_after_a_save(
    tmp_path: Path,
) -> None:
    """``put -> get`` and ``put -> save -> load -> get`` are one answer.

    The wire drops the row's own ``filepath``, so the writing side and the
    reading side each pick a domain independently and nothing makes them
    pick the same one.  When they disagree, an entry means one thing before
    a save and another after it — the identical split, one layer down, as
    the one that killed the warm run — and the disagreement is invisible to
    every test that only ever reads the reloaded side.
    """
    written, reloaded, _registry, runtime_path = _entry_with_one_surface(
        tmp_path / "cache.json"
    )
    before = written.get_file_entry(runtime_path)
    after = reloaded.get_file_entry(runtime_path)
    assert before is not None and after is not None

    rows = before.module_dependent.security_surfaces
    assert rows, "the probe stored no surface; the comparison would be hollow"
    assert rows == after.module_dependent.security_surfaces


def _decoded_surfaces(
    entry: CacheEntryV3, registry: ModuleRegistryHandle, runtime_path: str
) -> tuple[SecuritySurface, ...]:
    return load_cached_metrics_extended(
        entry,
        filepath=runtime_path,
        module_registry=registry,
    )[9]


# ---------------------------------------------------------------------------
# The class: the enabled half of the edge is a containment boundary
# ---------------------------------------------------------------------------


def test_the_enabled_half_of_the_edge_is_one_contained_region() -> None:
    """The containment covers a REGION, not the statements somebody wrapped.

    A boundary assembled out of remembered statements decays exactly the
    way a list of exception types decays: the next step added beside the
    ``try`` escapes it in silence, and no exception-shaped test can see
    that.  So ``publish_run_snapshot`` does three things and no more —
    count the attempt, answer the disabled flag, and delegate the whole
    enabled half from inside the ``try`` — and that is read off the syntax
    tree rather than off the comment above it.  Any work added anywhere
    else in this function reds here, which is the point.
    """
    source = (_ROOT / "codeclone" / "core" / "canonical_snapshot.py").read_text("utf-8")
    functions = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "publish_run_snapshot"
    ]
    assert len(functions) == 1
    body = [node for node in functions[0].body if not _is_docstring(node)]
    assert [type(node).__name__ for node in body] == ["With"]

    span_block = body[0]
    assert isinstance(span_block, ast.With)
    assert [type(node).__name__ for node in span_block.body] == ["Expr", "If", "Try"]

    contained = span_block.body[-1]
    assert isinstance(contained, ast.Try)
    # The whole enabled half is one delegated call, so there is nothing
    # inside the boundary for a later edit to accidentally step outside of.
    assert [type(node).__name__ for node in contained.body] == ["Return"]
    assert _called_names(contained.body) == {"_publish_enabled"}


def _is_docstring(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)


def _called_names(nodes: list[ast.stmt]) -> set[str]:
    return {
        node.func.id
        for statement in nodes
        for node in ast.walk(statement)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


class _AnUnheardOfFailure(Exception):
    """An exception type no production ``except`` clause has ever named.

    That is the whole point: a boundary that holds only for the errors
    somebody already met is an enumeration wearing a boundary's clothes.
    """


def _explode(**_kwargs: object) -> CanonicalModel:
    raise _AnUnheardOfFailure("the producer edge came apart")


def _enabled(tmp_path: Path) -> RunStoreConfig:
    return RunStoreConfig(enabled=True, path=tmp_path / "db" / "runs.sqlite3")


def test_an_unheard_of_failure_behind_the_edge_does_not_fail_the_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rollout flag may not fail an analysis — for ANY failure.

    The exception is a type this repository has never raised, thrown from
    the build step, which is exactly the mutation the acceptance names: a
    containment that survives only because somebody listed
    ``SemanticGrammarError`` beside ``ProducerSnapshotUnavailable`` is not
    a boundary.
    """
    monkeypatch.setattr(
        "codeclone.core.canonical_snapshot.canonical_snapshot_from_producers",
        _explode,
    )
    publication = publish_run_snapshot(
        config=_enabled(tmp_path),
        discovery=None,  # type: ignore[arg-type]
        processing=None,  # type: ignore[arg-type]
        analysis=None,  # type: ignore[arg-type]
        report_meta={},
    )
    assert publication.outcome == RUN_SNAPSHOT_PUBLICATION_FAILED
    assert not publication.admissible
    assert publication.run_id == ""
    # "Flag off" means the backend was not written, not that it was written
    # badly: a half-built database is a worse outcome than none.
    assert not (tmp_path / "db").exists()


def _prove_the_analysis_finished(
    run_store_cli: RunStoreCorpusRunner,
    corpus: Path,  # noqa: F811
    *,
    store: Path,
) -> None:
    """Run with the flag on and a store phase that is expected to fail.

    The rendered document is the evidence, and it is the only evidence that
    separates containment from an early exit: a run that dies at the
    producer edge never reaches the document work at all, so a report that
    exists and says ``full`` is the difference between the two.
    """

    report_path = corpus / "report.json"
    run_store_cli(corpus, *_FULL_METRICS_ARGS, "--json", str(report_path), store=store)
    document = orjson.loads(report_path.read_bytes())
    assert document["meta"]["analysis_mode"] == "full"


def test_a_store_path_that_cannot_be_created_does_not_fail_the_run(
    corpus: Path,  # noqa: F811
    run_store_cli: RunStoreCorpusRunner,
) -> None:
    """One REAL input reaches the boundary, through the real waterfall.

    A guard whose only witness is a monkeypatched raise is a guard nobody
    has shown an ordinary run can trip.  Here the operator points
    ``CODECLONE_RUN_STORE_PATH`` at a database whose parent directory is an
    existing regular file — an ordinary misconfiguration — so the snapshot
    builds and the very first filesystem call of the store phase fails.
    The analysis is expected to finish anyway and to render its document.
    """
    occupied = corpus / "occupied"
    occupied.write_text("not a directory\n", "utf-8")

    _prove_the_analysis_finished(run_store_cli, corpus, store=occupied / "runs.sqlite3")

    assert occupied.read_text("utf-8") == "not a directory\n"
    # The wide net stays -- a run store under any other name is still caught
    # -- but it excludes the disposable analysis cache, which became a SQLite
    # store on 2026-09-01.  A cache write is not a publish, so counting it
    # here would make this pin fail for the one reason it must not care
    # about.
    assert not [
        found
        for found in corpus.glob("**/*.sqlite3")
        if found != corpus / REL_CACHE_PATH
    ]


def test_a_failure_inside_the_store_constructor_is_contained(
    corpus: Path,  # noqa: F811
    run_store_cli: RunStoreCorpusRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The store's CONSTRUCTOR is inside the region, not beside it.

    The contour is a second way to lose this contract, independent of the
    exception dictionary: for one wave ``RunStore(...)`` stood outside the
    ``try`` altogether, so no list of exception types could have reached it
    even in principle — ``StoreCompatibilityError`` is not a
    ``ProducerSnapshotUnavailable`` and never had to be.  The failure
    injected here is of a type nothing names, raised from that exact call.
    """

    class _RefusingStore:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise _AnUnheardOfFailure("the store refused to open")

    monkeypatch.setattr("codeclone.canonical.store.RunStore", _RefusingStore)
    store = corpus / "runs.sqlite3"

    _prove_the_analysis_finished(run_store_cli, corpus, store=store)

    assert not store.exists()


def _stored_run_count(store: Path) -> int:
    connection = sqlite3.connect(store)
    try:
        return int(connection.execute("SELECT count(*) FROM runs").fetchone()[0])
    finally:
        connection.close()


def _age_the_store_witness(store: Path) -> None:
    """Make an existing store file the artefact of another generation.

    Nothing is patched in the process: the file on disk is edited, which is
    exactly the shape of the field case — a store written before a
    ``STORAGE_SCHEMA_REVISION`` bump, met by a build that has moved on.
    """
    connection = sqlite3.connect(store)
    try:
        connection.execute(
            "UPDATE witness SET revision = ? WHERE layer = ?",
            ("from-a-previous-generation", "storage_schema"),
        )
        connection.commit()
    finally:
        connection.close()


def test_a_store_from_another_generation_does_not_fail_the_run(
    corpus: Path,  # noqa: F811
    run_store_cli: RunStoreCorpusRunner,
) -> None:
    """The SECOND live instance of the class, and the boundary is the same.

    The store refuses an incompatible generation at ``open`` — law 7, its
    own decision and correctly loud INSIDE the store.  Outside it, that
    refusal is still just the optional recording failing, so the analysis
    finishes and the store is left exactly as it was.  This case is here
    because it arrived from a different direction than the first one (a
    schema revision rather than an identity grammar), which is the whole
    argument for a boundary instead of a list of exception types.
    """
    store = corpus / "runs.sqlite3"
    run_store_cli(corpus, *_FULL_METRICS_ARGS, store=store)
    # The instrument is proven on: there is a real store, with a real run
    # in it, for the second pass to be refused by.
    before = _stored_run_count(store)
    assert before == 1
    _age_the_store_witness(store)

    _prove_the_analysis_finished(run_store_cli, corpus, store=store)

    assert _stored_run_count(store) == before


@pytest.fixture
def observed(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "observed"
    root.mkdir()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("CODECLONE_OBSERVABILITY_ENABLED", "1")
    monkeypatch.delenv("CODECLONE_OBSERVABILITY_PROFILE", raising=False)
    bootstrap(root=root)
    try:
        yield root
    finally:
        shutdown()
        monkeypatch.undo()


def _publish_span_counters(root: Path) -> dict[str, int]:
    store = next(root.rglob("platform_observability.sqlite3"))
    connection = sqlite3.connect(store)
    try:
        rows = connection.execute(
            "SELECT counters_json FROM platform_spans WHERE name=? ORDER BY rowid",
            ("canonical.snapshot.publish",),
        ).fetchall()
    finally:
        connection.close()
    merged: dict[str, int] = {}
    for (raw,) in rows:
        for key, value in (orjson.loads(raw) if raw else {}).items():
            merged[str(key)] = merged.get(str(key), 0) + int(value)
    return merged


def test_a_contained_failure_is_named_and_counted(
    observed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Containment that says nothing trades a crash for a silent loss.

    This is the second half of the boundary and it fails for a different
    reason than the first: the analysis surviving proves nothing if the
    operator cannot tell a backend that refused to write from a backend
    nobody ever wired.  The outcome carries the failure's TYPE, and the
    edge's own counter says the case happened.
    """
    monkeypatch.setattr(
        "codeclone.core.canonical_snapshot.canonical_snapshot_from_producers",
        _explode,
    )
    with operation(name="cli.analyze", surface="cli"):
        publication = publish_run_snapshot(
            config=_enabled(observed),
            discovery=None,  # type: ignore[arg-type]
            processing=None,  # type: ignore[arg-type]
            analysis=None,  # type: ignore[arg-type]
            report_meta={},
        )
    shutdown()

    assert publication.outcome == RUN_SNAPSHOT_PUBLICATION_FAILED
    assert "_AnUnheardOfFailure" in publication.reason

    counters = _publish_span_counters(observed)
    assert counters["run_snapshot_publish_attempts"] == 1
    assert counters["run_snapshot_publish_failed"] == 1
    # The outcome counters stay exclusive: a contained failure is not a
    # store that wrote, and it is not the flag being off either.
    assert counters.get("run_snapshot_publish_stored", 0) == 0
    assert counters.get("run_snapshot_publish_disabled", 0) == 0
    assert counters.get("run_snapshot_publish_refused", 0) == 0


def test_the_typed_refusal_keeps_its_own_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Containment must not swallow the refusal it was built beside.

    ``ProducerSnapshotUnavailable`` is an anticipated statement about the
    RUN — this build cannot express that family — and collapsing it into
    the unanticipated-failure outcome would lose the distinction the
    rollout is being watched through.
    """

    def _refuse(**_kwargs: object) -> CanonicalModel:
        raise ProducerSnapshotUnavailable("the semantic lane is not expressible")

    monkeypatch.setattr(
        "codeclone.core.canonical_snapshot.canonical_snapshot_from_producers",
        _refuse,
    )
    publication = publish_run_snapshot(
        config=_enabled(tmp_path),
        discovery=None,  # type: ignore[arg-type]
        processing=None,  # type: ignore[arg-type]
        analysis=None,  # type: ignore[arg-type]
        report_meta={},
    )
    assert publication.outcome == RUN_SNAPSHOT_PUBLICATION_REFUSED
    assert publication.reason == "the semantic lane is not expressible"


def test_the_boundary_does_not_contain_the_process_coming_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The edge contains FAILURES, not interrupts.

    ``KeyboardInterrupt`` and ``SystemExit`` are the process being taken
    down, not the producer edge coming apart; a boundary that ate them
    would turn Ctrl-C into a warm rollout witness.  This is the pin that
    stops the containment from widening into ``except BaseException``.
    """

    def _interrupt(**_kwargs: object) -> CanonicalModel:
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "codeclone.core.canonical_snapshot.canonical_snapshot_from_producers",
        _interrupt,
    )
    with pytest.raises(KeyboardInterrupt):
        publish_run_snapshot(
            config=_enabled(tmp_path),
            discovery=None,  # type: ignore[arg-type]
            processing=None,  # type: ignore[arg-type]
            analysis=None,  # type: ignore[arg-type]
            report_meta={},
        )
