# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeclone.baseline.trust import current_python_tag
from codeclone.canonical.model import CanonicalModel
from codeclone.contracts import CACHE_VERSION, REPORT_SCHEMA_VERSION
from codeclone.models import RUN_SNAPSHOT_PUBLICATION_PUBLISHED
from tests._live_state import (
    LIVE_STATE_GUARD_KEY,
    LIVE_STATE_MARKER,
    TREE_RESIDUE_GATE_TEST,
    LiveStateGuard,
    live_state_guard,
)
from tests._served_run import (
    ServedComparisonRun,
    ServedRunStoreProjection,
    ServedUnitLocation,
)
from tests._sqlite_cleanup import (
    close_tracked_sqlite_connections,
    make_tracking_connect,
    sweep_leaked_sqlite_connections_via_gc,
)

# ``pytester`` drives the end-to-end controls of the live-state boundary: an
# inner pytest session, wired through this very conftest, must red on a
# deliberately offending test.
pytest_plugins = ["pytester"]

ReportMetaFactory = Callable[..., dict[str, object]]

# ---------------------------------------------------------------------------
# The wire-freeze distinguishing corpus (ruling 2026-08-24 §10, step 2b).
#
# Shared session infrastructure: the corpus tree is materialized from inert
# ``*.txt`` carriers and analyzed once through the real CLI; the resulting
# report document feeds BOTH the report-shape pins (an r4-subject module,
# ``test_wire_freeze_corpus``) and the canonical-family pins (an r2-subject
# module, ``test_canonical_wire_freeze_corpus``).  The builder lives here so
# each test module binds to exactly one architectural ring — the Phase 39S
# test-import law — while sharing one corpus run.
# ---------------------------------------------------------------------------

_WIRE_FREEZE_CORPUS = Path(__file__).parent / "fixtures" / "wire_freeze_corpus"

# The slice-5 distinguishing stage (its own tree, its own CLI run): the
# families it exists for (security surfaces, coverage join) carry zero
# rows on the base corpus, and extending the base tree would shift every
# measured base-corpus pin — new carriers live beside it, never inside it.
_WIRE_FREEZE_CORPUS_S5 = Path(__file__).parent / "fixtures" / "wire_freeze_corpus_s5"

# The F5 distinguishing stage (its own tree, its own CLI run).  Measured
# 2026-08-26: api-surface collection is OFF unless a project asks for it, so
# the base corpus and the slice-5 stage each carried 0 api_surface rows and
# the lane's identity spelling was never seen by the ingest oracle on real
# producer output.  This stage turns the switch on and carries @overload
# groups, so the ratified F5 key is exercised where a SYMBOL-only key would
# collapse rows.  Beside the others, never inside them — the same rule the
# slice-5 note above states.
_WIRE_FREEZE_CORPUS_F5 = Path(__file__).parent / "fixtures" / "wire_freeze_corpus_f5"

# The F7 distinguishing stage (its own tree, its own CLI run).  Measured
# 2026-08-30: the self-repository carries 0 dependency_cycles and the base
# corpus carries three whose member sets never collide, so the MODULE-domain
# key's member boundary had never been exercised.  This stage carries two
# DISJOINT components of the same kind whose sorted member names concatenate
# to one identical dotted text, plus both classification verdicts and a set
# that carries import-time and deferred edges at once.  Top-level module
# names (no shared package head) are load-bearing: a ``pkg.`` prefix on every
# member makes the flattened texts differ and the collision unreachable.
_WIRE_FREEZE_CORPUS_F7 = Path(__file__).parent / "fixtures" / "wire_freeze_corpus_f7"

# The F8 distinguishing stage (its own tree, its own CLI run).  Measured
# 2026-08-30: golden-fixture declaration is the only producer channel that
# fills ``findings.groups.clones.suppressed``, and no wire-freeze stage
# declared it — the self-repository carried 17 suppressed groups beside 0
# emitted, every corpus carried emitted groups with the container absent, so
# the two populations had never met in one document.  This stage carries
# both, with disjoint keys, and is the first input to reach all three emitted
# containers at once.
_WIRE_FREEZE_CORPUS_F8 = Path(__file__).parent / "fixtures" / "wire_freeze_corpus_f8"

# The F8-singleton distinguishing stage (its own tree, its own CLI run).
# Measured 2026-09-05 on 21 frozen external repositories: the segment lane
# emits clone groups carrying exactly ONE item -- 378 of them, across 17 of
# the 21 members -- and ``CloneGroupRow`` refuses a group of one, so those
# documents cannot be ingested at all.  No fixture in this suite had ever
# carried the shape: the base corpus pins segment groups at zero and this
# repository emits no clones family whatsoever, so the segment path was
# never proven on data.  The stage carries BOTH merge branches that produce
# the shape -- overlapping windows and adjacent windows -- because
# ``merge_overlapping_items`` reaches them through different comparisons and
# a stage carrying one would leave the other unproven.
_WIRE_FREEZE_CORPUS_F8_SINGLETON = (
    Path(__file__).parent / "fixtures" / "wire_freeze_corpus_f8_singleton"
)

# The F7-namespace distinguishing stage (its own tree, its own CLI run).
# Measured 2026-09-05: the dependency lane emits an edge whose endpoint is a
# NAMESPACE PACKAGE -- ``packaging`` in kivy, ``pyglet.experimental`` in
# pyglet -- which ``metrics.dependencies._is_internal_target`` admits as
# internal precisely because it is a ``package_prefixes`` node, while
# ``build_identity_index`` is assembled from file-bearing ``(path, module)``
# pairs alone and so cannot resolve it.  ``nsp/`` carries no ``__init__.py``:
# that absence is the whole point of the stage, and adding one erases it.
_WIRE_FREEZE_CORPUS_F7_NAMESPACE = (
    Path(__file__).parent / "fixtures" / "wire_freeze_corpus_f7_namespace"
)

