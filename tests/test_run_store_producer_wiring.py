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
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from codeclone.canonical.errors import SemanticGrammarError
from codeclone.canonical.identity import (
    PRODUCER_EXECUTION_STATES,
    EffectRoot,
    FileId,
    KnownModule,
    ModuleId,
    ModuleSymbol,
    OpaqueDottedHead,
    OpaqueEntity,
    OperationRoot,
    ProducerRoot,
    SymbolId,
)
from codeclone.canonical.ingest import canonical_model_from_legacy_document
from codeclone.canonical.model import (
    AnalysisFacts,
    AnalysisPopulation,
    CanonicalModel,
)
from codeclone.canonical.semantic_grammar import (
    IdentityIndex,
    parse_dead_code_entity,
    parse_endpoint,
    parse_lane_symbol,
    parse_symbol,
    surface_head,
)
from codeclone.canonical.store import HeadState, RunStore
from codeclone.contracts import DEFAULT_CACHE_PATH
from codeclone.core._types import AnalysisResult
from codeclone.core.canonical_snapshot import (
    ENV_RUN_STORE_ENABLED,
    ENV_RUN_STORE_FORCE,
    ENV_RUN_STORE_PATH,
    RUN_SNAPSHOT_NAMESPACE,
    ProducerSnapshotUnavailable,
    _clone_group_rows,
    _dependency_cycle_rows,
    _identity_index,
    _security_surface_rows,
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
        analysis_scope_digest="s",
    )
    assert withheld.outcome == RUN_SNAPSHOT_PUBLICATION_HEAD_WITHHELD
    published = RunSnapshotPublication(
        outcome=RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
        admissible=True,
        target=CANONICAL_HEAD_TARGET,
        run_id="r",
        generation=1,
        analysis_scope_digest="s",
    )
    assert published.admissible
    with pytest.raises(ValueError, match="inadmissible-profile outcome"):
        RunSnapshotPublication(
            outcome=RUN_SNAPSHOT_PUBLICATION_HEAD_WITHHELD,
            admissible=True,
            target=CANONICAL_HEAD_TARGET,
            run_id="r",
            generation=1,
            analysis_scope_digest="s",
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


def _semantic_run(
    run_store_cli: RunStoreCorpusRunner, corpus: Path
) -> tuple[Path, dict[str, object], CanonicalModel]:
    """One enabled run with the authority lane ON, and what it published.

    Both readings of this corpus — the equivalence comparison and the
    totality pin — need the same three things, and spelling the setup twice
    is how a corpus quietly forks between two tests that claim to describe
    one run.
    """

    (corpus / "pyproject.toml").write_text(
        "[tool.codeclone]\nsemantic_authority = true\n", "utf-8"
    )
    store, document = _run_and_read(run_store_cli, corpus)
    # The instrument is proven on before anything is counted: this corpus
    # has to have actually executed the lane.
    source_facts = cast("dict[str, object]", document["source_facts"])
    assert source_facts["semantic"] is not None
    head = _head(store, CANONICAL_HEAD_TARGET)
    assert head is not None
    with RunStore(store) as run_store:
        published = run_store.read_run(head.run_id)
    return store, document, published


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
    # The wider net stays -- a run store appearing under any other name is
    # still caught -- but it now excludes the disposable analysis cache.
    # That cache became a SQLite store on 2026-09-01, and a cache write is
    # not a publish: it takes no part in publish correctness, never enters
    # run_id, and deleting it changes no result. Letting it fail this pin
    # would be the exact confusion the boundary forbids, asserted from the
    # test side.
    assert not [
        found
        for found in corpus.glob("**/*.sqlite3")
        if found != corpus / DEFAULT_CACHE_PATH
    ]


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

    The corpus runs with the semantic-authority lane ON, and that is what
    the grammar transplant bought.  Before it the two paths' domains were
    DISJOINT — the oracle refuses a document whose ``source_facts.semantic``
    is null, and the producer refused a run whose lane had executed — so
    they could only ever be compared over an injected empty authority tier.
    Now they meet on a run where all six authority families carry rows.

    ``analysis_population`` is deliberately excluded and asserted
    separately: the producer edge can and must pronounce states the
    rendered document cannot witness, so equality there would mean the
    producer had forgotten what it knows.
    """
    _store, document, native = _semantic_run(run_store_cli, corpus)
    oracle = canonical_model_from_legacy_document(document)

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
        "contracts",
        "coupling_cohesion_observations",
        "dead_code_observations",
        "dependency_cycles",
        "dependency_occurrences",
        "dependency_relations",
        "graph_nodes",
        "risk_observations",
        "security_surfaces",
        "semantic_edges",
        "sink_roles",
        "unit_spans",
    ):
        rows = getattr(produced, family)
        assert rows, f"{family} carries no rows; the comparison would be hollow"
        assert rows == getattr(expected, family), family
    # Canonical model revision 2: the two families the sealed document does
    # not carry (the surface serves them out of the parent's memory).  The
    # oracle has no source for them and answers EMPTY by construction, so
    # equality would be hollow; what is asserted is the asymmetry itself on
    # a non-empty native population — a document that starts carrying them
    # turns this red, and the oracle is then taught deliberately.
    for family in ("import_observations", "relationship_observations"):
        assert getattr(produced, family), f"{family} carries no rows"
        assert getattr(expected, family) == frozenset(), family

    population = produced.analysis_population
    assert population is not None
    # Kept as data rather than four copy-pasted assertions: the producer
    # edge must pronounce THREE different states on one run, and the point
    # is the set of them, not any single one.
    states = dict(population.producer_states)
    assert {
        family: states[family]
        for family in ("complexity", "coverage_join", "near_miss", "semantic_authority")
    } == {
        "complexity": "complete",
        "coverage_join": "not_executed",
        "near_miss": "disabled",
        "semantic_authority": "complete",
    }


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
    # The serving door (2026-09-07) is the ONE read-side resolver, and it
    # resolves the same flag through the same owner on purpose: a store the
    # rollout does not name is never read, so turning the flag off after an
    # execution published sends the surface back to memory rather than to a
    # file the rollout no longer owns.  A third resolver is still drift.
    assert resolvers == [
        "codeclone/api/run_store_serving.py",
        "codeclone/core/canonical_snapshot.py",
        "codeclone/core/reporting.py",
    ]
    reporting = _tree("codeclone/core/reporting.py")
    assert _calls(reporting, "publish_run_snapshot") == 1
    assert _calls(reporting, "resolve_run_store_config") == 1
    assert _calls(reporting, "_publish_canonical_snapshot") == 1


def _calls_to(tree: ast.AST, callee: str) -> Iterator[ast.Call]:
    """Every direct call to ``callee`` in one tree."""

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == callee
        ):
            yield node


def _bound_names(tree: ast.AST, callee: str) -> set[str]:
    """Names an assignment binds from ``callee`` -- including tuple targets."""

    calls = set(map(id, _calls_to(tree, callee)))
    return {
        element.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and id(node.value) in calls
        for target in node.targets
        for element in ast.walk(target)
        if isinstance(element, ast.Name)
    }


def _keyword_argument(tree: ast.AST, callee: str, keyword: str) -> set[str]:
    """The names passed as ``keyword=`` to ``callee``."""

    return {
        entry.value.id
        for node in _calls_to(tree, callee)
        for entry in node.keywords
        if entry.arg == keyword and isinstance(entry.value, ast.Name)
    }


def test_the_publication_outcome_is_bound_and_carried_out_of_the_report() -> None:
    """The publication witness may not be computed and dropped.

    Every path through ``publish_run_snapshot`` returns a typed outcome --
    ``disabled``, ``refused``, ``failed`` and the three stored ones -- and
    the whole reason the flag-off path returns a witness at all is that a
    skip nobody can observe is indistinguishable from a backend that was
    never wired.  A call site that discards that witness puts the silence
    back one level out, where it looks like wiring.

    Pinned as an EDGE and not as a spelling: the assignment may be renamed,
    the tuple may grow, the call may move within ``report`` -- what has to
    hold is that the value the publisher produced reaches the bridge, and
    that the bridge's own answer reaches the artifacts the caller receives.
    Reverting either binding to a bare call turns this red.
    """

    reporting = _tree("codeclone/core/reporting.py")

    published = _bound_names(reporting, "_publish_canonical_snapshot")
    assert published, "the publication result is computed and dropped"
    assert published & _keyword_argument(
        reporting, "bridge_run_snapshot", "publication"
    )

    bridged = _bound_names(reporting, "bridge_run_snapshot")
    assert bridged, "the bridge result is computed and dropped"
    assert bridged & _keyword_argument(
        reporting, "ReportArtifacts", "run_snapshot_link"
    )


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
def index(tmp_path: Path) -> IdentityIndex:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/__init__.py").write_text("", "utf-8")
    (tmp_path / "pkg/a.py").write_text('"""A."""\n', "utf-8")
    (tmp_path / "loose.py").write_text('"""Loose."""\n', "utf-8")
    registry = build_module_registry(root=tmp_path)
    return _identity_index(registry, frozenset({"pkg/a.py", "loose.py"}))


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
    with pytest.raises(SemanticGrammarError, match="claims two files"):
        _identity_index(doubled, frozenset({"pkg/a.py", "pkg/twin.py"}))

    assert entry.identity.python_module is not None
    conflicting = replace(
        entry,
        identity=ResolvedSourceIdentity(
            file=entry.identity.file,
            python_module=replace(entry.identity.python_module, module="pkg.other"),
        ),
    )
    with pytest.raises(SemanticGrammarError, match="claims two modules"):
        _identity_index(
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
    index = _identity_index(doctored, frozenset({"pkg/a.py"}))
    assert "pkg.a" not in index.module_to_path
    assert parse_symbol(index, "pkg/a.py:fn", "s") == SymbolId(FileId("pkg/a.py"), "fn")


def test_the_symbol_resolver_reaches_both_heads_and_both_refusals(
    index: IdentityIndex,
) -> None:
    assert parse_symbol(index, "pkg.a:fn", "s") == SymbolId(FileId("pkg/a.py"), "fn")
    assert parse_symbol(index, "loose.py:fn", "s") == SymbolId(FileId("loose.py"), "fn")
    with pytest.raises(SemanticGrammarError, match="ModuleKey-headed"):
        parse_symbol(index, "bare_name", "s")
    with pytest.raises(SemanticGrammarError, match="refusing to guess"):
        parse_symbol(index, "nowhere:fn", "s")


def test_the_endpoint_resolver_reaches_both_domains_and_its_refusal(
    index: IdentityIndex,
) -> None:
    assert parse_endpoint(index, "pkg.a", "e") == ModuleId("pkg.a")
    assert parse_endpoint(index, "loose.py", "e") == FileId("loose.py")
    with pytest.raises(SemanticGrammarError, match="neither a registry module"):
        parse_endpoint(index, "nowhere", "e")


def test_the_producer_projection_carries_the_registrys_file_less_prefixes(
    tmp_path: Path,
) -> None:
    """The producer path resolves a namespace-package endpoint too.

    Measured 2026-09-07 with the run store enabled, on a tree whose only
    internal dependency target is an implicit namespace package: the
    producer-native publication came back ``outcome=failed`` carrying the
    SAME ``SemanticGrammarError`` the ingest oracle raised, because THIS
    projection handed the grammar file-bearing pairs alone while
    ``metrics.dependencies._is_internal_target`` had already called the
    prefix node internal and emitted the edge to it.

    The projection is extraction, the grammar decides -- but what the two
    readings EXTRACT must not differ, and only a pin on this side can say
    so.  Measured on the whole suite: with the prefix argument removed from
    this projection alone, every other test stayed green.
    """
    (tmp_path / "nsp").mkdir()
    # No __init__.py. That absence is the whole case: it is what makes the
    # registry publish ``nsp`` as a prefix node instead of an entry.
    (tmp_path / "nsp" / "leaf.py").write_text('"""Leaf."""\n', "utf-8")
    (tmp_path / "user.py").write_text("from nsp import leaf\n", "utf-8")
    registry = build_module_registry(root=tmp_path)

    # Probe validity, before anything is read off the index: the registry
    # really does publish the prefix node, and really does not carry it as a
    # file-bearing entry, so the assertions below are read on a case that
    # exists rather than on an empty one.
    assert [
        (prefix.module, prefix.node_kind) for prefix in registry.package_prefixes
    ] == [("nsp", "namespace_package")]

    index = _identity_index(registry, frozenset({"nsp/leaf.py", "user.py"}))
    assert "nsp" not in index.module_to_path
    assert index.prefix_modules == frozenset({"nsp"})
    assert parse_endpoint(index, "nsp", "dependencies.target") == ModuleId("nsp")


def test_the_lane_identity_law_refuses_both_ways(index: IdentityIndex) -> None:
    assert parse_lane_symbol(index, "pkg/a.py", "fn", "risk") == SymbolId(
        FileId("pkg/a.py"), "fn"
    )
    with pytest.raises(SemanticGrammarError, match="not an analyzed path"):
        parse_lane_symbol(index, "pkg/missing.py", "fn", "risk")
    with pytest.raises(SemanticGrammarError, match="glued identity"):
        parse_lane_symbol(index, "pkg/a.py", "mod:fn", "risk")


def test_the_dead_code_entity_reaches_all_three_variants_and_both_refusals(
    index: IdentityIndex,
) -> None:
    """The tagged reference keeps the head the producer made: a registry
    module stays MODULE-headed, an analyzed path stays FILE-headed, and
    anything else rides the opaque variant verbatim."""
    assert parse_dead_code_entity(index, "pkg.a:fn") == ModuleSymbol(
        ModuleId("pkg.a"), "fn"
    )
    assert parse_dead_code_entity(index, "loose.py:fn") == SymbolId(
        FileId("loose.py"), "fn"
    )
    assert parse_dead_code_entity(index, "nowhere:fn") == OpaqueEntity("nowhere", "fn")
    with pytest.raises(SemanticGrammarError, match="head:local"):
        parse_dead_code_entity(index, "nocolon")
    with pytest.raises(SemanticGrammarError, match="second ModuleKey colon"):
        parse_dead_code_entity(index, "pkg.a:mod:fn")


def test_the_surface_head_reaches_its_two_answers_and_its_refusal(
    index: IdentityIndex,
) -> None:
    assert surface_head(index, "pkg/a.py", "s") == "pkg.a"
    with pytest.raises(SemanticGrammarError, match="not an analyzed path"):
        surface_head(index, "pkg/missing.py", "s")


def test_a_cycle_row_is_refused_when_it_repeats_or_leaves_the_module_domain(
    index: IdentityIndex,
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
    index: IdentityIndex,
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
    index: IdentityIndex,
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


def _authority_roots(facts: AnalysisFacts) -> frozenset[EffectRoot]:
    """Every effect root the published authority tier actually carries.

    Both houses are read, and each keeps its OWN ``effect_signature``:
    ``ContractRow`` carries ``FunctionContractIR.effect_signature`` while
    ``GraphNodeRow`` carries the authority graph's own.  They are two
    different signatures — substituting one for the other diverges on a
    real corpus — so nothing here folds them together.
    """

    contracts = frozenset(root for row in facts.contracts for root in row.root_set)
    nodes = frozenset(root for node in facts.graph_nodes for root in node.root_set)
    return contracts | nodes


def test_a_semantic_lane_run_publishes_its_authority_families(
    corpus: Path,
    run_store_cli: RunStoreCorpusRunner,
) -> None:
    """Totality after the 2026-08-31 grammar transplant.

    Before it, a run whose semantic-authority lane executed was refused
    outright: its six families reach the producer edge as the same glued
    identity strings the report carries, and the grammar that resolves them
    lived only inside the legacy ingest oracle.  With one normative owner
    the producer path resolves them itself, so a supported form no longer
    gets a typed refusal — it gets published, with rows.
    """
    store, _document, model = _semantic_run(run_store_cli, corpus)
    assert store.exists()
    facts = model.facts.analysis
    assert facts.contracts, "the authority tier published no contracts"
    assert facts.graph_nodes
    assert facts.sink_roles
    population = facts.analysis_population
    assert population is not None
    assert dict(population.producer_states)["semantic_authority"] == "complete"


def test_the_published_authority_tier_carries_every_root_family(
    corpus: Path,
    run_store_cli: RunStoreCorpusRunner,
) -> None:
    """A VALUE pin on this reading, not a cross-reading equality.

    Measured while building this wave: the projection-equivalence assertion
    is blind to a mutation inside the shared grammar owner BY CONSTRUCTION,
    because both readings move together.  Only a test that reads what the
    rule produced can turn red when the rule breaks, so each reading keeps
    one.
    """
    _store, _document, model = _semantic_run(run_store_cli, corpus)
    roots = _authority_roots(model.facts.analysis)
    assert any(isinstance(root, ProducerRoot) for root in roots), (
        "no producer-family root reached the model; the root-family rule "
        "would be unpinned on this reading"
    )
    operations = [root for root in roots if isinstance(root, OperationRoot)]
    assert operations
    assert any(isinstance(root.target.head, OpaqueDottedHead) for root in operations)
    assert any(isinstance(root.target.head, KnownModule) for root in operations)


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


# -- canonical epoch E1: the eleven published-population families ------------

#: The E1 corpus: one tree that populates EVERY E1 family at once, so the
#: producer-native builder and the ingest oracle meet on a non-empty row set
#: per family — a family compared at zero rows proves nothing about its
#: mapping.  What each file is for: ``pkg/hub.py`` carries a class coupled to
#: eleven classes (coupling hotspot), a class whose four methods share no
#: attribute (cohesion hotspot), a twenty-two-branch function (complexity
#: hotspot, and the coverage hotspot once the report below covers half of
#: it), an if/elif with two identical loop-and-return bodies (a structural
#: duplicated-branches group), a function with statements after its return
#: (an unreachable region), a private function nobody calls and one only the
#: test suite calls (both dead-symbol reasons); ``tests/fixtures/golden_*``
#: carry two identical functions under the declared golden-fixture pattern
#: (a SUPPRESSED clone group, never an emitted one); every module is an
#: overloaded-modules row; the dead-code lane's counters are the summary.
_E1_CORPUS: dict[str, str] = {
    "pyproject.toml": (
        "[tool.codeclone]\nsemantic_authority = true\n"
        'golden_fixture_paths = ["tests/fixtures/golden_*"]\n'
    ),
    "pkg/__init__.py": "",
    "pkg/hub.py": '''"""Hub."""

from pkg.parts import A, B, C, D, E, F, G, H, I, J, K


class Hub:
    """Hub."""

    def __init__(self) -> None:
        self.a = A()
        self.b = B()
        self.c = C()
        self.d = D()
        self.e = E()
        self.f = F()
        self.g = G()
        self.h = H()
        self.i = I()
        self.j = J()
        self.k = K()

    def total(self) -> int:
        """Total."""
        return (
            self.a.v() + self.b.v() + self.c.v() + self.d.v() + self.e.v()
            + self.f.v() + self.g.v() + self.h.v() + self.i.v() + self.j.v()
            + self.k.v()
        )


class Scattered:
    """Four methods, four attributes, no sharing: lcom4 of four."""

    def one(self) -> int:
        """One."""
        self.p = 1
        return self.p

    def two(self) -> int:
        """Two."""
        self.q = 2
        return self.q

    def three(self) -> int:
        """Three."""
        self.r = 3
        return self.r

    def four(self) -> int:
        """Four."""
        self.s = 4
        return self.s


def maze(value: int) -> int:
    """Twenty-two branches."""
    total = 0
    if value > 1:
        total += 1
    if value > 2:
        total += 1
    if value > 3:
        total += 1
    if value > 4:
        total += 1
    if value > 5:
        total += 1
    if value > 6:
        total += 1
    if value > 7:
        total += 1
    if value > 8:
        total += 1
    if value > 9:
        total += 1
    if value > 10:
        total += 1
    if value > 11:
        total += 1
    if value > 12:
        total += 1
    if value > 13:
        total += 1
    if value > 14:
        total += 1
    if value > 15:
        total += 1
    if value > 16:
        total += 1
    if value > 17:
        total += 1
    if value > 18:
        total += 1
    if value > 19:
        total += 1
    if value > 20:
        total += 1
    if value > 21:
        total += 1
    return total


def route(kind: str, payload: list[int]) -> str:
    """Duplicated branches."""
    if kind == "a":
        for item in payload:
            print(item)
        return "a"
    elif kind == "b":
        for item in payload:
            print(item)
        return "b"
    return "c"


def stop(value: int) -> int:
    """Unreachable tail."""
    return value
    value += 1
    return value


def _orphan() -> int:
    """Nobody calls this."""
    return 1


def _tested_helper() -> int:
    """Referenced from the test suite alone."""
    return 2
''',
    "pkg/parts.py": "".join(
        f"""class {name}:
    def v(self) -> int:
        return {index + 1}


"""
        for index, name in enumerate("ABCDEFGHIJK")
    ),
    "tests/__init__.py": "",
    "tests/test_hub.py": '''"""Tests."""

from pkg.hub import Hub, _tested_helper


def test_hub() -> None:
    assert Hub().total() == 66


def test_only() -> None:
    assert _tested_helper() == 2
''',
    "tests/fixtures/golden_a/dup.py": '''"""Golden A."""


def sample(values: list[int]) -> int:
    total = 0
    for value in values:
        total += value * 2
    return total
''',
    "tests/fixtures/golden_b/dup.py": '''"""Golden B."""


def sample(values: list[int]) -> int:
    total = 0
    for value in values:
        total += value * 2
    return total
''',
}


def _e1_coverage_xml(root: Path) -> str:
    return f"""<?xml version="1.0" ?>
<coverage version="7.0" line-rate="0.5">
  <sources><source>{root}</source></sources>
  <packages><package name="pkg"><classes>
    <class name="hub.py" filename="pkg/hub.py"><lines>
      <line number="9" hits="1"/><line number="10" hits="1"/>
      <line number="11" hits="0"/><line number="25" hits="1"/>
      <line number="60" hits="0"/><line number="61" hits="0"/>
      <line number="62" hits="1"/><line number="63" hits="0"/>
    </lines></class>
  </classes></package></packages>
</coverage>
"""


def _write_e1_corpus(root: Path) -> Path:
    for relative, source in _E1_CORPUS.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, "utf-8")
    coverage = root / "coverage.xml"
    coverage.write_text(_e1_coverage_xml(root), "utf-8")
    return coverage


_E1_ROW_FAMILIES = (
    "suppressed_clone_groups",
    "structural_groups",
    "dead_symbol_groups",
    "unreachable_statement_groups",
    "complexity_hotspots",
    "coupling_hotspots",
    "cohesion_hotspots",
    "overloaded_modules",
    "coverage_units",
)


@pytest.fixture(scope="module")
def e1_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, object], CanonicalModel]:
    """One enabled full-metrics run over the E1 corpus, with a coverage
    report, and what it published — shared by the E1 pins below so the
    corpus cannot fork between them."""
    from tests.conftest import _run_codeclone_cli

    root = tmp_path_factory.mktemp("e1_corpus").resolve()
    coverage = _write_e1_corpus(root)
    store = root / "runs.sqlite3"
    report_path = root / "report.json"
    _run_codeclone_cli(
        [
            str(root),
            "--no-progress",
            "--baseline",
            str(root / "corpus.baseline.json"),
            *_FULL_METRICS_ARGS,
            "--coverage",
            str(coverage),
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
    head = _head(store, CANONICAL_HEAD_TARGET)
    assert head is not None
    with RunStore(store) as run_store:
        return document, run_store.read_run(head.run_id)


def test_the_e1_families_agree_between_producer_and_oracle(
    e1_run: tuple[dict[str, object], CanonicalModel],
) -> None:
    """Projection equivalence for the eleven E1 families on a corpus that
    populates every one of them (measured 2026-09-25: 1/1/2/1/1/1/1/7/26
    rows and both records), family by family, non-empty first.

    The two readings come from the SAME execution: the CLI rendered the
    document the oracle reads and published the run the store holds.  A
    red here is a regression — some E1 fact stopped being stated, or
    stopped agreeing — never a gap to restore.
    """
    document, native = e1_run
    oracle = canonical_model_from_legacy_document(document)
    produced = native.facts.analysis
    expected = oracle.facts.analysis
    for family in _E1_ROW_FAMILIES:
        rows = getattr(produced, family)
        assert rows, f"{family} carries no rows; the comparison would be hollow"
        assert rows == getattr(expected, family), family
    assert produced.coverage_join is not None
    assert produced.coverage_join == expected.coverage_join
    assert produced.coverage_join.status == "ok"
    assert produced.dead_code_summary is not None
    assert produced.dead_code_summary == expected.dead_code_summary
    # The distinguishing shapes, named: both dead-symbol reasons, a
    # test-only evidence source, the three coverage statuses.
    assert {row.reason for row in produced.dead_symbol_groups} == {
        "unreferenced",
        "test_only_reference",
    }
    assert any(row.test_reference_sources for row in produced.dead_symbol_groups)
    assert {row.coverage_status for row in produced.coverage_units} == {
        "measured",
        "missing_from_report",
        "no_executable_lines",
    }
    # A1: the suppressed group is NOT among the emitted groups.
    suppressed_keys = {row.group_key for row in produced.suppressed_clone_groups}
    assert suppressed_keys
    assert suppressed_keys.isdisjoint(row.group_key for row in produced.clone_groups)


def test_the_e1_families_agree_on_the_wiring_corpus(
    corpus: Path, run_store_cli: RunStoreCorpusRunner
) -> None:
    """The same equivalence on the wiring corpus, which populates only two
    of the eleven (every module is an overloaded row; the dead-code lane
    always publishes its counters) — stated as such, never as a hollow
    equality of empties: the empty nine are asserted empty on BOTH sides
    together with the reason the corpus leaves them so."""
    _store, document, native = _semantic_run(run_store_cli, corpus)
    oracle = canonical_model_from_legacy_document(document)
    produced = native.facts.analysis
    expected = oracle.facts.analysis
    assert produced.overloaded_modules
    assert {row.file.path for row in produced.overloaded_modules} == {
        path for path in _CORPUS if path.endswith(".py")
    }
    assert produced.dead_code_summary is not None
    for family in _E1_ROW_FAMILIES:
        assert getattr(produced, family) == getattr(expected, family), family
    assert produced.coverage_join is None
    assert expected.coverage_join is None
    assert produced.dead_code_summary == expected.dead_code_summary


def test_every_e1_closing_line_family_answers_alone_on_the_e1_corpus(
    e1_run: tuple[dict[str, object], CanonicalModel],
) -> None:
    """The reachability witness the closing-line ratchet defers to here.

    ``test_run_store_serving_equivalence`` teaches its unit-inventory reader
    the six E1 row types that declare an ``end_line`` and states that the
    serving corpus leaves every one of them empty.  Taught is not reached:
    each of the six is driven ALONE on this corpus and required to carry
    rows, and each is required to do its own job.  Three state UNIT
    declarations and state the same closing line ``unit_spans`` states for
    them (a dead symbol, a complexity hotspot, a coverage unit); two state
    CLASS declarations, which the unit index never carries, and the two
    agree with each other about every class they share; the unreachable
    region starts inside a unit and answers no declaration at all.
    """
    from tests.test_run_store_serving_equivalence import (
        _CLOSING_LINE_FAMILIES,
        _E1_CLOSING_LINE_ROW_TYPES,
        UnitKey,
    )

    _document, native = e1_run
    analysis = native.facts.analysis
    spans = {
        (row.symbol.file.path, row.symbol.qualname, row.start_line): row.end_line
        for row in analysis.unit_spans
    }
    stated_by: dict[str, dict[UnitKey, int]] = {}
    for row_type, read in _CLOSING_LINE_FAMILIES:
        if row_type.__name__ not in _E1_CLOSING_LINE_ROW_TYPES:
            continue
        stated = dict(read(analysis))
        assert stated, f"{row_type.__name__} carries no row on the E1 corpus"
        stated_by[row_type.__name__] = stated
    assert set(stated_by) == _E1_CLOSING_LINE_ROW_TYPES
    for name in ("DeadSymbolGroupRow", "ComplexityHotspotRow", "CoverageUnitRow"):
        assert set(stated_by[name]) <= set(spans), name
        assert all(spans[key] == end for key, end in stated_by[name].items()), name
    for name in ("CouplingHotspotRow", "CohesionHotspotRow"):
        assert not set(stated_by[name]) & set(spans), f"{name} answered a unit"
    shared = set(stated_by["CouplingHotspotRow"]) & set(stated_by["CohesionHotspotRow"])
    assert all(
        stated_by["CouplingHotspotRow"][key] == stated_by["CohesionHotspotRow"][key]
        for key in shared
    )
    assert not set(stated_by["UnreachableStatementRow"]) & set(spans), (
        "a region answered a declaration"
    )


def test_native_overloaded_scores_are_stored_at_the_published_precision(
    tmp_path: Path,
) -> None:
    """A4: the producer's raw composite score is canonical at the FOUR
    decimals the document publishes, never at the float the producer
    computed.  Driven on a synthetic payload row whose raw scores carry
    six decimals, because the E1 corpus's scores happen to be four-decimal
    clean already (measured 2026-09-25: the rounding mutant survived that
    corpus alone) — a rule pinned on a population that cannot distinguish
    it is no pin at all."""
    from codeclone.core.canonical_snapshot import _overloaded_module_rows

    root = tmp_path / "root"
    (root / "pkg").mkdir(parents=True)
    raw = {
        "module": "pkg.mod",
        "filepath": str(root / "pkg" / "mod.py"),
        "source_kind": "production",
        "loc": 10,
        "functions": 1,
        "methods": 0,
        "classes": 0,
        "callable_count": 1,
        "complexity_total": 3,
        "complexity_max": 3,
        "fan_in": 1,
        "fan_out": 2,
        "total_deps": 3,
        "import_edges": 3,
        "reimport_edges": 1,
        "reimport_ratio": 0.333333,
        "instability": 0.666667,
        "hub_balance": 0.123456,
        "size_score": 0.000049,
        "dependency_score": 0.999951,
        "shape_score": 0.5,
        "score": 0.98765432,
        "candidate_status": "ranked_only",
        "candidate_reasons": ["size_pressure", ""],
    }
    payload = {"overloaded_modules": {"items": [raw]}}
    (row,) = _overloaded_module_rows(payload, scan_root=str(root))
    assert row.file.path == "pkg/mod.py"
    assert (
        row.reimport_ratio,
        row.instability,
        row.hub_balance,
        row.size_score,
        row.dependency_score,
        row.shape_score,
        row.score,
    ) == (0.3333, 0.6667, 0.1235, 0.0, 1.0, 0.5, 0.9877)
    assert row.candidate_reasons == ("size_pressure",)
