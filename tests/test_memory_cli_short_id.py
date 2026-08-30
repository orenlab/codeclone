# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Short memory ids must mean the same thing on the CLI as they do on MCP.

Agents hand humans the short id MCP prints, so a governance command that only
accepts the full id sends the human back to a surface they are not on. These
pins hold the parity itself -- the exact string MCP resolves is the string the
CLI acts on -- and hold the refusal that parity must not cost: a prefix that
names more than one record aims an irreversible action at an unknown target,
so it has to be refused rather than resolved to whichever row sorts first.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.contracts import ExitCode
from codeclone.surfaces.cli.memory import memory_main

from .memory_short_id_fixtures import (
    MEMORY_ID_CANDIDATE_LIMIT,
    collide_id,
    memory_repo,
    open_memory_store,
    promote_to_active,
    read_record_status,
    record_resolver_calls,
    resolve_id_through_mcp,
    seed_colliding_draft,
    seed_colliding_trajectory,
)

# Two ids sharing the shortest prefix the id contract accepts, and one that
# shares nothing with them.
_SHARED_HEX = "abcd1234"
_LONE_HEX = "beef5678"
_BREAK_GLASS = "--i-know-what-im-doing"


def _governance_argv(command: str, record_id: str, root: Path) -> list[str]:
    return [command, record_id, "--root", str(root), "--by", "tester", _BREAK_GLASS]


# ---------------------------------------------------------------------------
# Parity: the string MCP resolves is the string the CLI acts on
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "expected_status"),
    [("reject", "rejected"), ("approve", "active")],
)
def test_cli_governance_accepts_the_short_id_mcp_accepts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
    expected_status: str,
) -> None:
    full = collide_id("mem", _LONE_HEX, "cc")
    short = f"mem-{_LONE_HEX}"
    with memory_repo(tmp_path) as (root, project):
        with open_memory_store(root) as store:
            seed_colliding_draft(
                store, project=project, record_id=full, statement="lone draft"
            )

        # The surface that already works, on the exact string under test.
        mcp = resolve_id_through_mcp(root, mode="get", record_id=short)
        assert mcp["status"] == "ok"
        payload = mcp["payload"]
        assert isinstance(payload, dict)
        assert payload["resolution"] == {"requested": short, "resolved": full}

        code = memory_main(_governance_argv(command, short, root))
        output = capsys.readouterr().out

        assert code == int(ExitCode.SUCCESS)
        assert read_record_status(root, full) == expected_status
        # The action is irreversible, so the surface names what it resolved to.
        assert f"{short} -> {full}" in output


def test_cli_archive_accepts_the_short_id(tmp_path: Path) -> None:
    full = collide_id("mem", _LONE_HEX, "cc")
    short = f"mem-{_LONE_HEX}"
    with memory_repo(tmp_path) as (root, project):
        with open_memory_store(root) as store:
            seed_colliding_draft(
                store, project=project, record_id=full, statement="to archive"
            )
            promote_to_active(store, full)

        code = memory_main(_governance_argv("archive", short, root))
        assert code == int(ExitCode.SUCCESS)
        assert read_record_status(root, full) == "archived"


def test_cli_short_id_asks_the_lane_resolver(tmp_path: Path) -> None:
    """The CLI reaches the lane's resolver rather than owning a second one.

    A message pin stays green for any implementation that prints the right
    words; this holds the edge, so a private re-implementation inside the CLI
    fails here even when its output is identical.
    """

    full = collide_id("mem", _LONE_HEX, "cc")
    short = f"mem-{_LONE_HEX}"
    with memory_repo(tmp_path) as (root, project):
        with open_memory_store(root) as store:
            seed_colliding_draft(
                store, project=project, record_id=full, statement="edge pin"
            )

        with record_resolver_calls() as prefixes:
            code = memory_main(_governance_argv("reject", short, root))

    assert code == int(ExitCode.SUCCESS)
    assert short in prefixes


# ---------------------------------------------------------------------------
# What parity must not cost: an ambiguous prefix is refused, not guessed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["approve", "reject", "archive"])
def test_cli_governance_refuses_an_ambiguous_prefix_and_writes_nothing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    first = collide_id("mem", _SHARED_HEX, "aa")
    second = collide_id("mem", _SHARED_HEX, "bb")
    short = f"mem-{_SHARED_HEX}"
    with memory_repo(tmp_path) as (root, project):
        with open_memory_store(root) as store:
            seed_colliding_draft(
                store, project=project, record_id=first, statement="first one"
            )
            seed_colliding_draft(
                store, project=project, record_id=second, statement="second one"
            )

        code = memory_main(_governance_argv(command, short, root))
        output = capsys.readouterr().out

        assert code == int(ExitCode.CONTRACT_ERROR)
        assert "2 matches" in output
        assert first in output
        assert second in output
        assert "ambiguous" in output.lower()
        # No governance transition may happen behind an unresolved id.
        assert read_record_status(root, first) == "draft"
        assert read_record_status(root, second) == "draft"


