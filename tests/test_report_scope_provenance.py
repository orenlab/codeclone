# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The source-population provenance on the report document.

The population owner derives the source population from git with a typed
fallback and keeps its provenance (``scope_source`` / ``fallback_reason``)
beside the identity owners, never inside them. This module pins the document
side of that contract:

- P-meta: the document carries the provenance in ``meta``, as the value the
  discovery owner recorded -- on the corpus, the CLI, the memory-analysis and
  the MCP paths alike. A path that drops it would publish ``null`` and hide
  the fact the field exists to state.
- P-identity: the same population from git and from the walk seals the same
  identity tiers and the same run identity; only ``meta`` differs, and with
  it the envelope, which seals the whole document by construction.
- P-version: the additive keys moved ``REPORT_SCHEMA_VERSION`` to ``3.5`` and
  the exact policy refuses a ``3.4`` document.
- render: text, markdown, HTML and SARIF show the source a human reads, taken
  from ``meta`` and never recomputed -- the fallback arm is what tells a
  renderer that copies ``meta`` apart from one that prints a constant.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Final, cast

import pytest

import codeclone.main as cli
from codeclone.api.population import derive_source_population
from codeclone.api.report import ReportArtifactFailure, load_report_artifact
from codeclone.contracts import REPORT_SCHEMA_VERSION
from codeclone.report.html.assemble import build_html_report
from codeclone.report.renderers.markdown import render_markdown_report_document
from codeclone.report.renderers.sarif import render_sarif_report_document
from codeclone.report.renderers.text import render_text_report_document
from codeclone.surfaces.cli.memory_analysis import run_memory_analysis_report
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest
from codeclone.utils.run_identity import report_run_identity

from ._projection_equivalence import build_probe_document, write_probe_tree

_FALLBACK_REASON: Final = "git_unavailable"
_IDENTITY_TIERS = ("observation", "analysis_facts", "comparison", "evaluation")


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _committed_probe_tree(root: Path) -> Path:
    """The projection corpus tree, committed so git owns its population."""

    root.mkdir(parents=True)
    write_probe_tree(root)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "provenance@example.invalid")
    _git(root, "config", "user.name", "provenance")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "probe")
    # Probe validity: the tree really is a clean repository, so ``git`` is the
    # answer the owner must give and the walk is reachable only by force.
    assert _git(root, "status", "--porcelain") == ""
    assert derive_source_population(root).scope_source == "git"
    return root


def _force_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the owner's git door refuse, so the walk answers with its reason."""

    monkeypatch.setattr(
        "codeclone.paths.population.list_git_workspace_paths",
        lambda _root: SimpleNamespace(
            available=False,
            paths=(),
            fallback_reason=_FALLBACK_REASON,
        ),
    )


def _meta(document: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], document["meta"])


def _digests(document: dict[str, object]) -> dict[str, str]:
    integrity = cast(dict[str, object], document["integrity"])
    digests = cast(dict[str, dict[str, object]], integrity["digests"])
    return {
        tier: str(digests[tier]["value"]) for tier in (*_IDENTITY_TIERS, "envelope")
    }


@dataclass(frozen=True, slots=True)
class _Arms:
    root: Path
    from_git: dict[str, object]
    from_walk: dict[str, object]


@pytest.fixture(scope="module")
def arms(tmp_path_factory: pytest.TempPathFactory) -> _Arms:
    """One committed tree, sealed twice: once by git, once by the forced walk."""

    root = _committed_probe_tree(tmp_path_factory.mktemp("provenance") / "repo")
    from_git = build_probe_document(root)
    with pytest.MonkeyPatch.context() as monkeypatch:
        _force_fallback(monkeypatch)
        from_walk = build_probe_document(root)
    return _Arms(root=root, from_git=from_git, from_walk=from_walk)


# --- P-meta ------------------------------------------------------------------


def test_the_document_carries_the_provenance_the_population_owner_recorded(
    arms: _Arms,
) -> None:
    git_meta = _meta(arms.from_git)
    owner = derive_source_population(arms.root)
    assert git_meta["scope_source"] == owner.scope_source == "git"
    assert git_meta["scope_fallback_reason"] is owner.fallback_reason is None

    walk_meta = _meta(arms.from_walk)
    assert walk_meta["scope_source"] == "filesystem_fallback"
    assert walk_meta["scope_fallback_reason"] == _FALLBACK_REASON


# --- P-identity --------------------------------------------------------------


def test_provenance_rides_meta_and_never_a_digest(arms: _Arms) -> None:
    """Table C, row 2: one population, two sources, one identity."""

    assert _meta(arms.from_git)["scope_source"] != _meta(arms.from_walk)["scope_source"]
    assert report_run_identity(arms.from_git) == report_run_identity(arms.from_walk)
    git_digests = _digests(arms.from_git)
    walk_digests = _digests(arms.from_walk)
    for tier in _IDENTITY_TIERS:
        assert git_digests[tier] == walk_digests[tier], tier
    # The envelope seals the whole document, ``meta`` included, so it is the
    # one digest the provenance is allowed to move.
    assert git_digests["envelope"] != walk_digests["envelope"]
    # And the fact never leaks into the tier that keys the run.
    assert "scope_source" not in json.dumps(arms.from_git["source_facts"])


# --- P-version ---------------------------------------------------------------


