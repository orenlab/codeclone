# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest, MCPGateRequest
from tests.memory_fixtures import cli_memory_repo


def _write_semantic_config(root: Path, *, enabled: bool) -> None:
    value = "true" if enabled else "false"
    (root / "pyproject.toml").write_text(
        f"[tool.codeclone.memory.semantic]\nenabled = {value}\ndimension = 64\n",
        encoding="utf-8",
    )


def _write_python_source(root: Path) -> None:
    package = root / "pkg"
    package.mkdir(exist_ok=True)
    (package / "mod.py").write_text(
        "\n".join(
            [
                "def compute(value: int) -> int:",
                "    total = value + 1",
                "    total += 2",
                "    total += 3",
                "    total += 4",
                "    total += 5",
                "    return total",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _deterministic_snapshot(
    service: CodeCloneMCPService, root: Path
) -> dict[str, object]:
    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(root),
            respect_pyproject=True,
            cache_policy="off",
        )
    )
    run_id = str(summary["run_id"])
    return {
        "run_id": run_id,
        "summary": summary,
        "gates": service.evaluate_gates(MCPGateRequest(run_id=run_id)),
        "receipt": service.create_review_receipt(run_id=run_id, format="json"),
        "memory": service.get_relevant_memory(
            root=str(root),
            scope=["pkg/mod.py"],
            max_records=5,
            detail_level="compact",
        ),
    }


def test_semantic_enabled_does_not_change_deterministic_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "codeclone.surfaces.mcp.session._current_report_timestamp_utc",
        lambda: "2026-06-03T00:00:00Z",
    )
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        _write_python_source(root)
        service = CodeCloneMCPService(history_limit=4)

        _write_semantic_config(root, enabled=False)
        disabled = _deterministic_snapshot(service, root)

        _write_semantic_config(root, enabled=True)
        enabled = _deterministic_snapshot(service, root)

    assert enabled == disabled
