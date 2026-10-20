# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""What ``renew`` says about an intent's hard ceiling (declaration + TTL).

A renewal moves the lease and never the ceiling, so its answer has to name
the ceiling, what remains of it, and -- once it has passed -- that the intent
expired by TTL, instead of a bare ``lease_renewed: false``.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.surfaces.mcp._workspace_intents import (
    find_workspace_intent,
    write_workspace_intent,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest

_PAST_CEILING = "2026-01-01T00:00:00Z"


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@e.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@e.invalid",
        },
    )


@pytest.fixture
def analysed(tmp_path: Path) -> tuple[Path, CodeCloneMCPService]:
    root = tmp_path / "repo"
    root.joinpath("pkg").mkdir(parents=True)
    root.joinpath("pkg", "__init__.py").write_text("", "utf-8")
    root.joinpath("pkg", "a.py").write_text("def f(x: int) -> int:\n    return x\n")
    root.joinpath("README.md").write_text("stable\n", "utf-8")
    for args in (("init", "-q"), ("add", "."), ("commit", "-qm", "init")):
        _git(root, *args)
    service = CodeCloneMCPService()
    service.analyze_repository(
        MCPAnalysisRequest(root=str(root), respect_pyproject=False)
    )
    return root, service


def _start(service: CodeCloneMCPService, root: Path, *, ttl_seconds: int) -> str:
    started = service.start_controlled_change(
        root=str(root),
        scope={"allowed_files": ["README.md"]},
        intent="edit the readme",
        ttl_seconds=ttl_seconds,
    )
    assert started["status"] == "active", started
    return str(started["intent_id"])


def test_renew_names_the_ceiling_and_what_remains_of_it(
    analysed: tuple[Path, CodeCloneMCPService],
) -> None:
    root, service = analysed
    intent_id = _start(service, root, ttl_seconds=3600)
    record = find_workspace_intent(root=root, intent_id=intent_id)
    assert record is not None

    renewed = service.manage_change_intent(action="renew", intent_id=intent_id)

    assert renewed["lease_renewed"] is True
    assert renewed["expires_at_utc"] == record.expires_at_utc
    assert 0 < int(str(renewed["ttl_remaining_seconds"])) <= 3600
    assert renewed["lease_beyond_ttl"] is False
    assert "reason" not in renewed


def test_renew_says_when_the_lease_runs_past_the_ceiling(
    analysed: tuple[Path, CodeCloneMCPService],
) -> None:
    root, service = analysed
    intent_id = _start(service, root, ttl_seconds=60)

    renewed = service.manage_change_intent(
        action="renew", intent_id=intent_id, lease_seconds=600
    )

    assert renewed["lease_renewed"] is True
    assert renewed["lease_beyond_ttl"] is True
    assert int(str(renewed["ttl_remaining_seconds"])) <= 60


def test_renew_past_the_ceiling_says_the_intent_expired_by_ttl(
    analysed: tuple[Path, CodeCloneMCPService],
) -> None:
    root, service = analysed
    intent_id = _start(service, root, ttl_seconds=3600)
    record = find_workspace_intent(root=root, intent_id=intent_id)
    assert record is not None
    write_workspace_intent(
        root=root, record=replace(record, expires_at_utc=_PAST_CEILING)
    )

    renewed = service.manage_change_intent(action="renew", intent_id=intent_id)

    assert renewed["lease_renewed"] is False
    assert renewed["reason"] == "intent_expired_ttl"
    assert renewed["expires_at_utc"] == _PAST_CEILING
    assert renewed["ttl_remaining_seconds"] == 0
    assert "expired (TTL)" in str(renewed["message"])


def test_renew_after_the_row_was_closed_says_it_is_no_longer_registered(
    analysed: tuple[Path, CodeCloneMCPService],
) -> None:
    """The first lookup past the ceiling closes the row; renew then cannot see
    the ceiling, and says the registry no longer holds the intent."""

    root, service = analysed
    intent_id = _start(service, root, ttl_seconds=3600)
    record = find_workspace_intent(root=root, intent_id=intent_id)
    assert record is not None
    write_workspace_intent(
        root=root, record=replace(record, expires_at_utc=_PAST_CEILING)
    )
    assert find_workspace_intent(root=root, intent_id=intent_id) is None

    renewed = service.manage_change_intent(action="renew", intent_id=intent_id)

    assert renewed["lease_renewed"] is False
    assert renewed["reason"] == "intent_not_registered"
    assert renewed["expires_at_utc"] is None
