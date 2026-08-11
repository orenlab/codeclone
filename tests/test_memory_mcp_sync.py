# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from typing import Final, get_args

import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.memory.ingest import run_fitness as run_fitness_mod
from codeclone.memory.ingest.mcp_sync import (
    decide_mcp_memory_sync,
    execute_mcp_memory_sync,
    read_stored_report_digest,
)
from codeclone.memory.project import resolve_memory_db_path
from tests.memory_fixtures import (
    git_repo_with_cached_report,
    report_document_for_counters,
    tool_calls_named_in,
)

#: The counters of a run that found Python files and opened none of them —
#: the one run ingest refuses. Written as what the run did, so the state's
#: name is never spelled here and cannot go stale under a rename.
_FOUND_READ_NONE: Final = (2, 0)
#: The sibling that must not be refused: everything found was read.
_FOUND_READ_ALL: Final = (2, 2)
_REGISTRY: Final = ["pkg/mod.py"]


def _repo_and_run(
    tmp_path: Path, counters: tuple[int, int]
) -> tuple[Path, dict[str, object]]:
    """A real git repo plus the report of a run with those counters."""

    found, analyzed = counters
    root, _report_path, _document = git_repo_with_cached_report(
        tmp_path,
        py_sources={_REGISTRY[0]: "def f():\n    return 1\n"},
        registry_items=list(_REGISTRY),
    )
    document = report_document_for_counters(
        root,
        found=found,
        analyzed=analyzed,
        registry_items=_REGISTRY,
    )
    return root, document


def test_decide_mcp_memory_sync_bootstrap_when_missing_db(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    config = resolve_memory_config(root)
    db_path = resolve_memory_db_path(root, config)
    decision = decide_mcp_memory_sync(
        policy="bootstrap_if_missing",
        db_path=db_path,
        report_digest="digest-a",
        stored_digest=None,
    )
    assert decision.action == "bootstrap"
    assert decision.reason == "missing_db"


@pytest.mark.parametrize(
    ("report_digest", "stored_digest", "expected_action", "expected_reason"),
    [
        ("digest-b", "digest-a", "refresh", "digest_changed"),
        ("digest-a", "digest-a", "none", "digest_unchanged"),
    ],
)
def test_decide_mcp_memory_sync_refresh_when_stale_policy(
    tmp_path: Path,
    report_digest: str,
    stored_digest: str,
    expected_action: str,
    expected_reason: str,
) -> None:
    db_path = tmp_path / "memory.sqlite3"
    db_path.write_text("", encoding="utf-8")
    decision = decide_mcp_memory_sync(
        policy="refresh_when_stale",
        db_path=db_path,
        report_digest=report_digest,
        stored_digest=stored_digest,
    )
    assert decision.action == expected_action
    assert decision.reason == expected_reason


def test_execute_mcp_memory_sync_auto_skips_when_unchanged(
    tmp_path: Path,
) -> None:
    from tests.memory_fixtures import git_repo_with_cached_report

    root, _report_path, report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/mod.py": "def f():\n    return 1\n"},
        registry_items=["pkg/mod.py"],
    )
    config = resolve_memory_config(root)
    db_path = resolve_memory_db_path(root, config)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    first = execute_mcp_memory_sync(
        root_path=root,
        report_document=report_document,
        config=config,
        trigger="explicit",
        run_id="run-first",
        force=True,
    )
    assert first["status"] == "completed"

    second = execute_mcp_memory_sync(
        root_path=root,
        report_document=report_document,
        config=config,
        trigger="auto",
        run_id="run-first",
        force=False,
    )
    assert second["status"] == "unchanged"
    assert read_stored_report_digest(db_path) is not None


def test_execute_mcp_memory_sync_rejects_invalid_policy(tmp_path: Path) -> None:
    from dataclasses import replace

    from tests.memory_fixtures import git_repo_with_cached_report

    root, _report_path, report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/mod.py": "pass\n"},
        registry_items=["pkg/mod.py"],
    )
    config = replace(resolve_memory_config(root), mcp_sync_policy="off")
    payload = execute_mcp_memory_sync(
        root_path=root,
        report_document=report_document,
        config=config,
        trigger="auto",
        run_id="run-off",
        force=False,
    )
    assert payload["status"] == "unchanged"
    assert payload["reason"] == "policy_off"


def test_execute_mcp_memory_sync_skips_without_report_digest(tmp_path: Path) -> None:
    from codeclone.memory.ingest.mcp_sync import execute_mcp_memory_sync

    root = tmp_path / "repo"
    root.mkdir()
    payload = execute_mcp_memory_sync(
        root_path=root,
        report_document={},
        trigger="auto",
        run_id="run-no-digest",
        force=False,
    )
    assert payload["status"] == "skipped"
    assert payload["reason"] == "missing_report_digest"


# ── the refusal must reach an agent as a move it can make ───────────


