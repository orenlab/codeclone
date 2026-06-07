# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOCS = _REPO_ROOT / "docs"

_GUIDE_MAX_LINES = 200
_CONTRACT_SPLIT_MAX_LINES = 200

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

_GUIDE_GLOBS = ("guide/**/*.md",)

_CONTRACT_SPLIT_GLOBS = (
    "book/12-structural-change-controller/*.md",
    "book/13-engineering-memory/*.md",
    "book/25-mcp-interface/**/*.md",
)


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_legacy_redirect_stub_pages_removed() -> None:
    present = [rel for rel in _REMOVED_LEGACY_STUBS if (_DOCS / rel).exists()]
    assert present == [], f"remove legacy stub pages: {present}"


def test_no_redirect_stub_markers_in_docs() -> None:
    violations: list[str] = []
    for path in sorted(_DOCS.rglob("*.md")):
        head = path.read_text(encoding="utf-8")[:300]
        if "REDIRECT STUB" in head or "class: redirect" in head:
            violations.append(str(path.relative_to(_DOCS)))
    assert violations == [], "\n".join(violations)


def test_guide_leaves_within_line_budget() -> None:
    violations: list[str] = []
    for pattern in _GUIDE_GLOBS:
        for path in sorted(_DOCS.glob(pattern)):
            count = _line_count(path)
            if count > _GUIDE_MAX_LINES:
                rel = path.relative_to(_DOCS)
                violations.append(
                    f"{rel}: {count} lines (max {_GUIDE_MAX_LINES})",
                )
    assert violations == [], "\n".join(violations)


def test_contract_split_leaves_within_line_budget() -> None:
    violations: list[str] = []
    for pattern in _CONTRACT_SPLIT_GLOBS:
        for path in sorted(_DOCS.glob(pattern)):
            count = _line_count(path)
            if count > _CONTRACT_SPLIT_MAX_LINES:
                rel = path.relative_to(_DOCS)
                violations.append(
                    f"{rel}: {count} lines (max {_CONTRACT_SPLIT_MAX_LINES})",
                )
    assert violations == [], "\n".join(violations)


def test_change_control_workflow_has_single_mermaid_diagram() -> None:
    path = _DOCS / "guide/mcp/workflows/change-control.md"
    text = path.read_text(encoding="utf-8")
    count = text.count("```mermaid")
    assert count == 1, f"expected one mermaid block, found {count}"
