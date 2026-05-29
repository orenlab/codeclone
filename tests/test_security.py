# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.contracts.errors import ValidationError
from codeclone.core._types import MAX_FILE_SIZE
from codeclone.core.worker import process_file
from codeclone.report.explain import build_block_group_facts
from codeclone.report.html import build_html_report
from codeclone.report.renderers.markdown import render_markdown_report_document
from codeclone.report.renderers.sarif import render_sarif_report_document
from codeclone.scanner import iter_py_files, resolved_path_under_root
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest, MCPServiceContractError


def test_scanner_path_traversal() -> None:
    """Test that scanner rejects paths outside root or sensitive paths."""
    with pytest.raises(ValidationError):
        list(iter_py_files("/etc"))

    with pytest.raises(ValidationError):
        list(iter_py_files("/etc/passwd"))


def test_process_file_size_limit() -> None:
    """Test that process_file rejects large files."""
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp:
        tmp.write(b"print('hello')")
        tmp_path = tmp.name

    try:
        cfg = NormalizationConfig()
        real_stat = os.stat(tmp_path)

        # Mock os.stat to return huge st_size
        def _huge_stat(path: str, *args: object, **kwargs: object) -> os.stat_result:
            return os.stat_result(
                (
                    real_stat.st_mode,
                    real_stat.st_ino,
                    real_stat.st_dev,
                    real_stat.st_nlink,
                    real_stat.st_uid,
                    real_stat.st_gid,
                    MAX_FILE_SIZE + 1,  # st_size
                    int(real_stat.st_atime),
                    int(real_stat.st_mtime),
                    int(real_stat.st_ctime),
                )
            )

        with patch("os.stat", side_effect=_huge_stat):
            result = process_file(tmp_path, os.path.dirname(tmp_path), cfg, 0, 0)
            assert result.success is False
            assert result.error is not None
            assert "File too large" in result.error

        # Normal size should pass (no mock — real stat)
        result = process_file(tmp_path, os.path.dirname(tmp_path), cfg, 0, 0)
        assert result.success is True

    finally:
        os.remove(tmp_path)


def test_process_file_rejects_symlink_target_outside_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    cfg = NormalizationConfig()

    module = workspace / "module.py"
    module.write_text("x = 1\n", encoding="utf-8")
    assert process_file(str(module), str(workspace), cfg, 0, 0).success is True

    outside_target = outside / "secret.py"
    outside_target.write_text("y = 2\n", encoding="utf-8")
    module.unlink()
    module.symlink_to(outside_target)

    result = process_file(str(module), str(workspace), cfg, 0, 0)
    assert result.success is False
    assert result.error_kind == "source_read_error"
    assert result.error is not None
    assert "outside repository root" in result.error


def test_html_report_escapes_user_content(tmp_path: Path) -> None:
    bad_path = tmp_path / 'x" onmouseover="alert(1).py'
    good_path = tmp_path / "y.py"
    bad_path.write_text("def f():\n    return 1\n", "utf-8")
    good_path.write_text("def g():\n    return 2\n", "utf-8")
    func_groups = {
        "k": [
            {
                "qualname": "<script>alert(1)</script>",
                "filepath": str(bad_path),
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            },
            {
                "qualname": "ok",
                "filepath": str(good_path),
                "start_line": 3,
                "end_line": 4,
                "loc": 2,
            },
        ]
    }
    html = build_html_report(
        func_groups=func_groups,
        block_groups={},
        segment_groups={},
        block_group_facts=build_block_group_facts({}),
        title="Security",
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert 'onmouseover="alert(1)' not in html
    assert 'data-qualname="&lt;script&gt;alert(1)&lt;/script&gt;"' in html
    assert "&quot; onmouseover=&quot;alert(1).py" in html


def test_html_report_escapes_title_and_does_not_emit_raw_script(tmp_path: Path) -> None:
    module = tmp_path / "mod.py"
    module.write_text("def f():\n    return 1\n", encoding="utf-8")
    payload = "<img src=x onerror=alert(1)>"
    html = build_html_report(
        func_groups={
            "k": [
                {
                    "qualname": payload,
                    "filepath": str(module),
                    "start_line": 1,
                    "end_line": 2,
                    "loc": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
        block_group_facts=build_block_group_facts({}),
        title=payload,
    )
    assert payload not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_markdown_and_sarif_projections_do_not_emit_raw_html_tags(
    tmp_path: Path,
) -> None:
    report_payload: dict[str, object] = {
        "report_schema_version": "2.11",
        "meta": {"generator": {"name": "codeclone", "version": "2.1.0"}},
        "inventory": {"files": 0, "lines": 0, "functions": 0, "classes": 0},
        "findings": {
            "groups": {
                "clones": {"functions": [], "blocks": [], "segments": []},
                "structural": [],
                "design": [],
            }
        },
        "summary": {},
        "metrics": {},
    }
    markdown = render_markdown_report_document(report_payload)
    sarif = render_sarif_report_document(report_payload)
    assert "<script>" not in markdown
    assert "<script>" not in sarif


def test_scanner_excludes_symlinked_sources_outside_root(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlink is not supported on this platform")
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "leak.py"
    outside_file.write_text("x = 1\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    link = workspace / "leak.py"
    try:
        link.symlink_to(outside_file)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available in this environment")

    files = list(iter_py_files(str(workspace)))
    assert str(link) not in files
    assert resolved_path_under_root(str(link), str(workspace)) is None


def test_mcp_service_rejects_refresh_cache_policy(tmp_path: Path) -> None:
    tmp_path.joinpath("pkg").mkdir()
    tmp_path.joinpath("pkg", "__init__.py").write_text("", encoding="utf-8")
    tmp_path.joinpath("pkg", "mod.py").write_text(
        "def f():\n    return 1\n",
        encoding="utf-8",
    )
    service = CodeCloneMCPService(history_limit=2)
    with pytest.raises(MCPServiceContractError, match="read-only"):
        service.analyze_repository(
            MCPAnalysisRequest(
                root=str(tmp_path.resolve()),
                respect_pyproject=False,
                cache_policy="refresh",
            )
        )


def test_mcp_service_rejects_relative_repository_root(tmp_path: Path) -> None:
    service = CodeCloneMCPService(history_limit=2)
    with pytest.raises(MCPServiceContractError, match="absolute repository root"):
        service.analyze_repository(
            MCPAnalysisRequest(
                root=".",
                respect_pyproject=False,
                cache_policy="off",
            )
        )


def test_mcp_service_rejects_changed_paths_outside_repository(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    service = CodeCloneMCPService(history_limit=2)
    service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path.resolve()),
            respect_pyproject=False,
            cache_policy="off",
        )
    )
    with pytest.raises(MCPServiceContractError, match="path traversal not allowed"):
        service.analyze_changed_paths(
            MCPAnalysisRequest(
                root=str(tmp_path.resolve()),
                respect_pyproject=False,
                cache_policy="off",
                changed_paths=("../outside.py",),
            )
        )


def test_html_report_does_not_use_unescaped_user_payload_in_script_context(
    tmp_path: Path,
) -> None:
    module = tmp_path / "mod.py"
    module.write_text("def f():\n    return 1\n", encoding="utf-8")
    payload = "</script><script>alert(1)</script>"
    html = build_html_report(
        func_groups={
            "k": [
                {
                    "qualname": payload,
                    "filepath": str(module),
                    "start_line": 1,
                    "end_line": 2,
                    "loc": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
        block_group_facts=build_block_group_facts({}),
    )
    assert payload not in html
    assert "</script><script>" not in html