# The post-baseline stage: materialized only after the baseline is written,
# so its clone pair is the corpus's one genuinely NEW novelty row.
_WIRE_FREEZE_POST_BASELINE = "pkg/clones_three.py"


def _materialize_corpus_tree(
    source: Path, target: Path, *, withhold: str | None = None
) -> None:
    """Write one corpus tree from its inert ``*.txt`` carriers.

    Every carrier becomes the file named by stripping the trailing
    ``.txt``; ``withhold`` names one relative destination to leave out.
    """
    for carrier in sorted(source.rglob("*.txt")):
        relative = carrier.relative_to(source).with_suffix("")
        if withhold is not None and relative.as_posix() == withhold:
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(carrier.read_text("utf-8"), "utf-8")


def materialize_wire_freeze_corpus(target: Path, *, post_baseline: bool) -> None:
    """Write the base corpus tree; stage A withholds the stage-B file."""
    _materialize_corpus_tree(
        _WIRE_FREEZE_CORPUS,
        target,
        withhold=None if post_baseline else _WIRE_FREEZE_POST_BASELINE,
    )


def _run_corpus_cli(args: list[str]) -> None:
    """The ONE spelling of a corpus CLI invocation (argv patch + main) —
    both corpus fixtures ride it, so the invocation block cannot fork."""
    import codeclone.surfaces.cli.workflow as cli

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(sys, "argv", ["codeclone", *args])
        cli.main()
    finally:
        monkeypatch.undo()


def _corpus_document(report_path: Path) -> dict[str, object]:
    document = json.loads(report_path.read_text("utf-8"))
    assert isinstance(document, dict)
    return document


@pytest.fixture(scope="session")
def corpus_report(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, object]:
    """One two-stage corpus run: baseline on stage A, report on stage B."""
    root = tmp_path_factory.mktemp("wire_freeze_corpus")
    baseline = root / "corpus.baseline.json"
    report_path = root / "corpus.report.json"
    materialize_wire_freeze_corpus(root, post_baseline=False)
    _run_corpus_cli(
        [
            str(root),
            "--baseline",
            str(baseline),
            "--update-baseline",
            "--no-progress",
        ]
    )
    materialize_wire_freeze_corpus(root, post_baseline=True)
    _run_corpus_cli(
        [
            str(root),
            "--baseline",
            str(baseline),
            "--json",
            str(report_path),
            "--no-progress",
        ]
    )
    return _corpus_document(report_path)


@pytest.fixture(scope="session")
def corpus_s5_report(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, object]:
    """One single-stage slice-5 corpus run (no baseline: the families it
    distinguishes are analysis-tier facts of the current run)."""
    root = tmp_path_factory.mktemp("wire_freeze_corpus_s5")
    report_path = root / "corpus.report.json"
    _materialize_corpus_tree(_WIRE_FREEZE_CORPUS_S5, root)
    _run_corpus_cli([str(root), "--json", str(report_path), "--no-progress"])
    return _corpus_document(report_path)


@pytest.fixture(scope="session")
def corpus_f7_report(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, object]:
    """One single-stage F7 corpus run (no baseline: dependency cycles are an
    analysis-tier fact of the current run)."""
    root = tmp_path_factory.mktemp("wire_freeze_corpus_f7")
    report_path = root / "corpus.report.json"
    _materialize_corpus_tree(_WIRE_FREEZE_CORPUS_F7, root)
    _run_corpus_cli([str(root), "--json", str(report_path), "--no-progress"])
    return _corpus_document(report_path)


@pytest.fixture(scope="session")
def corpus_f8_report(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, object]:
    """One single-stage F8 corpus run (no baseline: the emitted/suppressed
    split is an analysis-tier fact of the current run).  The stage's own
    ``pyproject.toml`` declares the golden-fixture tree; without it both
    populations collapse into the emitted one and the run proves nothing."""
    root = tmp_path_factory.mktemp("wire_freeze_corpus_f8")
    report_path = root / "corpus.report.json"
    _materialize_corpus_tree(_WIRE_FREEZE_CORPUS_F8, root)
    _run_corpus_cli([str(root), "--json", str(report_path), "--no-progress"])
    return _corpus_document(report_path)


@pytest.fixture(scope="session")
def corpus_f5_report(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, object]:
    """One single-stage F5 corpus run (no baseline: the api_surface lane is
    an analysis-tier fact of the current run).  The stage's own
    ``pyproject.toml`` turns api-surface collection on; without it the lane
    is empty and the run proves nothing."""
    root = tmp_path_factory.mktemp("wire_freeze_corpus_f5")
    report_path = root / "corpus.report.json"
    _materialize_corpus_tree(_WIRE_FREEZE_CORPUS_F5, root)
    _run_corpus_cli([str(root), "--json", str(report_path), "--no-progress"])
    return _corpus_document(report_path)


@pytest.fixture(scope="session")
def corpus_f8_singleton_report(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, object]:
    """One single-stage F8-singleton corpus run (no baseline: the segment
    lane is an analysis-tier fact of the current run).

    The stage exists to carry the one clone-group shape the ingest oracle
    refuses, so that the refusal is measured on a document this project's
    own CLI produced rather than on an external checkout.
    """
    root = tmp_path_factory.mktemp("wire_freeze_corpus_f8_singleton")
    report_path = root / "corpus.report.json"
    _materialize_corpus_tree(_WIRE_FREEZE_CORPUS_F8_SINGLETON, root)
    _run_corpus_cli([str(root), "--json", str(report_path), "--no-progress"])
    return _corpus_document(report_path)


