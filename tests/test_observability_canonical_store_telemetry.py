# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical backend run-store telemetry: the operational line of a publish.

The store is instrumented before the rollout flag and before any sweep, so
the first publish, the identical republish, the neighbour run that only
shares storage, head contention and database growth all leave a measured
trace instead of being reconstructed afterwards from an experiment nobody
can repeat.

Two properties are pinned here that a green counter alone never proves:

* every ``canonical_store_*`` name in the closed vocabulary is emitted from
  the canonical store and from nowhere else — the inventory is read off the
  module, not off a list kept beside it;
* the observer is a side effect and nothing else — a publish run with the
  observer off and the same publish run with it on produce the same run
  identity, the same head, the same receipt and byte-identical store
  contents, and differ only in the telemetry that was written.
"""

from __future__ import annotations

import ast
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import orjson
import pytest

from codeclone.canonical import (
    CanonicalModel,
    PublishReceipt,
    RunStore,
    StoreFenceError,
)
from codeclone.canonical import store as store_module
from codeclone.models import ObservabilityConfig
from codeclone.observability import bootstrap, operation, shutdown
from codeclone.observability.vocabulary import (
    COUNTER_KEYS,
    PARKED_COUNTER_KEYS,
    PARKED_SPAN_NAMES,
    SPAN_NAMES,
)
from tests.test_canonical_roundtrip import fixture_model

_ROOT = Path(__file__).resolve().parents[1]
_STORE_SOURCE = _ROOT / "codeclone" / "canonical" / "store.py"
_NS = "lineage-observed"
_TARGET = "worktree-observed"
_PUBLISH_SPAN = "canonical.store.publish"

#: The P0 operational set, spelled once. The store is the only module that
#: may emit these, and it must emit all of them — both directions are
#: checked against the module's own syntax tree below.
_PUBLISH_COUNTERS = frozenset(
    {
        "canonical_store_publish_attempts",
        "canonical_store_publish_successes",
        "canonical_store_publish_failures",
        "canonical_store_ingest_duration",
        "canonical_store_write_duration",
        "canonical_store_new_objects",
        "canonical_store_reused_objects",
        "canonical_store_membership_rows",
        "canonical_store_db_bytes",
        "canonical_store_head_advance_successes",
        "canonical_store_head_advance_conflicts",
    }
)

# A phase probe has to be longer than the phase it is not in could ever be,
# and the assertions leave a wide corridor on both sides: the injected phase
# must have absorbed most of the delay, the other phase must be nowhere near
# it. The store's own work on the fixture is sub-millisecond, so the corridor
# is three orders of magnitude wide.
_PROBE_SECONDS = 0.25
_PROBE_FLOOR_US = 200_000
_PROBE_CEILING_US = 200_000


@contextmanager
def _observed(root: Path) -> Iterator[None]:
    """Freeze an enabled observer bound to ``root`` for the block.

    The config object goes straight in rather than through the environment:
    the subject here is ring r2, so the config dataclass is legitimately in
    reach, and one frozen decision is one fewer thing that could differ
    between the two halves of the witness below.
    """
    bootstrap(ObservabilityConfig(enabled=True), root=root)
    try:
        yield
    finally:
        shutdown()


def _publish(
    store: RunStore, model: CanonicalModel, *, expected_generation: int = 0
) -> PublishReceipt:
    return store.write_full_run(
        model,
        namespace=_NS,
        target=_TARGET,
        expected_generation=expected_generation,
    )


def _neighbour(model: CanonicalModel) -> CanonicalModel:
    """A run that shares every object with ``model`` and adds exactly one."""
    coupled = set(model.coupled_sets)
    coupled.add(frozenset({"OnlyInNeighbour"}))
    return replace(model, coupled_sets=frozenset(coupled))


def _span_rows(root: Path, name: str = _PUBLISH_SPAN) -> list[dict[str, int]]:
    """Counters of every span with this name, in the order they were written."""
    store = root / ".codeclone" / "db" / "platform_observability.sqlite3"
    connection = sqlite3.connect(store)
    try:
        rows = connection.execute(
            "SELECT counters_json FROM platform_spans WHERE name=? ORDER BY rowid",
            (name,),
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            str(key): int(value)
            for key, value in (orjson.loads(raw) if raw else {}).items()
        }
        for (raw,) in rows
    ]


def _publish_observed(
    root: Path,
    *models: CanonicalModel,
    expected_generations: tuple[int, ...] | None = None,
) -> tuple[list[PublishReceipt], list[dict[str, int]]]:
    """Publish each model under one operation, then read back its spans."""
    generations = expected_generations or tuple(range(len(models)))
    receipts: list[PublishReceipt] = []
    with (
        _observed(root),
        operation(name="mcp.analyze_repository", surface="mcp"),
        RunStore(root / "runs.sqlite") as store,
    ):
        for model, generation in zip(models, generations, strict=True):
            receipts.append(_publish(store, model, expected_generation=generation))
    return receipts, _span_rows(root)


# -- the inventory: every declared name, emitted from exactly this module ---

_COUNTER_EMITTERS = frozenset({"add_counter", "record_counter", "set_counter"})


def _called_name(call: ast.Call) -> str | None:
    function = call.func
    if isinstance(function, ast.Attribute):
        return function.attr
    if isinstance(function, ast.Name):
        return function.id
    return None


def _string_literal(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _calls(tree: ast.AST, names: frozenset[str]) -> Iterator[ast.Call]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _called_name(node) in names:
            yield node


def _emitted_counter_keys(tree: ast.AST) -> set[str]:
    """Counter keys this module names in a literal emit call."""
    literals = (
        _string_literal(call.args[0])
        for call in _calls(tree, _COUNTER_EMITTERS)
        if call.args
    )
    return {literal for literal in literals if literal is not None}


def _emitted_span_names(tree: ast.AST) -> set[str]:
    """Span names this module opens with a literal ``name=``."""
    literals = (
        _string_literal(keyword.value)
        for call in _calls(tree, frozenset({"span"}))
        for keyword in call.keywords
        if keyword.arg == "name"
    )
    return {literal for literal in literals if literal is not None}


def _module_tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text("utf-8"), filename=str(path))


def test_the_canonical_store_names_are_declared_wired_and_never_parked() -> None:
    """The names, the emit sites and the parking list, compared mechanically.

    A declared name with no emit site is a claim the build cannot honour,
    and a name emitted from somewhere other than the store would make
    ``canonical_store_*`` a second instrumentation surface rather than one
    family inside the single observation point. Both are read off syntax
    trees here, never off a hand-kept list.
    """
    tree = _module_tree(_STORE_SOURCE)

    assert _emitted_span_names(tree) == {_PUBLISH_SPAN}
    assert _emitted_counter_keys(tree) == _PUBLISH_COUNTERS
    assert _PUBLISH_SPAN in SPAN_NAMES
    assert _PUBLISH_COUNTERS <= COUNTER_KEYS
    # The declared family is exactly the emitted family: a name minted for a
    # sweep that does not exist yet would show up here as an unwired claim.
    assert {key for key in COUNTER_KEYS if key.startswith("canonical_store")} == (
        _PUBLISH_COUNTERS
    )
    assert _PUBLISH_SPAN not in PARKED_SPAN_NAMES
    assert not (_PUBLISH_COUNTERS & set(PARKED_COUNTER_KEYS))


def _names_the_family(path: Path) -> bool:
    return any(
        (_string_literal(node) or "").startswith("canonical_store_")
        for node in ast.walk(_module_tree(path))
    )


def test_no_other_module_emits_the_canonical_store_family() -> None:
    """One family, one owner: the store, and not a second pipeline."""
    owners = sorted(
        path.relative_to(_ROOT).as_posix()
        for path in (_ROOT / "codeclone").rglob("*.py")
        if _names_the_family(path)
    )
    assert owners == [
        "codeclone/canonical/store.py",
        "codeclone/observability/vocabulary.py",
    ]


# -- the publish lifecycle --------------------------------------------------


def test_a_first_publish_is_an_attempt_a_success_and_a_head_advance(
    tmp_path: Path,
) -> None:
    receipts, rows = _publish_observed(tmp_path, fixture_model())

    assert receipts[0].head_advanced is True
    assert len(rows) == 1
    counters = rows[0]
    assert counters["canonical_store_publish_attempts"] == 1
    assert counters["canonical_store_publish_successes"] == 1
    assert "canonical_store_publish_failures" not in counters
    assert counters["canonical_store_head_advance_successes"] == 1
    assert "canonical_store_head_advance_conflicts" not in counters


def test_a_first_publish_counts_every_object_new_and_pays_its_membership_rows(
    tmp_path: Path,
) -> None:
    receipts, rows = _publish_observed(tmp_path, fixture_model())

    objects = receipts[0].object_count
    assert objects > 0
    assert rows[0]["canonical_store_new_objects"] == objects
    assert rows[0]["canonical_store_reused_objects"] == 0
    assert rows[0]["canonical_store_membership_rows"] == objects


def test_an_identical_republish_reuses_every_object_and_writes_no_membership_row(
    tmp_path: Path,
) -> None:
    """The measured shape of a repeat: content sharing saves the objects, and
    the run row is already there, so the republish costs no new row at all.
    """
    model = fixture_model()
    receipts, rows = _publish_observed(
        tmp_path, model, model, expected_generations=(0, 1)
    )

    assert receipts[0].run_id == receipts[1].run_id
    objects = receipts[0].object_count
    repeat = rows[1]
    assert repeat["canonical_store_new_objects"] == 0
    assert repeat["canonical_store_reused_objects"] == objects
    # Zero, not absent: the republish reached the site and wrote no row.
    assert repeat["canonical_store_membership_rows"] == 0


def test_a_neighbour_run_shares_storage_and_still_pays_its_own_membership_rows(
    tmp_path: Path,
) -> None:
    """Sharing is not free: the objects are reused, the membership snapshot
    is not, and that is the per-run cost a growth question has to see.
    """
    model = fixture_model()
    receipts, rows = _publish_observed(tmp_path, model, _neighbour(model))

    neighbour = rows[1]
    assert receipts[0].run_id != receipts[1].run_id
    assert neighbour["canonical_store_new_objects"] == receipts[1].new_objects
    assert neighbour["canonical_store_reused_objects"] == receipts[1].shared_objects
    assert 0 < neighbour["canonical_store_new_objects"] < receipts[1].object_count
    assert neighbour["canonical_store_membership_rows"] == receipts[1].object_count


def test_a_stale_generation_publish_is_a_head_conflict_and_not_a_failure(
    tmp_path: Path,
) -> None:
    """Contention has its own name. A publisher that lost the race still
    stored a valid run, so counting it a failure would hide both facts.
    """
    model = fixture_model()
    receipts, rows = _publish_observed(
        tmp_path, model, _neighbour(model), expected_generations=(0, 0)
    )

    assert receipts[1].head_advanced is False
    conflicted = rows[1]
    assert conflicted["canonical_store_publish_successes"] == 1
    assert "canonical_store_publish_failures" not in conflicted
    assert conflicted["canonical_store_head_advance_conflicts"] == 1
    assert "canonical_store_head_advance_successes" not in conflicted


def test_a_refused_publish_is_counted_a_failure_and_never_a_success(
    tmp_path: Path,
) -> None:
    """The other boundary of the same rule: a fenced-off handle is refused
    inside the transaction, and the attempt has to survive as a failure.
    """
    path = tmp_path / "runs.sqlite"
    with (
        _observed(tmp_path),
        operation(name="mcp.analyze_repository", surface="mcp"),
        RunStore(path) as held,
        RunStore(path) as migrator,
    ):
        migrator.bump_store_epoch()
        with pytest.raises(StoreFenceError):
            _publish(held, fixture_model())

    rows = _span_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["canonical_store_publish_attempts"] == 1
    assert rows[0]["canonical_store_publish_failures"] == 1
    assert "canonical_store_publish_successes" not in rows[0]
    assert "canonical_store_head_advance_successes" not in rows[0]
    assert "canonical_store_head_advance_conflicts" not in rows[0]


# -- growth and phase decomposition ----------------------------------------


def test_db_bytes_is_the_database_page_arithmetic_and_not_an_estimate(
    tmp_path: Path,
) -> None:
    """Pinned to the rule, not to a number: the counter is re-derived from
    the database itself, so a plausible-looking constant cannot pass.
    """
    _receipts, rows = _publish_observed(tmp_path, fixture_model())

    connection = sqlite3.connect(tmp_path / "runs.sqlite")
    try:
        pages = int(connection.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    finally:
        connection.close()
    assert pages > 0
    assert rows[0]["canonical_store_db_bytes"] == pages * page_size


def test_ingest_duration_measures_the_staging_phase_and_not_the_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A delay injected into staging must land on ``ingest_duration`` alone.

    ``analysis_scope_digest`` is called exactly once, in the staging phase,
    before the transaction opens.
    """
    original = store_module.analysis_scope_digest

    def _slow_scope_digest(analyzed_files: object) -> str:
        time.sleep(_PROBE_SECONDS)
        return original(analyzed_files)  # type: ignore[arg-type]

    monkeypatch.setattr(store_module, "analysis_scope_digest", _slow_scope_digest)
    _receipts, rows = _publish_observed(tmp_path, fixture_model())

    assert rows[0]["canonical_store_ingest_duration"] >= _PROBE_FLOOR_US
    assert rows[0]["canonical_store_write_duration"] < _PROBE_CEILING_US


