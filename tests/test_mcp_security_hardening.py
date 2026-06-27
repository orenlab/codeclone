# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.surfaces.mcp import _session_runtime as runtime
from codeclone.surfaces.mcp._session_runtime import (
    EXTERNAL_ARTIFACT_ROOTS_ENV,
    _external_artifact_roots,
    resolve_artifact_path,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import (
    MCPAnalysisRequest,
    MCPRunRecord,
    MCPServiceContractError,
)
from codeclone.utils.repo_paths import PathOutsideRepoError, RepoPathError


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


# --- allow_external_artifacts hardening (Tier 1 suffix/file-type, Tier 2 roots) ---


def _repo_and_external(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    root.mkdir()
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    return root, allowed


def _anchor_roots(monkeypatch: pytest.MonkeyPatch, root: Path, allowed: Path) -> None:
    """Pin the external-root allowlist so tests do not depend on the host temp
    dir (pytest's tmp_path lives under the real temp dir, a default root)."""
    monkeypatch.setattr(
        runtime,
        "_external_artifact_roots",
        lambda root_path: (root.resolve(), allowed.resolve()),
    )


def test_resolve_artifact_path_allows_repo_relative(tmp_path: Path) -> None:
    root, _ = _repo_and_external(tmp_path)
    target = root / "codeclone.baseline.json"
    assert resolve_artifact_path(
        "codeclone.baseline.json", root, kind="baseline"
    ) == target.resolve(strict=False)


def test_resolve_artifact_path_external_rejects_wrong_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, allowed = _repo_and_external(tmp_path)
    _anchor_roots(monkeypatch, root, allowed)
    bad = allowed / "coverage.txt"
    with pytest.raises(PathOutsideRepoError, match=r"must use one of \[\.xml\]"):
        resolve_artifact_path(
            str(bad), root, kind="coverage_xml", allow_external_artifacts=True
        )


def test_resolve_artifact_path_external_rejects_outside_permitted_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, allowed = _repo_and_external(tmp_path)
    _anchor_roots(monkeypatch, root, allowed)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "baseline.json"
    with pytest.raises(PathOutsideRepoError, match="escapes permitted roots"):
        resolve_artifact_path(
            str(target), root, kind="baseline", allow_external_artifacts=True
        )


def test_resolve_artifact_path_external_allows_permitted_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, allowed = _repo_and_external(tmp_path)
    _anchor_roots(monkeypatch, root, allowed)
    target = allowed / "baseline.json"
    target.write_text("{}", encoding="utf-8")
    assert (
        resolve_artifact_path(
            str(target), root, kind="baseline", allow_external_artifacts=True
        )
        == target.resolve()
    )


def test_resolve_artifact_path_external_rejects_symlink_to_disallowed_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, allowed = _repo_and_external(tmp_path)
    _anchor_roots(monkeypatch, root, allowed)
    secret = allowed / "secret.txt"
    secret.write_text("nope", encoding="utf-8")
    link = allowed / "evil.json"
    try:
        link.symlink_to(secret)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    # Suffix is checked on the resolved real path, so a .json link to a .txt
    # target is rejected even though the link name looks allowed.
    with pytest.raises(PathOutsideRepoError, match=r"must use one of \[\.json\]"):
        resolve_artifact_path(
            str(link), root, kind="baseline", allow_external_artifacts=True
        )


def test_resolve_artifact_path_external_rejects_non_regular_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, allowed = _repo_and_external(tmp_path)
    _anchor_roots(monkeypatch, root, allowed)
    weird = allowed / "cache.json"
    weird.mkdir()
    with pytest.raises(RepoPathError, match="regular file"):
        resolve_artifact_path(
            str(weird), root, kind="cache", allow_external_artifacts=True
        )


def test_resolve_artifact_path_without_kind_keeps_legacy_contract(
    tmp_path: Path,
) -> None:
    root, allowed = _repo_and_external(tmp_path)
    target = allowed / "anything.bin"
    target.write_text("x", encoding="utf-8")
    # kind=None reproduces the historical resolver: any external file allowed
    # once the explicit opt-in is set. Legacy callers stay unaffected.
    assert (
        resolve_artifact_path(str(target), root, allow_external_artifacts=True)
        == target.resolve()
    )


def test_external_artifact_roots_includes_defaults_and_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tempfile

    root = tmp_path / "repo"
    root.mkdir()
    extra = tmp_path / "extra"
    extra.mkdir()
    monkeypatch.setenv(EXTERNAL_ARTIFACT_ROOTS_ENV, str(extra))
    roots = _external_artifact_roots(root)
    assert root.resolve() in roots
    assert extra.resolve() in roots
    assert Path(tempfile.gettempdir()).resolve() in roots