@pytest.fixture(scope="session")
def corpus_f7_namespace_report(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, object]:
    """One single-stage F7-namespace corpus run (no baseline: the dependency
    lane is an analysis-tier fact of the current run).

    ``_materialize_corpus_tree`` copies ``*.txt`` carriers only, so the
    namespace package stays a directory without ``__init__.py`` -- the
    condition the stage measures.
    """
    root = tmp_path_factory.mktemp("wire_freeze_corpus_f7_namespace")
    report_path = root / "corpus.report.json"
    _materialize_corpus_tree(_WIRE_FREEZE_CORPUS_F7_NAMESPACE, root)
    _run_corpus_cli([str(root), "--json", str(report_path), "--no-progress"])
    return _corpus_document(report_path)


# ---------------------------------------------------------------------------
# The run-store serving corpus: what an MCP execution serves from RAM beside
# the canonical run the same execution published.
#
# The tree is built to CARRY the distinguishing cases the three equivalence
# pins need (Probe Validity Law, AGENTS.md §17.3), because a corpus without
# them cannot tell "no canonical family owns this fact" from "the family
# that owns it carried no rows on this input":
#
#   * a function clone pair — the one canonical population whose ``end_line``
#     IS the hosting unit's own;
#   * a security surface whose span is a statement inside a unit and NOT the
#     unit's own closing line;
#   * imports with external targets, which the canonical dependency lane
#     omits by design;
#   * relationships in both resolution states, resolved and unresolved.
# ---------------------------------------------------------------------------

_RUN_STORE_SERVING_CORPUS = (
    Path(__file__).parent / "fixtures" / "run_store_serving_corpus"
)


@contextmanager
def _run_store_rollout(store_path: Path) -> Iterator[None]:
    """The run-store rollout environment of one in-process MCP execution.

    The rollout is CI-neutral by design and the suite may run under CI; the
    fixture says so rather than depending on the host.
    """
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
        monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
        monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(store_path))
        yield
    finally:
        monkeypatch.undo()


def _published_store_run_id(record: object) -> str:
    """The store run an MCP execution published, proven before anything is
    counted: an execution that published nothing leaves the store empty,
    and every comparison downstream would then be measuring an ABSENT run
    rather than an inexpressible one."""
    execution = getattr(record, "execution", None)
    link = getattr(execution, "run_snapshot_link", None)
    assert link is not None, "the execution carries no run-snapshot link"
    assert link.outcome == RUN_SNAPSHOT_PUBLICATION_PUBLISHED, link
    assert link.store_run_id
    return str(link.store_run_id)


def _serve_run_store_corpus(root: Path, store_path: Path) -> ServedRunStoreProjection:
    """One MCP analysis of a materialized tree, with the run store enabled.

    The ``r4`` surface is driven HERE and not in the consuming module: the
    consumer compares against the ``r2`` canonical model and has to stay an
    ``r2`` subject (the Phase 39S test-import law), which is the same reason
    ``run_store_cli`` lives in this file.
    """
    from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest
    from codeclone.surfaces.mcp.service import CodeCloneMCPService

    with _run_store_rollout(store_path):
        service = CodeCloneMCPService(history_limit=4)
        service.analyze_repository(
            MCPAnalysisRequest(root=str(root), analysis_mode="full")
        )
        record = service._runs.resolve_any_root()
        # Canonical epoch E1: the two tool answers of THIS execution, taken
        # while the store is still the one the run published into, so the
        # r2 shadow pins compare the store's projection with the surface's
        # own bytes.
        run_summary = service.get_run_summary(root=str(root))
        production_triage = service.get_production_triage(root=str(root))
    return ServedRunStoreProjection(
        root=root,
        store_path=store_path,
        store_run_id=_published_store_run_id(record),
        unit_inventory=tuple(
            ServedUnitLocation(
                qualname=unit.qualname,
                path=unit.path,
                start_line=unit.start_line,
                end_line=unit.end_line,
            )
            for unit in record.unit_inventory
        ),
        relationship_facts=record.relationship_facts,
        module_imports=record.module_imports,
        run_summary=run_summary,
        production_triage=production_triage,
    )


@pytest.fixture(scope="session")
def served_run_store_projection(
    tmp_path_factory: pytest.TempPathFactory,
) -> ServedRunStoreProjection:
    """One MCP analysis of the serving corpus (the fixture tree above)."""
    root = tmp_path_factory.mktemp("run_store_serving").resolve()
    store_path = root.parent / "run_store_serving.sqlite3"
    _materialize_corpus_tree(_RUN_STORE_SERVING_CORPUS, root)
    return _serve_run_store_corpus(root, store_path)


# ---------------------------------------------------------------------------
# The projection corpus (canonical epoch E1, cycle 4): the tree behind the
# shadow pins of ``codeclone.canonical.finding_projection`` /
# ``summary_projection``.  It exists because the serving corpus and the E1
# corpus carry NONE of three cases the projections have to be measured on
# (Probe Validity Law, AGENTS.md §17.3):
#
#   * a dependency cycle — two modules, so a member order the projection
#     fails to sort is visible;
#   * a dynamic load with an OPAQUE argument, the one import observation the
#     document publishes as a ``dynamic_boundaries`` site;
#   * a security family with MORE rows than categories, split across
#     production and tests, so the category count cannot pass as a row
#     count and the production/tests split is not a constant;
#   * a clone group of THREE members (measured 2026-09-25: every clone
#     group of the E1 and serving corpora is a pair, so a projected
#     ``group_arity`` of a constant 2 survived the battery — the arity has
#     to be read off the items on a group where the two differ).
#
# Inline rather than a fixture directory: the tree is the pin's own input
# and is read next to the pin that states it.
# ---------------------------------------------------------------------------

