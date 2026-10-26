# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The MCP server never reads its cache through a link that leaves the repository.

The read-only MCP server does not write the analysis cache, but it reads one.
A repository that commits ``.cache`` (or a directory on the way) as a link to
somewhere else made ``analyze_repository`` load a cache file from outside the
repository and reuse its facts. The CLI already refuses that path; the MCP
server applies the same rule and answers with a contract error. Every test
drives the public service entry point.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codeclone.surfaces.mcp._session_shared import (
    MCPAnalysisRequest,
    MCPServiceContractError,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests._cli_inprocess_run import run_cli

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="symbolic links need privileges on Windows"
)

_SOURCE = "def f(x):\n    return x + 1\n"


class _Layout:
    """A repository, a directory beside it, and a cache CodeClone wrote there."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.repo = tmp_path / "repo"
        self.outside = tmp_path / "outside"
        (self.repo / "pkg").mkdir(parents=True)
        self.outside.mkdir()
        (self.repo / "pkg" / "a.py").write_text(_SOURCE, encoding="utf-8")
        self._monkeypatch = monkeypatch

    def write_cache(self, cache_path: Path) -> Path:
        """A valid cache for this repository, written by the CLI at *cache_path*."""

        assert (
            run_cli(
                self._monkeypatch,
                self.repo,
                ".",
                "--no-progress",
                "--cache-path",
                str(cache_path),
            )
            == 0
        )
        assert cache_path.is_file()
        return cache_path


def _analyze(repo: Path, **request: object) -> dict[str, object]:
    service = CodeCloneMCPService(history_limit=2)
    return service.analyze_repository(
        MCPAnalysisRequest(root=str(repo), respect_pyproject=False, **request)  # type: ignore[arg-type]
    )


def _cache_used(summary: dict[str, object]) -> bool:
    cache = summary["cache"]
    assert isinstance(cache, dict)
    return cache["used"] is True


@pytest.mark.parametrize(
    "linked",
    [
        pytest.param(".cache", id="cache-root-directory"),
        pytest.param(".cache/codeclone", id="cache-subdirectory"),
    ],
)
def test_mcp_refuses_a_cache_behind_a_committed_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, linked: str
) -> None:
    layout = _Layout(tmp_path, monkeypatch)
    target = layout.outside if linked == ".cache" else layout.outside / "codeclone"
    layout.write_cache(
        layout.outside / "codeclone" / "cache.json"
        if linked == ".cache"
        else target / "cache.json"
    )
    link = layout.repo / linked
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(MCPServiceContractError, match="symbolic link"):
        _analyze(layout.repo)


def test_mcp_refuses_a_requested_cache_path_a_planted_link_leads_outside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _Layout(tmp_path, monkeypatch)
    layout.write_cache(layout.outside / "cache.json")
    (layout.repo / "ci").symlink_to(layout.outside, target_is_directory=True)

    with pytest.raises(MCPServiceContractError, match="symbolic link"):
        _analyze(layout.repo, cache_path="ci/cache.json")


def test_mcp_refuses_a_cache_behind_a_link_that_cannot_be_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A failed resolution is not evidence that the link stays inside.
    layout = _Layout(tmp_path, monkeypatch)
    (layout.repo / "build-cache").mkdir()
    (layout.repo / ".cache").symlink_to(
        layout.repo / "build-cache", target_is_directory=True
    )
    original_resolve = Path.resolve

    def _resolve(self: Path, strict: bool = False) -> Path:
        if ".cache" in self.parts:
            raise OSError("resolve failed")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve)

    with pytest.raises(MCPServiceContractError, match="symbolic link"):
        _analyze(layout.repo)


def test_mcp_uses_a_cache_in_an_ordinary_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _Layout(tmp_path, monkeypatch)
    layout.write_cache(layout.repo / ".cache" / "codeclone" / "cache.json")

    assert _cache_used(_analyze(layout.repo))


def test_mcp_uses_a_cache_behind_a_link_that_stays_inside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _Layout(tmp_path, monkeypatch)
    layout.write_cache(layout.repo / "build-cache" / "codeclone" / "cache.json")
    (layout.repo / ".cache").symlink_to(
        layout.repo / "build-cache", target_is_directory=True
    )

    assert _cache_used(_analyze(layout.repo))


def test_mcp_uses_a_requested_cache_path_spelled_outside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _Layout(tmp_path, monkeypatch)
    cache = layout.write_cache(layout.outside / "shared" / "cache.json")

    assert _cache_used(_analyze(layout.repo, cache_path=str(cache)))


def test_mcp_judges_a_requested_path_by_the_root_as_the_caller_spelled_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The caller reaches the repository through a linked parent directory and
    # spells the cache path the same way; the rule still sees it as inside.
    layout = _Layout(tmp_path, monkeypatch)
    layout.write_cache(layout.outside / "cache.json")
    (layout.repo / "ci").symlink_to(layout.outside, target_is_directory=True)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    spelled_repo = alias / "repo"

    service = CodeCloneMCPService(history_limit=2)
    with pytest.raises(MCPServiceContractError, match="symbolic link"):
        service.analyze_repository(
            MCPAnalysisRequest(
                root=str(spelled_repo),
                respect_pyproject=False,
                cache_path=str(spelled_repo / "ci" / "cache.json"),
            )
        )


def test_mcp_uses_a_cache_spelled_through_the_callers_linked_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same spelling as above, but the cache sits in an ordinary directory
    # of the repository: reaching the checkout through a link is not a reason
    # to refuse its own cache.
    layout = _Layout(tmp_path, monkeypatch)
    layout.write_cache(layout.repo / "ci" / "cache.json")
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    spelled_repo = alias / "repo"

    summary = CodeCloneMCPService(history_limit=2).analyze_repository(
        MCPAnalysisRequest(
            root=str(spelled_repo),
            respect_pyproject=False,
            cache_path=str(spelled_repo / "ci" / "cache.json"),
        )
    )

    assert _cache_used(summary)


def test_mcp_does_not_refuse_an_unresolvable_cache_path_with_no_link_on_the_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other side of the unresolvable case: with no link on the way the
    # path stays where it is spelled, so a failed resolution alone is no
    # reason to refuse an ordinary cache directory.
    layout = _Layout(tmp_path, monkeypatch)
    layout.write_cache(layout.repo / ".cache" / "codeclone" / "cache.json")
    original_resolve = Path.resolve

    def _resolve(self: Path, strict: bool = False) -> Path:
        if self.name == "cache.json" and ".cache" in self.parts:
            raise OSError("resolve failed")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve)

    assert _cache_used(_analyze(layout.repo))
