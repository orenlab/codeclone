# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import (
    MCPAnalysisRequest,
    MCPRunRecord,
    MCPServiceContractError,
)


def _run_record(root: Path, run_id: str = "security-run-1234") -> MCPRunRecord:
    return MCPRunRecord(
        run_id=run_id,
        root=root,
        request=MCPAnalysisRequest(root=str(root), respect_pyproject=False),
        comparison_settings=(),
        report_document={"findings": {"groups": {}}},
        summary={"run_id": run_id, "health": {"score": 100, "grade": "A"}},
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


def test_mcp_granular_run_id_rejects_mismatched_root(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    service = CodeCloneMCPService(history_limit=4)
    service._runs.register(_run_record(first_root))

    with pytest.raises(MCPServiceContractError, match="does not belong"):
        service.check_clones(
            run_id="security-run-1234",
            root=str(second_root),
            detail_level="summary",
        )


@pytest.mark.parametrize(
    "uri_template",
    (
        "codeclone://latest/../summary",
        "codeclone://latest//summary",
        "codeclone://runs/{run_id}/../summary",
        "codeclone://runs/{run_id}//summary",
        "codeclone://runs/{run_id}/findings/../summary",
    ),
)
def test_mcp_resource_uri_rejects_unsafe_suffixes(
    tmp_path: Path,
    uri_template: str,
) -> None:
    service = CodeCloneMCPService(history_limit=4)
    record = _run_record(tmp_path)
    service._runs.register(record)

    with pytest.raises(MCPServiceContractError, match="path traversal not allowed"):
        service.read_resource(uri_template.format(run_id=record.run_id))


def test_mcp_finding_location_uris_stay_under_repo_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    package = root / "pkg"
    package.mkdir()
    (package / "safe.py").write_text("def safe():\n    return 1\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
        symlink_item = {"relative_path": "link/secret.py", "start_line": 4}
    except (NotImplementedError, OSError):
        symlink_item = {"relative_path": "", "start_line": 4}
    service = CodeCloneMCPService(history_limit=4)
    record = _run_record(root)

    locations = service._locations_for_finding(
        record,
        {
            "items": [
                {
                    "relative_path": "pkg/safe.py",
                    "start_line": 1,
                    "qualname": "pkg.safe:safe",
                },
                {"relative_path": "../outside.py", "start_line": 2},
                {"relative_path": str(outside / "abs.py"), "start_line": 3},
                symlink_item,
            ]
        },
    )

    assert locations == [
        {
            "file": "pkg/safe.py",
            "line": 1,
            "end_line": 0,
            "symbol": "pkg.safe:safe",
            "uri": f"{(package / 'safe.py').resolve().as_uri()}#L1",
        }
    ]


def test_mcp_normalize_relative_path_rejects_absolute(tmp_path: Path) -> None:
    from codeclone.surfaces.mcp import _session_helpers as helpers

    with pytest.raises(MCPServiceContractError, match="path traversal not allowed"):
        helpers._normalize_relative_path(str(tmp_path / "outside.py"))