PROJECTION_CORPUS: dict[str, str] = {
    "pyproject.toml": "[tool.codeclone]\nsemantic_authority = true\n",
    "pkg/__init__.py": "",
    "pkg/cyc_a.py": '''"""Cycle A."""

from pkg.cyc_b import b


def a() -> int:
    """A."""
    return b()
''',
    "pkg/cyc_b.py": '''"""Cycle B."""

from pkg.cyc_a import a


def b() -> int:
    """B."""
    return a()
''',
    "pkg/loader.py": '''"""Loader: one dynamic load whose argument is opaque."""

import importlib


def load(name: str) -> object:
    """Load."""
    return importlib.import_module(name)
''',
    "pkg/danger.py": '''"""Danger: two surfaces of ONE category in production."""


def run_a(source: str) -> object:
    """Run A."""
    return eval(source)


def run_b(source: str) -> object:
    """Run B."""
    return eval(f"({source})")
''',
    "pkg/trio_a.py": '''"""Trio A: one of three identical functions."""


def fold(values: list[int]) -> int:
    """Fold a."""
    total = 0
    count = 0
    for value in values:
        count += 1
        if value > 10:
            total += value * 2
        elif value > 5:
            total += value
        else:
            total -= 1
    if count == 0:
        return -1
    total += count
    return total
''',
    "pkg/trio_b.py": '''"""Trio B: one of three identical functions."""


def fold(values: list[int]) -> int:
    """Fold b."""
    total = 0
    count = 0
    for value in values:
        count += 1
        if value > 10:
            total += value * 2
        elif value > 5:
            total += value
        else:
            total -= 1
    if count == 0:
        return -1
    total += count
    return total
''',
    "pkg/trio_c.py": '''"""Trio C: one of three identical functions."""


def fold(values: list[int]) -> int:
    """Fold c."""
    total = 0
    count = 0
    for value in values:
        count += 1
        if value > 10:
            total += value * 2
        elif value > 5:
            total += value
        else:
            total -= 1
    if count == 0:
        return -1
    total += count
    return total
''',
    "tests/test_danger.py": '''"""One surface of the same category under tests."""


def test_run() -> None:
    assert eval("1 + 1") == 2
''',
}


def materialize_projection_corpus(root: Path) -> None:
    """Write the projection corpus tree under ``root``."""
    for relative, source in PROJECTION_CORPUS.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, "utf-8")


@pytest.fixture(scope="session")
def served_projection_corpus(
    tmp_path_factory: pytest.TempPathFactory,
) -> ServedRunStoreProjection:
    """One MCP analysis of the projection corpus, with the run store
    enabled — the second served population of the shadow pins."""
    root = tmp_path_factory.mktemp("run_store_projection").resolve()
    store_path = root.parent / "run_store_projection.sqlite3"
    materialize_projection_corpus(root)
    return _serve_run_store_corpus(root, store_path)


# ---------------------------------------------------------------------------
# The comparison corpus (canonical epoch E2, 2026-09-26): the wire-freeze
# corpus compared against its own stage-A baseline, grown so every governed
# novelty family carries BOTH verdicts where the producer can utter them —
# a known complexity hotspot and a new one, a known dead symbol and a new
# one, a new coupling hotspot, a known and a new dependency cycle, a known
# and a new clone pair — and run under six configurations, one per
# comparison state the families must distinguish (Probe Validity Law):
#
#   * ``compared``      — every metric lane compared, the API lane included;
#   * ``partial``       — an unparsable file leaves the population partial,
#                         so the set-difference lanes are NOT compared;
#   * ``api_disabled``  — the API lane is not enabled: a disabled capability;
#   * ``lanes_skipped`` — dead code and dependencies not collected: two
#                         compared lanes are disabled capabilities;
#   * ``foreign_scope`` — the container belongs to another scope: every lane
#                         unavailable, the witness ``untrusted``;
#   * ``missing``       — no container at all: the witness ``missing``.
# ---------------------------------------------------------------------------

