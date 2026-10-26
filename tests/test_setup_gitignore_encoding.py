# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A ``.gitignore`` that is not UTF-8 is a refusal to read, not a crash.

Git itself treats ``.gitignore`` as bytes, so a Latin-1 file is a valid
repository. Three readers decoded it as UTF-8 and caught only ``OSError``:
the workspace-hygiene check every ``setup`` command and every MCP analysis
runs first, the setup plan, and the setup apply. ``UnicodeDecodeError`` is a
``ValueError``, so it went past all three: ``setup plan``, ``status`` and
``doctor`` ended in "Setup failed" with exit 5.

The undecodable file is read the way an unreadable one already was: the
hygiene check cannot confirm coverage, the plan blocks the append and names
the decoding error, and the apply fails the action with that reason. How a
non-UTF-8 ``.gitignore`` should be matched is a separate question this change
does not answer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeclone.surfaces.cli.setup.engine.apply import _apply_gitignore_append
from tests._cli_child import run_codeclone

# ".codeclone/" preceded by a Latin-1 comment: valid for git, invalid UTF-8.
_LATIN1_GITIGNORE = b"# caf\xe9\n.codeclone/\n"


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "mod.py").write_text("VALUE = 1\n", "utf-8")
    (root / ".gitignore").write_bytes(_LATIN1_GITIGNORE)
    return root


def test_setup_plan_blocks_the_append_and_names_the_decoding_error(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)

    run = run_codeclone(tmp_path, "setup", "plan", "--json", "--root", str(root))

    assert run.returncode == 0, run.stdout + run.stderr
    actions = {
        str(action["kind"]): action for action in json.loads(run.stdout)["actions"]
    }
    append = actions["gitignore_append"]
    assert append["status"] == "blocked"
    assert "utf-8" in str(append["block_reason"])


@pytest.mark.parametrize("command", ["status", "doctor"])
def test_setup_readiness_commands_survive_an_undecodable_file(
    tmp_path: Path, command: str
) -> None:
    root = _project(tmp_path)

    run = run_codeclone(tmp_path, "setup", command, "--root", str(root))

    output = run.stdout + run.stderr
    assert run.returncode == 0, output
    assert "Setup failed" not in output, output


def test_the_apply_action_fails_with_the_decoding_reason(tmp_path: Path) -> None:
    """The apply reads the file again; a file changed under it fails typed."""

    root = _project(tmp_path)

    result = _apply_gitignore_append(
        root,
        {"id": "gitignore_append:workspace_hygiene", "lines": [".codeclone/"]},
        dry_run=True,
    )

    assert result["status"] == "failed"
    assert "utf-8" in str(result["message"])
    assert (root / ".gitignore").read_bytes() == _LATIN1_GITIGNORE


def test_an_mcp_analysis_survives_an_undecodable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hygiene check is also what every MCP analysis runs first."""

    from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest
    from codeclone.surfaces.mcp.service import CodeCloneMCPService

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    root = _project(tmp_path)

    summary = CodeCloneMCPService(history_limit=4).analyze_repository(
        MCPAnalysisRequest(root=str(root), respect_pyproject=False)
    )

    assert summary.get("run_id")
