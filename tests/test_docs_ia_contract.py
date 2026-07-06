# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path
from typing import cast

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOCS = _REPO_ROOT / "docs"
_ZENSICAL = _REPO_ROOT / "zensical.toml"

pytestmark = pytest.mark.skipif(
    not (_DOCS / "index.md").is_file(),
    reason="repo docs source tree is not present",
)

_REMOVED_LEGACY_STUBS = (
    "mcp.md",
    "architecture.md",
    "vscode-extension.md",
    "cursor-plugin.md",
    "codex-plugin.md",
    "claude-desktop-bundle.md",
    "sarif.md",
    "book/12-structural-change-controller.md",
    "book/13-engineering-memory.md",
    "book/25-mcp-interface.md",
)

_LEGACY_TOP_LEVEL_DIRS = ("book", "guide")

_PUBLIC_NAV_PAGES = (
    "index.md",
    "getting-started.md",
    "examples/report.md",
    "concepts/controlled-change.md",
    "concepts/engineering-memory.md",
    "guides/agent-safe-change.md",
    "guides/engineering-memory-workflow.md",
    "integrations/claude.md",
    "integrations/cursor.md",
    "integrations/codex.md",
    "integrations/vscode.md",
    "reference/cli.md",
    "reference/mcp-tools.md",
    "troubleshooting/index.md",
    "privacy-policy.md",
    "terms-of-use.md",
)

_COMPLEX_SURFACE_PAGES = (
    "concepts/controlled-change.md",
    "concepts/engineering-memory.md",
    "guides/agent-safe-change.md",
    "guides/engineering-memory-workflow.md",
)


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _collect_nav_targets(nav: object) -> list[str]:
    targets: list[str] = []
    if isinstance(nav, list):
        for entry in nav:
            targets.extend(_collect_nav_targets(entry))
        return targets
    if isinstance(nav, dict):
        for value in nav.values():
            if isinstance(value, str):
                targets.append(value)
            else:
                targets.extend(_collect_nav_targets(value))
    return targets


def test_legacy_redirect_stub_pages_removed() -> None:
    present = [rel for rel in _REMOVED_LEGACY_STUBS if (_DOCS / rel).exists()]
    assert present == [], f"remove legacy stub pages: {present}"


def test_legacy_book_and_guide_trees_removed() -> None:
    present = [name for name in _LEGACY_TOP_LEVEL_DIRS if (_DOCS / name).exists()]
    assert present == [], f"legacy docs trees should not exist: {present}"


def test_no_redirect_stub_markers_in_docs() -> None:
    violations: list[str] = []
    for path in sorted(_DOCS.rglob("*.md")):
        head = path.read_text(encoding="utf-8")[:300]
        if "REDIRECT STUB" in head or "class: redirect" in head:
            violations.append(str(path.relative_to(_DOCS)))
    assert violations == [], "\n".join(violations)


def _load_zensical_config() -> dict[str, object]:
    text = _ZENSICAL.read_text(encoding="utf-8")
    if sys.version_info >= (3, 11):
        tomllib = importlib.import_module("tomllib")
        return cast(dict[str, object], tomllib.loads(text))
    tomli = importlib.import_module("tomli")
    return cast(dict[str, object], tomli.loads(text.encode("utf-8")))


def test_zensical_nav_targets_exist() -> None:
    config = _load_zensical_config()
    project = cast(dict[str, object], config["project"])
    nav = project["nav"]
    missing = [
        rel
        for rel in sorted(set(_collect_nav_targets(nav)))
        if not (_DOCS / rel).is_file()
    ]
    assert missing == [], f"zensical nav targets missing on disk: {missing}"


def test_public_nav_pages_exist() -> None:
    missing = [rel for rel in _PUBLIC_NAV_PAGES if not (_DOCS / rel).is_file()]
    assert missing == [], f"public docs pages missing: {missing}"


def test_agent_safe_change_workflow_has_single_mermaid_diagram() -> None:
    path = _DOCS / "guides/agent-safe-change.md"
    text = path.read_text(encoding="utf-8")
    count = text.count("```mermaid")
    assert count == 1, f"expected one mermaid block, found {count}"


def test_complex_surfaces_have_visual_contracts() -> None:
    missing = [
        rel
        for rel in _COMPLEX_SURFACE_PAGES
        if "```mermaid" not in (_DOCS / rel).read_text(encoding="utf-8")
    ]
    assert missing == [], f"complex pages without Mermaid diagrams: {missing}"


def test_new_surfaces_are_reachable_from_navigation() -> None:
    nav_text = _ZENSICAL.read_text(encoding="utf-8")
    missing = [rel for rel in _PUBLIC_NAV_PAGES if rel not in nav_text]
    assert missing == [], f"pages missing from navigation: {missing}"


def test_engineering_memory_guides_cross_link_contracts() -> None:
    pairs = (
        (
            "guides/engineering-memory-workflow.md",
            "docs/concepts/engineering-memory.md",
        ),
        (
            "concepts/engineering-memory.md",
            "engineering-memory-workflow.md",
        ),
        (
            "concepts/controlled-change.md",
            "engineering-memory.md",
        ),
    )
    missing = [
        f"{rel} -> {target}"
        for rel, target in pairs
        if target not in (_DOCS / rel).read_text(encoding="utf-8")
    ]
    assert missing == [], f"missing required cross-links: {missing}"


def test_integration_docs_reference_mcp_workflow_tools() -> None:
    expectations = {
        "integrations/codex.md": ("start_controlled_change", "analyze_repository"),
        "integrations/claude.md": ("start_controlled_change", "analyze_repository"),
        "integrations/cursor.md": ("start_controlled_change", "analyze_repository"),
        "integrations/vscode.md": ("codeclone-mcp", "MCP"),
    }
    for rel, needles in expectations.items():
        text = (_DOCS / rel).read_text(encoding="utf-8")
        for needle in needles:
            assert needle in text, f"{rel} missing {needle}"
        assert re.search(r"docs/(book|guide)/", text) is None, rel