COMPARISON_CORPUS_STAGE_A: dict[str, str] = {
    "pkg/complex_old.py": "def old_tangle(a: int) -> int:\n    t = 0\n"
    + "".join(f"    if a > {i}:\n        t += {i}\n" for i in range(24))
    + "    return t\n",
    "pkg/dead_old.py": (
        "def _old_orphan(value: int) -> int:\n"
        "    total = value\n    total += 3\n    return total\n"
    ),
    # The API the baseline records: stage B removes two symbols (breaking)
    # and widens one signature compatibly, so the three API counts differ.
    "pkg/api_mod.py": (
        "def keep(a: int) -> int:\n    return a\n\n\n"
        "def gone_one() -> int:\n    return 1\n\n\n"
        "def gone_two() -> int:\n    return 2\n"
    ),
}
COMPARISON_CORPUS_STAGE_B: dict[str, str] = {
    "pkg/complex_new.py": "def new_tangle(a: int) -> int:\n    t = 0\n"
    + "".join(f"    if a < {i}:\n        t -= {i}\n" for i in range(24))
    + "    return t\n",
    "pkg/dead_new.py": (
        "def _new_orphan(value: int) -> int:\n"
        "    total = value\n    total += 1\n    return total\n"
    ),
    "pkg/parts.py": "\n\n".join(
        f"class Part{i}:\n    def value(self) -> int:\n        return {i}\n"
        for i in range(14)
    ),
    "pkg/hub.py": "from pkg.parts import "
    + ", ".join(f"Part{i}" for i in range(14))
    + "\n\n\nclass Hub:\n    def __init__(self) -> None:\n"
    + "\n".join(f"        self.p{i} = Part{i}()" for i in range(14))
    + "\n",
    "pkg/api_mod.py": "def keep(a: int, b: int = 0) -> int:\n    return a + b\n",
    # Unannotated and one documented: the three adoption deltas differ.
    "pkg/loose.py": (
        'def loose_one(a, b):\n    """Documented."""\n    return a\n\n\n'
        "def loose_two(c):\n    return c\n"
    ),
    "pkg/cyc_c.py": (
        "from pkg.cyc_d import d\n\n\ndef c() -> int:\n    return d() + 1\n"
    ),
    "pkg/cyc_d.py": (
        "from pkg.cyc_c import c\n\n\ndef d() -> int:\n    return c() - 1\n"
    ),
}
_COMPARISON_FOREIGN_SCOPE = "11111111-2222-4333-8444-555555555555"


@dataclass(frozen=True, slots=True)
class ComparisonRun:
    """One CLI execution of the comparison corpus: the document it rendered
    (the oracle) beside the run it published (the store), one execution."""

    name: str
    document: dict[str, object]
    stored: CanonicalModel
    store_path: Path
    run_id: str


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for relative, source in files.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, "utf-8")


def materialize_comparison_corpus(root: Path, *, stage_b: bool) -> None:
    """The comparison corpus tree: stage A is the baseline's, stage B is
    what the comparison runs see."""
    materialize_wire_freeze_corpus(root, post_baseline=stage_b)
    _write_tree(root, COMPARISON_CORPUS_STAGE_A)
    if stage_b:
        _write_tree(root, COMPARISON_CORPUS_STAGE_B)


def _rewrite_scope_as_foreign(root: Path) -> None:
    """Point the tree's ``baseline_scope_id`` at another scope, so the
    stage-A container no longer describes it."""
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text("utf-8").replace(
            "9e6a3f60-1df0-4c1e-9f3a-6f2f4b6a0c11", _COMPARISON_FOREIGN_SCOPE
        ),
        "utf-8",
    )


def _published_run(store_path: Path) -> tuple[str, CanonicalModel]:
    from codeclone.canonical.store import RunStore

    with RunStore(store_path, create=False) as store:
        (run_id,) = [
            str(row[0])
            for row in store._connection.execute(
                "SELECT run_id FROM runs WHERE published = 1"
            )
        ]
        return run_id, store.read_run(run_id)


def _comparison_run(
    base: Path, name: str, baseline: Path, args: list[str]
) -> ComparisonRun:
    root = base / name
    materialize_comparison_corpus(root, stage_b=True)
    if name == "partial":
        (root / "pkg" / "unparsable.py").write_text("def broken(:\n    pass\n", "utf-8")
    if name == "foreign_scope":
        _rewrite_scope_as_foreign(root)
    store_path = base / f"{name}.sqlite3"
    report_path = base / f"{name}.report.json"
    _run_codeclone_cli(
        [
            str(root),
            "--no-progress",
            "--baseline",
            str(baseline if name != "missing" else base / "absent.baseline.json"),
            "--json",
            str(report_path),
            *args,
        ],
        {
            "CODECLONE_RUN_STORE_FORCE": "1",
            "CODECLONE_RUN_STORE_ENABLED": "1",
            "CODECLONE_RUN_STORE_PATH": str(store_path),
        },
    )
    run_id, stored = _published_run(store_path)
    return ComparisonRun(
        name=name,
        document=json.loads(report_path.read_text("utf-8")),
        stored=stored,
        store_path=store_path,
        run_id=run_id,
    )


#: Every comparison population, by name, and the CLI arguments it runs with.
COMPARISON_POPULATIONS: dict[str, tuple[str, ...]] = {
    "compared": ("--api-surface",),
    "partial": ("--api-surface",),
    "api_disabled": (),
    "lanes_skipped": ("--api-surface", "--skip-dead-code", "--skip-dependencies"),
    "foreign_scope": ("--api-surface",),
    "missing": ("--api-surface",),
}


def _comparison_baseline(base: Path) -> Path:
    """The stage-A baseline (API lane included) every comparison run of
    the corpus is compared against, written under ``base``."""
    stage_a = base / "stage_a"
    materialize_comparison_corpus(stage_a, stage_b=False)
    baseline = base / "corpus.baseline.json"
    _run_codeclone_cli(
        [
            str(stage_a),
            "--no-progress",
            "--api-surface",
            "--baseline",
            str(baseline),
            "--update-baseline",
        ],
        {},
    )
    return baseline


@pytest.fixture(scope="session")
def comparison_runs(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, ComparisonRun]:
    """The comparison corpus under all six configurations (see above),
    each its own tree copy and its own store, one shared stage-A baseline."""
    base = tmp_path_factory.mktemp("comparison_corpus").resolve()
    baseline = _comparison_baseline(base)
    return {
        name: _comparison_run(base, name, baseline, list(args))
        for name, args in COMPARISON_POPULATIONS.items()
    }