def test_cli_refusal_counts_every_match_not_just_the_listed_ones(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The reported count is the total behind the prefix, not the list length.

    The lane caps the candidates it hands back, so a refusal that counted its
    own list would under-report by exactly the rows it hid, and the human
    would lengthen the prefix believing there were fewer collisions than there
    are. Only a prefix with more matches than the cap separates the two.
    """

    over_cap = MEMORY_ID_CANDIDATE_LIMIT + 1
    short = f"mem-{_SHARED_HEX}"
    with memory_repo(tmp_path) as (root, project):
        with open_memory_store(root) as store:
            for index in range(over_cap):
                seed_colliding_draft(
                    store,
                    project=project,
                    record_id=collide_id("mem", _SHARED_HEX, f"{index:02d}"),
                    statement=f"collision number {index}",
                )

        code = memory_main(_governance_argv("reject", short, root))
        output = capsys.readouterr().out

    assert code == int(ExitCode.CONTRACT_ERROR)
    assert f"{over_cap} matches" in output
    assert f"{over_cap - MEMORY_ID_CANDIDATE_LIMIT} more not listed" in output


def test_cli_governance_not_found_is_distinct_from_ambiguous(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with memory_repo(tmp_path) as (root, project):
        with open_memory_store(root) as store:
            seed_colliding_draft(
                store,
                project=project,
                record_id=collide_id("mem", _LONE_HEX, "cc"),
                statement="unrelated",
            )

        code = memory_main(_governance_argv("reject", "mem-99999999", root))
        output = capsys.readouterr().out

    assert code == int(ExitCode.CONTRACT_ERROR)
    assert "not found" in output.lower()
    assert "ambiguous" not in output.lower()


def test_cli_governance_still_accepts_the_full_id(tmp_path: Path) -> None:
    """The regression invariant: a full id keeps working exactly as before.

    Seeded alongside a prefix twin on purpose -- a full id must stay an exact
    lookup, not become one more thing the resolver has an opinion about.
    """

    first = collide_id("mem", _SHARED_HEX, "aa")
    second = collide_id("mem", _SHARED_HEX, "bb")
    with memory_repo(tmp_path) as (root, project):
        with open_memory_store(root) as store:
            seed_colliding_draft(
                store, project=project, record_id=first, statement="first one"
            )
            seed_colliding_draft(
                store, project=project, record_id=second, statement="second one"
            )

        code = memory_main(_governance_argv("reject", first, root))
        assert code == int(ExitCode.SUCCESS)
        assert read_record_status(root, first) == "rejected"
        assert read_record_status(root, second) == "draft"


# ---------------------------------------------------------------------------
# The fourth surface: trajectory show takes an id too
# ---------------------------------------------------------------------------


def test_cli_trajectory_show_accepts_the_short_id_mcp_accepts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    full = collide_id("traj", _LONE_HEX, "cc")
    short = f"traj-{_LONE_HEX}"
    with memory_repo(tmp_path) as (root, project):
        with open_memory_store(root) as store:
            seed_colliding_trajectory(store, project_id=project.id, trajectory_id=full)

        assert (
            resolve_id_through_mcp(root, mode="trajectory_get", record_id=short)[
                "status"
            ]
            == "ok"
        )

        code = memory_main(["trajectory", "show", short, "--root", str(root)])
        output = capsys.readouterr().out

        assert code == int(ExitCode.SUCCESS)
        assert f"{short} -> {full}" in output


def test_cli_trajectory_show_refuses_an_ambiguous_prefix(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = collide_id("traj", _SHARED_HEX, "aa")
    second = collide_id("traj", _SHARED_HEX, "bb")
    short = f"traj-{_SHARED_HEX}"
    with memory_repo(tmp_path) as (root, project):
        with open_memory_store(root) as store:
            seed_colliding_trajectory(store, project_id=project.id, trajectory_id=first)
            seed_colliding_trajectory(
                store, project_id=project.id, trajectory_id=second
            )

        code = memory_main(["trajectory", "show", short, "--root", str(root)])
        output = capsys.readouterr().out

    assert code == int(ExitCode.CONTRACT_ERROR)
    assert "2 matches" in output
    assert first in output
    assert second in output
