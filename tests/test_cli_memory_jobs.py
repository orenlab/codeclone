# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from codeclone.surfaces.cli.memory import memory_main

from .memory_fixtures import cli_memory_repo


def test_cli_memory_jobs_status(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        exit_code = memory_main(
            [
                "jobs",
                "status",
                "--root",
                str(root),
            ]
        )
        assert exit_code == 0


def test_cli_memory_jobs_enqueue_force(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        exit_code = memory_main(
            [
                "jobs",
                "enqueue",
                "--root",
                str(root),
                "--force",
                "--no-spawn",
            ]
        )
        assert exit_code == 0