# ---------------------------------------------------------------------------
# The comparison corpus served by MCP (canonical epoch E2, cycle 3): the
# surface's own answers are the oracle of the comparison projections, so
# the corpus is analysed by an in-process ``CodeCloneMCPService`` with the
# stage-A baseline at the tree's default baseline path — the way a user's
# checkout carries it — under three configurations:
#
#   * ``trusted``       — every lane compared, the API lane included;
#   * ``foreign_scope`` — the container belongs to another scope: the
#                         surface's resolver refuses it (loaded false);
#   * ``api_disabled``  — the API lane is not enabled on the run.
#
# (The baseline-less state is the serving corpus above.)  One served-only
# carrier sits beside stage B, never inside it (the CLI populations' pins
# are measured on stage B as it is): a NEW clone pair with one member in
# production and one under ``tests/``, the one group whose dominant source
# kind is ``mixed`` — without it the ``mixed`` bucket of
# ``new_by_source_kind`` is zero on every population and a projection that
# folded it into ``other`` would pass unseen (measured 2026-09-27).
# ---------------------------------------------------------------------------

_TWIN_SOURCE = """def twin_tally(values: list[int]) -> dict[str, int]:
    evens = 0
    odds = 0
    peak = 0
    floor = 10**9
    for value in values:
        if value % 2 == 0:
            evens = evens + 1
        else:
            odds = odds + 1
        if value > peak:
            peak = value
        if value < floor:
            floor = value
    return {"evens": evens, "odds": odds, "peak": peak, "floor": floor}
"""
SERVED_COMPARISON_MIXED_CARRIER: dict[str, str] = {
    "pkg/twin_prod.py": _TWIN_SOURCE,
    "tests/test_twin.py": _TWIN_SOURCE,
}
#: The changed paths the PR summary is asked about: one new and one known
#: complexity hotspot, so both filters (path and novelty) must bite.
SERVED_COMPARISON_CHANGED_PATHS: tuple[str, ...] = (
    "pkg/complex_new.py",
    "pkg/complex_old.py",
)
#: The blast-radius origins, by answer label: ``pkg/tri_a.py`` reaches the
#: KNOWN tri cycle transitively, ``pkg/cyc_c.py`` reaches only the NEW
#: cyc cycle — known debt is present in one zone and absent from the other.
SERVED_COMPARISON_BLAST_ORIGINS: dict[str, tuple[str, str]] = {
    "blast_known": ("pkg/tri_a.py", "transitive"),
    "blast_new": ("pkg/cyc_c.py", "direct"),
}
#: Every served comparison population, by name: (API lane enabled,
#: container scope rewritten to a foreign one).
SERVED_COMPARISON_POPULATIONS: dict[str, tuple[bool, bool]] = {
    "trusted": (True, False),
    "foreign_scope": (True, True),
    "api_disabled": (False, False),
}


def _served_comparison_answers(
    service: object, root: Path
) -> dict[str, dict[str, object]]:
    from codeclone.surfaces.mcp.service import CodeCloneMCPService

    assert isinstance(service, CodeCloneMCPService)
    answers: dict[str, dict[str, object]] = {
        "run_summary": service.get_run_summary(root=str(root)),
        "production_triage": service.get_production_triage(root=str(root)),
        "pr_summary": service.generate_pr_summary(root=str(root), format="json"),
        "pr_summary_changed": service.generate_pr_summary(
            root=str(root),
            changed_paths=SERVED_COMPARISON_CHANGED_PATHS,
            format="json",
        ),
        "check_authority": service.check_authority(root=str(root), max_results=100),
    }
    for label, (origin, depth) in SERVED_COMPARISON_BLAST_ORIGINS.items():
        answers[label] = service.get_blast_radius(
            root=str(root), files=[origin], depth=depth
        )
    return answers


def _serve_comparison_corpus(
    base: Path, name: str, baseline: Path
) -> ServedComparisonRun:
    """One MCP analysis of stage B (plus the mixed carrier) against the
    stage-A baseline at the tree's default path, with the run store on."""
    from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest
    from codeclone.surfaces.mcp.service import CodeCloneMCPService

    api_surface, foreign = SERVED_COMPARISON_POPULATIONS[name]
    root = base / f"served_{name}"
    materialize_comparison_corpus(root, stage_b=True)
    _write_tree(root, SERVED_COMPARISON_MIXED_CARRIER)
    (root / "codeclone.baseline.json").write_bytes(baseline.read_bytes())
    if foreign:
        _rewrite_scope_as_foreign(root)
    store_path = base / f"served_{name}.sqlite3"
    with _run_store_rollout(store_path):
        service = CodeCloneMCPService(history_limit=4)
        service.analyze_repository(
            MCPAnalysisRequest(
                root=str(root), analysis_mode="full", api_surface=api_surface
            )
        )
        record = service._runs.resolve_any_root()
        answers = _served_comparison_answers(service, root)
    return ServedComparisonRun(
        name=name,
        store_path=store_path,
        store_run_id=_published_store_run_id(record),
        answers=answers,
    )


@pytest.fixture(scope="session")
def served_comparison_runs(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, ServedComparisonRun]:
    """The comparison corpus served by MCP under all three configurations
    (see above), each its own tree and store, one shared stage-A baseline."""
    base = tmp_path_factory.mktemp("served_comparison").resolve()
    baseline = _comparison_baseline(base)
    return {
        name: _serve_comparison_corpus(base, name, baseline)
        for name in SERVED_COMPARISON_POPULATIONS
    }


@pytest.fixture(autouse=True)
def _clear_workspace_intent_store_cache() -> Generator[None, None, None]:
    from codeclone.surfaces.mcp._workspace_intent_store import (
        clear_workspace_intent_store_cache,
    )

    clear_workspace_intent_store_cache()
    yield
    clear_workspace_intent_store_cache()