def test_write_duration_measures_the_transaction_and_not_the_staging_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The opposite boundary: a delay inside the open transaction must land
    on ``write_duration`` alone. ``_before_publish`` is the store's own
    in-transaction seam, so the delay is provably inside it.
    """
    monkeypatch.setattr(
        RunStore,
        "_before_publish",
        lambda _self: time.sleep(_PROBE_SECONDS),
    )
    _receipts, rows = _publish_observed(tmp_path, fixture_model())

    assert rows[0]["canonical_store_write_duration"] >= _PROBE_FLOOR_US
    assert rows[0]["canonical_store_ingest_duration"] < _PROBE_CEILING_US


# -- the distinguishing witness --------------------------------------------


def _store_contents(path: Path) -> dict[str, list[tuple[object, ...]]]:
    """Every row of every table, in a deterministic order."""
    connection = sqlite3.connect(path)
    try:
        tables = [
            str(name)
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        return {
            table: sorted(connection.execute(f"SELECT * FROM {table}"))
            for table in tables
        }
    finally:
        connection.close()


def _publish_sequence(root: Path) -> tuple[list[PublishReceipt], list[bytes], object]:
    """The same publish story, run wherever the observer decision is frozen."""
    model = fixture_model()
    receipts: list[PublishReceipt] = []
    projections: list[bytes] = []
    with RunStore(root / "runs.sqlite") as store:
        receipts.append(_publish(store, model, expected_generation=0))
        receipts.append(_publish(store, model, expected_generation=1))
        receipts.append(_publish(store, _neighbour(model), expected_generation=0))
        projections = [store.project_run(receipt.run_id) for receipt in receipts]
        head = store.head(namespace=_NS, target=_TARGET)
    return receipts, projections, head


def test_the_observer_writes_telemetry_and_changes_nothing_else(
    tmp_path: Path,
) -> None:
    """The witness the instrumentation is only allowed to exist under.

    Publication must not depend on the observer in any way: same run ids,
    same head, same receipts, byte-identical store contents. That the span
    is inert while disabled is a property of the code; this is the pin, and
    the only difference it tolerates is the telemetry itself.
    """
    # Both roots are created by the stores that open inside them, so the two
    # halves of the witness differ in exactly one thing: the observer.
    dark = tmp_path / "dark"
    lit = tmp_path / "lit"

    bootstrap(ObservabilityConfig(enabled=False))
    try:
        dark_receipts, dark_projections, dark_head = _publish_sequence(dark)
    finally:
        shutdown()
    assert not (dark / ".codeclone").exists()

    with _observed(lit), operation(name="mcp.analyze_repository", surface="mcp"):
        lit_receipts, lit_projections, lit_head = _publish_sequence(lit)

    assert lit_receipts == dark_receipts
    assert lit_projections == dark_projections
    assert lit_head == dark_head
    assert _store_contents(lit / "runs.sqlite") == _store_contents(dark / "runs.sqlite")

    # ... and the one thing that is allowed to differ, did.
    lit_rows = _span_rows(lit)
    assert len(lit_rows) == 3
    assert sum(row["canonical_store_publish_attempts"] for row in lit_rows) == 3
