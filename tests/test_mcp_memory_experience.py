# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.memory.experience.distillation_workflow import (
    execute_experience_distillation,
)
from codeclone.memory.trajectory.store import upsert_trajectory
from codeclone.surfaces.mcp._session_shared import MCPServiceContractError
from codeclone.surfaces.mcp.service import CodeCloneMCPService

from .memory_fixtures import cli_memory_repo
from .test_memory_experience_distiller import _multi_agent_cohort


def test_mcp_promote_experience_creates_draft(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        for trajectory in _multi_agent_cohort(5):
            upsert_trajectory(
                store.connection, replace(trajectory, project_id=project.id)
            )
        store.connection.commit()
        execute_experience_distillation(
            root_path=root,
            config=resolve_memory_config(root),
            store=store,
            project=project,
        )
        experience_id = store.list_experiences(project_id=project.id)[0].id

        service = CodeCloneMCPService(history_limit=2)
        result = service.manage_engineering_memory(
            root=str(root),
            action="promote_experience",
            experience_id=experience_id,
        )

        assert result["action"] == "promote_experience"
        assert result["status"] == "draft"
        assert result["type"] == "risk_note"
        assert result["promoted_from_experience"] == experience_id


def test_mcp_promote_experience_requires_experience_id(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        with pytest.raises(MCPServiceContractError, match="requires experience_id"):
            service.manage_engineering_memory(
                root=str(root),
                action="promote_experience",
            )