@pytest.fixture(autouse=True)
def _track_sqlite_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    monkeypatch.setattr(
        sqlite3,
        "connect",
        make_tracking_connect(sqlite3.connect),
    )
    yield


@pytest.fixture(autouse=True)
def _reset_observability_runtime(
    request: pytest.FixtureRequest,
) -> Generator[None, None, None]:
    yield
    from codeclone.observability.runtime import shutdown

    shutdown()
    close_tracked_sqlite_connections()
    if request.node.get_closest_marker("needs_sqlite_cleanup") is not None:
        sweep_leaked_sqlite_connections_via_gc()


@pytest.fixture
def report_meta_factory() -> ReportMetaFactory:
    def _make(**overrides: object) -> dict[str, object]:
        runtime_tag = current_python_tag()
        runtime_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        meta: dict[str, object] = {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "codeclone_version": "1.4.0",
            "python_version": runtime_version,
            "python_tag": runtime_tag,
            "baseline_path": "/repo/codeclone.baseline.json",
            "baseline_fingerprint_version": "1",
            "baseline_schema_version": "1.0",
            "baseline_python_tag": runtime_tag,
            "baseline_generator_name": "codeclone",
            "baseline_generator_version": "1.4.0",
            "baseline_payload_sha256": "a" * 64,
            "baseline_payload_sha256_verified": True,
            "baseline_loaded": True,
            "baseline_status": "ok",
            "cache_path": "/repo/.codeclone/cache.json",
            "cache_schema_version": CACHE_VERSION,
            "cache_status": "ok",
            "cache_used": True,
            "files_skipped_source_io": 0,
            "report_generated_at_utc": "2026-03-10T12:00:00Z",
        }
        meta.update(overrides)
        return meta

    return _make


# ---------------------------------------------------------------------------
# Backend P0 step 8: the candidate row, read twice.
#
# One probe run published through the canonical store, projected back out of
# it, and spliced into a copy of its own report document.  The builder lives
# here for the same reason the wire-freeze corpus does — the acceptance is
# read by an r4 module (the MCP pager) while the projection it compares is an
# r2 fact, and each module still binds exactly one ring.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def candidate_projection_documents(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, object], dict[str, object], str]:
    """``(report document, same document rebuilt from the store, run id)``.

    Only the candidate items differ in provenance: the rebuilt document
    keeps every other authority item verbatim, so a pager reading both sees
    the same union, the same filter and the same neighbours — and any
    disagreement it reports is the projection's, not the fixture's.
    """
    from codeclone.canonical.authority_projection import candidate_projection_rows
    from tests._projection_equivalence import build_corpus

    base = tmp_path_factory.mktemp("candidate-projection")
    tree = base / "tree"
    tree.mkdir()
    corpus = build_corpus(tree, store_path=base / "runs.sqlite3")

    document = json.loads(json.dumps(corpus.document))
    rebuilt = json.loads(json.dumps(corpus.document))
    items = rebuilt["metrics"]["families"]["semantic_authority"]["items"]
    projected = iter(
        dict(row) for row in candidate_projection_rows(corpus.stored_model)
    )
    rebuilt["metrics"]["families"]["semantic_authority"]["items"] = [
        next(projected) if item.get("item_kind") == "candidate" else item
        for item in items
    ]
    assert next(projected, None) is None, "the projection outran the report"
    return document, rebuilt, corpus.run_id


# ---------------------------------------------------------------------------
# The sink and violation rows, read twice.
#
# Same builder as the candidate fixture above and for the same reason: the
# acceptance is read through a consumer surface (r4) while the projection it
# compares is an r2 fact, so the splice lives here rather than in either
# test module.  ``locations`` used to be the ONE key the violation
# projection did not claim, and the rebuilt document kept the reported value
# for it; the column is stored now, so the projection claims every key and
# the fall-back path below has no exempt key left to take.  The assertion
# that no key falls back is kept rather than deleted: it is what turns a
# projection quietly dropping a column back into a failure.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def authority_projection_documents(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, object], dict[str, object], str]:
    """``(report document, same document rebuilt from the store, run id)``."""
    from codeclone.canonical.authority_projection import (
        VIOLATION_UNPROJECTED_COLUMNS,
        sink_projection_rows,
        violation_projection_rows,
    )
    from tests._projection_equivalence import build_corpus

    base = tmp_path_factory.mktemp("authority-projection")
    tree = base / "tree"
    tree.mkdir()
    corpus = build_corpus(tree, store_path=base / "runs.sqlite3")

    document = json.loads(json.dumps(corpus.document))
    rebuilt = json.loads(json.dumps(corpus.document))
    items = rebuilt["metrics"]["families"]["semantic_authority"]["items"]
    projected = {
        "sink": iter(dict(row) for row in sink_projection_rows(corpus.stored_model)),
        "violation": iter(
            dict(row) for row in violation_projection_rows(corpus.stored_model)
        ),
    }

    def _rebuild(item: dict[str, object]) -> dict[str, object]:
        """One item, rebuilt where a projection owns it.

        Assembled by walking the REPORT row's keys rather than the
        projection's, so the rebuilt row carries the document builder's own
        key ORDER -- without which a byte comparison of two serialized pages
        would report a difference that is not one.  A key the projection
        does not claim falls back to the reported value, and the only key
        allowed to take that path is asserted below.
        """

        rows = projected.get(str(item.get("item_kind")))
        if rows is None:
            return item
        row = next(rows)
        assert set(row) - set(item) == set(), "the projection invented a column"
        assert set(item) - set(row) <= set(VIOLATION_UNPROJECTED_COLUMNS), (
            "the projection dropped a column nobody exempted"
        )
        return {key: row.get(key, value) for key, value in item.items()}

    rebuilt["metrics"]["families"]["semantic_authority"]["items"] = [
        _rebuild(item) for item in items
    ]
    for kind, rows in projected.items():
        assert next(rows, None) is None, f"the {kind} projection outran the report"
    return document, rebuilt, corpus.run_id