def test_mcp_sync_refusal_names_a_tool_the_agent_can_call(tmp_path: Path) -> None:
    """The step handed to an MCP caller names MCP tools, not shell commands.

    ``bootstrap_if_missing`` makes this sync an agent's first contact with
    memory, so this is the refusal an agent is most likely to meet. A remedy
    spelled ``codeclone <root>`` sends the one caller that has a native
    ``analyze_repository`` out to a shell to look for it, and it fails the
    standard this surface already holds its other typed outcomes to: an
    executable instruction names a tool to call, not just a diagnosis.
    """

    root, document = _repo_and_run(tmp_path, _FOUND_READ_NONE)
    payload = execute_mcp_memory_sync(
        root_path=root,
        report_document=document,
        trigger="auto",
        run_id="run-unmeasured",
        force=False,
    )

    assert payload["status"] == "skipped"
    step = str(payload["next_step"])
    # The two moves the remedy prescribes, each spelled as this surface's own
    # tool: re-analyse the root, then re-ingest that run.
    assert "analyze_repository" in step, step
    assert "manage_engineering_memory" in step, step
    # The substance rides with them. Without this, "name a tool" would be
    # satisfied by citing one and dropping the reason to call it.
    assert "inventory.files" in step, step
    # And the other surface's spelling does not leak into this one: two
    # audiences, one fact, but not one blob.
    assert "codeclone memory init" not in step, step


def test_mcp_sync_offers_no_next_step_when_nothing_was_refused(
    tmp_path: Path,
) -> None:
    """An outcome that is not a dead end carries no step out of it.

    ``next_step`` is remediation, and the convention this payload joins —
    start, finish, verify — attaches it only where the caller is blocked;
    terminal successful outcomes omit the key rather than carry a null or a
    congratulation. A step on a healthy outcome is noise, and noise is what
    teaches a reader to stop reading the field that matters.
    """

    root, document = _repo_and_run(tmp_path, _FOUND_READ_ALL)
    completed = execute_mcp_memory_sync(
        root_path=root,
        report_document=document,
        trigger="explicit",
        run_id="run-measured",
        force=True,
    )
    unchanged = execute_mcp_memory_sync(
        root_path=root,
        report_document=document,
        trigger="auto",
        run_id="run-measured",
        force=False,
    )

    assert completed["status"] == "completed"
    assert unchanged["status"] == "unchanged"
    assert "next_step" not in completed, completed
    assert "next_step" not in unchanged, unchanged


def test_mcp_sync_next_step_has_exactly_one_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The payload reads the refusal owner; it does not restate it.

    Equality against the owner's current text cannot tell delegation from a
    verbatim copy pasted beside it, and the copy is the defect: two wordings
    of one refusal drift the moment either is edited, and the two surfaces
    then disagree about what the caller should do.

    The redirect is installed on the owning module, so only a call that
    resolves there can follow it: a same-named twin defined next to the
    caller — the copy that survives an equality check, because its text is
    identical today — reds here.
    """

    root, document = _repo_and_run(tmp_path, _FOUND_READ_NONE)
    monkeypatch.setattr(
        run_fitness_mod,
        "unmeasured_refusal_message",
        lambda *, root, surface: f"redirected-owner::{surface}::{root}",
    )

    payload = execute_mcp_memory_sync(
        root_path=root,
        report_document=document,
        trigger="auto",
        run_id="run-unmeasured",
        force=False,
    )

    assert payload["next_step"] == f"redirected-owner::mcp::{root.resolve()}"


def test_every_refusal_reason_ships_a_step_naming_an_mcp_tool() -> None:
    """No typed refusal may reach an agent without a move it can make.

    Coverage, not an allowlist: the vocabulary is read from the owner, so a
    refusal added for a new population state joins this guard by existing.
    The patch-contract surface has held its typed outcomes to exactly this
    standard for a while; memory-sync reasons were simply outside anything
    that looked, which is how a shell command reached an agent unnoticed.
    """

    assert run_fitness_mod.REFUSAL_REASONS, "the refusal vocabulary is empty"
    for reason in sorted(run_fitness_mod.REFUSAL_REASONS):
        step = run_fitness_mod.refusal_message(
            reason=reason, root="/repo", surface="mcp"
        )
        assert step is not None, f"{reason} ships no MCP next step"
        # That a call is named at all is this ring's business; that the name
        # answers on the surface is checked where the registry lives, against
        # the server itself, so neither place keeps a list of tool names.
        assert tool_calls_named_in(step), (
            f"{reason} next_step names no tool to call: {step}"
        )


def test_each_surface_gets_its_own_spelling_of_one_remedy() -> None:
    """Two audiences, one fact — and no audience silently served another's.

    Every declared surface must render, and render differently: a surface
    added without its own spelling would fall through to a neighbour's and
    hand, say, a shell command to an agent, which is the whole defect this
    split exists to prevent.
    """

    rendered = {
        surface: run_fitness_mod.unmeasured_refusal_message(
            root="/repo", surface=surface
        )
        for surface in get_args(run_fitness_mod.RefusalSurface)
    }

    assert len(rendered) > 1, "a split with one surface is not a split"
    for surface, message in rendered.items():
        assert message.strip(), f"{surface} renders nothing"
        # The cause is the shared substance and must survive every rendering.
        assert "inventory.files" in message, (surface, message)
    assert len(set(rendered.values())) == len(rendered), rendered
