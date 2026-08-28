# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Root is part of the blast-radius cache identity, and it partitions the quota.

Two claims live here, and they are different claims.

*Correctness.* ``CodeCloneMCPRunStore`` already identifies a run by
``(root, run_id)`` because "run ids are content-addressed, so two worktrees at
the same commit produce the same id". The blast-radius cache used to key on the
bare ``run_id``, so one session serving two checkouts could answer one root's
question with the other root's dependency graph. Root in the key is a
correctness boundary first.

*Quota.* ``memory.max_blast_radius_cache_entries`` is a per-root configuration
key. Applied to the session-wide dictionary it would mean that, with two roots
in one session, whichever config was read last silently governs the other
root's residency. It therefore bounds the partition of one root, and the
enforcement witness these tests demand is the structural path from
``resolve_memory_config`` to that bound -- not that the value parses.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from codeclone.api.memory import blast_radius_cache_limit
from codeclone.surfaces.mcp._blast_radius import BlastRadiusResult
from codeclone.surfaces.mcp._session_blast_radius_mixin import (
    BLAST_RADIUS_CACHE_KEY_ROOT,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest, MCPRunRecord

_DOCS_CONFIG_REFERENCE = (
    Path(__file__).resolve().parents[1] / "docs" / "reference" / "configuration.md"
)
_CACHE_ENTRIES_KEY = "memory.max_blast_radius_cache_entries"


def _declared_default(unconfigured_root: Path) -> int:
    """The default the production path actually yields for a bare root.

    Re-derived through the door rather than restated from the constant, so
    the number never lives twice.
    """

    unconfigured_root.mkdir(parents=True, exist_ok=True)
    return blast_radius_cache_limit(root_path=unconfigured_root)


def _report_document(
    *,
    dependent_module: str,
    dependent_path: str,
) -> dict[str, object]:
    """A report whose only structural fact is "one module imports ``pkg.a``"."""

    return {
        "inventory": {"file_registry": {"items": ["pkg/a.py", dependent_path]}},
        "metrics": {
            "families": {
                "dependencies": {
                    "items": [
                        {
                            "source": dependent_module,
                            "target": "pkg.a",
                            "import_type": "import",
                            "line": 1,
                        }
                    ],
                    "cycles": [],
                    "longest_chains": [],
                }
            }
        },
    }


def _record(
    root: Path,
    *,
    run_id: str = "abcdef1234567890",
    dependent_module: str = "pkg.b",
    dependent_path: str = "pkg/b.py",
) -> MCPRunRecord:
    return MCPRunRecord(
        run_id=run_id,
        root=root,
        request=MCPAnalysisRequest(root=str(root), respect_pyproject=False),
        comparison_settings=(),
        report_document=_report_document(
            dependent_module=dependent_module,
            dependent_path=dependent_path,
        ),
        summary={"run_id": run_id, "health": {"score": 0, "grade": "N/A"}},
        changed_paths=(),
        changed_projection=None,
        warnings=(),
        failures=(),
        func_clones_count=0,
        block_clones_count=0,
        project_metrics=None,
        coverage_join=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
    )


@pytest.fixture(name="service")
def _service() -> CodeCloneMCPService:
    return CodeCloneMCPService(history_limit=4)


def _checkout(parent: Path, name: str, *, bound: str | None = None) -> Path:
    """A repository root, optionally carrying a memory table with *bound*."""

    root = parent / name
    root.mkdir(parents=True, exist_ok=True)
    if bound is not None:
        (root / "pyproject.toml").write_text(
            f"[tool.codeclone.memory]\nmax_blast_radius_cache_entries = {bound}\n",
            encoding="utf-8",
        )
    return root


def _fill(
    service: CodeCloneMCPService,
    record: MCPRunRecord,
    *,
    count: int,
    tag: str,
) -> None:
    """Insert *count* distinct entries for one root, one per forbidden pattern."""

    for index in range(count):
        service._blast_radius_result(
            record=record,
            files=("pkg/a.py",),
            depth="direct",
            forbidden_patterns=(f"pkg/{tag}_{index}.py",),
        )


def _dependents(
    service: CodeCloneMCPService,
    record: MCPRunRecord,
) -> BlastRadiusResult:
    """One direct-depth blast-radius answer for ``pkg/a.py`` under *record*."""

    return service._blast_radius_result(
        record=record, files=("pkg/a.py",), depth="direct"
    )


def _entries_under(service: CodeCloneMCPService, root: Path) -> int:
    """Count the cache entries this root owns, by the key's own root slot."""

    resolved = str(root.resolve())
    return sum(
        1
        for key in service._blast_radius_cache
        if key[BLAST_RADIUS_CACHE_KEY_ROOT] == resolved
    )


def test_one_run_id_under_two_roots_does_not_share_a_blast_radius_answer(
    service: CodeCloneMCPService,
    tmp_path: Path,
) -> None:
    """Same content-addressed id, two checkouts, two different graphs.

    The run store admits this pair by construction: it keys on
    ``(root, run_id)`` precisely because the id alone cannot tell two
    checkouts apart. A cache keyed on the bare id answers the second root
    with the first root's dependents.
    """

    left = _record(_checkout(tmp_path, "left"), dependent_path="pkg/b.py")
    right = _record(
        _checkout(tmp_path, "right"),
        dependent_module="pkg.c",
        dependent_path="pkg/c.py",
    )

    left_result = _dependents(service, left)
    right_result = _dependents(service, right)

    assert left_result.direct_dependents == ("pkg/b.py",)
    assert right_result.direct_dependents == ("pkg/c.py",)
    assert len(service._blast_radius_cache) == 2


def test_one_root_spelled_two_ways_shares_one_cache_entry(
    service: CodeCloneMCPService,
    tmp_path: Path,
) -> None:
    """The opposite error: root in the key, but not canonically.

    ``run_store_key`` resolves the root before keying on it. A cache that
    keys on the raw spelling splits one checkout into as many partitions as
    it has aliases, so every aliased call recomputes and each alias gets its
    own quota.
    """

    real_root = _checkout(tmp_path, "checkout")
    alias_root = tmp_path / "alias"
    alias_root.symlink_to(real_root, target_is_directory=True)

    direct = _dependents(service, _record(real_root))
    through_alias = _dependents(service, _record(alias_root))

    assert direct is through_alias
    assert len(service._blast_radius_cache) == 1


@pytest.mark.parametrize(("configured", "offered"), [(3, 7), (5, 9)])
def test_partition_bound_is_read_from_the_repository_memory_config(
    service: CodeCloneMCPService,
    tmp_path: Path,
    configured: int,
    offered: int,
) -> None:
    """The enforcement witness: an atypical configured bound governs residency.

    Neither 3 nor 5 is the declared default or any literal the module could
    plausibly carry, and no single literal satisfies both cases, so a bound
    taken from anywhere but this root's own configuration fails here.
    """

    root = _checkout(tmp_path, "configured", bound=str(configured))

    _fill(service, _record(root), count=offered, tag="entry")

    assert _entries_under(service, root) == configured


@pytest.mark.parametrize(
    ("bounded", "neighbour", "offered", "retained"),
    [(2, 4, 9, 2), (0, 4, 3, 0)],
    ids=["quota-evicts-only-its-own-root", "non-positive-bound-retains-nothing"],
)
def test_one_roots_bound_never_reaches_another_roots_entries(
    service: CodeCloneMCPService,
    tmp_path: Path,
    bounded: int,
    neighbour: int,
    offered: int,
    retained: int,
) -> None:
    """The partition is the unit of eviction, not the session dictionary.

    The second case is the guard for a non-positive bound: zero entries means
    zero entries, and still only for the root that asked for it.
    """

    bounded_root = _checkout(tmp_path, "bounded", bound=str(bounded))
    neighbour_root = _checkout(tmp_path, "neighbour", bound=str(neighbour))

    _fill(service, _record(neighbour_root), count=neighbour, tag="neighbour")
    _fill(service, _record(bounded_root), count=offered, tag="bounded")

    assert _entries_under(service, bounded_root) == retained
    assert _entries_under(service, neighbour_root) == neighbour


@pytest.mark.parametrize("memory_table", [None, "true"])
def test_an_unconfigured_or_unreadable_root_falls_back_to_the_declared_default(
    service: CodeCloneMCPService,
    tmp_path: Path,
    memory_table: str | None,
) -> None:
    """Both roads to the declared default, including the fallback guard.

    With no ``[tool.codeclone.memory]`` table the default simply applies. With
    ``max_blast_radius_cache_entries = true`` the resolver rejects the value --
    ``expected_type=int`` admits ``true`` because ``bool`` is an ``int``
    subclass, so the refusal happens inside the memory resolver, which is the
    input that reaches the guard. Blast radius must not become unavailable
    because an unrelated memory key is mistyped, and the partition must still
    be bounded rather than unbounded.

    The default is substituted, not named: the number itself is pinned by
    ``test_documented_default_is_the_default_the_door_actually_yields``.
    """

    declared = _declared_default(tmp_path / "unconfigured")
    root = _checkout(tmp_path, "subject", bound=memory_table)

    _fill(service, _record(root), count=declared + 3, tag="entry")

    assert _entries_under(service, root) == declared


def test_pruning_a_stale_run_keeps_the_live_run_of_the_same_root(
    service: CodeCloneMCPService,
    tmp_path: Path,
) -> None:
    """The pruner reads the run-id slot of the key, not the key's first slot.

    Root leads the key, so a pruner that still indexes slot zero compares a
    checkout path against the live run ids and drops the whole cache.
    """

    root = _checkout(tmp_path, "checkout")
    live = _record(root, run_id="live1234567890ab")
    stale = _record(root, run_id="stale234567890ab")
    service._runs.register(live)

    _dependents(service, live)
    _dependents(service, stale)
    assert len(service._blast_radius_cache) == 2

    service._prune_session_state()

    assert len(service._blast_radius_cache) == 1


def _configuration_row(key: str) -> tuple[str, str]:
    """Return ``(default_cell, purpose_cell)`` for one documented config key."""

    text = _DOCS_CONFIG_REFERENCE.read_text(encoding="utf-8")
    match = re.search(rf"^\|\s*`{re.escape(key)}`\s*\|(.*)$", text, re.MULTILINE)
    assert match is not None, f"{key} is not documented in {_DOCS_CONFIG_REFERENCE}"
    cells = [cell.strip() for cell in match.group(1).split("|")]
    return cells[1], cells[2]


def test_documented_default_is_the_default_the_door_actually_yields(
    tmp_path: Path,
) -> None:
    """The documented number is measured through the door, not restated.

    This is the pin that dies when the constant moves: every other test here
    substitutes the default instead of naming it, and would stay green for any
    value. The basis for 64 is that 64 is the bound the session was actually
    enforcing; 500 was documented and never executed, so the documented number
    has to be the one an unconfigured root really gets.
    """

    default_cell, _ = _configuration_row(_CACHE_ENTRIES_KEY)

    assert default_cell == f"`{_declared_default(tmp_path / 'unconfigured')}`"


def test_only_this_key_lost_the_not_enforced_marking() -> None:
    """The doc delta, both directions.

    Six sibling keys keep the marking because each has its own ruling and its
    own owner. Removing it from one of them here, or leaving it on this one,
    is the same lie about coverage.
    """

    _, purpose = _configuration_row(_CACHE_ENTRIES_KEY)
    assert "Not enforced" not in purpose

    still_unenforced = (
        "memory.active_retention_days",
        "memory.stale_retention_days",
        "memory.receipt_retention_days",
        "memory.max_records",
        "memory.max_evidence_per_record",
        "memory.trajectory_retention_days",
    )
    for key in still_unenforced:
        _, sibling_purpose = _configuration_row(key)
        assert "Not enforced" in sibling_purpose, key
