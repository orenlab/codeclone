# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.surfaces.mcp.service import CodeCloneMCPService

from .memory_fixtures import cli_memory_repo


def test_mcp_manage_memory_projection_rebuild_status(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        payload = service.manage_engineering_memory(
            root=str(root.resolve()),
            action="projection_rebuild_status",
        )
        assert payload["action"] == "projection_rebuild_status"
        assert payload["policy"] == "off"
        assert payload["stale"] is True


def test_mcp_manage_memory_enqueue_projection_rebuild_force_via_policy_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "codeclone.memory.jobs.workflow.is_ci_environment",
        lambda: False,
    )
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        payload = service.manage_engineering_memory(
            root=str(root.resolve()),
            action="enqueue_projection_rebuild",
        )
        assert payload["action"] == "enqueue_projection_rebuild"
        assert payload["status"] == "skipped"
        assert payload["reason"] == "policy_off"