# ---------------------------------------------------------------------------
# The producer-wiring corpus runner (backend step 7).
#
# Lives here, beside the wire-freeze runner and for the same reason: the
# subject of ``test_run_store_producer_wiring`` is ring r2 throughout, and
# importing the r4 CLI surface from that module would make every r2 import
# in it a new architecture-ratchet entry (the Phase 39S test-import law).
# The invocation is in-process rather than in a subprocess so the coverage
# instrument actually sees the production path it drives; the rollout
# environment is applied through monkeypatch, undone on the way out.
# ---------------------------------------------------------------------------

RunStoreCorpusRunner = Callable[..., None]


def _run_codeclone_cli(args: list[str], environment: dict[str, str]) -> None:
    """One CLI invocation with an explicit rollout environment."""

    import codeclone.surfaces.cli.workflow as cli

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(sys, "argv", ["codeclone", *args])
        for key, value in environment.items():
            monkeypatch.setenv(key, value)
        for key in (
            "CODECLONE_RUN_STORE_ENABLED",
            "CODECLONE_RUN_STORE_PATH",
            "CODECLONE_RUN_STORE_FORCE",
        ):
            if key not in environment:
                monkeypatch.delenv(key, raising=False)
        try:
            cli.main()
        except SystemExit as exit_signal:
            code = exit_signal.code
            assert code in (None, 0, 1), f"CLI exited {code!r}: {args}"
    finally:
        monkeypatch.undo()


@pytest.fixture
def run_store_cli() -> RunStoreCorpusRunner:
    """Run the real CLI waterfall over a corpus, with a rollout environment."""

    def _run(
        root: Path,
        *args: str,
        store: Path | None = None,
        force_ci: bool = True,
    ) -> None:
        environment: dict[str, str] = {}
        if force_ci:
            # The rollout is CI-neutral by design and the suite may run
            # under CI; the probe says so rather than depending on the host.
            environment["CODECLONE_RUN_STORE_FORCE"] = "1"
        if store is not None:
            environment["CODECLONE_RUN_STORE_ENABLED"] = "1"
            environment["CODECLONE_RUN_STORE_PATH"] = str(store)
        _run_codeclone_cli(
            [
                str(root),
                "--no-progress",
                "--baseline",
                str(root / "corpus.baseline.json"),
                *args,
            ],
            environment,
        )

    return _run


# ---------------------------------------------------------------------------
# The live-state boundary (tests/_live_state.py).
#
# One mechanism, installed once per session and applied to every test without
# the test knowing it exists: the live repository's default durable-state
# anchor is relocated to a scratch directory private to the running test (and
# the product's containment gate reads the relocated path as contained where
# its original is, so consumers re-validating it get the original's answer), an
# open of any SQLite store under a live service directory is refused, a git
# subprocess that would mutate a live repository is refused, and the hosting
# checkout's tree is compared before and after the run. Session- and
# module-scoped fixtures are covered too, because the patches are process-wide
# and the per-test toggle happens in hooks that run before any fixture.
#
# ``@pytest.mark.live_state(reason=...)`` lifts the in-process enforcements for
# a test whose legitimate subject is live state; every opt-in is listed in the
# terminal summary so it cannot be quiet.
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{LIVE_STATE_MARKER}(reason): the test's legitimate subject is live "
        "CodeClone state; the live-state boundary is lifted for it and the "
        "opt-in is listed in the terminal summary",
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    session.config.stash[LIVE_STATE_GUARD_KEY] = LiveStateGuard.install()


def pytest_sessionfinish(session: pytest.Session) -> None:
    guard = session.config.stash.get(LIVE_STATE_GUARD_KEY, None)
    if guard is not None:
        guard.uninstall()


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    """The residue gate measures the whole run, so it runs after everything."""

    gate = [item for item in items if item.name == TREE_RESIDUE_GATE_TEST]
    for item in gate:
        items.remove(item)
    items.extend(gate)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    marker = item.get_closest_marker(LIVE_STATE_MARKER)
    reason: str | None = None
    if marker is not None:
        candidate = marker.kwargs.get("reason", marker.args[0] if marker.args else None)
        if not isinstance(candidate, str) or not candidate.strip():
            pytest.fail(
                f"{item.nodeid}: @pytest.mark.{LIVE_STATE_MARKER} requires "
                "reason='...': say what live state the test measures and why it "
                "cannot use tmp_path",
                pytrace=False,
            )
        reason = candidate.strip()
    live_state_guard(item.config).enter_test(item.nodeid, reason)


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item: pytest.Item) -> None:
    violations = live_state_guard(item.config).exit_test()
    if violations:
        pytest.fail(
            "the test reached for live CodeClone state (refused; nothing was "
            "written):\n" + "\n".join(f"  {violation}" for violation in violations),
            pytrace=False,
        )


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, exitstatus: int, config: pytest.Config
) -> None:
    guard = config.stash.get(LIVE_STATE_GUARD_KEY, None)
    if guard is None or not guard.opted_in:
        return
    terminalreporter.section("live-state opt-ins", sep="-")
    for nodeid, reason in guard.opted_in:
        terminalreporter.line(f"{nodeid}: {reason}")