def test_the_provenance_keys_moved_the_report_schema_to_3_5(
    arms: _Arms, tmp_path: Path
) -> None:
    """The keys are additive, the version is not: a 3.4 reader must refuse.

    3.5 is where these keys entered; 3.6 (the ``api_surface``
    ``signature_changed`` kind) carries them unchanged, so the pin follows
    the live version as every schema pin does.
    """

    assert REPORT_SCHEMA_VERSION == "3.6"
    assert arms.from_git["report_schema_version"] == "3.6"

    current = tmp_path / "current.json"
    current.write_text(json.dumps(arms.from_git), "utf-8")
    assert not isinstance(load_report_artifact(current), ReportArtifactFailure)

    stale = tmp_path / "stale.json"
    stale.write_text(
        json.dumps({**arms.from_git, "report_schema_version": "3.4"}), "utf-8"
    )
    refusal = load_report_artifact(stale)
    assert isinstance(refusal, ReportArtifactFailure)
    assert refusal.reason == "incompatible_schema"
    assert "'3.4'" in refusal.detail


# --- every producing surface -------------------------------------------------


def _run_cli_json(
    root: Path, out_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, object]:
    report_path = out_dir / "report.json"
    argv = [
        "codeclone",
        str(root),
        "--json",
        str(report_path),
        "--cache-path",
        str(out_dir / "cache.json"),
        "--processes",
        "1",
        "--no-progress",
        "--quiet",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code in (0, None), exc.code
    return cast(dict[str, object], json.loads(report_path.read_text("utf-8")))


def _mcp_meta(root: Path) -> dict[str, object]:
    service = CodeCloneMCPService(history_limit=4)
    summary = service.analyze_repository(
        MCPAnalysisRequest(root=str(root), respect_pyproject=False, processes=1)
    )
    return service.get_report_section(run_id=str(summary["run_id"]), section="meta")


def test_the_cli_and_the_mcp_documents_carry_the_same_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two producing surfaces, one fact: each hands the owner's value on."""

    root = _committed_probe_tree(tmp_path / "repo")

    cli_meta = _meta(_run_cli_json(root, tmp_path / "git", monkeypatch))
    mcp_meta = _mcp_meta(root)
    assert cli_meta["scope_source"] == mcp_meta["scope_source"] == "git"
    assert (
        cli_meta["scope_fallback_reason"] is mcp_meta["scope_fallback_reason"] is None
    )

    _force_fallback(monkeypatch)
    cli_meta = _meta(_run_cli_json(root, tmp_path / "walk", monkeypatch))
    mcp_meta = _mcp_meta(root)
    assert cli_meta["scope_source"] == mcp_meta["scope_source"] == "filesystem_fallback"
    assert (
        cli_meta["scope_fallback_reason"]
        == mcp_meta["scope_fallback_reason"]
        == _FALLBACK_REASON
    )


def test_the_memory_analysis_document_carries_the_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _committed_probe_tree(tmp_path / "repo")

    meta = _meta(run_memory_analysis_report(root_path=root))
    assert meta["scope_source"] == "git"
    assert meta["scope_fallback_reason"] is None

    _force_fallback(monkeypatch)
    meta = _meta(run_memory_analysis_report(root_path=root))
    assert meta["scope_source"] == "filesystem_fallback"
    assert meta["scope_fallback_reason"] == _FALLBACK_REASON


# --- render: the source a human reads --------------------------------------


def test_text_and_markdown_show_the_scope_source_a_human_reads(arms: _Arms) -> None:
    git_text = render_text_report_document(arms.from_git).splitlines()
    assert "Scope source: git" in git_text
    assert "Scope fallback reason: (none)" in git_text
    walk_text = render_text_report_document(arms.from_walk).splitlines()
    assert "Scope source: filesystem_fallback" in walk_text
    assert f"Scope fallback reason: {_FALLBACK_REASON}" in walk_text

    git_md = render_markdown_report_document(arms.from_git).splitlines()
    assert "- Scope source: git" in git_md
    assert "- Scope fallback reason: (none)" in git_md
    walk_md = render_markdown_report_document(arms.from_walk).splitlines()
    assert "- Scope source: filesystem_fallback" in walk_md
    assert f"- Scope fallback reason: {_FALLBACK_REASON}" in walk_md


def test_html_shows_the_scope_source_a_human_reads(arms: _Arms) -> None:
    git_html = build_html_report(report_document=arms.from_git)
    assert 'data-scope-source="git"' in git_html
    assert "data-scope-fallback-reason=" not in git_html
    assert 'prov-td-label">Scope source' in git_html
    assert '<span class="prov-badge-val">git</span>' in git_html

    walk_html = build_html_report(report_document=arms.from_walk)
    assert 'data-scope-source="filesystem_fallback"' in walk_html
    assert f'data-scope-fallback-reason="{_FALLBACK_REASON}"' in walk_html
    assert 'prov-td-label">Scope fallback reason' in walk_html
    assert '<span class="prov-badge-val">filesystem_fallback</span>' in walk_html


def test_sarif_carries_the_scope_source_in_the_run_properties(arms: _Arms) -> None:
    def _properties(document: dict[str, object]) -> dict[str, object]:
        sarif = json.loads(render_sarif_report_document(document))
        run = cast(dict[str, object], cast(list[object], sarif["runs"])[0])
        return cast(dict[str, object], run["properties"])

    git_properties = _properties(arms.from_git)
    assert git_properties["scopeSource"] == "git"
    assert git_properties["scopeFallbackReason"] == ""
    walk_properties = _properties(arms.from_walk)
    assert walk_properties["scopeSource"] == "filesystem_fallback"
    assert walk_properties["scopeFallbackReason"] == _FALLBACK_REASON
