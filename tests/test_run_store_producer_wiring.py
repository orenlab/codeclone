# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Producer wiring of the canonical run-store (backend step 7).

The subject is ring r2 throughout.  The end-to-end runs reach the real CLI
waterfall through the ``run_store_cli`` fixture in ``tests/conftest.py``
rather than by importing an r4 surface here: an r4 import would make this
an r4-subject module and every r2 import below a new architecture-ratchet
entry (the Phase 39S test-import law).

Four properties are pinned that no green publish proves on its own:

* the flag is off by default and a default run stores NOTHING;
* an enabled run stores its snapshot and advances the canonical head;
* a clones-only run leaves as ``disabled`` producer states — never as
  fifteen honest-looking zeros — and never touches the canonical head;
* the producer-native model equals the legacy-oracle model row for row on
  one real corpus run (projection equivalence in the producer's half).
"""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from codeclone.canonical.identity import (
    PRODUCER_EXECUTION_STATES,
    FileId,
    ModuleId,
    ModuleSymbol,
    OpaqueEntity,
    SymbolId,
)
from codeclone.canonical.ingest import canonical_model_from_legacy_document
from codeclone.canonical.model import AnalysisPopulation
from codeclone.canonical.store import HeadState, RunStore
from codeclone.core._types import AnalysisResult
from codeclone.core.canonical_snapshot import (
    ENV_RUN_STORE_ENABLED,
    ENV_RUN_STORE_FORCE,
    ENV_RUN_STORE_PATH,
    RUN_SNAPSHOT_NAMESPACE,
    ProducerSnapshotUnavailable,
    _clone_group_rows,
    _dead_code_entity,
    _dependency_cycle_rows,
    _endpoint,
    _lane_symbol,
    _RegistryIndex,
    _security_surface_rows,
    _surface_head,
    _symbol,
    population_is_admissible,
    producer_state,
    profile_head_target,
    publish_run_snapshot,
    resolve_run_store_config,
)
from codeclone.models import (
    CANONICAL_HEAD_TARGET,
    CANONICAL_PROFILE_HEAD_PREFIX,
    RUN_SNAPSHOT_PUBLICATION_DISABLED,
    RUN_SNAPSHOT_PUBLICATION_HEAD_WITHHELD,
    RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
    FileIdentity,
    ModuleInventoryEntry,
    ModuleInventoryIndex,
    ModuleRegistryHandle,
    ResolvedSourceIdentity,
    RunSnapshotPublication,
    RunStoreConfig,
)
from codeclone.paths.module_identity.inventory import build_module_registry
from codeclone.paths.workspace import REL_RUN_STORE_DB_PATH
from tests.conftest import RunStoreCorpusRunner

_ROOT = Path(__file__).resolve().parents[1]

# One corpus that carries a NON-EMPTY population in every family the
# producer-native builder owns: a clone pair, an import cycle, coupled
# classes, a security surface, dead code and public API symbols.  A family
# compared at zero rows on both sides proves nothing about its mapping,
# which is why the equivalence corpus is built to be loaded rather than
# convenient.
_CORPUS: dict[str, str] = {
    "pkg/__init__.py": "",
    "pkg/c1.py": '''"""C1."""

import json


def alpha(value: int) -> int:
    """Alpha."""
    total = 0
    for index in range(value):
        total += index
        if total > 10:
            total -= 1
        else:
            total += 2
    return total


def render(payload: dict) -> str:
    """Render."""
    return json.dumps(payload)
''',
    "pkg/c2.py": '''"""C2."""


def beta(value: int) -> int:
    """Beta."""
    total = 0
    for index in range(value):
        total += index
        if total > 10:
            total -= 1
        else:
            total += 2
    return total


def danger(source: str) -> object:
    """Danger."""
    return eval(source)
''',
    "pkg/cyc_a.py": '''"""Cycle A."""

from pkg.cyc_b import b


class Holder:
    """Holder."""

    def __init__(self) -> None:
        self.first = 1
        self.second = 2

    def one(self) -> int:
        """One."""
        return self.first

    def two(self) -> int:
        """Two."""
        return self.second


def a() -> int:
    """A."""
    return b()
''',
    "pkg/cyc_b.py": '''"""Cycle B."""

from pkg.cyc_a import Holder


def b() -> int:
    """B."""
    return Holder().one()
''',
    # Coupled classes: the ``coupled_sets`` value family is empty on a tree
    # whose classes never reference each other, and a family compared at
    # zero rows on both sides proves nothing about its mapping.
    "pkg/coupled.py": '''"""Coupled."""


class Engine:
    """Engine."""

    def __init__(self) -> None:
        self.wheel = Wheel()
        self.axle = Axle()

    def spin(self) -> int:
        """Spin."""
        return self.wheel.turn() + self.axle.hold()


class Wheel:
    """Wheel."""

    def turn(self) -> int:
        """Turn."""
        return 1


class Axle:
    """Axle."""

    def hold(self) -> int:
        """Hold."""
        return 2
''',
}

_FULL_METRICS_ARGS = (
    "--fail-health",
    "0",
    "--api-surface",
    "--min-loc",
    "3",
    "--min-stmt",
    "2",
)


def _write_corpus(root: Path) -> None:
    for relative, source in _CORPUS.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, "utf-8")


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    _write_corpus(root)
    return root


# -- the rollout flag -------------------------------------------------------


def test_the_rollout_flag_is_off_by_default(tmp_path: Path) -> None:
    """T1 is "no backend", and no backend is the ABSENCE of a
    representation — never a second truth about the run."""
    config = resolve_run_store_config(root=tmp_path, environ={})
    assert config == RunStoreConfig(enabled=False, path=None)
    assert not config.enabled
    assert config.path is None


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "", "maybe"])
def test_only_an_affirmative_value_enables_the_rollout(
    tmp_path: Path, raw: str
) -> None:
    assert not resolve_run_store_config(
        root=tmp_path, environ={ENV_RUN_STORE_ENABLED: raw}
    ).enabled


@pytest.mark.parametrize("raw", ["1", "true", "yes", "on", "ON"])
def test_an_affirmative_value_enables_the_rollout(tmp_path: Path, raw: str) -> None:
    config = resolve_run_store_config(
        root=tmp_path, environ={ENV_RUN_STORE_ENABLED: raw}
    )
    assert config.enabled
    assert config.path == tmp_path / REL_RUN_STORE_DB_PATH


def test_ci_is_neutral_unless_the_rollout_is_forced(tmp_path: Path) -> None:
    """A backend that starts writing a database inside every CI checkout
    because a shared profile exported a variable is a surprise, not a
    rollout.  FORCE lifts the CI gate and enables nothing by itself."""
    gated = resolve_run_store_config(
        root=tmp_path, environ={ENV_RUN_STORE_ENABLED: "1", "CI": "true"}
    )
    assert not gated.enabled
    forced = resolve_run_store_config(
        root=tmp_path,
        environ={ENV_RUN_STORE_ENABLED: "1", "CI": "true", ENV_RUN_STORE_FORCE: "1"},
    )
    assert forced.enabled
    assert not resolve_run_store_config(
        root=tmp_path, environ={"CI": "true", ENV_RUN_STORE_FORCE: "1"}
    ).enabled


def test_a_relative_path_override_resolves_against_the_analysis_root(
    tmp_path: Path,
) -> None:
    """The three waterfalls do not share one working directory, so a
    relative override anchors on the root that is being analyzed."""
    config = resolve_run_store_config(
        root=tmp_path,
        environ={ENV_RUN_STORE_ENABLED: "1", ENV_RUN_STORE_PATH: "db/runs.sqlite3"},
    )
    assert config.path == tmp_path / "db/runs.sqlite3"
    absolute = resolve_run_store_config(
        root=tmp_path,
        environ={ENV_RUN_STORE_ENABLED: "1", ENV_RUN_STORE_PATH: "/tmp/x/runs.db"},
    )
    assert absolute.path == Path("/tmp/x/runs.db")


# -- the execution-population decision table --------------------------------


def test_the_producer_state_table_is_total_and_every_state_is_reachable() -> None:
    """Five states, five reachable inputs, and the hard law in the middle
    row: a zero count is admissible ONLY under ``complete``.

    The table is pinned by its inputs rather than by a literal list, so a
    branch that stops firing is a red test and not a silently narrower
    classification.
    """
    reached = {
        producer_state(executed=False, disabled=True, population="complete_nonempty"),
        producer_state(executed=True, disabled=True, population="complete_nonempty"),
        producer_state(executed=False, disabled=False, population="complete_nonempty"),
        producer_state(executed=True, disabled=False, population="partial"),
        producer_state(executed=True, disabled=False, population="unmeasured"),
        producer_state(executed=True, disabled=False, population="complete_nonempty"),
        producer_state(executed=True, disabled=False, population="complete_empty"),
    }
    assert reached == set(PRODUCER_EXECUTION_STATES)
    assert (
        producer_state(executed=True, disabled=True, population="complete_nonempty")
        == "disabled"
    )
    assert (
        producer_state(executed=False, disabled=False, population="complete_nonempty")
        == "not_executed"
    )
    assert (
        producer_state(executed=True, disabled=False, population="partial")
        == "truncated"
    )
    assert (
        producer_state(executed=True, disabled=False, population="unmeasured")
        == "unavailable"
    )
    assert (
        producer_state(executed=True, disabled=False, population="complete_empty")
        == "complete"
    )


def _population(mode: str, **states: str) -> AnalysisPopulation:
    return AnalysisPopulation(
        analysis_mode=mode,
        analysis_profile=(("min_loc", 6),),
        producer_states=tuple(sorted(states.items())),
    )


def test_only_a_complete_untruncated_profile_may_hold_the_canonical_head() -> None:
    """Ratified I2-D: partial, clones-only and truncated analyses are
    stored and never replace a complete measurement.  Every one of the
    three inadmissible cases is exercised, and both admissible states
    (``disabled`` and ``not_executed`` producers) are exercised too — a
    predicate that rejected those would leave the canonical head
    unreachable by every ordinary run."""
    complete = _population("full", complexity="complete", coverage_join="not_executed")
    assert population_is_admissible(complete)
    assert profile_head_target(complete) == CANONICAL_HEAD_TARGET

    opt_in_off = _population("full", complexity="complete", near_miss="disabled")
    assert population_is_admissible(opt_in_off)
    assert profile_head_target(opt_in_off) == CANONICAL_HEAD_TARGET

    for inadmissible in (
        _population("clones_only", complexity="disabled"),
        _population("full", complexity="truncated"),
        _population("full", complexity="unavailable"),
    ):
        assert not population_is_admissible(inadmissible)
        target = profile_head_target(inadmissible)
        assert target.startswith(CANONICAL_PROFILE_HEAD_PREFIX)
        assert target != CANONICAL_HEAD_TARGET


def test_different_realized_profiles_take_different_heads() -> None:
    """``generation`` proves publication ORDER and nothing about
    completeness, so two different realized profiles must never share one
    head — otherwise the newer poorer measurement wins by arriving late."""
    first = profile_head_target(_population("clones_only", complexity="disabled"))
    second = profile_head_target(_population("full", complexity="truncated"))
    assert first != second


# -- the publication witness ------------------------------------------------


def test_the_stored_outcomes_cannot_disagree_with_the_admissibility_verdict() -> None:
    """``head_withheld`` and ``head_conflict`` are both "the head did not
    move for me", and only the admissibility flag says which question was
    answered.  The type refuses the combination that would let a complete
    profile be reported as head-withheld — which would turn a lost race
    into a completeness claim.
    """
    withheld = RunSnapshotPublication(
        outcome=RUN_SNAPSHOT_PUBLICATION_HEAD_WITHHELD,
        admissible=False,
        target="profile:abc",
        run_id="r",
        generation=1,
    )
    assert withheld.outcome == RUN_SNAPSHOT_PUBLICATION_HEAD_WITHHELD
    published = RunSnapshotPublication(
        outcome=RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
        admissible=True,
        target=CANONICAL_HEAD_TARGET,
        run_id="r",
        generation=1,
    )
    assert published.admissible
    with pytest.raises(ValueError, match="inadmissible-profile outcome"):
        RunSnapshotPublication(
            outcome=RUN_SNAPSHOT_PUBLICATION_HEAD_WITHHELD,
            admissible=True,
            target=CANONICAL_HEAD_TARGET,
            run_id="r",
            generation=1,
        )
    with pytest.raises(ValueError, match="carries no store receipt"):
        RunSnapshotPublication(
            outcome=RUN_SNAPSHOT_PUBLICATION_DISABLED,
            admissible=False,
            target=CANONICAL_HEAD_TARGET,
            run_id="r",
        )


def test_a_disabled_rollout_returns_a_typed_witness_and_stores_nothing(
    tmp_path: Path,
) -> None:
    """The skip is the DEFAULT path.  A publication that skipped silently
    would be indistinguishable from a backend nobody wired, which is the
    exact confusion this rollout exists to avoid."""
    publication = publish_run_snapshot(
        config=RunStoreConfig(enabled=False, path=None),
        discovery=None,  # type: ignore[arg-type]
        processing=None,  # type: ignore[arg-type]
        analysis=None,  # type: ignore[arg-type]
        report_meta={},
    )
    assert publication.outcome == RUN_SNAPSHOT_PUBLICATION_DISABLED
    assert not publication.admissible
    assert publication.run_id == ""
    assert list(tmp_path.iterdir()) == []


# -- end to end through the real CLI waterfall ------------------------------


def _run_and_read(
    run_store_cli: RunStoreCorpusRunner, corpus: Path
) -> tuple[Path, dict[str, object]]:
    """One enabled full-metrics run, plus the document it rendered."""

    store = corpus / "runs.sqlite3"
    report_path = corpus / "report.json"
    run_store_cli(corpus, *_FULL_METRICS_ARGS, "--json", str(report_path), store=store)
    document: dict[str, object] = json.loads(report_path.read_text("utf-8"))
    assert isinstance(document, dict)
    return store, document


def _head(store: Path, target: str) -> HeadState | None:
    with RunStore(store) as run_store:
        return run_store.head(namespace=RUN_SNAPSHOT_NAMESPACE, target=target)


def test_a_default_run_publishes_nothing_at_all(
    corpus: Path,
    run_store_cli: RunStoreCorpusRunner,
) -> None:
    """Default OFF is a property of the shipped build, not of a test
    fixture: the run is driven with no rollout variable in its environment
    and the repo-local database must not come into existence."""
    report_path = corpus / "report.json"
    run_store_cli(corpus, *_FULL_METRICS_ARGS, "--json", str(report_path), store=None)
    # The instrument is proven on before the count is read: the absence of
    # a database means nothing unless the analysis actually ran.
    assert report_path.exists()
    meta = cast("dict[str, object]", json.loads(report_path.read_text("utf-8"))["meta"])
    assert meta["analysis_mode"] == "full"
    assert not (corpus / REL_RUN_STORE_DB_PATH).exists()
    assert not list(corpus.glob("**/*.sqlite3"))


def test_an_enabled_full_run_advances_the_canonical_head(
    corpus: Path,
    run_store_cli: RunStoreCorpusRunner,
) -> None:
    store = corpus / "runs.sqlite3"
    run_store_cli(corpus, *_FULL_METRICS_ARGS, store=store)
    assert store.exists()
    head = _head(store, CANONICAL_HEAD_TARGET)
    assert head is not None
    assert head.generation == 1
    with RunStore(store) as run_store:
        model = run_store.read_run(head.run_id)
    population = model.facts.analysis.analysis_population
    assert population is not None
    assert population.analysis_mode == "full"
    states = dict(population.producer_states)
    assert states["complexity"] == "complete"
    assert model.facts.analysis.run_scalars is not None


def test_a_clones_only_run_is_stored_as_disabled_and_never_moves_the_head(
    corpus: Path,
    run_store_cli: RunStoreCorpusRunner,
) -> None:
    """The measured defect this wave closes: a clones-only run used to
    reach the store as fifteen honest-looking zeros and to advance the
    same head a complete analysis had just published.

    Both halves are pinned here, because fixing only the first would leave
    a poorer measurement quietly displacing a fuller one.
    """
    store = corpus / "runs.sqlite3"
    run_store_cli(corpus, *_FULL_METRICS_ARGS, store=store)
    complete_head = _head(store, CANONICAL_HEAD_TARGET)
    assert complete_head is not None

    run_store_cli(corpus, "--skip-metrics", store=store)
    after = _head(store, CANONICAL_HEAD_TARGET)
    assert after == complete_head, "a clones-only run displaced the canonical head"

    with RunStore(store) as run_store:
        published = {
            str(row[0])
            for row in run_store._connection.execute("SELECT run_id FROM runs")
        }
        targets = {
            str(row[0])
            for row in run_store._connection.execute("SELECT target FROM heads")
        }
    assert len(published) == 2, "the clones-only snapshot was not stored at all"
    partial_targets = {
        target for target in targets if target.startswith(CANONICAL_PROFILE_HEAD_PREFIX)
    }
    assert len(partial_targets) == 1
    partial_head = _head(store, partial_targets.pop())
    assert partial_head is not None
    with RunStore(store) as run_store:
        partial = run_store.read_run(partial_head.run_id)
    population = partial.facts.analysis.analysis_population
    assert population is not None
    assert population.analysis_mode == "clones_only"
    states = dict(population.producer_states)
    # Every metric producer the run-wide switch turned off says so. A zero
    # count is admissible ONLY as the result of an executed measurement.
    assert states["complexity"] == "disabled"
    assert states["dead_code"] == "disabled"
    assert states["dependencies"] == "disabled"
    assert "complete" not in set(states.values())
    assert partial.facts.analysis.risk_observations == frozenset()


def test_the_producer_native_model_equals_the_legacy_oracle(
    corpus: Path,
    run_store_cli: RunStoreCorpusRunner,
) -> None:
    """Projection equivalence on ONE real corpus run, family by family.

    The oracle refuses a document whose ``source_facts.semantic`` is null,
    and the producer-native builder refuses a run whose semantic lane
    executed, so the two paths meet only over a semantic-off run with the
    empty semantic containers the document omits.  Supplying those empty
    containers fabricates no row; every family below is compared on the
    producer output of the same single run.

    ``analysis_population`` is deliberately excluded and asserted
    separately: the producer edge can and must pronounce states the
    rendered document cannot witness, so equality there would mean the
    producer had forgotten what it knows.
    """
    store, document = _run_and_read(run_store_cli, corpus)
    source_facts = cast("dict[str, object]", document["source_facts"])
    assert source_facts["semantic"] is None
    source_facts["semantic"] = {
        "contract_ir": {"contracts": []},
        "graph": {"nodes": [], "edges": []},
        "sinks": [],
        "candidates": [],
        "violations": [],
    }
    oracle = canonical_model_from_legacy_document(document)
    head = _head(store, CANONICAL_HEAD_TARGET)
    assert head is not None
    with RunStore(store) as run_store:
        native = run_store.read_run(head.run_id)

    assert native.files == oracle.files
    assert native.modules == oracle.modules
    assert native.analyzed_files == oracle.analyzed_files
    assert native.file_modules == oracle.file_modules
    # Asserted non-empty first: the coupled-class value family was silently
    # never wired into the model, and the comparison stayed green because
    # BOTH sides were empty on a corpus whose classes never referenced each
    # other.  A family compared at zero is a hollow pin.
    assert native.coupled_sets
    assert native.coupled_sets == oracle.coupled_sets

    produced = native.facts.analysis
    expected = oracle.facts.analysis
    assert produced.run_scalars == expected.run_scalars
    # Loaded families: a family compared at zero rows proves nothing about
    # its mapping, so each of these is asserted non-empty first.
    for family in (
        "adoption_counts",
        "api_symbols",
        "clone_groups",
        "coupling_cohesion_observations",
        "dead_code_observations",
        "dependency_cycles",
        "dependency_occurrences",
        "dependency_relations",
        "risk_observations",
        "security_surfaces",
    ):
        rows = getattr(produced, family)
        assert rows, f"{family} carries no rows; the comparison would be hollow"
        assert rows == getattr(expected, family), family

    population = produced.analysis_population
    assert population is not None
    states = dict(population.producer_states)
    assert states["coverage_join"] == "not_executed"
    assert states["near_miss"] == "disabled"
    assert states["complexity"] == "complete"


# -- one call site, three waterfalls ----------------------------------------


def _calls(tree: ast.AST, name: str) -> int:
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    )


def _tree(relative: str) -> ast.AST:
    return ast.parse((_ROOT / relative).read_text("utf-8"), filename=relative)


def test_the_publication_has_exactly_one_production_call_site() -> None:
    """The resolver and the publisher are called from ONE module, and the
    flag is resolved where it is used.

    A flag read somewhere other than the publication point lets one
    surface answer "enabled" while another answers "disabled" for the same
    run — the configuration drift the delivery ratchet exists to catch —
    and a second publish site would give the three waterfalls two dialects
    of one fact.  Read off the syntax trees, never off a list kept beside
    them.
    """
    owners = sorted(
        path.relative_to(_ROOT).as_posix()
        for path in (_ROOT / "codeclone").rglob("*.py")
        if "publish_run_snapshot" in path.read_text("utf-8")
    )
    assert owners == [
        "codeclone/core/canonical_snapshot.py",
        "codeclone/core/reporting.py",
    ]
    resolvers = sorted(
        path.relative_to(_ROOT).as_posix()
        for path in (_ROOT / "codeclone").rglob("*.py")
        if "resolve_run_store_config" in path.read_text("utf-8")
    )
    assert resolvers == [
        "codeclone/core/canonical_snapshot.py",
        "codeclone/core/reporting.py",
    ]
    reporting = _tree("codeclone/core/reporting.py")
    assert _calls(reporting, "publish_run_snapshot") == 1
    assert _calls(reporting, "resolve_run_store_config") == 1
    assert _calls(reporting, "_publish_canonical_snapshot") == 1


def test_every_waterfall_reaches_the_single_publication_point() -> None:
    """The three surfaces that produce a semantic run all call ``report``.

    This is the structural edge from the publication point back to each
    waterfall: MCP deliberately bypasses the CLI stage runner, so a publish
    hung off that runner would reach two of the three and the third would
    silently store nothing.
    """
    for waterfall in (
        "codeclone/surfaces/cli/workflow.py",
        "codeclone/surfaces/cli/memory_analysis.py",
        "codeclone/surfaces/mcp/session.py",
    ):
        assert _calls(_tree(waterfall), "report") == 1, waterfall


# -- every refusal has an input that reaches it -----------------------------
#
# A guard no input can trip is theater.  Each block below supplies the input
# that reaches one refusal, so the guard set is proven reachable rather than
# merely present.


def _package_registry(
    root: Path,
) -> tuple[
    ModuleRegistryHandle,
    tuple[tuple[str, ModuleInventoryEntry], ...],
    ModuleInventoryEntry,
]:
    """A real one-package registry plus the row the doctoring tests edit."""

    (root / "pkg").mkdir()
    (root / "pkg/__init__.py").write_text("", "utf-8")
    (root / "pkg/a.py").write_text('"""A."""\n', "utf-8")
    registry = build_module_registry(root=root)
    rows = registry.entries_by_path.rows
    return registry, rows, dict(rows)["pkg/a.py"]


@pytest.fixture
def index(tmp_path: Path) -> _RegistryIndex:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/__init__.py").write_text("", "utf-8")
    (tmp_path / "pkg/a.py").write_text('"""A."""\n', "utf-8")
    (tmp_path / "loose.py").write_text('"""Loose."""\n', "utf-8")
    registry = build_module_registry(root=tmp_path)
    return _RegistryIndex(registry, frozenset({"pkg/a.py", "loose.py"}))


def test_a_registry_that_claims_two_files_for_one_module_is_refused(
    tmp_path: Path,
) -> None:
    """The identity laws are refusals, never repairs — a registry at war
    with itself cannot be silently normalized into one answer."""
    registry, rows, entry = _package_registry(tmp_path)
    twin = replace(
        entry,
        identity=replace(entry.identity, file=FileIdentity(path="pkg/twin.py")),
    )
    doubled = replace(
        registry,
        entries_by_path=ModuleInventoryIndex(
            rows=tuple(sorted((*rows, ("pkg/twin.py", twin))))
        ),
    )
    with pytest.raises(ProducerSnapshotUnavailable, match="claims two files"):
        _RegistryIndex(doubled, frozenset({"pkg/a.py", "pkg/twin.py"}))

    assert entry.identity.python_module is not None
    conflicting = replace(
        entry,
        identity=ResolvedSourceIdentity(
            file=entry.identity.file,
            python_module=replace(entry.identity.python_module, module="pkg.other"),
        ),
    )
    with pytest.raises(ProducerSnapshotUnavailable, match="claims two modules"):
        _RegistryIndex(
            replace(
                registry,
                entries_by_path=ModuleInventoryIndex(
                    rows=tuple(
                        sorted(
                            (
                                *(row for row in rows if row[0] != "pkg/a.py"),
                                ("pkg/a.py", entry),
                                ("zz", conflicting),
                            )
                        )
                    )
                ),
            ),
            frozenset({"pkg/a.py"}),
        )


def test_a_registry_entry_without_a_module_identity_is_skipped_not_guessed(
    tmp_path: Path,
) -> None:
    """A registry row the identity strategy could not name as a module
    carries no MODULE head, so it joins no module index — the FILE head
    still resolves, and nothing is invented for it."""
    registry, rows, entry = _package_registry(tmp_path)
    nameless = replace(
        entry,
        identity=ResolvedSourceIdentity(file=entry.identity.file, python_module=None),
    )
    doctored = replace(
        registry,
        entries_by_path=ModuleInventoryIndex(
            rows=tuple(
                sorted(
                    (
                        *(row for row in rows if row[0] != "pkg/a.py"),
                        ("pkg/a.py", nameless),
                    )
                )
            )
        ),
    )
    index = _RegistryIndex(doctored, frozenset({"pkg/a.py"}))
    assert "pkg.a" not in index.module_to_path
    assert _symbol(index, "pkg/a.py:fn", "s") == SymbolId(FileId("pkg/a.py"), "fn")


def test_the_symbol_resolver_reaches_both_heads_and_both_refusals(
    index: _RegistryIndex,
) -> None:
    assert _symbol(index, "pkg.a:fn", "s") == SymbolId(FileId("pkg/a.py"), "fn")
    assert _symbol(index, "loose.py:fn", "s") == SymbolId(FileId("loose.py"), "fn")
    with pytest.raises(ProducerSnapshotUnavailable, match="ModuleKey-headed"):
        _symbol(index, "bare_name", "s")
    with pytest.raises(ProducerSnapshotUnavailable, match="refusing to guess"):
        _symbol(index, "nowhere:fn", "s")


def test_the_endpoint_resolver_reaches_both_domains_and_its_refusal(
    index: _RegistryIndex,
) -> None:
    assert _endpoint(index, "pkg.a", "e") == ModuleId("pkg.a")
    assert _endpoint(index, "loose.py", "e") == FileId("loose.py")
    with pytest.raises(ProducerSnapshotUnavailable, match="neither a registry module"):
        _endpoint(index, "nowhere", "e")


def test_the_lane_identity_law_refuses_both_ways(index: _RegistryIndex) -> None:
    assert _lane_symbol(index, "pkg/a.py", "fn", "risk") == SymbolId(
        FileId("pkg/a.py"), "fn"
    )
    with pytest.raises(ProducerSnapshotUnavailable, match="not an analyzed path"):
        _lane_symbol(index, "pkg/missing.py", "fn", "risk")
    with pytest.raises(ProducerSnapshotUnavailable, match="glued identity"):
        _lane_symbol(index, "pkg/a.py", "mod:fn", "risk")


def test_the_dead_code_entity_reaches_all_three_variants_and_both_refusals(
    index: _RegistryIndex,
) -> None:
    """The tagged reference keeps the head the producer made: a registry
    module stays MODULE-headed, an analyzed path stays FILE-headed, and
    anything else rides the opaque variant verbatim."""
    assert _dead_code_entity(index, "pkg.a:fn") == ModuleSymbol(ModuleId("pkg.a"), "fn")
    assert _dead_code_entity(index, "loose.py:fn") == SymbolId(FileId("loose.py"), "fn")
    assert _dead_code_entity(index, "nowhere:fn") == OpaqueEntity("nowhere", "fn")
    with pytest.raises(ProducerSnapshotUnavailable, match="head:local"):
        _dead_code_entity(index, "nocolon")
    with pytest.raises(ProducerSnapshotUnavailable, match="second ModuleKey colon"):
        _dead_code_entity(index, "pkg.a:mod:fn")


def test_the_surface_head_reaches_its_two_answers_and_its_refusal(
    index: _RegistryIndex,
) -> None:
    assert _surface_head(index, "pkg/a.py") == "pkg.a"
    with pytest.raises(ProducerSnapshotUnavailable, match="not an analyzed path"):
        _surface_head(index, "pkg/missing.py")


def test_a_cycle_row_is_refused_when_it_repeats_or_leaves_the_module_domain(
    index: _RegistryIndex,
) -> None:
    """A cycle set is a MODULE-domain fact; a member that is not a registry
    module would mint an identity, and a repeated member would be absorbed
    silently by the set."""
    assert _dependency_cycle_rows({}, index) == frozenset()
    with pytest.raises(ProducerSnapshotUnavailable, match="repeats a member"):
        _dependency_cycle_rows(
            {
                "dependencies": {
                    "cycle_details": [
                        {"kind": "import_cycle", "modules": ["pkg.a", "pkg.a"]}
                    ]
                }
            },
            index,
        )
    with pytest.raises(ProducerSnapshotUnavailable, match="not a registry module"):
        _dependency_cycle_rows(
            {
                "dependencies": {
                    "cycle_details": [
                        {"kind": "import_cycle", "modules": ["pkg.a", "loose.py"]}
                    ]
                }
            },
            index,
        )


def _surface(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "category": "process_boundary",
        "capability": "subprocess.run",
        "module": "pkg.a",
        "filepath": "pkg/a.py",
        "qualname": "pkg.a:fn",
        "start_line": 3,
        "end_line": 3,
        "source_kind": "production",
        "location_scope": "callable",
        "classification_mode": "exact_call",
        "evidence_kind": "call",
        "evidence_symbol": "run",
    }
    row.update(overrides)
    return row


def test_a_security_surface_at_war_with_the_registry_is_refused(
    index: _RegistryIndex,
) -> None:
    """Three registry-consistency laws, each a refusal and never a repair."""
    payload = {"security_surfaces": {"items": [_surface()]}}
    assert len(_security_surface_rows(payload, index)) == 1

    module_scope = {
        "security_surfaces": {
            "items": [_surface(location_scope="module", qualname="pkg.a")]
        }
    }
    rows = _security_surface_rows(module_scope, index)
    assert next(iter(rows)).qualname is None

    with pytest.raises(ProducerSnapshotUnavailable, match="disagrees with the"):
        _security_surface_rows(
            {"security_surfaces": {"items": [_surface(module="pkg.other")]}}, index
        )
    with pytest.raises(ProducerSnapshotUnavailable, match="is not"):
        _security_surface_rows(
            {
                "security_surfaces": {
                    "items": [_surface(location_scope="module", qualname="pkg.a:fn")]
                }
            },
            index,
        )
    with pytest.raises(
        ProducerSnapshotUnavailable, match="disagrees with its own file"
    ):
        _security_surface_rows(
            {"security_surfaces": {"items": [_surface(qualname="loose.py:fn")]}}, index
        )


def test_a_clone_group_with_two_items_under_one_identity_is_refused(
    index: _RegistryIndex,
) -> None:
    """A ``frozenset`` would absorb the arity defect silently, so the
    collapse is measured before the set is built."""
    item = {"qualname": "pkg.a:fn", "start_line": 1, "end_line": 4}
    analysis = cast(
        "AnalysisResult",
        SimpleNamespace(
            func_groups={"g": [item, dict(item)]},
            block_groups_report={},
            segment_groups={},
        ),
    )
    with pytest.raises(ProducerSnapshotUnavailable, match="one identity"):
        _clone_group_rows(analysis, index)

    pair = cast(
        "AnalysisResult",
        SimpleNamespace(
            func_groups={
                "g": [item, {"qualname": "loose.py:fn", "start_line": 1, "end_line": 4}]
            },
            block_groups_report={},
            segment_groups={},
        ),
    )
    rows = _clone_group_rows(pair, index)
    assert len(rows) == 1
    assert next(iter(rows)).group_key == "g"


def test_a_semantic_lane_run_is_refused_rather_than_published_as_zeros(
    corpus: Path,
    run_store_cli: RunStoreCorpusRunner,
) -> None:
    """The refusal has an input that reaches it, and the run still succeeds.

    The six semantic-authority families reach the producer edge as the same
    glued identity strings the document carries, and their canonical
    grammar lives only inside the legacy ingest oracle.  Publishing them as
    empty would be the fake zero the population law forbids; failing the
    analysis would let a rollout flag break a run.  The third answer is a
    typed refusal that stores nothing.
    """
    (corpus / "pyproject.toml").write_text(
        "[tool.codeclone]\nsemantic_authority = true\n", "utf-8"
    )
    store, document = _run_and_read(run_store_cli, corpus)
    # The instrument is proven on before the absence is read.
    source_facts = cast("dict[str, object]", document["source_facts"])
    assert source_facts["semantic"] is not None
    assert not store.exists()


def test_a_lost_head_race_is_a_conflict_and_never_a_completeness_claim(
    corpus: Path,
    run_store_cli: RunStoreCorpusRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``head_conflict`` is the store's own CAS outcome, not an error: the
    run stays stored and only the head race is lost.  A stale generation is
    injected because two racing publishers cannot be scheduled from one
    test, and the store's CAS is what decides either way."""
    store = corpus / "runs.sqlite3"

    def _stale_head(_self: RunStore, *, namespace: str, target: str) -> HeadState:
        return HeadState(
            namespace=namespace, target=target, generation=7, run_id="stale"
        )

    monkeypatch.setattr(RunStore, "head", _stale_head)
    run_store_cli(corpus, *_FULL_METRICS_ARGS, store=store)
    monkeypatch.undo()
    assert store.exists()
    with RunStore(store) as run_store:
        stored = [
            str(row[0])
            for row in run_store._connection.execute(
                "SELECT run_id FROM runs WHERE published = 1"
            )
        ]
        heads = list(run_store._connection.execute("SELECT target FROM heads"))
    assert len(stored) == 1, "the run must be stored even when it loses the head"
    assert heads == [], "a stale publisher must not create a head"
